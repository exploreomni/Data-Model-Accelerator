"""Real guided handoff -> coordinator -> independent signed lane simulation."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import guided_workflow as guided
import deployment_workflow as deploy
import delivery_portal as portal
import delivery_release as release
from ae_common import hash_json
from disclosure_fixtures import synthetic_disclosure
import test_deployment_workflow as deploytests
from test_deployment_workflow import ScriptedTransport, dbt_response, Ed25519PrivateKey
from test_delivery_release import fixture, add_evidence


@unittest.skipUnless(Ed25519PrivateKey, 'Pinned deployment runtime required')
class ReleaseCoordinatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.h = deploytests.DeploymentWorkflowTests('test_prepared_handoff_to_signed_simulation_receipt_end_to_end')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        h = self.h
        state = guided.update_answers(h.run, {'migration_scope':'model_only','input_handling':'pre_sanitized'})
        review = json.loads(h.review.read_text())
        review['context_sha256'] = portal.context_fingerprint(state)
        review['disclosure'] = synthetic_disclosure([a['id'] for a in review['artifacts']])
        h.review.write_text(json.dumps(review))
        guided.record_handoff(h.run,h.review,h.candidate,audience='engineer')
        _, policy, key, _ = fixture('model_only',mode='simulation')
        h.policy['issuers']['independent-validator'] = policy['issuers']['independent-validator']
        h.keys['independent-validator'] = key; h.write_policy()
        self.draft = h.make_plan(path=h.root/'scoped-draft.json')

    def evidence_request(self):
        h = self.h
        draft = copy.deepcopy(self.draft)
        template,_,_,_ = fixture('model_only',mode='simulation')
        descriptor = template['delivery_assurance']['descriptor']
        access = descriptor['access']; c=access['contract']
        binding=dict(release.evidence_bindings(draft,descriptor),policy='d'*64)
        identity=c['destination']['identity']
        target=draft['target']
        identity.update(target['namespace'], principal=target['identity'], base_url=target['base_url'])
        c['bindings']=binding
        for name in ('current','candidate','readback'):
            access[name]['bindings']=copy.deepcopy(binding)
            access[name]['destination']=copy.deepcopy(c['destination'])
        import security_contract as security
        from test_security_contract import seal
        seal(c,access['current'],access['candidate'])
        access['observations'].update(bindings=binding,destination=copy.deepcopy(c['destination']),
            contract_sha256=hash_json(c),state_sha256=security.state_hash(access['candidate']),
            cases={case['id']:{'context':security.expected_context(c,case),'result':copy.deepcopy(case['expected'])} for case in c['cases']})
        draft['delivery_assurance']=release.bind_context(draft,descriptor)
        add_evidence(draft,h.policy,h.keys['independent-validator'],datetime.now(timezone.utc),release.DEV_LANES)
        return dict(h.request,delivery_assurance=draft['delivery_assurance']['descriptor'])

    def test_scoped_coordinator_blocks_missing_evidence_before_transport(self):
        h=self.h; model,approval=h.approvals(self.draft); transport=ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError,'assurance context'):
            deploy.submit(h.root/'scoped-draft.json',h.policy_path,model,approval,transport=transport)
        self.assertEqual(transport.calls,[])

    def test_scoped_prepared_handoff_runs_development_with_independent_gates(self):
        h=self.h; request=self.evidence_request()
        plan=h.make_plan(request,path=h.root/'scoped-final.json'); model,approval=h.approvals(plan)
        transport=ScriptedTransport(dbt_response())
        record=deploy.submit(h.root/'scoped-final.json',h.policy_path,model,approval,transport=transport)
        self.assertEqual(len(transport.calls),1)
        self.assertEqual(record['state'],'verification_pending')
        h.plan=plan
        accepted=deploy.accept(h.policy_path,record['operation_id'],h.acceptance(record))
        self.assertEqual(accepted['state'],'simulation_verified')
        self.assertFalse(accepted['migration_acceptance_ready'])

    def test_drift_between_plan_and_submission_is_rejected(self):
        h=self.h; plan=h.make_plan(self.evidence_request(),path=h.root/'scoped-final.json')
        model,approval=h.approvals(plan)
        (h.candidate/'models/orders.sql').write_text('select 9 as order_id\n')
        transport=ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError): deploy.submit(h.root/'scoped-final.json',h.policy_path,model,approval,transport=transport)
        self.assertEqual(transport.calls,[])


if __name__=='__main__':unittest.main()
