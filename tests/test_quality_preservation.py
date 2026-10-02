"""Lint export must preserve independently recorded quality results."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import deployment_review
import deployment_workflow as deployment
import guided_workflow as guided
import lint_delivery
import test_deployment_workflow as fixture


@unittest.skipUnless(importlib.util.find_spec('sqlfluff') and fixture.Ed25519PrivateKey,
                     'Optional SQLFluff and deployment verification dependencies unavailable')
class QualityPreservationTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.DeploymentWorkflowTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def prepare(self, lanes):
        case = self.case
        state = guided.update_answers(case.run, {'deliverables': ['implementation', 'documentation', 'validation']})
        context = portal.context_fingerprint(state)
        rows = []
        for lane in lanes:
            row = dict(id=lane, scope=portal.QUALITY_SCOPES[lane], status='fail', unit='cases',
                       checked=3, total=3, failed=1, skipped=0, unsupported=0, pending=0,
                       unknown=0, not_applicable=0, summary='Previously observed independent failure.',
                       next_action='Resolve the failed case and retain new evidence.',
                       gaps=['One previously observed case is still failing.'])
            rows.append(row)
        original_evidence = {'schema_version': 1, 'kind': 'quality_evidence', 'context_sha256': context,
                             'target': {'framework': 'dbt', 'warehouse': 'snowflake'}, 'checks': rows}
        evidence_path = case.candidate / 'validation/prior-quality.json'
        evidence_path.parent.mkdir()
        evidence_path.write_text(json.dumps(original_evidence))
        artifact = {'id': 'prior-quality', 'path': 'validation/prior-quality.json', 'category': 'validation',
                    'audiences': ['engineer'], 'sha256': deployment.hash_file(evidence_path)}
        review = json.loads(case.review.read_text())
        review['context_sha256'] = context
        review['artifacts'].append(artifact)
        original = [dict(copy.deepcopy(row), context_sha256=context, evidence_artifact_id=artifact['id'],
                         sha256=artifact['sha256']) for row in rows]
        review['quality_checks'] = original
        case.review.write_text(json.dumps(review))
        guided.record_handoff(case.run, case.review, case.candidate, audience='engineer')
        files = []
        for path, role, fmt, units, sources in [
            ('models/orders.sql', 'model_sql', 'compiled_sql', ['orders'], ['macros/identity.sql']),
            ('macros/identity.sql', 'macro', 'jinja', [], []),
            ('validation/prior-quality.json', 'project_config', 'json', [], []),
        ]:
            files.append(dict(path=path, sha256=deployment.hash_file(case.candidate / path), role=role,
                              format=fmt, execution_units=units, source_paths=sources))
        manifest = dict(schema_version=1, kind='sql_lint_manifest', expected_execution_units=['orders'], files=files)
        target = dict(framework='dbt', warehouse='snowflake', context_sha256=context)
        report = lint_delivery.lint_delivery(case.candidate, manifest, target, python_executable=sys.executable)
        self.assertEqual(report['status'], 'passed')
        report_path, manifest_path = case.root / 'lint.json', case.root / 'lint-manifest.json'
        report_path.write_text(json.dumps(report))
        manifest_path.write_text(json.dumps(manifest))
        planpath = case.root / 'quality-plan.json'
        deployment.create_plan(case.run, dict(case.request, quality={'report_path': str(report_path),
                               'manifest_path': str(manifest_path)}), case.policy_path, planpath)
        return planpath, original

    def exported_checks(self, planpath):
        result = deployment_review.export_review(planpath, self.case.policy_path, self.case.root / 'quality-export')
        with zipfile.ZipFile(result['package']) as archive:
            page = archive.read('START_HERE.html').decode()
        payload = json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(portal.verify_delivery(result['package'])['status'], 'integrity_verified')
        return {row['id']: row for row in payload['review']['quality_checks']}

    def test_static_pass_preserves_each_existing_nonstatic_failure_and_evidence_binding(self):
        planpath, original = self.prepare(['project_validity', 'warehouse_validation', 'data_accuracy'])
        checks = self.exported_checks(planpath)
        self.assertEqual(checks['code_conventions']['status'], 'pass')
        for row in original:
            self.assertEqual(checks[row['id']], dict(row, evidence_state='selected'))

    def test_new_static_pass_does_not_replace_an_existing_static_failure(self):
        planpath, original = self.prepare(['code_conventions'])
        checks = self.exported_checks(planpath)
        self.assertEqual(checks['code_conventions'], dict(original[0], evidence_state='selected'))


if __name__ == '__main__':
    unittest.main()
