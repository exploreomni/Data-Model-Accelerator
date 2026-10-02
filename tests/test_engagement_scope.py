import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))

from ae_common import hash_file, snapshot
import verify_engagement_scope as scope


class EngagementScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'source'
        self.project.mkdir()
        self.contract_path = self.root / 'scope.json'
        self.contract = self.make_contract('parcel')

    def make_contract(self, domain):
        files = {
            'dbt_project.yml': 'name: generic_scope_fixture\n',
            'models/sources.yml': 'metadata only; no YAML parser required\n',
            'models/' + domain + '.sql': 'select 1 as original_identifier\n',
            'models/shared.sql': 'select 2 as shared_identifier\n',
            'semantic/metrics.yml': 'metadata only\n',
            'reports/overview.sql': 'source evidence, never executed\n',
            'reports/unrelated.sql': 'another source report\n',
            'README.md': 'Read-only source notes.\n',
        }
        for path, content in files.items():
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return {
            'schema_version': 1, 'kind': 'engagement_scope',
            'source_revision': snapshot(self.project)['sha256'],
            'nodes': [
                {'id': 'source.' + domain, 'kind': 'source', 'paths': ['models/sources.yml'], 'depends_on': []},
                {'id': 'source.shared', 'kind': 'source', 'paths': ['models/sources.yml'], 'depends_on': []},
                {'id': 'model.' + domain, 'kind': 'model', 'paths': ['models/' + domain + '.sql'], 'depends_on': ['source.' + domain]},
                {'id': 'model.shared', 'kind': 'model', 'paths': ['models/shared.sql'], 'depends_on': ['source.shared']},
                {'id': 'semantic.' + domain, 'kind': 'semantic', 'paths': ['semantic/metrics.yml'], 'depends_on': ['model.' + domain]},
                {'id': 'report.overview', 'kind': 'report', 'paths': ['reports/overview.sql'], 'depends_on': ['semantic.' + domain, 'model.shared']},
                {'id': 'report.unrelated', 'kind': 'report', 'paths': ['reports/unrelated.sql'], 'depends_on': ['model.shared']},
                {'id': 'support.project', 'kind': 'support', 'paths': ['dbt_project.yml'], 'depends_on': []},
            ],
            'selected_nodes': ['model.' + domain],
            'exclusions': [{'path': 'README.md', 'reason': 'Narrative notes outside the refactor.'}],
            'consumers': [
                {'node_id': 'semantic.' + domain, 'disposition': 'migrate', 'reason': 'Preserve this metric contract.'},
                {'node_id': 'report.overview', 'disposition': 'retire', 'reason': 'Declared retirement; authority reviewed separately.'},
            ],
        }

    def verify(self, contract=None):
        self.contract_path.write_text(json.dumps(self.contract if contract is None else contract))
        return scope.verify(self.contract_path, self.project)

    def test_transitive_consumer_shared_ancestors_and_denominator(self):
        report = self.verify()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(report['required_nodes'], [
            'model.parcel', 'model.shared', 'report.overview', 'semantic.parcel',
            'source.parcel', 'source.shared',
        ])
        self.assertEqual(report['affected_consumers'], ['report.overview', 'semantic.parcel'])
        self.assertNotIn('report.unrelated', report['affected_nodes'])
        self.assertEqual(report['source_file_count'], 8)
        self.assertEqual(report['accounted_file_count'], 8)
        self.assertEqual(report['contract_sha256'], hash_file(self.contract_path))
        self.assertEqual(report['source_revision'], snapshot(self.project)['sha256'])
        self.assertTrue(any('not parser proof' in item for item in report['limitations']))

    def test_domain_renaming_and_order_do_not_drive_behavior(self):
        for node in self.contract['nodes']:
            node['id'] = node['id'].replace('parcel', 'shipment')
            node['depends_on'] = [value.replace('parcel', 'shipment') for value in node['depends_on']]
        self.contract['selected_nodes'] = ['model.shipment']
        self.contract['consumers'][0]['node_id'] = 'semantic.shipment'
        first = self.verify()
        self.assertTrue(first['passed'])
        self.contract['nodes'].reverse()
        self.contract['consumers'].reverse()
        for node in self.contract['nodes']:
            node['depends_on'].reverse()
        second = self.verify()
        self.assertEqual(first['normalized_scope_sha256'], second['normalized_scope_sha256'])
        self.assertNotEqual(first['contract_sha256'], second['contract_sha256'])
        self.assertEqual(first['required_nodes'], second['required_nodes'])

    def test_selected_consumer_itself_requires_disposition_and_ancestors(self):
        self.contract['selected_nodes'] = ['report.overview']
        self.contract['consumers'] = self.contract['consumers'][1:]
        report = self.verify()
        self.assertTrue(report['passed'])
        self.assertEqual(report['affected_consumers'], ['report.overview'])
        self.assertIn('source.shared', report['required_nodes'])
        self.assertIn('source.parcel', report['required_nodes'])

    def test_missing_and_unaffected_consumer_decisions_fail(self):
        self.contract['consumers'][1]['node_id'] = 'report.unrelated'
        report = self.verify()
        self.assertFalse(report['passed'])
        self.assertTrue(any('report.overview' in error and 'Declare' in error for error in report['errors']))
        self.assertTrue(any('report.unrelated' in error and 'unaffected' in error for error in report['errors']))

    def test_defer_fails_with_reason_and_retire_is_declared_only(self):
        self.contract['consumers'][1].update(disposition='defer', reason='Report owner has not decided.')
        report = self.verify()
        self.assertFalse(report['passed'])
        self.assertIn('Report owner has not decided.', report['errors'][0])
        self.assertIn('declare migrate or retire', report['errors'][0])

    def test_omitted_file_is_not_hidden_by_selected_scope(self):
        self.contract['exclusions'] = []
        report = self.verify()
        self.assertFalse(report['passed'])
        self.assertEqual(report['accounted_file_count'], 7)
        self.assertIn('README.md', report['errors'][0])

    def test_nonexistent_and_unsafe_paths_rejected(self):
        for path in ['missing.sql', '../outside.sql', '/absolute.sql', 'models/*.sql', 'models\\parcel.sql', 'models//parcel.sql']:
            with self.subTest(path=path):
                contract = copy.deepcopy(self.contract)
                contract['nodes'][2]['paths'] = [path]
                with self.assertRaises(ValueError):
                    self.verify(contract)

    def test_exclusion_overlap_duplicates_missing_path_and_reason_rejected(self):
        for exclusions in [
            [{'path': 'models/sources.yml', 'reason': 'Cannot cover and exclude.'}],
            self.contract['exclusions'] * 2,
            [{'path': 'absent.md', 'reason': 'Does not exist.'}],
            [{'path': 'README.md', 'reason': ''}],
        ]:
            with self.subTest(exclusions=exclusions):
                contract = dict(self.contract, exclusions=exclusions)
                with self.assertRaises(ValueError):
                    self.verify(contract)

    def test_unresolved_dependency_selection_and_consumer_rejected(self):
        for field in ['depends_on', 'selected_nodes', 'node_id']:
            with self.subTest(field=field):
                contract = copy.deepcopy(self.contract)
                if field == 'depends_on':
                    contract['nodes'][0][field] = ['missing']
                elif field == 'selected_nodes':
                    contract[field] = ['missing']
                else:
                    contract['consumers'][0][field] = 'missing'
                with self.assertRaisesRegex(ValueError, 'Unresolved'):
                    self.verify(contract)

    def test_unselected_cycle_and_self_cycle_rejected(self):
        for dependencies in [['report.unrelated'], ['report.overview']]:
            with self.subTest(dependencies=dependencies):
                contract = copy.deepcopy(self.contract)
                contract['nodes'][3]['depends_on'] = dependencies
                with self.assertRaisesRegex(ValueError, 'cycle'):
                    self.verify(contract)
        self.contract['nodes'][0]['depends_on'] = ['source.parcel']
        with self.assertRaisesRegex(ValueError, 'cycle'):
            self.verify()

    def test_duplicate_ids_paths_selections_dependencies_and_consumers_rejected(self):
        mutations = [
            lambda c: c['nodes'].append(copy.deepcopy(c['nodes'][0])),
            lambda c: c['nodes'][0]['paths'].append('models/sources.yml'),
            lambda c: c['selected_nodes'].append('model.parcel'),
            lambda c: c['nodes'][2]['depends_on'].append('source.parcel'),
            lambda c: c['consumers'].append(copy.deepcopy(c['consumers'][0])),
        ]
        for mutate in mutations:
            contract = copy.deepcopy(self.contract)
            mutate(contract)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                self.verify(contract)

    def test_strict_shapes_and_empty_graph_or_selection_rejected(self):
        mutations = [
            lambda c: c.update(schema_version=True),
            lambda c: c.update(kind='other'),
            lambda c: c.update(extra='unknown'),
            lambda c: c.update(nodes=[]),
            lambda c: c.update(selected_nodes=[]),
            lambda c: c.update(selected_nodes='model.parcel'),
            lambda c: c.update(exclusions={}),
            lambda c: c.update(consumers={}),
            lambda c: c['nodes'][0].update(kind='macro'),
            lambda c: c['nodes'][0].update(paths=[]),
            lambda c: c['nodes'][0].update(depends_on={}),
            lambda c: c['consumers'][0].update(disposition='approve'),
            lambda c: c['consumers'][0].update(reason=' '),
            lambda c: c['consumers'][0].update(node_id='model.parcel'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                contract = copy.deepcopy(self.contract)
                mutate(contract)
                with self.assertRaises(ValueError):
                    self.verify(contract)

    def test_source_drift_before_and_during_verification_rejected(self):
        (self.project / 'README.md').write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'Source revision drift'):
            self.verify()
        self.contract['source_revision'] = snapshot(self.project)['sha256']
        before = snapshot(self.project)
        with patch.object(scope, 'snapshot', side_effect=[before, dict(before, sha256='f' * 64)]):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.verify()

    def test_contract_drift_during_verification_rejected(self):
        original_snapshot = scope.snapshot
        calls = 0

        def mutate_contract(project):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.contract_path.write_text('{}')
            return original_snapshot(project)

        with patch.object(scope, 'snapshot', side_effect=mutate_contract):
            with self.assertRaisesRegex(ValueError, 'Scope contract changed'):
                self.verify()

    def test_source_paths_are_metadata_only_and_not_executed(self):
        marker = self.root / 'executed'
        source_file = self.project / 'models/parcel.sql'
        source_file.write_text("{% set dangerous = run_query('drop schema anything') %}\n" +
                               "__import__('pathlib').Path(" + repr(str(marker)) + ").touch()\n")
        self.contract['source_revision'] = snapshot(self.project)['sha256']
        with patch('subprocess.run', side_effect=AssertionError('Execution forbidden')):
            self.assertTrue(self.verify()['passed'])
        self.assertFalse(marker.exists())

    def test_duplicate_json_keys_rejected(self):
        self.contract_path.write_text('{"kind":"engagement_scope","kind":"engagement_scope"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            scope.verify(self.contract_path, self.project)


if __name__ == '__main__':
    unittest.main()
