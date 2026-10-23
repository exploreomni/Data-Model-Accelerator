"""Assignment checks use the actual packet, not only caller-supplied hash syntax."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import run_control as control
import test_agent_context as fixtures
from test_task_routing import assignment


class AssignmentDispatchTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.AgentContextTests(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = {'inputs': {'source': {'path': str(self.h.source)}}, 'answers': {},
                      'workflow': {'tasks': [], 'runs': [], 'design': None}}
        self.request = {'schema_version': 1, 'work_id': 'orders-design', 'attempt_id': 'design-1',
                        'role': 'warehouse_architect', 'scope_ids': ['orders'], 'source_paths': ['orders.sql']}
        bindings = control.assignment_bindings(self.state, self.request)['input_bindings']
        self.request['assignment'] = assignment(task_id='orders-design', stage='design', role='warehouse_architect',
                                              outputs=['design/orders.json'], input_bindings=bindings)
        self.h.request.update(bindings=bindings, assignment=copy.deepcopy(self.request['assignment']))

    def test_bound_packet_dispatch_provisional_completion_and_reuse(self):
        claim = control.claim_work(self.state, self.request)
        receipt = self.h.build()
        dispatch = {'schema_version': 1, 'attempt_id': 'design-1', 'fingerprint': claim['fingerprint'],
                    'execution_mode': 'specialist', 'host_run_reference': 'synthetic://builder',
                    'observed_model': None, 'observed_effort': None, 'packet_sha256': receipt['packet_sha256'],
                    'packet_dir': str(self.h.root / 'packet')}
        control.record_dispatch(self.state, dispatch)
        self.assertEqual(control.prepare_dispatch(self.state, {k: dispatch[k] for k in ('attempt_id', 'fingerprint', 'packet_dir', 'packet_sha256')})['status'], 'ready')
        out = self.h.root / 'candidate'; (out / 'design').mkdir(parents=True)
        (out / 'design/orders.json').write_text('{"grain":"order","status":"provisional"}')
        control.checkpoint_work(self.state, {'schema_version': 1, 'attempt_id': 'design-1',
            'status': 'outputs_recorded', 'reason': 'Provisional design retained', 'outputs': ['design/orders.json']}, out)
        self.assertEqual(control.claim_work(self.state, {**self.request, 'attempt_id': 'design-2'})['action'], 'reuse')
        progress = control.public_summary(self.state)['progress']['tasks'][0]
        self.assertEqual(progress['authoring_mode'], 'provisional')
        self.assertEqual(progress['review_status'], 'unverified')

    def test_review_pins_root_and_completed_correction_gets_new_attempt(self):
        self.test_bound_packet_dispatch_provisional_completion_and_reuse()
        out = self.h.root / 'candidate'
        wrong = self.h.root / 'wrong'; (wrong / 'design').mkdir(parents=True)
        (wrong / 'design/orders.json').write_text('{}')
        start = {'attempt_id': 'design-1', 'action': 'start'}
        with self.assertRaisesRegex(ValueError, 'root differs'):
            control.review_work(self.state, start, wrong)
        candidate = out / 'design/orders.json'; original = candidate.read_bytes()
        candidate.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            control.review_work(self.state, start, out)
        candidate.write_bytes(original)
        result = control.review_work(self.state, start, out)
        for review in result['review']['plan']['reviews']:
            finding = {'id': 'grain', 'severity': 'blocking', 'message': 'Document the order key',
                       'evidence': ['Source orders.id'], 'affected_ids': ['orders'], 'acceptance': 'Key is explicit'}
            result = control.review_work(self.state, {'attempt_id': 'design-1', 'action': 'record', 'result': {
                'review_id': review['id'], 'candidate_sha256': result['review']['candidate_sha256'],
                'verdict': 'changes', 'findings': [finding], 'reviewer_reference': 'synthetic://independent',
                'execution_mode': 'specialist'}}, out)
        reserved = control.review_work(self.state, {'attempt_id': 'design-1', 'action': 'correct',
                                                    'correction_attempt_id': 'correction-1'}, out)
        previous = self.state['operations']['attempts'][0]
        dispatch = {k: v for k, v in previous['dispatch_observation'].items()
                    if k not in {'assurance', 'execution_verified', 'recorded_at'}}
        dispatch.update(attempt_id='correction-1', host_run_reference='synthetic://new-builder')
        control.record_dispatch(self.state, dispatch)
        candidate.write_text('{"grain":"order","key":"id","status":"provisional"}')
        revised = control.review_work(self.state, {'attempt_id': reserved['attempt_id'], 'action': 'revise'}, out)
        self.assertEqual(revised['review']['builder_reference'], 'synthetic://new-builder')
        control.checkpoint_work(self.state, {'schema_version': 1, 'attempt_id': 'correction-1',
            'status': 'outputs_recorded', 'reason': 'Corrected candidate retained', 'outputs': ['design/orders.json']}, out)
        self.assertEqual(control.claim_work(self.state, {**self.request, 'attempt_id': 'design-3'})['action'], 'reuse')

    def test_missing_packet_changed_assignment_and_output_collision_fail(self):
        claim = control.claim_work(self.state, self.request)
        dispatch = {'schema_version': 1, 'attempt_id': 'design-1', 'fingerprint': claim['fingerprint'],
                    'execution_mode': 'specialist', 'host_run_reference': 'synthetic://builder',
                    'observed_model': None, 'observed_effort': None}
        with self.assertRaisesRegex(ValueError, 'actual context'):
            control.record_dispatch(self.state, dispatch)
        self.h.request['assignment']['domain_id'] = 'different'
        receipt = self.h.build()
        with self.assertRaisesRegex(ValueError, 'assignment differs'):
            control.record_dispatch(self.state, {**dispatch, 'packet_sha256': receipt['packet_sha256'],
                                                'packet_dir': str(self.h.root / 'packet')})
        other = copy.deepcopy(self.request)
        other.update(work_id='other', attempt_id='other-1')
        other['assignment']['task_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'already owned'):
            control.claim_work(self.state, other)
        self.assertIsNone(self.state['operations']['attempts'][0].get('dispatch_observation'))

    def test_context_and_claim_mismatch_rejected_without_reservation(self):
        for key, value in [('scope_ids', ['payments']), ('role', 'semantic_modeler')]:
            request = copy.deepcopy(self.request); request['assignment'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                control.claim_work(self.state, request)
        self.assertNotIn('operations', self.state)

    def test_planned_provisional_dbt_task_keeps_existing_stage_and_approval_rules(self):
        from test_provisional_generation import ProvisionalGenerationTests
        pilot = ProvisionalGenerationTests(); pilot.setUp(); self.addCleanup(pilot.doCleanups)
        pilot.request_draft()
        specification = pilot.tasks()
        plan = pilot.h.plan(specification)
        task = next(t for t in plan['tasks'] if t['action'] == 'regenerate')
        request = {'schema_version': 1, 'work_id': task['id'], 'attempt_id': 'build-attempt-1',
                   'task_id': task['id'], 'role': 'analytics_engineer',
                   'scope_ids': task['entity_ids'], 'source_paths': []}
        binding = control.assignment_bindings(pilot.h.state, request)
        outputs = next(t['outputs'] for t in specification['tasks'] if t['id'] == task['id'])
        request['assignment'] = assignment(task_id=task['id'], scope_ids=task['entity_ids'], outputs=outputs,
                                          input_bindings=binding['input_bindings'])
        self.assertEqual(binding['generation_mode'], 'provisional')
        self.assertEqual(control.claim_work(pilot.h.state, request)['action'], 'dispatch')
        self.assertFalse(pilot.h.state['readiness']['execution_authorized'])
        self.assertFalse(pilot.h.state['readiness']['generation_ready'])


if __name__ == '__main__':
    unittest.main()
