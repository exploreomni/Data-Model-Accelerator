"""Prepared-handoff deployment scenarios using external test-only Ed25519 issuers.

The actual guided collector, prepared handoff, coordinator and adapters run. Only
remote transport is replaced. No fixture qualifies a live service or customer.
"""
import base64
import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import deployment_workflow as deploy
import guided_workflow as guided
import delivery_portal as portal

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    Ed25519PrivateKey = None

COMMIT = 'a' * 40
CHECKS = ['access', 'fanout', 'grain', 'metrics', 'physical_schema', 'principal_namespace', 'source_reconciliation']


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def dbt_response(status=10, **overrides):
    # Deliberately independent of the adapter's expected_identity implementation.
    data = {'id': 901, 'account_id': 11, 'project_id': 22, 'environment_id': 33,
            'job_definition_id': 44, 'git_sha': COMMIT, 'status': status}
    data.update(overrides)
    return {'status_code': 200, 'body': {'data': data}}


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, operation):
        self.calls.append(copy.deepcopy(operation))
        if not self.responses:
            raise AssertionError('Unexpected native call')
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


@unittest.skipUnless(Ed25519PrivateKey, 'Optional deployment cryptography dependency is unavailable')
class DeploymentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'dbt_project.yml').write_text('name: synthetic_source\nversion: "1.0"\nconfig-version: 2\n')
        (self.source / 'models').mkdir()
        (self.source / 'models/source.sql').write_text('select 1 as order_id\n')
        self.catalogue = self.root / 'catalogue.json'
        self.catalogue.write_text('{"objects":[{"name":"orders"}],"provenance":"synthetic"}')
        self.keys = {
            'approval-service': Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
            'validation-service': Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))),
        }
        self.policy = {
            'schema_version': 1, 'kind': 'deployment_runner_policy', 'runner_id': 'synthetic-runner',
            'mode': 'simulation', 'allowed_actions': ['deploy_development', 'publish_pr'],
            'state_root': str(self.root / 'trusted-runner-state'), 'journal_key_env': 'DMA_TEST_JOURNAL_KEY',
            'issuers': {}, 'tools': {}, 'max_attestation_age_seconds': 3600, 'revoked_ids': [],
            'destinations': {'dev': {
                'adapter': 'dbt_platform', 'framework': 'dbt', 'warehouse': 'snowflake',
                'environment': 'development', 'namespace': {'database': 'TEST_DB', 'schema': 'GOLD'},
                'identity': 'synthetic-service', 'runtime_version': 'qualified-fixture-1',
                'base_url': 'https://cloud.getdbt.com', 'account_id': 11, 'project_id': 22,
                'environment_id': 33, 'job_id': 44, 'auth_env': {'token': 'DMA_TEST_DBT_TOKEN'},
            }},
        }
        for issuer, key in self.keys.items():
            purposes = ['model_signoff', 'deployment_approval'] if issuer == 'approval-service' else [
                'deployment_acceptance', 'deployment_recovery', 'deployment_reconciliation']
            self.policy['issuers'][issuer] = {
                'public_key': base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                'actors': ['synthetic-reviewer' if issuer == 'approval-service' else 'synthetic-validator'],
                'purposes': purposes,
            }
        self.policy_path = self.root / 'runner-policy.json'
        self.write_policy()
        self.env = patch.dict(os.environ, {'DMA_TEST_JOURNAL_KEY': 'test-only-journal-integrity-key-0000000000'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.run, self.candidate, self.review = self.make_handoff('first')
        self.request = {
            'schema_version': 1, 'action': 'deploy_development', 'destination_id': 'dev',
            'release_id': 'synthetic-release', 'commit_sha': COMMIT,
            'artifacts': [{'path': 'models/orders.sql', 'role': 'model_sql'}],
            'impact': ['Build the reviewed synthetic development model.'],
            'recovery': ['Retain partial evidence and prepare a reviewed repair.'],
            'required_checks': CHECKS,
        }
        self.plan_path = self.root / 'plan.json'
        self.plan = self.make_plan()
        self.model, self.approval = self.approvals()

    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy))
        self.policy_path.chmod(0o600)

    def make_handoff(self, name, *, framework='dbt', warehouse='snowflake', extra_contents=None, extra_answers=None):
        run, candidate = self.root / (name + '-engagement'), self.root / (name + '-candidate')
        candidate.mkdir()
        answers = {'engagement_type': 'new_model', 'priority_domain': 'Orders', 'framework': framework,
                   'warehouse': warehouse, 'semantic_target': 'none',
                   'deliverables': ['implementation', 'documentation']}
        answers.update(extra_answers or {})
        state = guided.start_engagement(self.source, run, answers, catalogue=self.catalogue)
        self.assertEqual(state['status'], 'candidate_preparation_ready')
        contents = {'models/orders.sql': ('implementation', b'select 1 as order_id\n'),
                    'macros/identity.sql': ('implementation', b'{% macro identity(x) %}{{ x }}{% endmacro %}\n'),
                    'docs/release.md': ('documentation', b'Synthetic deployment exercise only.\n')}
        contents.update(extra_contents or {})
        artifacts = []
        for index, (path, (category, body)) in enumerate(contents.items()):
            destination = candidate / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            artifacts.append({'id': 'artifact-' + str(index), 'path': path, 'category': category,
                              'audiences': ['engineer'], 'sha256': hashlib.sha256(body).hexdigest()})
        review = {'schema_version': 1, 'title': 'Synthetic deployment handoff',
                  'source_fingerprint': portal.source_fingerprint(state),
                  'context_sha256': portal.context_fingerprint(state),
                  'target': {'framework': framework, 'warehouse': warehouse},
                  'models': [], 'relationships': [], 'validation': [], 'artifacts': artifacts}
        review_path = self.root / (name + '-review.json')
        review_path.write_text(json.dumps(review))
        prepared = guided.record_handoff(run, review_path, candidate, audience='engineer')
        self.assertEqual(prepared['status'], 'handoff_prepared')
        self.assertFalse(prepared['readiness']['execution_authorized'])
        return run, candidate, review_path

    def make_plan(self, request=None, run=None, path=None):
        return deploy.create_plan(run or self.run, request or self.request, self.policy_path, path or self.plan_path)

    def sign(self, purpose, bindings, *, issuer=None, claims=None, **changes):
        issuer = issuer or ('validation-service' if purpose == 'deployment_acceptance' else 'approval-service')
        observed = datetime.now(timezone.utc)
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': purpose,
                   'issuer': issuer, 'actor': self.policy['issuers'][issuer]['actors'][0],
                   'mode': self.policy['mode'], 'id': purpose + '-fixture',
                   'review_reference': 'synthetic://independent-review/' + purpose,
                   'issued_at': (observed - timedelta(minutes=1)).isoformat(),
                   'expires_at': (observed + timedelta(minutes=20)).isoformat(), 'bindings': bindings}
        if claims is not None:
            payload['claims'] = claims
        payload.update(changes)
        return {'payload': payload, 'signature': base64.b64encode(self.keys[issuer].sign(canonical(payload))).decode()}

    def approvals(self, plan=None):
        plan = plan or self.plan
        return (self.sign('model_signoff', deploy.model_bindings(plan)),
                self.sign('deployment_approval', deploy.approval_bindings(plan)))

    def submit(self, transport, **kwargs):
        return deploy.submit(self.plan_path, self.policy_path, kwargs.pop('model', self.model),
                             kwargs.pop('approval', self.approval), transport=transport, **kwargs)

    def acceptance(self, record, checks=None, **kwargs):
        if checks is None:
            checks = [{'id': name, 'status': 'passed',
                       'evidence_sha256': hashlib.sha256(('independent fixture: ' + name).encode()).hexdigest(),
                       'evidence_reference': 'synthetic://validator-evidence/' + name} for name in CHECKS]
        return self.sign('deployment_acceptance', deploy.execution_bindings(record, self.plan),
                         claims={'checks': checks}, **kwargs)

    def test_prepared_handoff_to_signed_simulation_receipt_end_to_end(self):
        transport = ScriptedTransport(dbt_response())
        record = self.submit(transport)
        self.assertEqual(record['state'], 'verification_pending')
        self.assertEqual(len(transport.calls), 1)
        operation = transport.calls[0]
        self.assertEqual(operation['method'], 'POST')
        self.assertEqual(operation['url'], 'https://cloud.getdbt.com/api/v2/accounts/11/jobs/44/run/')
        self.assertEqual(operation['body']['git_sha'], COMMIT)
        snapshot = Path(record['snapshot'])
        for relative in ('models/orders.sql', 'macros/identity.sql', 'docs/release.md'):
            self.assertEqual((snapshot / relative).read_bytes(), (self.candidate / relative).read_bytes())
        final = deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record))
        self.assertEqual(final['state'], 'simulation_verified')
        self.assertNotEqual(final['state'], 'deployed_verified')
        self.assertEqual(deploy.status(self.policy_path, record['operation_id']), final)
        self.assertEqual(deploy.observe(self.policy_path, record['operation_id'], transport=transport), final)
        self.assertEqual(len(transport.calls), 1)
        self.assertFalse(guided.load_engagement(self.run)['readiness']['execution_authorized'])

    def test_unsigned_or_tampered_approval_has_zero_native_calls(self):
        for approval in ({'human_approved': True}, dict(self.approval, signature=base64.b64encode(b'0' * 64).decode())):
            transport = ScriptedTransport(dbt_response())
            with self.subTest(fields=list(approval)), self.assertRaises(ValueError):
                self.submit(transport, approval=approval)
            self.assertEqual(transport.calls, [])

    def test_expired_approval_has_zero_native_calls(self):
        approval = self.sign('deployment_approval', deploy.approval_bindings(self.plan),
                             expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        transport = ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError):
            self.submit(transport, approval=approval)
        self.assertEqual(transport.calls, [])

    def test_selected_model_drift_blocks_submit(self):
        (self.candidate / 'models/orders.sql').write_text('select 2 as order_id\n')
        transport = ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_unselected_but_prepared_macro_drift_blocks_submit(self):
        (self.candidate / 'macros/identity.sql').write_text('unreviewed macro\n')
        transport = ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def assert_drift_blocks_submit(self):
        transport = ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_source_drift_blocks_submit(self):
        (self.source / 'models/source.sql').write_text('select 7 as order_id\n')
        self.assert_drift_blocks_submit()

    def test_catalogue_drift_blocks_submit(self):
        self.catalogue.write_text('{"objects":[]}')
        self.assert_drift_blocks_submit()

    def test_discovery_drift_blocks_submit(self):
        guided.update_answers(self.run, {'priority_domain': 'Changed business scope'})
        self.assert_drift_blocks_submit()

    def test_changed_destination_or_runtime_policy_blocks_submit(self):
        for key, value in (('environment_id', 999), ('runtime_version', 'unqualified-runtime')):
            original = copy.deepcopy(self.policy)
            self.policy['destinations']['dev'][key] = value
            self.write_policy()
            transport = ScriptedTransport(dbt_response())
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.submit(transport)
            self.assertEqual(transport.calls, [])
            self.policy = original
            self.write_policy()

    def test_target_change_in_resealed_plan_invalidates_old_approval(self):
        changed = copy.deepcopy(self.plan)
        changed['target']['namespace']['schema'] = 'UNREVIEWED'
        changed['plan_sha256'] = hashlib.sha256(canonical({k: v for k, v in changed.items() if k != 'plan_sha256'})).hexdigest()
        self.plan_path.write_text(json.dumps(changed))
        transport = ScriptedTransport(dbt_response())
        with self.assertRaises(ValueError):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_required_acceptance_categories_cannot_be_removed_at_planning(self):
        request = dict(self.request, required_checks=['physical_schema'])
        with self.assertRaisesRegex(ValueError, 'cannot be removed'):
            self.make_plan(request, path=self.root / 'incomplete-plan.json')

    def test_development_action_rejects_production_destination(self):
        self.policy['destinations']['dev']['environment'] = 'production'
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'production'):
            self.make_plan(path=self.root / 'production-plan.json')

    def test_native_success_never_implies_acceptance_and_claimed_json_is_rejected(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        self.assertEqual(record['state'], 'verification_pending')
        with self.assertRaises(ValueError):
            deploy.accept(self.policy_path, record['operation_id'], {'passed': True, 'state': 'deployed_verified'})
        self.assertEqual(deploy.status(self.policy_path, record['operation_id'])['state'], 'verification_pending')

    def test_timeout_after_possible_acceptance_never_retries(self):
        transport = ScriptedTransport(TimeoutError('accepted remotely; response lost'))
        record = self.submit(transport)
        self.assertEqual(record['state'], 'unknown_remote_state')
        self.assertEqual(record['operations'][0]['state'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'active|recovery|replay'):
            self.submit(transport)
        with self.assertRaisesRegex(ValueError, 'identity is unknown'):
            deploy.observe(self.policy_path, record['operation_id'], transport=transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(deploy.status(self.policy_path, record['operation_id'])['state'], 'unknown_remote_state')

    def test_async_resume_polls_original_run_and_preserves_submission_count(self):
        transport = ScriptedTransport(dbt_response(3), dbt_response(3), dbt_response(10))
        record = self.submit(transport)
        self.assertEqual(record['state'], 'running')
        record = deploy.observe(self.policy_path, record['operation_id'], transport=transport)
        self.assertEqual(record['state'], 'running')
        record = deploy.observe(self.policy_path, record['operation_id'], transport=transport)
        self.assertEqual(record['state'], 'verification_pending')
        self.assertEqual([operation['method'] for operation in transport.calls], ['POST', 'GET', 'GET'])
        self.assertTrue(all(call['url'].endswith('/runs/901/') for call in transport.calls[1:]))

    def test_wrong_native_run_target_or_checkout_is_not_accepted(self):
        for field, value in (('git_sha', 'b' * 40), ('environment_id', 123)):
            with self.subTest(field=field):
                # The response contract itself is challenged before any result claim.
                operation = self.plan['native']['operations'][0]
                self.assertEqual(deploy._normalize(operation, dbt_response(**{field: value}))['state'], 'failed')

    def test_missing_native_response_identity_remains_unknown(self):
        record = self.submit(ScriptedTransport({'status_code': 200, 'body': {}}))
        self.assertEqual(record['state'], 'unknown_remote_state')

    def test_shared_runner_excludes_second_engagement_while_first_is_pending(self):
        first = self.submit(ScriptedTransport(dbt_response(3)))
        run, _, _ = self.make_handoff('second')
        second_path = self.root / 'second-plan.json'
        second = self.make_plan(dict(self.request, release_id='second-release'), run=run, path=second_path)
        model, approval = self.approvals(second)
        transport = ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError, 'active|recovery'):
            deploy.submit(second_path, self.policy_path, model, approval, transport=transport)
        self.assertEqual(transport.calls, [])
        self.assertEqual(deploy.status(self.policy_path, first['operation_id'])['state'], 'running')

    def test_runner_file_lock_blocks_concurrent_submit(self):
        transport = ScriptedTransport(dbt_response())
        with deploy._runner_lock(self.policy):
            with self.assertRaisesRegex(ValueError, 'busy|lock|another|writer'):
                self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_verified_plan_cannot_be_submitted_again(self):
        transport = ScriptedTransport(dbt_response())
        record = self.submit(transport)
        deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record))
        with self.assertRaisesRegex(ValueError, 'already submitted'):
            self.submit(transport)
        self.assertEqual(len(transport.calls), 1)

    def test_acceptance_requires_exact_unique_passed_check_set(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        good = self.acceptance(record)['payload']['claims']['checks']
        cases = [[], good[:-1], good + [copy.deepcopy(good[0])], good + [dict(good[0], id='extra-check')],
                 [dict(c, status='failed') if c['id'] == 'grain' else c for c in good],
                 [dict(c, evidence_sha256='not-a-digest') if c['id'] == 'metrics' else c for c in good],
                 [dict(c, evidence_reference='') if c['id'] == 'access' else c for c in good]]
        for index, checks in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record, checks))
        self.assertEqual(deploy.status(self.policy_path, record['operation_id'])['state'], 'verification_pending')

    def test_acceptance_binds_actual_attempt_target_and_receipts(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        for field in ('operation_id', 'target_sha256', 'native_receipts_sha256'):
            bindings = dict(deploy.execution_bindings(record, self.plan), **{field: 'b' * 64})
            attestation = self.sign('deployment_acceptance', bindings,
                                    claims=self.acceptance(record)['payload']['claims'])
            with self.subTest(field=field), self.assertRaises(ValueError):
                deploy.accept(self.policy_path, record['operation_id'], attestation)

    def test_acceptance_is_refused_until_native_execution_finishes(self):
        record = self.submit(ScriptedTransport(dbt_response(3)))
        with self.assertRaisesRegex(ValueError, 'complete'):
            deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record))

    def test_artifact_drift_after_execution_prevents_acceptance(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        attestation = self.acceptance(record)
        (self.candidate / 'models/orders.sql').write_text('select 8 as order_id')
        with self.assertRaises(ValueError):
            deploy.accept(self.policy_path, record['operation_id'], attestation)

    def test_journal_tampering_cannot_claim_verified(self):
        record = self.submit(ScriptedTransport(dbt_response(3)))
        path = Path(self.policy['state_root']) / 'operations' / record['operation_id'] / 'state.json'
        altered = json.loads(path.read_text())
        altered['state'] = 'deployed_verified'
        path.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            deploy.status(self.policy_path, record['operation_id'])

    def test_live_policy_refuses_injected_transport(self):
        self.policy['mode'] = 'live'
        self.write_policy()
        self.plan_path = self.root / 'live-plan.json'
        self.plan = self.make_plan()
        self.model, self.approval = self.approvals()
        self.approval = self.sign('deployment_approval', deploy.approval_bindings(self.plan),
            claims={'preflight': {'status': 'passed', 'target_sha256': deploy.digest(self.plan['target']),
                'runtime_version': 'qualified-fixture-1', 'principal_namespace_verified': True,
                'artifact_commit_verified': True, 'permissions_verified': True,
                'evidence_sha256': 'c' * 64, 'evidence_reference': 'synthetic://preflight/fixture'}})
        transport = ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError, 'Injected'):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_cli_approval_request_is_request_only_and_execution_needs_bootstrap_policy(self):
        output = self.root / 'approval-request.json'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(deploy.main(['approval-request', '--plan', str(self.plan_path), '--output', str(output)]), 0)
        request = json.loads(output.read_text())
        self.assertTrue(request['request_only'])
        self.assertNotIn('signature', request)
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(deploy.main(['status', '--operation', 'a' * 32]), 2)

    def test_publication_finishes_at_publication_without_deployment_acceptance(self):
        self.configure_publication()
        request = dict(self.request, action='publish_pr', artifacts=[{'path': 'docs/release.md', 'role': 'documentation'}],
                       publication={'repository': 'example/models', 'base': 'main', 'head': 'reviewed-release',
                                    'title': 'Reviewed synthetic change', 'body_artifact': 'docs/release.md'})
        self.plan_path = self.root / 'publication-plan.json'
        self.plan = self.make_plan(request)
        self.model, self.approval = self.approvals()
        calls = []
        frozen_remote = {'models/orders.sql': b'select 1 as order_id\n',
                         'macros/identity.sql': b'{% macro identity(x) %}{{ x }}{% endmacro %}\n'}

        def transport(operation):
            calls.append(copy.deepcopy(operation))
            contract = operation['contract']
            if contract == 'publication_head':
                body = {'sha': COMMIT}
            elif contract == 'publication_file':
                path = operation['argv'][2].split('/contents/', 1)[1].split('?ref=', 1)[0]
                self.assertIn(path, frozen_remote)
                self.assertTrue(operation['argv'][2].endswith('?ref=' + COMMIT))
                body = {'encoding': 'base64', 'content': base64.b64encode(frozen_remote[path]).decode()}
            elif contract == 'publication_pr':
                return {'exit_code': 0, 'stdout': 'https://github.com/example/models/pull/123\n'}
            elif contract == 'publication_verify':
                body = {'url': 'https://github.com/example/models/pull/123', 'headRefOid': COMMIT,
                        'baseRefName': 'main', 'headRefName': 'reviewed-release', 'state': 'OPEN'}
            else:
                raise AssertionError('Unexpected publication operation')
            return {'exit_code': 0, 'stdout': json.dumps(body)}

        record = self.submit(transport)
        self.assertEqual(record['state'], 'published')
        self.assertEqual(len(calls), 5)
        self.assertEqual([c['contract'] for c in calls],
                         ['publication_head', 'publication_file', 'publication_file', 'publication_pr', 'publication_verify'])
        with self.assertRaises(ValueError):
            deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record))

    def test_publication_remote_content_is_checked_before_creating_pr(self):
        self.configure_publication()
        request = dict(self.request, action='publish_pr', artifacts=[
            {'path': 'models/orders.sql', 'role': 'model_sql'},
            {'path': 'docs/release.md', 'role': 'documentation'}], publication={
                'repository': 'example/models', 'base': 'main', 'head': 'reviewed-release',
                'title': 'Reviewed change', 'body_artifact': 'docs/release.md'})
        self.plan_path = self.root / 'publication-content-plan.json'
        self.plan = self.make_plan(request)
        self.model, self.approval = self.approvals()
        transport = ScriptedTransport({'exit_code': 0, 'stdout': json.dumps({'sha': COMMIT})},
            {'exit_code': 0, 'stdout': json.dumps({'encoding': 'base64',
                'content': base64.b64encode(b'select 999 as order_id\n').decode()})})
        record = self.submit(transport)
        self.assertEqual(record['state'], 'failed')
        self.assertEqual(len(transport.calls), 2)
        self.assertFalse(any(call['effect'] == 'write' for call in transport.calls))

    def configure_publication(self):
        self.policy['publication_destinations'] = {'dev': {
            'repository': 'example/models', 'base': 'main', 'head': 'reviewed-release'}}
        self.write_policy()

    def publication_request(self, **changes):
        publication = {'repository': 'example/models', 'base': 'main', 'head': 'reviewed-release',
                       'title': 'Reviewed fixture', 'body_artifact': 'docs/release.md'}
        publication.update(changes)
        return dict(self.request, action='publish_pr',
                    artifacts=[{'path': 'docs/release.md', 'role': 'documentation'}], publication=publication)

    def journal_snapshot(self):
        root = Path(self.policy['state_root'])
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def replace_plan(self, **changes):
        edited = copy.deepcopy(self.plan)
        edited.update(changes)
        edited['plan_sha256'] = deploy.envelope_digest(edited, 'plan_sha256')
        self.plan_path.write_text(json.dumps(edited))
        return edited

    def test_publication_requires_exact_trusted_repository_base_and_head(self):
        with self.assertRaisesRegex(ValueError, 'not provisioned'):
            self.make_plan(self.publication_request(), path=self.root / 'missing-publication.json')
        self.configure_publication()
        for field, value in [('repository', 'other/models'), ('base', 'production'), ('head', 'unreviewed-release')]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'trusted destination'):
                self.make_plan(self.publication_request(**{field: value}), path=self.root / (field + '.json'))

    def test_publication_review_and_approval_show_exact_repository_refs_and_commit(self):
        self.configure_publication()
        plan = self.make_plan(self.publication_request(), path=self.root / 'review-publication.json')
        projection = deploy.review_projection(plan)
        for value in ('example/models', 'main', 'reviewed-release', COMMIT):
            self.assertIn(value, projection['plan']['summary'])
        self.assertEqual(projection['plan']['target_label'], 'example/models / main')
        self.assertEqual(deploy.approval_bindings(plan)['publication_destination_sha256'],
                         deploy.digest(self.policy['publication_destinations']['dev']))
        self.assertEqual(plan['publication_destination'], self.policy['publication_destinations']['dev'])

    def test_publication_cannot_relabel_implementation_or_use_code_as_body(self):
        self.configure_publication()
        request = self.publication_request()
        request['artifacts'] += [{'path': 'models/orders.sql', 'role': 'documentation'},
                                 {'path': 'macros/identity.sql', 'role': 'documentation'}]
        with self.assertRaisesRegex(ValueError, 'relabeled'):
            self.make_plan(request, path=self.root / 'relabeled.json')
        with self.assertRaisesRegex(ValueError, 'plain-text documentation'):
            self.make_plan(self.publication_request(body_artifact='models/orders.sql'), path=self.root / 'code-body.json')

    def test_publication_verifies_nonbody_documentation_and_all_implementation(self):
        self.configure_publication()
        run, _, _ = self.make_handoff('publication-docs', extra_contents={
            'docs/guide.md': ('documentation', b'Separately reviewed guide.\n'),
            'dbt_project.yml': ('implementation', b'name: reviewed_model\n')})
        request = self.publication_request()
        request['artifacts'].append({'path': 'docs/guide.md', 'role': 'documentation'})
        plan = self.make_plan(request, run=run, path=self.root / 'all-publication-files.json')
        checked = [operation['argv'][2].split('/contents/')[1].split('?ref=')[0]
                   for operation in plan['native']['operations'] if operation['contract'] == 'publication_file']
        self.assertEqual(set(checked), {'docs/guide.md', 'models/orders.sql', 'macros/identity.sql', 'dbt_project.yml'})

    def test_acceptance_rejects_resealed_required_checks_without_journal_mutation(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        before = self.journal_snapshot()
        edited = self.replace_plan(required_checks=[])
        attestation = self.sign('deployment_acceptance', deploy.execution_bindings(record, edited), claims={'checks': []})
        with self.assertRaisesRegex(ValueError, 'Recorded plan changed'):
            deploy.accept(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(self.journal_snapshot(), before)

    def test_simulation_cannot_be_upgraded_with_resealed_live_plan_and_fresh_acceptance(self):
        transport = ScriptedTransport(dbt_response())
        record = self.submit(transport)
        before = self.journal_snapshot()
        self.policy['mode'] = 'live'
        self.write_policy()
        edited = self.replace_plan(mode='live', policy_sha256=deploy.digest(self.policy))
        attestation = self.sign('deployment_acceptance', deploy.execution_bindings(record, edited),
                                claims=self.acceptance(record)['payload']['claims'])
        with self.assertRaisesRegex(ValueError, 'Recorded plan changed'):
            deploy.accept(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(self.journal_snapshot(), before)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(deploy.status(self.policy_path, record['operation_id'])['mode'], 'simulation')

    def test_reconciliation_rejects_plan_drift_before_journal_or_native_call(self):
        record = self.submit(ScriptedTransport(TimeoutError('fixture timeout')))
        before = self.journal_snapshot()
        edited = self.replace_plan(required_checks=[])
        receipt = {'adapter': 'dbt_platform', 'operation_id': 'dbt-run', 'native_id': 901,
                   'target_sha256': deploy.digest(edited['target']), 'state': 'running'}
        attestation = self.sign('deployment_reconciliation', deploy.recovery_bindings(record, edited),
                                issuer='validation-service', claims={'receipt': receipt})
        transport = ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError, 'Recorded plan changed'):
            deploy.reconcile(self.policy_path, record['operation_id'], attestation, transport=transport)
        self.assertEqual(self.journal_snapshot(), before)
        self.assertEqual(transport.calls, [])

    def test_recovery_preserves_original_policy_and_allows_candidate_drift(self):
        record = self.submit(ScriptedTransport(TimeoutError('fixture timeout')))
        before = self.journal_snapshot()
        self.policy['runner_id'] = 'rotated-runner'
        self.write_policy()
        attestation = self.sign('deployment_recovery', deploy.recovery_bindings(record, self.plan),
            issuer='validation-service', claims={'remote_quiescent': True, 'recovery_verified': True,
                'evidence_sha256': 'd' * 64, 'evidence_reference': 'synthetic://recovery/901'})
        with self.assertRaisesRegex(ValueError, 'Recorded runner policy changed'):
            deploy.recover(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(self.journal_snapshot(), before)
        self.policy['runner_id'] = 'synthetic-runner'
        self.write_policy()
        (self.candidate / 'models/orders.sql').write_text('select 2 as order_id\n')
        recovered = deploy.recover(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(recovered['state'], 'recovered')

    def test_record_binding_checks_each_immutable_obligation(self):
        record = self.submit(ScriptedTransport(dbt_response()))
        for field, value in [('plan_sha256', 'f' * 64), ('policy_sha256', 'f' * 64),
                             ('target_sha256', 'f' * 64), ('mode', 'live'), ('bindings', {}),
                             ('required_checks', []), ('action', 'publish_pr'), ('destination_id', 'other')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                deploy._record_plan(dict(record, **{field: value}), self.plan, self.policy)

    def test_observe_rejects_policy_drift_without_native_call_or_journal_mutation(self):
        record = self.submit(ScriptedTransport(dbt_response(3)))
        before = self.journal_snapshot()
        self.policy['runner_id'] = 'unreviewed-runner'
        self.write_policy()
        transport = ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError, 'Recorded runner policy changed'):
            deploy.observe(self.policy_path, record['operation_id'], transport=transport)
        self.assertEqual(self.journal_snapshot(), before)
        self.assertEqual(transport.calls, [])

    def test_cancel_acknowledgement_holds_lock_until_independent_recovery(self):
        transport = ScriptedTransport(dbt_response(3), {'status_code': 200, 'body': {}}, dbt_response(30))
        record = self.submit(transport)
        record = deploy.observe(self.policy_path, record['operation_id'], cancel=True, transport=transport)
        self.assertEqual(record['state'], 'cancel_requested')
        record = deploy.observe(self.policy_path, record['operation_id'], transport=transport)
        self.assertEqual(record['state'], 'cancelled')
        with self.assertRaises(ValueError):
            self.submit(transport)
        attestation = self.sign('deployment_recovery', deploy.recovery_bindings(record, self.plan),
            issuer='validation-service', claims={'remote_quiescent': True, 'recovery_verified': True,
                'evidence_sha256': 'd' * 64, 'evidence_reference': 'synthetic://recovery/901'})
        recovered = deploy.recover(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(recovered['state'], 'recovered')
        self.assertEqual(len(transport.calls), 3)
        # Recovery releases the shared lock, but never replays the old plan.
        with self.assertRaisesRegex(ValueError, 'already submitted'):
            self.submit(transport)

    def test_recovery_requires_quiescence_and_exact_current_journal(self):
        record = self.submit(ScriptedTransport(TimeoutError('uncertain remote acceptance')))
        good = {'remote_quiescent': True, 'recovery_verified': True, 'evidence_sha256': 'd' * 64,
                'evidence_reference': 'synthetic://recovery/901'}
        for claims in (dict(good, remote_quiescent=False), dict(good, recovery_verified=False),
                       dict(good, evidence_sha256='missing')):
            attestation = self.sign('deployment_recovery', deploy.recovery_bindings(record, self.plan),
                issuer='validation-service', claims=claims)
            with self.assertRaises(ValueError):
                deploy.recover(self.policy_path, record['operation_id'], attestation)
        wrong = dict(deploy.recovery_bindings(record, self.plan), journal_head_sha256='f' * 64)
        attestation = self.sign('deployment_recovery', wrong, issuer='validation-service', claims=good)
        with self.assertRaises(ValueError):
            deploy.recover(self.policy_path, record['operation_id'], attestation)
        self.assertEqual(deploy.status(self.policy_path, record['operation_id'])['state'], 'unknown_remote_state')

    def test_independent_reconciliation_only_polls_located_run(self):
        transport = ScriptedTransport(TimeoutError('accepted; response lost'), dbt_response())
        record = self.submit(transport)
        receipt = {'adapter': 'dbt_platform', 'operation_id': 'dbt-run', 'native_id': 901,
                   'target_sha256': hashlib.sha256(canonical(self.plan['target'])).hexdigest(), 'state': 'running'}
        attestation = self.sign('deployment_reconciliation', deploy.recovery_bindings(record, self.plan),
            issuer='validation-service', claims={'receipt': receipt})
        reconciled = deploy.reconcile(self.policy_path, record['operation_id'], attestation, transport=transport)
        self.assertEqual(reconciled['state'], 'verification_pending')
        self.assertEqual([call['method'] for call in transport.calls], ['POST', 'GET'])
        self.assertTrue(transport.calls[-1]['url'].endswith('/runs/901/'))

    def test_reconciliation_rejects_wrong_operation_without_native_call(self):
        transport = ScriptedTransport(TimeoutError('unknown'))
        record = self.submit(transport)
        receipt = {'adapter': 'dbt_platform', 'operation_id': 'wrong-operation', 'native_id': 901,
                   'target_sha256': hashlib.sha256(canonical(self.plan['target'])).hexdigest(), 'state': 'running'}
        attestation = self.sign('deployment_reconciliation', deploy.recovery_bindings(record, self.plan),
            issuer='validation-service', claims={'receipt': receipt})
        with self.assertRaises(ValueError):
            deploy.reconcile(self.policy_path, record['operation_id'], attestation, transport=transport)
        self.assertEqual(len(transport.calls), 1)

    def test_acceptance_issuer_must_differ_even_when_policy_allows_both_purposes(self):
        self.policy['issuers']['approval-service']['purposes'].append('deployment_acceptance')
        self.write_policy()
        self.plan_path = self.root / 'two-purpose-plan.json'
        self.plan = self.make_plan()
        self.model, self.approval = self.approvals()
        record = self.submit(ScriptedTransport(dbt_response()))
        attestation = self.acceptance(record, issuer='approval-service')
        with self.assertRaisesRegex(ValueError, 'independent'):
            deploy.accept(self.policy_path, record['operation_id'], attestation)

    def test_simulation_attestation_cannot_authorize_live_policy(self):
        self.policy['mode'] = 'live'
        self.write_policy()
        self.plan_path = self.root / 'simulation-mismatch-plan.json'
        self.plan = self.make_plan()
        self.model = self.sign('model_signoff', deploy.model_bindings(self.plan), mode='simulation')
        self.approval = self.sign('deployment_approval', deploy.approval_bindings(self.plan), mode='simulation')
        transport = ScriptedTransport(dbt_response())
        with self.assertRaisesRegex(ValueError, 'Simulation'):
            self.submit(transport)
        self.assertEqual(transport.calls, [])

    def test_coalesce_live_continuation_gap_is_visible_and_blocks_before_submission(self):
        self.policy['mode'] = 'live'
        self.policy['destinations']['dev'] = {
            'adapter': 'coalesce', 'framework': 'coalesce', 'warehouse': 'snowflake',
            'environment': 'development', 'namespace': {'database': 'TEST_DB', 'schema': 'GOLD'},
            'identity': 'synthetic-service', 'runtime_version': 'qualified-fixture-1',
            'base_url': 'https://app.eu.coalescesoftware.io', 'profile': 'test',
            'environment_id': 33, 'job_id': 44, 'auth_env': {'config': 'COA_CONFIG'}}
        self.write_policy()
        # Exercise the approval/preflight gate with an externally signed scoped
        # plan. Collector capability coverage is separate from this unit test.
        self.plan = dict(self.plan, mode='live', target=self.policy['destinations']['dev'],
                         policy_sha256=deploy.digest(self.policy))
        self.plan['plan_sha256'] = deploy.envelope_digest(self.plan, 'plan_sha256')
        self.model, self.approval = self.approvals()
        projection = deploy.review_projection(self.plan)
        self.assertIn('live execution is blocked', projection['plan']['summary'])
        self.assertTrue(any('profile-domain' in item for item in projection['plan']['prerequisites']))
        with patch('subprocess.Popen') as process, self.assertRaisesRegex(ValueError, 'Coalesce live execution is unavailable'):
            deploy._approval(self.plan, self.policy, self.model, self.approval)
        process.assert_not_called()
        self.assertFalse(Path(self.policy['state_root']).exists())

    def test_bundle_submission_and_verified_summary_require_independent_acceptance(self):
        self.run, self.candidate, self.review = self.make_handoff('bundle', framework='native_sql',
            warehouse='databricks', extra_contents={'databricks.yml': ('implementation', b'bundle:\n  name: models\n')})
        self.policy['destinations']['dev'] = {
            'adapter': 'databricks_bundle', 'framework': 'native_sql', 'warehouse': 'databricks',
            'environment': 'development', 'namespace': {'catalog': 'test', 'schema': 'gold'},
            'identity': 'synthetic-service', 'runtime_version': 'qualified-fixture-1',
            'base_url': 'https://example.cloud.databricks.com', 'profile': 'test',
            'bundle_name': 'models', 'bundle_target': 'test', 'workspace_root': '/Workspace/models/test',
            'auth_env': {'token': 'DATABRICKS_TOKEN'}}
        self.write_policy()
        self.plan_path = self.root / 'bundle-plan.json'
        self.plan = self.make_plan(dict(self.request, artifacts=[{'path': 'databricks.yml', 'role': 'project_file'}]))
        self.model, self.approval = self.approvals()
        transport = ScriptedTransport({'exit_code': 0, 'body': {}}, {'exit_code': 0, 'body': {
            'bundle': {'name': 'models', 'target': 'test'},
            'workspace': {'host': 'https://example.cloud.databricks.com', 'root_path': '/Workspace/models/test'},
            'resources': {'jobs': {'models': {'id': '42'}}}}})
        record = self.submit(transport)
        self.assertEqual(record['state'], 'verification_pending')
        self.assertEqual([item['receipt']['state'] for item in record['operations']], ['submitted', 'succeeded'])
        accepted = deploy.accept(self.policy_path, record['operation_id'], self.acceptance(record))
        self.assertEqual(accepted['state'], 'simulation_verified')
        self.assertEqual(len(transport.calls), 2)


if __name__ == '__main__':
    unittest.main()
