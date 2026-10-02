"""Mandatory engagement gates composed from synthetic, never-executed receipts.

The native artifacts and actor chronology are deliberately synthetic test data.
These tests invoke the real verifiers; they do not establish warehouse execution.
"""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import test_refactor_run as refactor_fixtures
import test_review_package as review_fixtures
import test_catalogue_provenance as provenance_fixtures
from ae_common import hash_file, hash_json, load_json, snapshot
from benchmark_results import compare
from freeze_benchmark import freeze
from plan_refactor import make_plan
from repair_events import append_event
from verify_dbt_evidence import instant
import verify_engagement as engagement


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def association(path):
    return {'path': str(path), 'sha256': hash_file(path)}


class EngagementTests(unittest.TestCase):
    def setUp(self):
        # Module-qualified helpers avoid importing additional discoverable suites.
        self.refactor = refactor_fixtures.RefactorRunTests()
        self.refactor.setUp()
        self.addCleanup(self.refactor.doCleanups)
        self.review = review_fixtures.ReviewPackageTests()
        self.review.setUp()
        self.addCleanup(self.review.doCleanups)
        r, review = self.refactor, self.review
        self.root, self.project = r.root, r.candidate

        # Explicitly identify the source relation in both parse/build artifacts.
        native = load_json(r.native)
        for name in ('manifest', 'preflight_manifest'):
            path = r.native.parent / native[name]['path']
            manifest = load_json(path)
            manifest['sources']['source.billing.raw.invoices'].update(
                resource_type='source', database='Billing', schema='Raw', identifier='Invoices')
            save(path, manifest)
            native[name]['sha256'] = hash_file(path)
        save(r.native, native)
        self.native = native
        manifest = load_json(r.native.parent / native['manifest']['path'])

        source_inventory = {'schema_version': 1, 'kind': 'engagement_source_inventory',
                            'project_root': str(r.source), 'snapshot': snapshot(r.source)}
        review.replace_artifact_json('source_inventory', source_inventory)
        review.replace_artifact_json('code', {'schema_version': 1, 'kind': 'engagement_candidate_inventory',
                                              'project_root': str(self.project), 'snapshot': snapshot(self.project)})
        review.package['source_snapshot_sha256'] = next(
            item['sha256'] for item in review.package['artifacts'] if item['id'] == 'source_inventory')
        review.refresh_catalogue_artifacts(sync_source=True)

        # Rebind every dependent artifact to the one normalized catalogue.
        catalogue_sha = hash_file(review.catalogue_path)
        spec = load_json(self.root / 'spec.json')
        spec['catalogue_sha256'] = catalogue_sha
        spec['models'][0]['domain'] = 'receivables'
        save(self.root / 'spec.json', spec)
        plan = make_plan(r.source, spec)
        save(self.root / 'plan.json', plan)
        original_baseline = load_json(self.root / 'baseline.json')
        contract = load_json(self.root / 'contract.json')
        contract['catalogue_sha256'] = catalogue_sha
        save(self.root / 'contract.json', contract)
        (self.root / 'baseline.json').unlink()
        baseline = freeze(self.root / 'contract.json', self.root / 'baseline.json')
        baseline['created_at'] = original_baseline['created_at']
        baseline['baseline_sha256'] = hash_json({k: v for k, v in baseline.items() if k != 'baseline_sha256'})
        save(self.root / 'baseline.json', baseline)
        actual = load_json(self.root / 'actual.json')
        actual['baseline_sha256'] = baseline['baseline_sha256']
        save(self.root / 'actual.json', actual)
        save(self.root / 'benchmark.json', compare(self.root / 'baseline.json', self.root / 'actual.json', self.project))
        task_id = plan['tasks'][0]['task_id']
        r.record['tasks'][0]['task_id'] = task_id
        (self.root / 'events.jsonl').unlink()
        event = append_event(self.root / 'events.jsonl', {
            'kind': 'validation_passed', 'candidate_sha256': actual['candidate_sha256'],
            'evidence_sha256': hash_file(self.root / 'benchmark.json'),
            'at': (instant(native['execution']['finished_at'], 'finish') + timedelta(seconds=1)).isoformat(),
            'actor_id': 'analyst-1', 'task_id': None, 'case_ids': []},
            '0' * 64, {'metric'}, {task_id})
        r.record['events_head'] = event['event_sha256']
        for field, filename in (('plan', 'plan.json'), ('specification', 'spec.json'),
                                ('baseline', 'baseline.json'), ('actual', 'actual.json'),
                                ('benchmark', 'benchmark.json'), ('events', 'events.jsonl')):
            r.record[field] = r.assoc(filename)
        r.record['event_evidence'] = [r.assoc('benchmark.json')]
        r.record['native'] = association(r.native)
        self.assertTrue(r.check()['evidence_complete'])

        definitions = [
            ('bronze.invoices', 'source.billing.raw.invoices', 'bronze', ['InvoiceId', 'Payload']),
            ('silver.currencies', 'seed.billing.currencies', 'silver', ['currency']),
            ('gold.history', 'snapshot.billing.history', 'gold', ['invoice_id']),
            ('gold.fact', 'model.billing.fact', 'gold', ['invoice_id']),
        ]
        nodes = dict(manifest['nodes'], **manifest['sources'])
        self.inventory = {'schema_version': 1, 'kind': 'data_model_inventory', 'models': [
            {'model_id': mid, 'physical_name': engagement.qualified_relation(nodes[uid]),
             'layer': layer, 'columns': columns} for mid, uid, layer, columns in definitions]}
        self.dictionary = {'schema_version': 1, 'kind': 'data_dictionary', 'models': [
            {'model_id': model['model_id'], 'description': 'Synthetic relation', 'grain': 'Declared fixture grain',
             'columns': [{'name': name, 'description': 'Synthetic value', 'data_type': 'Fixture type',
                          'nullability': 'Fixture contract', 'key_role': 'Fixture key', 'source': 'Synthetic input',
                          'transformation': 'Fixture identity', 'units': 'Identifier', 'classification': 'Synthetic',
                          'validation': 'Synthetic receipt association'} for name in model['columns']]}
            for model in self.inventory['models']]}
        self.sync_documentation()
        self.assertEqual(review.verify(), [])
        self.inventory_path = review.root / 'model_spec.txt'
        self.observed = {'schema_version': 1, 'kind': 'physical_schema_observation',
                         'candidate_sha256': snapshot(self.project)['sha256'], 'origin': 'provided_export',
                         'validation_scope': 'local', 'adapter_type': 'duckdb',
                         'captured_at': native['execution']['finished_at'], 'identifier_policy': 'exact',
                         'scope': ['"Billing"."Raw"', '"qualification"."main"'],
                         'native_receipt_sha256': hash_file(r.native),
                         'invocation_id': manifest['metadata']['invocation_id'], 'relations': [
                             {'physical_name': model['physical_name'], 'columns': list(model['columns'])}
                             for model in self.inventory['models']]}
        self.values = {'schema_version': 1, 'kind': 'source_value_contract',
                       'source_revision': plan['source_snapshot']['sha256'], 'catalogue_sha256': catalogue_sha,
                       'baseline_sha256': baseline['baseline_sha256'], 'preserved_fields': [
                           {'model_id': 'gold.fact', 'model_column': 'invoice_id', 'case_id': 'metric',
                            'case_column': 'id', 'source_reference': 'raw.invoices.InvoiceId'}]}
        self.scope = self.make_scope(plan)
        for filename, value in (('observed.json', self.observed), ('values.json', self.values), ('scope.json', self.scope)):
            save(self.root / filename, value)
        self.native_source_bindings = [{'source_id': 'source.billing.raw.invoices', 'catalogue_object_id': 'object-1', 'local_remap': None}]
        self.authority = {'schema_version': 1, 'kind': 'engagement_authority', 'purpose': 'simulation',
                          'decision_state': 'simulation_authorized', 'actor_id': 'fixture-author',
                          'review_reference': 'Synthetic integration exercise',
                          'source_revision': plan['source_snapshot']['sha256'], 'candidate_sha256': snapshot(self.project)['sha256'],
                          'catalogue_sha256': catalogue_sha, 'baseline_sha256': baseline['baseline_sha256'],
                          'scope_contract_sha256': hash_file(self.root / 'scope.json'),
                          'value_contract_sha256': hash_file(self.root / 'values.json'),
                          'native_source_bindings_sha256': hash_json(self.native_source_bindings),
                          'rule_ids': ['r1'], 'decision_ids': []}
        save(self.root / 'authority.json', self.authority)
        save(self.root / 'provenance.json', provenance_fixtures.build_provenance(review.catalogue_path))
        self.request = {'schema_version': 1, 'kind': 'engagement_validation_request',
                        'native_source_bindings': self.native_source_bindings,
                        'refactor_record': association(r.path), 'review_package': association(review.manifest),
                        'model_inventory': association(self.inventory_path),
                        'physical_observation': association(self.root / 'observed.json'),
                        'value_contract': association(self.root / 'values.json'),
                        'scope_contract': association(self.root / 'scope.json'),
                        'authority': association(self.root / 'authority.json'),
                        'catalogue_provenance': association(self.root / 'provenance.json')}
        self.path = self.root / 'engagement.json'

    def make_scope(self, plan):
        return {'schema_version': 1, 'kind': 'engagement_scope',
                'source_revision': plan['source_snapshot']['sha256'],
                'nodes': [{'id': 'receivables-support', 'kind': 'support',
                           'paths': [item['path'] for item in plan['source_snapshot']['files']],
                           'depends_on': []}],
                'selected_nodes': ['receivables-support'], 'exclusions': [], 'consumers': []}

    def sync_documentation(self):
        review = self.review
        review.replace_artifact_json('model_spec', self.inventory)
        self.dictionary['model_inventory_sha256'] = hash_file(review.root / 'model_spec.txt')
        review.replace_artifact_json('data_dictionary', self.dictionary)
        for layer in review.package['model_documentation']['layers']:
            layer['model_ids'] = [m['model_id'] for m in self.inventory['models'] if m['layer'] == layer['layer']]
        save(review.manifest, review.package)

    def refresh(self, field, value=None):
        path = Path(self.request[field]['path'])
        if value is not None:
            save(path, value)
        self.request[field] = association(path)

    def check(self):
        save(self.path, self.request)
        return engagement.verify(self.path)

    def repin_scope_authority(self):
        self.authority['scope_contract_sha256'] = hash_file(self.root / 'scope.json')
        self.refresh('authority', self.authority)

    def denied(self, text=None):
        result = self.check()
        self.assertFalse(result['evidence_complete'], result)
        self.assertEqual(result['state'], 'incomplete')
        self.assertTrue(result['errors'])
        if text:
            self.assertIn(text.lower(), ' '.join(result['errors']).lower(), result)
        return result

    def test_complete_local_fixture_recomputes_all_gates(self):
        result = self.check()
        self.assertTrue(result['evidence_complete'], result)
        self.assertEqual(result['state'], 'enhanced_local_validated')
        self.assertEqual(result['execution_mode'], 'fixture_replay')
        self.assertEqual(set(result['gates']), {'refactor', 'review', 'physical', 'source_values', 'scope', 'authority', 'catalogue_provenance'})
        self.assertEqual(result['gates']['authority']['decision_state'], 'simulation_authorized')
        self.assertFalse(result['gates']['authority']['promotion_authorized'])
        self.assertEqual(result['gates']['physical']['relations'], 4)
        self.assertEqual(result['gates']['physical']['columns'], 5)

    def test_every_mandatory_association_is_required(self):
        original = copy.deepcopy(self.request)
        for field in engagement.ASSOCIATIONS:
            with self.subTest(field=field):
                self.request = copy.deepcopy(original)
                del self.request[field]
                self.denied('fields')

    def test_rehashed_matching_dictionary_and_inventory_cannot_hide_column(self):
        self.inventory['models'][0]['columns'].remove('Payload')
        self.dictionary['models'][0]['columns'].pop()
        self.sync_documentation()
        self.assertEqual(self.review.verify(), [])
        self.refresh('review_package')
        self.refresh('model_inventory')
        result = self.denied('Physical column coverage differs')
        self.assertTrue(result['gates']['review']['passed'])
        self.assertFalse(result['gates']['physical']['passed'])

    def test_missing_value_case_is_not_replaced_by_passing_native(self):
        actual = load_json(self.root / 'actual.json')
        actual['cases'] = []
        save(self.root / 'actual.json', actual)
        self.refactor.record['actual'] = self.refactor.assoc('actual.json')
        save(self.refactor.path, self.refactor.record)
        self.refresh('refactor_record')
        result = self.denied('source-value')
        self.assertFalse(result['gates']['source_values']['passed'])
        self.assertTrue(result['gates']['physical']['passed'])

    def test_wrong_observation_build_identity_or_early_capture_rejected(self):
        original = copy.deepcopy(self.observed)
        mutations = [('invocation_id', 'other-invocation', 'invocation'),
                     ('native_receipt_sha256', 'a' * 64, 'native receipt'),
                     ('captured_at', self.native['execution']['started_at'], 'predates'),
                     ('adapter_type', 'snowflake', 'adapter/scope'),
                     ('validation_scope', 'target', 'adapter/scope')]
        for field, value, message in mutations:
            with self.subTest(field=field):
                self.observed = dict(original, **{field: value})
                self.refresh('physical_observation', self.observed)
                self.denied(message)

    def test_missing_relation_cannot_hide_in_agreeing_physical_and_docs(self):
        removed = self.inventory['models'].pop(2)
        self.dictionary['models'] = [m for m in self.dictionary['models'] if m['model_id'] != removed['model_id']]
        self.observed['relations'] = [m for m in self.observed['relations'] if m['physical_name'] != removed['physical_name']]
        self.sync_documentation()
        self.assertEqual(self.review.verify(), [])
        self.refresh('review_package')
        self.refresh('model_inventory')
        self.refresh('physical_observation', self.observed)
        self.denied('native materialized')

    def test_source_and_candidate_drift_cannot_pass(self):
        for project in (self.refactor.source, self.project):
            with self.subTest(project=project.name):
                path = project / 'dbt_project.yml'
                original = path.read_bytes()
                path.write_bytes(original + b'\n# drift\n')
                self.denied()
                path.write_bytes(original)

    def test_failed_native_receipt_is_rechecked_despite_other_passing_gates(self):
        self.native['execution']['exit_code'] = 1
        save(self.refactor.native, self.native)
        self.refactor.record['native'] = association(self.refactor.native)
        save(self.refactor.path, self.refactor.record)
        self.observed['native_receipt_sha256'] = hash_file(self.refactor.native)
        self.refresh('refactor_record')
        self.refresh('physical_observation', self.observed)
        result = self.denied('Native evidence incomplete')
        self.assertFalse(result['gates']['refactor']['evidence_complete'])
        self.assertTrue(result['gates']['source_values']['passed'])

    def test_source_value_contract_cannot_be_empty_or_invent_a_case(self):
        original = copy.deepcopy(self.values)
        for mode in ('empty', 'unknown'):
            with self.subTest(mode=mode):
                value = copy.deepcopy(original)
                if mode == 'empty':
                    value['preserved_fields'] = []
                else:
                    value['preserved_fields'][0]['case_id'] = 'not-frozen'
                self.refresh('value_contract', value)
                self.denied('source-value')

    def test_declared_review_failure_is_not_hidden_by_new_gates(self):
        self.review.package['tests'][0]['status'] = 'fail'
        save(self.review.manifest, self.review.package)
        self.refresh('review_package')
        result = self.denied('not passed')
        self.assertFalse(result['gates']['review']['passed'])
        self.assertTrue(result['gates']['physical']['passed'])

    def test_scope_omitted_file_fails_even_when_other_gates_pass(self):
        self.scope['nodes'][0]['paths'].remove('macros/net.sql')
        self.refresh('scope_contract', self.scope)
        self.repin_scope_authority()
        result = self.denied('Account for source files')
        self.assertFalse(result['gates']['scope']['passed'])
        self.assertTrue(result['gates']['refactor']['evidence_complete'])
        self.assertTrue(result['gates']['source_values']['passed'])

    def test_affected_semantic_and_report_consumers_require_dispositions(self):
        # YAML can describe multiple nodes; this is an explicit synthetic graph.
        self.scope['nodes'].extend([
            {'id': 'receivables-metric', 'kind': 'semantic', 'paths': ['models/schema.yml'],
             'depends_on': ['receivables-support']},
            {'id': 'receivables-report', 'kind': 'report', 'paths': ['models/schema.yml'],
             'depends_on': ['receivables-metric']},
        ])
        self.refresh('scope_contract', self.scope)
        self.repin_scope_authority()
        result = self.denied('every affected semantic/report consumer')
        self.assertEqual(result['gates']['scope']['affected_consumers'],
                         ['receivables-metric', 'receivables-report'])
        self.scope['consumers'] = [
            {'node_id': node, 'disposition': 'migrate', 'reason': 'Synthetic reviewed migration scope'}
            for node in ('receivables-metric', 'receivables-report')]
        self.refresh('scope_contract', self.scope)
        self.repin_scope_authority()
        result = self.check()
        self.assertTrue(result['evidence_complete'], result)
        self.scope['consumers'][1]['disposition'] = 'defer'
        self.refresh('scope_contract', self.scope)
        self.repin_scope_authority()
        self.denied('Resolve deferred consumer')

    def test_scope_or_value_pin_change_requires_new_authority_record(self):
        self.scope['nodes'][0]['id'] = 'renamed'
        self.scope['selected_nodes'] = ['renamed']
        self.refresh('scope_contract', self.scope)
        self.denied('Authority pin mismatch')

    def test_simulation_cannot_record_human_approval(self):
        self.authority['decision_state'] = 'human_approval_recorded'
        self.refresh('authority', self.authority)
        self.denied('Simulation cannot record')

    def test_catalogue_mapping_cannot_substitute_different_export_value(self):
        provenance = load_json(self.root / 'provenance.json')
        mapping = next(item for item in provenance['mappings'] if item['catalogue_pointer'] == '/objects/0/identity/catalog')
        mapping['export_pointer'] = '/0/schema'
        self.refresh('catalogue_provenance', provenance)
        result = self.denied()
        self.assertFalse(result['gates']['catalogue_provenance']['passed'])

    def test_incomplete_native_source_identity_cannot_disappear_from_denominator(self):
        manifest = load_json(self.refactor.native.parent / self.native['manifest']['path'])
        del next(iter(manifest['sources'].values()))['resource_type']
        with self.assertRaisesRegex(ValueError, 'Native sources'):
            engagement.physical_denominator(manifest)

    def test_cli_relative_record_new_output_and_source_candidate_containment(self):
        self.request['refactor_record']['path'] = 'run.json'
        save(self.path, self.request)
        output = self.root / 'verified.json'
        self.assertEqual(engagement.main([str(self.path), '--output', str(output)]), 0)
        self.assertEqual(load_json(output)['state'], 'enhanced_local_validated')
        before = output.read_bytes()
        self.assertEqual(engagement.main([str(self.path), '--output', str(output)]), 1)
        self.assertEqual(output.read_bytes(), before)
        for project in (self.project, self.refactor.source):
            blocked = project / 'verification.json'
            self.assertEqual(engagement.main([str(self.path), '--output', str(blocked)]), 1)
            self.assertFalse(blocked.exists())

    def test_unrelated_or_missing_review_code_inventory_cannot_pass(self):
        self.review.replace_artifact_json('code', {'kind': 'engagement_candidate_inventory',
                                                 'project_root': str(self.project), 'snapshot': snapshot(self.refactor.source)})
        save(self.review.manifest, self.review.package)
        self.refresh('review_package')
        self.denied('Review code inventory')

    def test_native_source_namespace_change_requires_explicit_local_remap(self):
        receipt = load_json(self.refactor.native)
        for name in ('manifest', 'preflight_manifest'):
            path = self.refactor.native.parent / receipt[name]['path']
            manifest = load_json(path)
            manifest['sources']['source.billing.raw.invoices']['database'] = 'DifferentWarehouse'
            save(path, manifest)
            receipt[name]['sha256'] = hash_file(path)
        save(self.refactor.native, receipt)
        self.refactor.record['native'] = association(self.refactor.native)
        save(self.refactor.path, self.refactor.record)
        self.refresh('refactor_record')
        self.inventory['models'][0]['physical_name'] = '"DifferentWarehouse"."Raw"."Invoices"'
        self.observed['relations'][0]['physical_name'] = self.inventory['models'][0]['physical_name']
        self.observed['native_receipt_sha256'] = hash_file(self.refactor.native)
        self.sync_documentation()
        self.refresh('model_inventory')
        self.refresh('review_package')
        self.refresh('physical_observation', self.observed)
        self.denied()
        self.native_source_bindings[0]['local_remap'] = {'relation': ['DifferentWarehouse', 'Raw', 'Invoices'],
                                                       'reason': 'Synthetic local execution namespace, not warehouse identity'}
        self.denied('Authority pin mismatch')
        self.authority['native_source_bindings_sha256'] = hash_json(self.native_source_bindings)
        self.refresh('authority', self.authority)
        self.assertTrue(self.check()['evidence_complete'])

    def test_native_source_bindings_cannot_omit_or_invent_catalogue_inputs(self):
        original = copy.deepcopy(self.request['native_source_bindings'])
        for bindings in ([], original * 2, [dict(original[0], catalogue_object_id='unknown')]):
            self.request['native_source_bindings'] = bindings
            with self.subTest(bindings=bindings): self.denied()

    def test_target_source_cannot_use_local_remap(self):
        manifest = load_json(self.refactor.native.parent / self.native['manifest']['path'])
        manifest['sources']['source.billing.raw.invoices']['database'] = 'DifferentWarehouse'
        bindings = copy.deepcopy(self.native_source_bindings)
        bindings[0]['local_remap'] = {'relation': ['DifferentWarehouse', 'Raw', 'Invoices'], 'reason': 'local only'}
        with self.assertRaisesRegex(ValueError, 'Target native source identity'):
            engagement.verify_native_sources(bindings, manifest, load_json(self.review.catalogue_path),
                                             load_json(self.review.bindings_path), self.observed, 'target')


if __name__ == '__main__':
    unittest.main()
