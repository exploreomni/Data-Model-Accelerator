"""Synthetic occurrence coverage is mapping evidence, never native parity."""
import copy
import importlib
import unittest

import test_engagement_stages as fixtures
from source_adapters.base import Report, occurrence_id, sha


class MappingCoverageTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.coverage = importlib.import_module('mapping_coverage')
        path = 'orders.sql'
        text = (self.h.repo / path).read_text()
        report = Report('dbt', {path: text})
        owner = report.object(path, '$model', 'model', 'orders', native_id='model.synthetic.orders')
        report.expression(path, '$model.code', 'sql', text, owner,
                          filters={'status': 'complete'}, population='active orders',
                          currency_time={'currency': 'EUR', 'timezone': 'America/Chicago'})
        report.dependency(path, '$model.inputs[0]', owner, 'raw.orders', resolution='unresolved')
        report.cover(path)
        self.report = report.finish()
        self.occurrence = self.report['expressions'][0]['occurrence_id']
        self.request = {
            'schema_version': 1,
            'expected_files': [{'source': 'dbt', 'path': path, 'sha256': sha(text)}],
            'reports': [self.report],
            'requirements': [{'id': 'order-key', 'description': 'Retain the order identity', 'domain': 'commerce'}],
            'targets': [{'id': 'warehouse-order-key', 'kind': 'warehouse',
                         'model_id': 'orders', 'column': 'orders_id'}],
            'mappings': [self.mapping()],
        }

    def mapping(self, **changes):
        return {'occurrence_id': self.occurrence, 'requirement_ids': ['order-key'],
                'target_ids': ['warehouse-order-key'], 'status': 'mapped',
                'basis': 'expression_analysis',
                'rationale': 'Synthetic expression reviewed against the declared target.', **changes}

    def register(self, request=None):
        self.coverage.register(self.h.state, request or self.request, self.h.run)
        return self.coverage.summarize(self.h.state)

    def assert_rejected_atomically(self, request):
        before = copy.deepcopy(self.h.state)
        files = {str(p.relative_to(self.h.run)): p.read_bytes()
                 for p in self.h.run.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):
            self.coverage.register(self.h.state, request, self.h.run)
        self.assertEqual(self.h.state, before)
        self.assertEqual({str(p.relative_to(self.h.run)): p.read_bytes()
                          for p in self.h.run.rglob('*') if p.is_file()}, files)

    def test_inventory_includes_every_category_and_derives_legacy_occurrences(self):
        before = copy.deepcopy(self.report)
        occurrences = self.coverage.inventory([self.report], self.request['expected_files'])
        expected = {row['occurrence_id'] for category in ('objects', 'expressions', 'dependencies')
                    for row in self.report[category]}
        self.assertEqual(set(occurrences), expected)
        legacy = copy.deepcopy(self.report)
        for category in ('objects', 'expressions', 'dependencies', 'gaps'):
            for row in legacy[category]:
                row.pop('occurrence_id', None)
        derived = self.coverage.inventory([legacy], self.request['expected_files'])
        self.assertEqual(set(derived), expected)
        self.assertIn(occurrence_id('dbt', 'expressions', 'orders.sql', '$model.code'), derived)
        self.assertEqual(self.report, before)

    def test_omitted_mappings_remain_in_the_denominator_as_unresolved(self):
        summary = self.register()
        self.assertEqual(summary['counts'], {'total': 3, 'mapped': 1, 'unresolved': 2,
                                            'unsupported': 0, 'excluded_by_review': 0, 'stale': 0})
        self.assertEqual(summary['native_parity'], 'not_validated')
        self.assertEqual(summary['export_completeness'], 'not_established')
        self.assertFalse(self.h.state['readiness']['execution_authorized'])
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_dangling_occurrence_requirement_and_target_reject_atomically(self):
        self.register()
        for field, value in [('occurrence_id', 'missing-occurrence'),
                             ('requirement_ids', ['missing-requirement']),
                             ('target_ids', ['missing-target'])]:
            with self.subTest(field=field):
                request = copy.deepcopy(self.request)
                request['mappings'][0][field] = value
                self.assert_rejected_atomically(request)

    def test_conflicting_duplicate_definitions_do_not_overwrite_existing_ledger(self):
        self.register()
        for collection, change in [('requirements', {'description': 'Contradictory meaning'}),
                                   ('targets', {'column': 'different_column'}),
                                   ('mappings', {'status': 'unsupported', 'basis': 'unassessed'})]:
            with self.subTest(collection=collection):
                request = copy.deepcopy(self.request)
                request[collection].append({**request[collection][0], **change})
                self.assert_rejected_atomically(request)

    def test_source_byte_change_stales_prior_mapping_without_erasing_denominator(self):
        self.register()
        (self.h.repo / 'orders.sql').write_text('select 2 as orders_id')
        summary = self.coverage.summarize(self.h.state)
        self.assertEqual(summary['counts']['total'], 3)
        self.assertEqual(summary['counts']['mapped'], 0)
        self.assertEqual(summary['counts']['stale'], 3)
        self.assertEqual(summary['native_parity'], 'not_validated')

    def test_mapped_source_outside_declared_dependencies_invalidates_only_affected_scope(self):
        self.request['targets'][0].update(model_id='products', column='products_id')
        self.register()
        before = fixtures.stages.entity_bindings(self.h.state, ['customers', 'products'])
        (self.h.repo / 'orders.sql').write_text('select 2 as orders_id')
        after = fixtures.stages.entity_bindings(self.h.state, ['customers', 'products'])
        self.assertNotEqual(before['products'], after['products'])
        self.assertEqual(before['customers'], after['customers'])

    def test_missing_ledger_preserves_unknowns_and_provisional_request_path(self):
        from review_assurance import records, public_summary
        from pathlib import Path
        self.register()
        before = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        Path(records(self.h.state)['coverage']['document']['path']).unlink()
        after = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(public_summary(self.h.state)['coverage']['status'], 'unavailable')
        binding = fixtures.stages.draft_bindings(self.h.state, ['orders'])
        fixtures.stages.record_draft_request(self.h.state, ['orders'], {'schema_version': 1,
            'kind': 'provisional_code_request', 'requester': 'Synthetic operator',
            'request_reference': 'synthetic://request', 'request_text': 'Generate provisional code', 'bindings': binding})
        self.assertIn('orders', fixtures.stages.draft_entities(self.h.state))

    def test_guided_registration_resumes_without_adding_approval_or_rewriting_sources(self):
        before = {p.name: p.read_bytes() for p in self.h.repo.iterdir()}
        self.h.action('record-coverage', document=self.request)
        self.h.state = fixtures.guided.resume_engagement(self.h.run)
        view = fixtures.stages.public_view(self.h.state)
        self.assertEqual(view['review_assurance']['coverage']['counts']['total'], 3)
        self.assertEqual(self.h.state['workflow']['approvals'], [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.h.repo.iterdir()})

    def test_changed_parent_filter_evidence_changes_mapped_field_binding(self):
        dependency = self.report['dependencies'][0]['occurrence_id']
        self.request['mappings'][0]['occurrence_id'] = dependency
        self.register()
        before = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.request['reports'][0]['expressions'][0]['details']['filters']['status'] = 'pending'
        self.register()
        after = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])

    def test_cross_file_owner_context_and_bytes_invalidate_only_mapped_scope(self):
        source_text = {path: (self.h.repo / path).read_text()
                       for path in ('customers.sql', 'orders.sql')}
        report = Report('dbt', source_text)
        owner = report.object('customers.sql', '$model', 'model', 'source_customers',
                              native_id='model.synthetic.source_customers', filters={'active': True})
        # The contract explicitly permits an expression's owner object to live
        # in another source file in the same report; this is not an inferred link.
        report.expression('orders.sql', '$field', 'sql', 'select 1', owner)
        for path in source_text:
            report.cover(path)
        raw = report.finish()
        occurrence = raw['expressions'][0]['occurrence_id']
        request = {
            'schema_version': 1,
            'expected_files': [{'source': 'dbt', 'path': path, 'sha256': sha(content)}
                               for path, content in source_text.items()],
            'reports': [raw],
            'requirements': [{'id': 'source-population', 'description': 'Retain the owner population',
                              'domain': 'commerce'}],
            'targets': [{'id': 'mapped-product-key', 'kind': 'warehouse', 'model_id': 'products',
                         'column': 'products_id'}],
            'mappings': [{'occurrence_id': occurrence, 'requirement_ids': ['source-population'],
                          'target_ids': ['mapped-product-key'], 'status': 'mapped',
                          'basis': 'expression_analysis', 'rationale': 'Retain explicit source owner context'}],
        }
        self.register(request)
        scope = ['orders', 'products']
        before = fixtures.stages.entity_bindings(self.h.state, scope)
        # Refreshing only owner metadata must invalidate prior target bindings,
        # even though the mapped occurrence and all actual source bytes match.
        request['reports'][0]['objects'][0]['details']['filters']['active'] = False
        self.register(request)
        metadata_changed = fixtures.stages.entity_bindings(self.h.state, scope)
        self.assertNotEqual(before['products'], metadata_changed['products'])
        self.assertEqual(before['orders'], metadata_changed['orders'])

        # Independently change only the owner's bytes after the refreshed ledger.
        # Products declares neither source file, so this must follow the mapping.
        (self.h.repo / 'customers.sql').write_text('select 2 as customers_id')
        bytes_changed = fixtures.stages.entity_bindings(self.h.state, scope)
        self.assertNotEqual(metadata_changed['products'], bytes_changed['products'])
        # Orders has a canonical customer dependency; use the unchanged orders
        # entity itself rather than comparing the entire dependency closure.
        self.assertEqual(metadata_changed['orders'], bytes_changed['orders'])
        summary = self.coverage.summarize(self.h.state)
        mapped_row = next(row for row in summary['rows'] if row['id'] == occurrence)
        self.assertEqual(mapped_row['status'], 'stale')
        self.assertEqual(summary['counts']['mapped'], 0)
        self.assertEqual(summary['counts']['stale'], 2)

    def test_name_only_and_unreferenced_exclusions_reject_without_inventing_review(self):
        for mapping in (self.mapping(basis='name_only'),
                        self.mapping(status='excluded_by_review', requirement_ids=[], target_ids=[])):
            request = copy.deepcopy(self.request)
            request['mappings'] = [mapping]
            self.assert_rejected_atomically(request)
        request = copy.deepcopy(self.request)
        request['mappings'] = [self.mapping(status='excluded_by_review', basis='reviewed_definition',
            requirement_ids=[], target_ids=[], review_reference='synthetic://review/exclusion-1')]
        summary = self.register(request)
        self.assertEqual(summary['counts']['excluded_by_review'], 1)
        self.assertEqual(summary['counts']['mapped'], 0)
        self.assertEqual(summary['native_parity'], 'not_validated')
        self.assertEqual(self.h.state['workflow']['approvals'], [])

    def test_missing_expected_file_is_visible_without_inventing_occurrences(self):
        request = copy.deepcopy(self.request)
        path = 'customers.sql'
        request['expected_files'].append({'source': 'dbt', 'path': path,
                                         'sha256': sha((self.h.repo / path).read_text())})
        summary = self.register(request)
        self.assertEqual(summary['supplied_files']['expected'], 2)
        self.assertEqual(summary['supplied_files']['observed'], 1)
        self.assertEqual(summary['supplied_files']['missing'], 1)
        self.assertEqual(summary['counts']['total'], 3)
        self.assertEqual(summary['export_completeness'], 'not_established')

    def test_many_to_many_warehouse_and_semantic_mapping_counts_occurrences_once(self):
        request = copy.deepcopy(self.request)
        request['requirements'].append({'id': 'order-metric', 'description': 'Retain order counts', 'domain': 'commerce'})
        request['targets'].append({'id': 'semantic-order-count', 'kind': 'semantic',
                                  'model_id': 'orders', 'semantic_object': 'orders.count'})
        request['mappings'] = [self.mapping(requirement_ids=['order-key', 'order-metric'],
            target_ids=['warehouse-order-key', 'semantic-order-count'])]
        request['mappings'].append({**request['mappings'][0],
                                   'occurrence_id': self.report['objects'][0]['occurrence_id']})
        summary = self.register(request)
        self.assertEqual(summary['counts']['total'], 3)
        self.assertEqual(summary['counts']['mapped'], 2)
        self.assertEqual(summary['counts']['unresolved'], 1)
        self.assertEqual(summary['native_parity'], 'not_validated')


if __name__ == '__main__':
    unittest.main()
