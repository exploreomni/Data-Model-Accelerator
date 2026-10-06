"""A task plan, an observed callback and native acceptance are distinct."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_modeler as modeler
import omni_contract as omni
import plan_specialists as planner
from test_privacy_contract import approved_classification, approved_policy
from test_omni_contract import files, context


class ModelerTests(unittest.TestCase):
    def setUp(self):
        self.projection = {'definitions': {'total': 'Reviewed synthetic sum'}, 'model_context': context()}
        self.classification, self.policy = approved_classification(), approved_policy()
        self.task = modeler.prepare_task('trial-1', self.projection, self.classification, self.policy,
                                         intent='refactor', warehouse='snowflake')

    def result(self):
        return {'schema_version': 1, 'kind': 'omni_modeler_result',
                'task_sha256': self.task['task_sha256'], 'model_files': files(),
                'model_context': context(), 'decisions': [{'id': 'metric', 'status': 'proposed',
                    'reason': 'Preserve reviewed definition', 'source_refs': ['/definitions/total']}], 'gaps': []}

    def run_result(self, result=None, **kw):
        return modeler.run_task(self.task, self.projection, self.classification, self.policy,
            host='codex', mode='simulation', runner=lambda *args: {'execution_id': 'synthetic-run',
            'result': self.result() if result is None else result}, **kw)

    def test_planning_never_claims_execution_or_deployment(self):
        self.assertEqual(self.task['state'], 'planned')
        self.assertFalse(any(self.task['permissions'].values()))
        absent = modeler.run_task(self.task, self.projection, self.classification, self.policy, host='codex')
        self.assertEqual(absent['receipt']['state'], 'unavailable')
        self.assertFalse(absent['receipt']['runner_invoked'])
        self.assertIsNone(absent['result'])

    def test_callback_completed_with_pins_but_not_native_or_independent_proof(self):
        result = self.run_result()
        receipt = result['receipt']
        runtime = omni.yaml is not None and omni.sqlglot is not None
        self.assertEqual(receipt['events'], ['planned', 'running', 'completed' if runtime else 'needs_review'])
        self.assertEqual(receipt['result_sha256'], modeler.digest(result['result']))
        self.assertEqual(receipt['static_check']['status'], 'passed' if runtime else 'unsupported')
        for key in ('native_verified', 'deployment_authorized', 'host_identity_authenticated', 'independent_reasoning_verified'):
            self.assertFalse(receipt[key])

    def test_stale_input_policy_and_modified_task_never_invoke_runner(self):
        for mutation in ('projection', 'classification', 'policy', 'task'):
            task, projection, classification, policy = map(copy.deepcopy,
                (self.task, self.projection, self.classification, self.policy))
            if mutation == 'projection': projection['definitions']['total'] = 'Different'
            if mutation == 'classification': classification['review_reference'] = 'Changed'
            if mutation == 'policy': policy['review_reference'] = 'Changed'
            if mutation == 'task': task['intent'] = 'migration'
            invoked = []
            with self.subTest(mutation=mutation), self.assertRaises(modeler.ModelerError):
                modeler.run_task(task, projection, classification, policy, host='codex', runner=lambda *a: invoked.append(a))
            self.assertEqual(invoked, [])

    def test_protected_input_denied_even_for_inline_and_claimed_containment(self):
        for category in ('PII', 'PCI', 'PHI'):
            with self.subTest(category=category), self.assertRaises(modeler.ModelerError):
                modeler.prepare_task('trial', self.projection,
                    approved_classification('RESTRICTED', [category]), self.policy,
                    intent='assessment', warehouse='snowflake')
        self.policy['host_boundary']['mode'] = 'claimed_enforced'
        with self.assertRaises(modeler.ModelerError):
            modeler.prepare_task('trial', self.projection, self.classification, self.policy,
                                  intent='assessment', warehouse='snowflake')

    def test_invalid_result_and_provider_error_are_redacted(self):
        for mutation in ('native_claim', 'candidate_binding', 'context', 'source', 'sensitive'):
            result = self.result()
            if mutation == 'native_claim': result['human_approved'] = True
            if mutation == 'candidate_binding': result['task_sha256'] = 'f' * 64
            if mutation == 'context': result['model_context']['catalogue_sha256'] = 'f' * 64
            if mutation == 'source': result['decisions'][0]['source_refs'] = ['/missing']
            if mutation == 'sensitive': result['decisions'][0]['reason'] = 'SYNTHETIC_PHI_CANARY'
            observed = self.run_result(result)
            self.assertEqual(observed['receipt']['state'], 'failed', mutation)
            self.assertIsNone(observed['result'])
            self.assertNotIn('SYNTHETIC_PHI_CANARY', str(observed))
        def raises(*args): raise ValueError('SYNTHETIC_PHI_CANARY')
        observed = modeler.run_task(self.task, self.projection, self.classification, self.policy,
                                   host='codex', runner=raises)
        self.assertEqual(observed['receipt']['state'], 'failed')
        self.assertNotIn('SYNTHETIC_PHI_CANARY', str(observed))

    def test_unresolved_gap_and_static_failure_remain_needs_review(self):
        result = self.result(); result['gaps'] = [{'code': 'unknown_definition', 'scope': 'total'}]
        self.assertEqual(self.run_result(result)['receipt']['state'], 'needs_review')
        result = self.result(); result['model_files']['activity.topic'] = 'base_view: absent\n'
        self.assertEqual(self.run_result(result)['receipt']['state'], 'needs_review')

    def test_assessment_can_finish_without_a_candidate(self):
        self.task = modeler.prepare_task('assessment', self.projection, self.classification, self.policy,
            intent='assessment', warehouse='snowflake', operations=('inspect',))
        result = self.result(); result['model_files'] = {}; result['model_context'] = None
        self.assertEqual(self.run_result(result)['receipt']['state'], 'completed')

    def test_host_and_missing_result_contract(self):
        for host in modeler.HOSTS:
            receipt = modeler.run_task(self.task, self.projection, self.classification, self.policy, host=host)['receipt']
            self.assertEqual(receipt['state'], 'unavailable')
        with self.assertRaises(modeler.ModelerError):
            modeler.run_task(self.task, self.projection, self.classification, self.policy, host='genie')

    def test_complete_envelope_ids_are_scanned(self):
        with self.assertRaises(modeler.ModelerError):
            modeler.prepare_task('SYNTHETIC_PHI_CANARY', self.projection, self.classification, self.policy,
                                  intent='assessment', warehouse='snowflake')
        observed = modeler.run_task(self.task, self.projection, self.classification, self.policy,
            host='codex', mode='simulation', runner=lambda *args: {
                'execution_id': 'SYNTHETIC_PHI_CANARY', 'result': self.result()})
        self.assertEqual(observed['receipt']['state'], 'failed')
        self.assertNotIn('SYNTHETIC_PHI_CANARY', str(observed))
        self.assertEqual(observed['receipt']['events'], ['planned', 'running', 'failed'])

    def test_mid_execution_input_change_cannot_return_completed(self):
        def runner(*args):
            self.projection['definitions']['total'] = 'Changed during execution'
            return {'execution_id': 'synthetic-run', 'result': self.result()}
        observed = modeler.run_task(self.task, self.projection, self.classification, self.policy,
                                    host='codex', mode='simulation', runner=runner)
        self.assertEqual(observed['receipt']['state'], 'failed')
        self.assertIsNone(observed['result'])

    def test_installation_detects_missing_changed_and_extra_files_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); expected = root / 'expected'; actual = root / 'actual'
            expected.mkdir(); (expected / 'scripts').mkdir()
            (expected / 'SKILL.md').write_text('skill')
            (expected / 'scripts/a.py').write_text('a')
            shutil.copytree(expected, actual)
            self.assertEqual(modeler.inspect_installation(actual, expected=expected)['status'], 'matched')
            (actual / 'SKILL.md').write_text('old')
            (actual / 'scripts/a.py').unlink(); (actual / 'scripts/extra.py').write_text('extra')
            report = modeler.inspect_installation(actual, expected=expected)
            self.assertEqual(report['missing'], ['scripts/a.py'])
            self.assertEqual(report['changed'], ['SKILL.md'])
            self.assertEqual(report['unexpected'], ['scripts/extra.py'])
            self.assertFalse(report['installation_modified'])

    def test_stale_selected_installation_blocks_before_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory).resolve() / 'skill'
            shutil.copytree(modeler.ROOT, installed, ignore=shutil.ignore_patterns('examples', '__pycache__', '*.pyc'))
            (installed / 'SKILL.md').write_text('outdated')
            calls = []
            observed = modeler.run_task(self.task, self.projection, self.classification, self.policy,
                host='codex', runner=lambda *args: calls.append(args), installed_root=installed)
            self.assertEqual(calls, [])
            self.assertEqual(observed['receipt']['state'], 'unavailable')
            self.assertEqual(observed['receipt']['code'], 'modeler.installation_mismatch')
            self.assertEqual(observed['receipt']['installation']['scope'], 'selected_installation')

    def test_default_runtime_reports_checkout_only(self):
        receipt = modeler.run_task(self.task, self.projection, self.classification, self.policy, host='codex')['receipt']
        self.assertEqual(receipt['installation']['scope'], 'active_checkout_only')
        self.assertFalse(receipt['installation']['host_qualified'])

    def test_omni_source_and_selected_target_route_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; source.mkdir()
            for name, text in {'model': 'label: Example\n', 'relationships': '[]\n',
                               'events.view': files()['events.view'], 'activity.topic': files()['activity.topic'],
                               'totals.query.view': 'query:\n  base_view: events\n  fields:\n    events.total: total\n'}.items():
                (source / name).write_text(text)
            plan = planner.plan_repository(source, root / 'planned', inspect_git=False, warehouse='snowflake')
            self.assertEqual({t['source_type'] for t in plan['tasks']}, {'omni'})
            self.assertEqual(plan['target_tasks'][0]['state'], 'planned')
            self.assertEqual(plan['review_roles'], ['warehouse_architect', 'omni_modeler', 'independent_qa'])
            self.assertEqual(plan['coverage']['specialists_executed'], 0)
            other = root / 'other'; other.mkdir(); (other / 'dbt_project.yml').write_text('name: demo\n')
            plan = planner.plan_repository(other, root / 'selected', inspect_git=False,
                                           semantic_target='omni', warehouse='bigquery')
            self.assertEqual(plan['target_tasks'][0]['warehouse'], 'bigquery')
            self.assertNotIn('target_tasks', planner.plan_repository(other, root / 'unselected', inspect_git=False))


if __name__ == '__main__':
    unittest.main()
