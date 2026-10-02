"""Real linter -> frozen release -> portable quality review integration."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import deployment_workflow as deployment
import deployment_review
import release_quality
import test_deployment_workflow as fixture


@unittest.skipUnless(importlib.util.find_spec('sqlfluff') and fixture.Ed25519PrivateKey,
                     'Optional SQLFluff and deployment verification dependencies unavailable')
class ReleaseQualityTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.DeploymentWorkflowTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def prepare_quality(self, *, style_exception=False):
        import lint_delivery
        case = self.case
        plan = case.plan
        root = Path(plan['artifact_root'])
        if style_exception:
            (root / 'models/orders.sql').write_text('select\n    1 as order_id,\n    2 as CUSTOMER_ID\n')
        files = []
        for path, role, fmt, units, sources in [
            ('models/orders.sql', 'model_sql', 'compiled_sql', ['orders'], ['macros/identity.sql']),
            ('macros/identity.sql', 'macro', 'jinja', [], []),
        ]:
            files.append(dict(path=path, sha256=deployment.hash_file(root / path), role=role,
                              format=fmt, execution_units=units, source_paths=sources))
        manifest = dict(schema_version=1, kind='sql_lint_manifest', expected_execution_units=['orders'], files=files)
        if style_exception:
            manifest['style_exceptions'] = [dict(path='models/orders.sql', rule='CP02',
                reason='Preserve the explicitly reviewed output identifier spelling in this fixture.')]
        target = release_quality.quality_target(plan)
        report = lint_delivery.lint_delivery(root, manifest, target, python_executable=sys.executable)
        self.assertEqual(report['status'], 'passed', {k: report[k] for k in ('status', 'files', 'findings')})
        report_path, manifest_path = case.root / 'lint.json', case.root / 'lint-manifest.json'
        report_path.write_text(json.dumps(report))
        manifest_path.write_text(json.dumps(manifest))
        return dict(report_path=str(report_path), manifest_path=str(manifest_path))

    def test_real_lint_is_bound_and_exported_without_claiming_native_accuracy(self):
        reference = self.prepare_quality()
        case = self.case
        path = case.root / 'quality-plan.json'
        plan = deployment.create_plan(case.run, dict(case.request, quality=reference), case.policy_path, path)
        self.assertEqual(plan['quality']['status'], 'verified_static')
        result = deployment_review.export_review(path, case.policy_path, case.root / 'quality-review')
        review = json.loads(Path(result['review']).read_text())
        checks = {item['id']: item for item in review['quality_checks']}
        self.assertEqual(checks['code_conventions']['status'], 'pass')
        self.assertEqual(checks['data_accuracy']['status'], 'unknown')
        self.assertEqual(checks['warehouse_validation']['status'], 'unknown')
        self.assertNotIn(str(case.root), Path(result['page']).read_text())
        self.assertTrue(Path(result['package']).is_file())

    def test_report_edit_after_plan_invalidates_the_release(self):
        reference = self.prepare_quality()
        case = self.case
        path = case.root / 'quality-plan.json'
        plan = deployment.create_plan(case.run, dict(case.request, quality=reference), case.policy_path, path)
        report_path = Path(reference['report_path'])
        report_path.write_text(report_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'Lint evidence changed'):
            deployment._current(plan, case.policy_path)

    def test_portable_quality_summary_discloses_real_style_exceptions(self):
        reference = self.prepare_quality(style_exception=True)
        case = self.case
        review = json.loads(case.review.read_text())
        for artifact in review['artifacts']:
            artifact['sha256'] = deployment.hash_file(case.candidate / artifact['path'])
        case.review.write_text(json.dumps(review))
        fixture.guided.record_handoff(case.run, case.review, case.candidate, audience='engineer')
        path = case.root / 'exception-plan.json'
        deployment.create_plan(case.run, dict(case.request, quality=reference), case.policy_path, path)
        result = deployment_review.export_review(path, case.policy_path, case.root / 'exception-review')
        checks = json.loads(Path(result['review']).read_text())['quality_checks']
        lane = next(c for c in checks if c['id'] == 'code_conventions')
        report = json.loads(Path(reference['report_path']).read_text())
        self.assertEqual(report['style_exceptions']['used_count'], 1)
        self.assertGreater(report['style_exceptions']['excepted_finding_count'], 0)
        self.assertIn('1 exact-file convention policy exceptions', lane['summary'])
        self.assertIn('not a zero-finding result or human approval', lane['summary'])
        self.assertTrue(any(f['findings'] for f in report['files']))

    def test_context_change_prevents_reusing_a_lint_report(self):
        reference = self.prepare_quality()
        case = self.case
        _, handoff, _ = deployment._handoff(case.run)
        target = dict(release_quality.quality_target(case.plan), context_sha256='0' * 64)
        with self.assertRaises(ValueError):
            release_quality.bind_quality(reference, case.plan['artifact_root'], handoff, target)

    def test_lint_clean_wrong_result_fails_frozen_independent_expectation(self):
        import sqlite3
        # Expected output is fixed before changing the engineering candidate.
        expected = [(1,)]
        root = Path(self.case.plan['artifact_root'])
        (root / 'models/orders.sql').write_text('select 2 as order_id\n')
        reference = self.prepare_quality()
        self.assertEqual(json.loads(Path(reference['report_path']).read_text())['status'], 'passed')
        with sqlite3.connect(':memory:') as connection:
            actual = connection.execute((root / 'models/orders.sql').read_text()).fetchall()
        self.assertNotEqual(actual, expected)

    def test_live_approval_without_lint_never_reaches_transport(self):
        case = self.case
        policy = copy.deepcopy(case.policy)
        policy['mode'] = 'live'
        plan = copy.deepcopy(case.plan)
        plan['mode'] = 'live'
        # Purpose and signature are checked before the explicit missing-lint gate.
        from unittest.mock import patch
        with patch.object(deployment, 'verify_attestation', return_value={'claims': {}}):
            with self.assertRaisesRegex(ValueError, 'lint report'):
                deployment._approval(plan, policy, {}, {})


if __name__ == '__main__':
    unittest.main()
