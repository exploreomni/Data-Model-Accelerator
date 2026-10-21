"""Optional historical comparisons coexist with staged code, review and reuse."""
import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import guided_workflow as guided
import engagement_stages as stages
import legacy_alignment as alignment
import legacy_alignment_tools as inspection
import migration_review
import test_engagement_stages as fixtures
from ae_common import hash_json


def config():
    return {'schema_version': 1, 'domain_id': 'commerce', 'mode': 'refactor',
            'comparison_requested': True, 'behavior': 'preserve',
            'request_reference': 'synthetic://user/refactor'}


def baseline():
    return {'schema_version': 1, 'status': 'partial', 'tables': [{
        'id': 'legacy.orders', 'namespace': 'RAW.PUBLIC', 'native_id': 'orders_final',
        'label': 'Old orders final', 'consumer_domains': ['commerce'],
        'columns': [{'id': 'order_id', 'name': 'orders_id', 'type': 'integer',
                     'definition': 'One identifier per order'}],
        'rules': [], 'evidence_ids': ['schema.orders'],
        'completeness': {'columns': 'complete', 'rules': 'unknown'}}],
        'evidence': [{'id': 'schema.orders', 'kind': 'schema',
                      'reference': 'synthetic://schema/orders',
                      'sha256': hashlib.sha256(b'synthetic schema').hexdigest()}]}


def mappings(model='orders'):
    return {'schema_version': 1, 'domain_id': 'commerce', 'mappings': [{
        'id': 'orders.key', 'sources': [{'table_id': 'legacy.orders', 'kind': 'column', 'field_id': 'order_id'}],
        'targets': [{'model_id': model, 'kind': 'column', 'field': model + '_id'}],
        'status': 'mapped', 'basis': 'structural_binding', 'behavior': 'preserve',
        'rationale': 'Synthetic explicit source key binding; values not verified.'}]}


class LegacyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def enable(self):
        self.h.action('configure-legacy-comparison', document=config())
        self.h.action('record-legacy-baseline', document=baseline())
        self.h.action('record-legacy-alignment', document=mappings())

    def test_configure_records_intent_without_design_approval(self):
        before = copy.deepcopy(self.h.state['workflow']['approvals'])
        self.h.action('configure-legacy-comparison', document=config())
        self.assertEqual(self.h.state['workflow']['approvals'], before)
        self.assertIsNotNone(alignment.public_summary(self.h.state))
        self.assertEqual(stages.approved_entities(self.h.state), set())
        action = next(a for a in self.h.state['next_actions'] if a['id'] == 'legacy_comparison:commerce')
        self.assertIn('provisional code remains available', action['action'])
        self.h.action('configure-legacy-comparison', document=config())
        self.assertEqual(sum(a['id'] == 'legacy_comparison:commerce' for a in self.h.state['next_actions']), 1)

    def test_absent_option_preserves_bindings_and_inspection_is_unassessed(self):
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertIsNone(inspection.inspect(self.h.state, 'summary'))
        self.assertEqual(alignment.scope_bindings(self.h.state), {})
        self.assertEqual(before, stages.entity_bindings(self.h.state, ['orders', 'products']))

    def test_changed_mapping_invalidates_previous_and_new_target_only(self):
        self.enable()
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.h.action('record-legacy-alignment', document=mappings('products'))
        after = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertNotEqual(before['products'], after['products'])
        self.assertEqual(before['customers'], after['customers'])

    def test_mapping_proposal_never_grants_generation_approval(self):
        self.enable()
        self.assertEqual(stages.approved_entities(self.h.state), set())
        with self.assertRaises(ValueError):
            self.h.action('stage', entities=['orders'], stage='implementation')

    def test_optional_intake_preserves_prior_approval_until_targets_are_associated(self):
        self.h.approve()
        approved = stages.approved_entities(self.h.state)
        self.h.action('configure-legacy-comparison', document=config())
        self.assertEqual(stages.approved_entities(self.h.state), approved)
        self.h.action('record-legacy-baseline', document=baseline())
        self.assertEqual(stages.approved_entities(self.h.state), approved)
        self.h.action('stage', entities=['orders'], stage='implementation')
        self.h.action('record-legacy-alignment', document=mappings())
        self.assertNotIn('orders', stages.approved_entities(self.h.state))
        self.assertTrue({'products', 'customers'} <= stages.approved_entities(self.h.state))

    def test_display_label_only_refreshes_package_not_code_bindings(self):
        self.enable()
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        package_before = alignment.fingerprint(self.h.state)
        changed = baseline(); changed['tables'][0]['label'] = 'Historical order output'
        self.h.action('record-legacy-baseline', document=changed)
        self.assertEqual(before, stages.entity_bindings(self.h.state, ['orders', 'products']))
        self.assertNotEqual(package_before, alignment.fingerprint(self.h.state))

    def test_material_definition_change_does_not_invalidate_unrelated_model(self):
        self.enable()
        before = stages.entity_bindings(self.h.state, ['orders', 'products'])
        changed = baseline(); changed['tables'][0]['columns'][0]['definition'] = 'Tenant-scoped identifier'
        self.h.action('record-legacy-baseline', document=changed)
        after = stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(before['customers'], after['customers'])

    def test_missing_history_keeps_explicit_provisional_code_available(self):
        self.h.action('configure-legacy-comparison', document=config())
        self.h.action('record-legacy-baseline', document={
            'schema_version': 1, 'status': 'not_supplied', 'tables': [], 'evidence': []})
        scope = ['orders']
        self.h.action('request-draft', entities=scope, document={
            'schema_version': 1, 'kind': 'provisional_code_request',
            'requester': 'Synthetic operator', 'request_reference': 'synthetic://draft',
            'request_text': 'Generate provisional dbt code; historical context is unavailable.',
            'bindings': stages.draft_bindings(self.h.state, scope)})
        self.h.action('stage', entities=scope, stage='implementation')
        self.assertEqual(stages.approved_entities(self.h.state), set())

    def test_inspection_does_not_rescan_repository_and_warm_result_is_stable(self):
        self.enable()
        first, second = self.h.root / 'first.json', self.h.root / 'second.json'
        args = ['context', '--run', str(self.h.run), '--domain', 'commerce']
        with patch.object(guided, '_assess_repository', side_effect=AssertionError('Unexpected project rescan')):
            with redirect_stdout(io.StringIO()):
                inspection.main(args + ['--output', str(first)])
                inspection.main(args + ['--previous', str(first), '--output', str(second)])
        initial, repeated = json.loads(first.read_text()), json.loads(second.read_text())
        self.assertEqual(initial['result_sha256'], repeated['result_sha256'])
        self.assertFalse(initial['unchanged_inputs'])
        self.assertTrue(repeated['unchanged_inputs'])
        self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        self.assertIn('not prove a completed reviewer', repeated['qualification'])

    def test_private_inspection_never_overwrites_source_or_existing_output(self):
        self.enable()
        args = ['summary', '--run', str(self.h.run)]
        source = self.h.repo / 'orders.sql'
        original = source.read_bytes()
        with self.assertRaises(ValueError):
            inspection.main(args + ['--output', str(source)])
        self.assertEqual(source.read_bytes(), original)
        out = self.h.root / 'result.json'
        with redirect_stdout(io.StringIO()):
            inspection.main(args + ['--output', str(out)])
        with self.assertRaises((ValueError, FileExistsError)):
            inspection.main(args + ['--output', str(out)])

    def test_packet_growth_needs_reason_and_limits_are_enforced(self):
        self.enable()
        for amount in (0, 65537):
            with self.assertRaises(ValueError):
                inspection.inspect(self.h.state, 'context', 'commerce', amount)
        with self.assertRaisesRegex(ValueError, 'reason'):
            inspection.inspect(self.h.state, 'context', 'commerce', 65536)
        with self.assertRaisesRegex(ValueError, 'domain'):
            inspection.inspect(self.h.state, 'candidates')

    def test_validation_suggestions_do_not_record_parity_or_execute_sources(self):
        self.enable()
        before = copy.deepcopy(self.h.state)
        result = inspection.inspect(self.h.state, 'validation-cases', 'commerce')
        self.assertTrue(result)
        self.assertEqual(self.h.state, before)
        self.assertNotIn('parity', self.h.state['workflow'].get('migration_review', {}))

    def record_parity(self):
        from test_migration_review_integration import MigrationReviewIntegrationTests
        helper = MigrationReviewIntegrationTests()
        helper.h = self.h
        self.h.action('record-migration-validation', document=helper.parity_request())
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'pass')

    def test_changed_historical_definition_invalidates_saved_parity(self):
        self.enable(); self.record_parity()
        changed = baseline()
        changed['tables'][0]['columns'][0]['definition'] = 'Tenant-scoped identifier'
        self.h.action('record-legacy-baseline', document=changed)
        report = migration_review.public_summary(self.h.state)['parity']
        self.assertEqual(report['status'], 'pending')
        self.assertTrue(report['stale'])

    def test_changed_mapping_invalidates_saved_parity(self):
        self.enable(); self.record_parity()
        self.h.action('record-legacy-alignment', document=mappings('products'))
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'pending')

    def test_label_only_change_preserves_saved_parity(self):
        self.enable(); self.record_parity()
        changed = baseline(); changed['tables'][0]['label'] = 'Friendlier display name'
        self.h.action('record-legacy-baseline', document=changed)
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'pass')

    def test_unrelated_mapping_does_not_stale_saved_parity(self):
        self.h.action('configure-legacy-comparison', document=config())
        self.h.action('record-legacy-baseline', document=baseline())
        self.h.action('record-legacy-alignment', document=mappings('products'))
        self.record_parity()
        changed = mappings('products'); changed['mappings'][0]['rationale'] = 'Updated product comparison rationale'
        self.h.action('record-legacy-alignment', document=changed)
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'pass')

    def test_old_parity_record_and_declined_comparison_remain_compatible(self):
        self.record_parity()
        record = migration_review.load(self.h.state, 'parity')
        del record['comparison_bindings']; del record['model_ids']
        migration_review.store(self.h.state, 'parity', record, self.h.run)
        request = config(); request['comparison_requested'] = False
        alignment.configure(self.h.state, request)
        self.assertEqual(migration_review.public_summary(self.h.state)['parity']['status'], 'pass')


if __name__ == '__main__':
    unittest.main()
