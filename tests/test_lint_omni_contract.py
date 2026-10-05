"""Native Omni syntax participates in delivery lint without native pass claims."""
import copy
import unittest
from test_lint_delivery import Fixture, RUNTIME, lint


@unittest.skipUnless(RUNTIME, 'Pinned lint runtime required')
class OmniLintTests(Fixture):
    def configure(self):
        self.target['semantic_target'] = 'omni'
        self.add('model.sql')
        self.add('semantic/events.view', 'catalog: TEST\nschema: GOLD\ntable_name: EVENTS\n'
                 'dimensions:\n  id:\n    sql: ID\n', role='semantic_config', format='yaml')
        self.add('semantic/events.topic', 'base_view: events\n', role='semantic_config', format='yaml')
        self.manifest['omni_context'] = {'schema_version':1, 'kind':'omni_model_context',
            'warehouse':'snowflake', 'environment':'dev', 'catalogue_sha256':'a'*64,
            'bindings': {'events': {'namespace': {'database':'TEST','schema':'GOLD','table':'EVENTS'},
                'columns': {'ID':'number'}, 'evidence_sha256':'b'*64}},
            'inherited_views': {}, 'default_catalog': None, 'user_attributes': [], 'access_grants': []}

    def test_valid_contract_and_missing_context(self):
        self.configure()
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed', report)
        self.assertEqual(report['omni_contract']['status'], 'passed')
        self.assertFalse(lint.verify_report(report,self.root,self.target,self.manifest,runtime=RUNTIME)['native_verified'])
        del self.manifest['omni_context']
        self.assertEqual(self.run_lint()['status'], 'failed')

    def test_yaml_only_receipt_and_context_drift_cannot_pass(self):
        self.configure()
        report = self.run_lint()
        del report['omni_contract']
        self.resign(report)
        with self.assertRaisesRegex(ValueError, 'Omni contract'):
            lint.verify_report(report,self.root,self.target,self.manifest,runtime=RUNTIME)
        report = self.run_lint()
        manifest = copy.deepcopy(self.manifest)
        manifest['omni_context']['environment'] = 'production'
        with self.assertRaises(ValueError):
            lint.verify_report(report,self.root,self.target,manifest,runtime=RUNTIME)
        self.manifest['omni_context']['warehouse'] = 'bigquery'
        self.assertEqual(self.run_lint()['status'], 'failed')

    def test_valid_yaml_invalid_omni_fails_lint(self):
        self.configure()
        self.add('semantic/model', 'week_start_day: Funday\n', role='semantic_config', format='yaml')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['omni_contract']['status'], 'failed')


if __name__ == '__main__': unittest.main()
