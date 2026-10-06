"""Independent Package 2 boundaries; synthetic inputs and observed callbacks only.

No generator baseline, live host, authentication claim or native qualification.
The frozen corpus remains read-only. Tests own temporary copies of interfaces.
"""
import contextlib
import copy
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'skills/data-model-accelerator/scripts'
CORPUS = REPO / 'tests/fixtures/omni_modeler'
sys.path.insert(0, str(SCRIPTS))

import omni_modeler as modeler
import omni_contract
from omni_knowledge import KnowledgeError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def synthetic_classification():
    """A declared fixture gate, never an actual reviewer authentication."""
    return {'schema_version': 1, 'kind': 'sensitive_data_classification',
            'sensitivity': 'PUBLIC', 'categories': [], 'categories_known': True,
            'review_status': 'approved', 'review_reference': 'corpus-declared-review-only',
            'evidence': [{'reference': 'synthetic-corpus', 'sha256': '6' * 64}],
            'lineage': {'status': 'complete', 'upstream_ids': [], 'transformation': 'source'},
            'handling': {key: 'allow' for key in ('agent_input', 'metadata', 'ai_context', 'share')}}


def synthetic_policy():
    return {'schema_version': 1, 'kind': 'disclosure_policy',
            'policy_id': 'corpus-local-only', 'review_status': 'approved',
            'review_reference': 'corpus-declared-policy-only',
            'evidence': [{'reference': 'synthetic-corpus-policy', 'sha256': '7' * 64}],
            'destinations': {key: {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
                             for key in ('agent_input', 'metadata', 'ai_context', 'share')},
            'host_boundary': {'mode': 'presanitized_only',
                              'evidence_reference': 'fixture-only-no-host-containment-claim'}}


class IndependentModelerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tmp = Path(self.temporary.name).resolve()
        self.skill = self.tmp / 'interface-snapshot'
        shutil.copytree(SCRIPTS.parent, self.skill,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'examples'))
        self.context = json.loads((CORPUS / 'context.json').read_text())
        self.files = {'orders.view': (CORPUS / 'source/auth_noop_orders.view').read_text(),
                      'orders.topic': (CORPUS / 'source/auth_noop_orders.topic').read_text()}
        self.projection = {
            'definitions': {'shipping': {'grain': 'order_id', 'unit': 'integer_cents'},
                            'escaped/metric': 'A source key requiring JSON Pointer escaping',
                            'array': ['first', 'second']},
            'source_files': copy.deepcopy(self.files),
            'model_context': copy.deepcopy(self.context)}
        self.classification = synthetic_classification()
        self.policy = synthetic_policy()
        # A network attempt is a test failure; no usable endpoint or credential
        # is needed by this package's host callback interface.
        self.addCleanup(patch.stopall)
        patch('socket.create_connection', side_effect=AssertionError('network forbidden')).start()
        patch('socket.socket.connect', side_effect=AssertionError('network forbidden')).start()
        self.task = self.prepare()

    def prepare(self, **overrides):
        args = {'run_id': 'independent-corpus', 'projection': self.projection,
                'classification': self.classification, 'policy': self.policy,
                'intent': 'refactor', 'warehouse': 'snowflake',
                'objects': ['views', 'topics'], 'operations': ['inspect', 'preserve', 'generate'],
                'knowledge_root': self.skill}
        args.update(overrides)
        return modeler.prepare_task(**args)

    def result(self, task=None):
        return {'schema_version': 1, 'kind': 'omni_modeler_result',
                'task_sha256': (task or self.task)['task_sha256'],
                'model_files': copy.deepcopy(self.files), 'model_context': copy.deepcopy(self.context),
                'decisions': [{'id': 'keep-shipping-grain', 'status': 'proposed',
                               'reason': 'Shipping is additive once per order.',
                               'source_refs': ['/definitions/shipping']}], 'gaps': []}

    def run_callback(self, callback=None, **overrides):
        if callback is None:
            callback = lambda *args: {'execution_id': 'observed-corpus-callback', 'result': self.result()}
        args = {'task': self.task, 'projection': self.projection,
                'classification': self.classification, 'policy': self.policy,
                'host': 'codex', 'mode': 'simulation', 'runner': callback, 'knowledge_root': self.skill}
        args.update(overrides)
        return modeler.run_task(**args)

    def assert_failed_redacted(self, observed, marker=None):
        self.assertEqual(observed['receipt']['state'], 'failed', observed)
        self.assertEqual(observed['receipt']['events'], ['planned', 'running', 'failed'])
        self.assertTrue(observed['receipt']['runner_invoked'])
        self.assertIsNone(observed['receipt']['execution_id'])
        self.assertIsNone(observed['receipt']['result_sha256'])
        self.assertIsNone(observed['result'])
        if marker:
            self.assertNotIn(marker, json.dumps(observed))

    def assert_candidate_runtime_outcome(self, observed):
        """Missing optional runtimes retain all boundary checks without passing SQL."""
        receipt = observed['receipt']
        if omni_contract.yaml is not None and omni_contract.sqlglot is not None:
            self.assertEqual(receipt['state'], 'completed')
            self.assertEqual(receipt['static_check']['status'], 'passed')
        else:
            self.assertEqual(receipt['state'], 'needs_review')
            self.assertEqual(receipt['static_check']['status'], 'unsupported')
            codes = {row['code'] for row in receipt['static_check']['findings']}
            self.assertTrue(codes & {'runtime.yaml_unavailable', 'sql.runtime_or_dialect_unavailable'}, codes)

    def cli_request(self):
        return {'run_id': 'offline-request', 'projection': self.projection,
                'classification': self.classification, 'policy': self.policy,
                'intent': 'refactor', 'warehouse': 'snowflake',
                'objects': ['views'], 'operations': ['inspect']}

    def invoke_prepare_cli(self, request, output):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status = modeler.main(['prepare', '--request', str(request), '--output', str(output)])
        return status, json.loads(captured.getvalue())

    def test_frozen_corpus_is_unchanged(self):
        frozen = json.loads((CORPUS / 'FROZEN_SHA256.json').read_text())
        for path, expected in frozen['files'].items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((CORPUS / path).read_bytes()).hexdigest(), expected)

    def test_completed_requires_observed_callback_but_never_authenticates_host_or_authority(self):
        before = copy.deepcopy((self.task, self.projection, self.classification, self.policy))
        calls = []
        def callback(task, projection, knowledge):
            calls.append((task, projection, knowledge))
            self.assertEqual(task, self.task)
            self.assertEqual(projection, self.projection)
            self.assertEqual(knowledge['knowledge_sha256'], task['knowledge_sha256'])
            projection['definitions']['shipping']['unit'] = 'callback-local mutation'
            task['permissions']['deployment'] = True
            return {'execution_id': 'actual-callback-entry', 'result': self.result()}
        observed = self.run_callback(callback)
        self.assertEqual(len(calls), 1)
        self.assert_candidate_runtime_outcome(observed)
        self.assertEqual(observed['receipt']['execution_id'], 'actual-callback-entry')
        self.assertEqual(observed['receipt']['result_sha256'], digest(observed['result']))
        self.assertEqual(before, (self.task, self.projection, self.classification, self.policy))
        for key in ('native_verified', 'deployment_authorized', 'host_identity_authenticated',
                    'independent_reasoning_verified'):
            self.assertIs(observed['receipt'][key], False)

    def test_no_adapter_is_unavailable_and_imported_result_is_not_a_runner(self):
        for host in modeler.HOSTS:
            result = self.run_callback(host=host, runner=None)
            self.assertEqual(result['receipt']['state'], 'unavailable')
            self.assertFalse(result['receipt']['runner_invoked'])
            self.assertEqual(result['receipt']['events'], ['planned', 'unavailable'])
        with self.assertRaises(modeler.ModelerError):
            self.run_callback(runner={'execution_id': 'invented', 'result': self.result()})

    def test_provider_exception_and_sensitive_result_do_not_escape(self):
        marker = 'SYNTHETIC_PHI_CANARY'
        def fail(*args):
            raise RuntimeError('provider detail ' + marker)
        self.assert_failed_redacted(self.run_callback(fail), marker)
        for location in ('execution', 'reason', 'source_sql'):
            result = self.result(); execution = 'observed'
            if location == 'execution': execution = marker
            elif location == 'reason': result['decisions'][0]['reason'] = marker
            else: result['model_files']['orders.view'] += '\n# ' + marker + '\n'
            with self.subTest(location=location):
                self.assert_failed_redacted(self.run_callback(
                    lambda *a: {'execution_id': execution, 'result': result}), marker)

    def test_sensitive_task_and_projection_block_before_callback(self):
        for target in ('run_id', 'projection'):
            args = {'run_id': 'SYNTHETIC_PHI_CANARY'} if target == 'run_id' else {
                'projection': {'source': 'SYNTHETIC_PHI_CANARY'}}
            with self.subTest(target=target), self.assertRaises(modeler.ModelerError):
                self.prepare(**args)

    def test_sensitive_pinned_knowledge_is_scanned_before_callback(self):
        path = self.skill / 'assets/omni-knowledge.json'
        manifest = json.loads(path.read_text())
        module = manifest['modules']['core']
        target = self.skill / module['path']
        target.write_text(target.read_text() + '\nSYNTHETIC_PHI_CANARY\n')
        module['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest))
        task = self.prepare()
        calls = []
        with self.assertRaises(modeler.ModelerError):
            self.run_callback(lambda *a: calls.append(a), task=task)
        self.assertEqual(calls, [])

    def test_claimed_enforcement_is_denied_for_every_execution_mode(self):
        for mode in ('inline', 'delegated', 'simulation'):
            policy = copy.deepcopy(self.policy)
            policy['host_boundary']['mode'] = 'claimed_enforced'
            calls = []
            with self.subTest(mode=mode), self.assertRaises(modeler.ModelerError):
                self.run_callback(lambda *a: calls.append(a), policy=policy, mode=mode)
            self.assertEqual(calls, [])

    def test_all_protected_categories_and_unapproved_declarations_are_noops(self):
        for mutation in ('PII', 'PCI', 'PHI', 'classification-proposed', 'policy-proposed'):
            classification, policy = copy.deepcopy((self.classification, self.policy))
            if mutation in ('PII', 'PCI', 'PHI'):
                classification['categories'] = [mutation]
                policy['destinations']['agent_input']['allowed_categories'] = [mutation]
            elif mutation == 'classification-proposed': classification['review_status'] = 'proposed'
            else: policy['review_status'] = 'proposed'
            calls = []
            with self.subTest(mutation=mutation), self.assertRaises(modeler.ModelerError):
                self.run_callback(lambda *a: calls.append(a), classification=classification, policy=policy)
            self.assertEqual(calls, [])

    def test_input_freshness_is_rechecked_after_callback(self):
        for surface in ('projection', 'context', 'classification', 'policy', 'task'):
            task, projection, classification, policy = copy.deepcopy(
                (self.task, self.projection, self.classification, self.policy))
            def callback(*args):
                if surface == 'projection': projection['definitions']['shipping']['unit'] = 'changed'
                elif surface == 'context': projection['model_context']['catalogue_sha256'] = 'e' * 64
                elif surface == 'classification': classification['review_reference'] = 'changed'
                elif surface == 'policy': policy['review_reference'] = 'changed'
                else: task['permissions']['external_writes'] = True
                return {'execution_id': 'observed-change', 'result': self.result()}
            with self.subTest(surface=surface):
                self.assert_failed_redacted(self.run_callback(callback, task=task, projection=projection,
                    classification=classification, policy=policy))

    def test_knowledge_freshness_is_rechecked_after_callback(self):
        manifest_path = self.skill / 'assets/omni-knowledge.json'
        original_manifest = manifest_path.read_bytes()
        for surface in ('manifest', 'module'):
            manifest = json.loads(original_manifest)
            module = self.skill / manifest['modules']['core']['path']
            original_module = module.read_bytes()
            def callback(*args):
                if surface == 'manifest':
                    manifest['version'] += '-changed-during-callback'
                    manifest_path.write_text(json.dumps(manifest))
                else: module.write_bytes(original_module + b'\nChanged during callback.\n')
                return {'execution_id': 'observed-knowledge-change', 'result': self.result()}
            try:
                with self.subTest(surface=surface):
                    self.assert_failed_redacted(self.run_callback(callback))
            finally:
                manifest_path.write_bytes(original_manifest)
                module.write_bytes(original_module)

    def test_knowledge_review_expiring_inside_callback_cannot_complete(self):
        class AfterReviewWindow(date):
            @classmethod
            def today(cls):
                return cls(2099, 1, 1)
        clock = patch('omni_knowledge.date', AfterReviewWindow)
        def callback(*args):
            clock.start()
            return {'execution_id': 'observed-expiry', 'result': self.result()}
        try:
            self.assert_failed_redacted(self.run_callback(callback))
        finally:
            clock.stop()

    def test_invalid_callback_and_fabricated_result_envelopes_fail(self):
        for change in ('empty', 'extra', 'wrong-task', 'approved-claim', 'unhashable-id', 'context-drift'):
            result = self.result()
            observed = {'execution_id': 'observed', 'result': result}
            if change == 'empty': observed = {}
            elif change == 'extra': observed['host_authenticated'] = True
            elif change == 'wrong-task': result['task_sha256'] = 'f' * 64
            elif change == 'approved-claim': result['human_approved'] = True
            elif change == 'unhashable-id': observed['execution_id'] = []
            else: result['model_context']['bindings']['orders']['namespace']['schema'] = 'OTHER'
            with self.subTest(change=change):
                self.assert_failed_redacted(self.run_callback(lambda *a: observed))

    def test_source_refs_must_resolve_in_the_exact_projection(self):
        for ref in ('/missing', '/definitions/array/-1', '/definitions/array/02',
                    '/definitions/escaped~2metric', 'definitions/shipping'):
            result = self.result(); result['decisions'][0]['source_refs'] = [ref]
            with self.subTest(ref=ref):
                self.assert_failed_redacted(self.run_callback(
                    lambda *a: {'execution_id': 'observed', 'result': result}))
        result = self.result(); result['decisions'][0]['source_refs'] = ['/definitions/escaped~1metric']
        self.assert_candidate_runtime_outcome(self.run_callback(
            lambda *a: {'execution_id': 'observed', 'result': result}))

    def test_unhashable_result_collections_fail_with_value_free_diagnostics(self):
        for field, value in (('model_files', []), ('decisions', {}), ('gaps', [[]])):
            result = self.result(); result[field] = value
            with self.subTest(field=field):
                self.assert_failed_redacted(self.run_callback(
                    lambda *a: {'execution_id': 'observed', 'result': result}))
        for field in ('id', 'status', 'source_refs'):
            result = self.result(); result['decisions'][0][field] = [{}]
            with self.subTest(field=field):
                self.assert_failed_redacted(self.run_callback(
                    lambda *a: {'execution_id': 'observed', 'result': result}))

    def test_malformed_prepare_selections_have_a_stable_boundary_error(self):
        for field, value in (('objects', None), ('operations', 4), ('objects', [[]]),
                             ('operations', [{}]), ('warehouse', {}), ('intent', [])):
            with self.subTest(field=field, value=value), self.assertRaises(modeler.ModelerError):
                self.prepare(**{field: value})

    def test_missing_candidate_and_explicit_partial_result_are_distinct(self):
        result = self.result(); result['model_files'] = {}; result['model_context'] = None
        self.assert_failed_redacted(self.run_callback(lambda *a: {'execution_id': 'observed', 'result': result}))
        result['gaps'] = [{'code': 'unsupported_query_view', 'scope': 'candidate'}]
        observed = self.run_callback(lambda *a: {'execution_id': 'observed', 'result': result})
        self.assertEqual(observed['receipt']['state'], 'needs_review')
        self.assertEqual(observed['receipt']['static_check']['status'], 'not_applicable')
        self.assertIsNotNone(observed['result'])

    def test_assessment_without_candidate_has_only_structural_completion(self):
        task = self.prepare(intent='assessment', operations=['inspect'])
        result = self.result(task); result['model_files'] = {}; result['model_context'] = None
        observed = self.run_callback(lambda *a: {'execution_id': 'observed', 'result': result}, task=task)
        self.assertEqual(observed['receipt']['state'], 'completed')
        self.assertFalse(observed['receipt']['native_verified'])
        self.assertFalse(observed['receipt']['independent_reasoning_verified'])

    def test_unresolved_decision_is_partial_even_when_gap_list_is_empty(self):
        result = self.result(); result['decisions'][0]['status'] = 'unresolved'
        observed = self.run_callback(lambda *a: {'execution_id': 'observed', 'result': result})
        self.assertEqual(observed['receipt']['state'], 'needs_review')

    def test_unsupported_native_construct_is_retained_for_review(self):
        result = self.result()
        result['model_files']['orders.view'] += '\nfuture_extension: true\n'
        observed = self.run_callback(lambda *a: {'execution_id': 'observed', 'result': result})
        self.assertEqual(observed['receipt']['state'], 'needs_review')
        self.assertEqual(observed['result']['model_files'], result['model_files'])
        self.assertNotEqual(observed['receipt']['static_check']['status'], 'passed')

    def test_installation_refuses_direct_root_and_nested_file_symlinks(self):
        linked = self.tmp / 'linked-install'; linked.symlink_to(self.skill, target_is_directory=True)
        with self.assertRaises(modeler.ModelerError):
            modeler.inspect_installation(linked, expected=self.skill)
        actual = self.tmp / 'actual'; shutil.copytree(self.skill, actual)
        linked_file = actual / 'scripts/omni_modeler.py'; linked_file.unlink()
        linked_file.symlink_to(self.skill / 'scripts/omni_modeler.py')
        with self.assertRaises(modeler.ModelerError):
            modeler.inspect_installation(actual, expected=self.skill)

    def test_installation_refuses_symlinked_ancestor(self):
        link = self.tmp / 'linked-parent'; link.symlink_to(self.tmp, target_is_directory=True)
        with self.assertRaises(modeler.ModelerError):
            modeler.inspect_installation(link / self.skill.name, expected=self.skill)

    def test_knowledge_reference_symlink_is_refused_before_callback(self):
        manifest = json.loads((self.skill / 'assets/omni-knowledge.json').read_text())
        target = self.skill / manifest['modules']['core']['path']
        saved = self.tmp / 'external-module'; saved.write_bytes(target.read_bytes())
        target.unlink(); target.symlink_to(saved)
        calls = []
        with self.assertRaises((modeler.ModelerError, KnowledgeError)):
            self.run_callback(lambda *a: calls.append(a))
        self.assertEqual(calls, [])

    def test_cli_refuses_direct_request_symlink_without_output(self):
        request = self.tmp / 'request.json'; request.write_text(json.dumps(self.cli_request()))
        linked = self.tmp / 'request-link.json'; linked.symlink_to(request)
        output = self.tmp / 'task.json'
        status, report = self.invoke_prepare_cli(linked, output)
        self.assertEqual(status, 2)
        self.assertEqual(report['status'], 'blocked')
        self.assertFalse(output.exists())

    def test_cli_refuses_request_with_symlinked_ancestor_without_output(self):
        inputs = self.tmp / 'inputs'; inputs.mkdir()
        request = inputs / 'request.json'; request.write_text(json.dumps(self.cli_request()))
        linked = self.tmp / 'linked-inputs'; linked.symlink_to(inputs, target_is_directory=True)
        output = self.tmp / 'task.json'
        status, report = self.invoke_prepare_cli(linked / 'request.json', output)
        self.assertEqual(status, 2, report)
        self.assertFalse(output.exists())

    def test_cli_refuses_output_with_symlinked_ancestor(self):
        request = self.tmp / 'request.json'; request.write_text(json.dumps(self.cli_request()))
        outputs = self.tmp / 'outputs'; outputs.mkdir()
        linked = self.tmp / 'linked-output'; linked.symlink_to(outputs, target_is_directory=True)
        status, report = self.invoke_prepare_cli(request, linked / 'task.json')
        self.assertEqual(status, 2, report)
        self.assertFalse((outputs / 'task.json').exists())


if __name__ == '__main__':
    unittest.main()
