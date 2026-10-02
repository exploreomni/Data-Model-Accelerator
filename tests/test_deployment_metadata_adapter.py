"""Offline Statement Execution API contracts; no live Databricks qualification."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/data-model-accelerator/scripts'))
import deployment_adapters as adapters
from test_deployment_adapters import target as existing_target

STATEMENT = '01ee48eb-5124-1922-bb90-f98c82f024fe'
OTHER_STATEMENT = '01ee48eb-5124-1922-bb90-f98c82f024ff'


def target():
    return {'adapter': 'databricks_sql', 'framework': 'native_sql', 'warehouse': 'databricks',
            'environment': 'test', 'namespace': {'catalog': 'analytics', 'schema': 'gold'},
            'identity': 'synthetic-service-principal', 'runtime_version': 'qualified-synthetic-runtime',
            'base_url': 'https://example.cloud.databricks.com', 'warehouse_id': 'abcdef0123456789',
            'auth_env': {'token': 'DATABRICKS_TOKEN'}}


def artifact(content='COMMENT ON TABLE `analytics`.`gold`.`orders` IS \'Reviewed\';', role='model_sql', name='statement.sql'):
    return {'path': name, 'role': role, 'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest()}


def plan(files=None, declaration=None):
    return adapters.build_plan(declaration or target(), files or [artifact()], release_id='synthetic-release', commit_sha='a' * 40)


def response(state='PENDING', native=STATEMENT):
    return {'status_code': 200, 'body': {'statement_id': native, 'status': {'state': state}}}


def complete_response(rows=None):
    rows = [['orders', None], ['order_lines', 'Independent description']] if rows is None else rows
    value = response('SUCCEEDED')
    value['body'].update(manifest={
        'format': 'JSON_ARRAY', 'schema': {'column_count': 2, 'columns': [
            {'name': 'table_name', 'position': 0, 'type_text': 'STRING', 'type_name': 'STRING'},
            {'name': 'comment', 'position': 1, 'type_text': 'STRING', 'type_name': 'STRING'}]},
        'total_row_count': len(rows), 'total_chunk_count': 1,
        'chunks': [{'chunk_index': 0, 'row_offset': 0, 'row_count': len(rows)}], 'truncated': False},
        result={'chunk_index': 0, 'row_offset': 0, 'row_count': len(rows), 'data_array': rows})
    return value


class DatabricksMetadataAdapterTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan()
        self.operation = self.plan['operations'][0]

    def normalize(self, envelope, operation=None):
        return adapters.normalize_response(operation or self.operation, envelope)

    def test_target_requires_string_warehouse_id_exact_namespace_and_token_reference(self):
        self.assertEqual(adapters.validate_target(target()), target())
        for field, invalid in [('warehouse_id', 123), ('warehouse_id', 'has space'), ('warehouse_id', 'a/b'),
                               ('warehouse_id', ''), ('framework', 'dbt'), ('warehouse', 'snowflake'),
                               ('namespace', {'database': 'analytics', 'schema': 'gold'}),
                               ('namespace', {'catalog': 'analytics'}), ('auth_env', {'password': 'TOKEN'}),
                               ('base_url', 'http://example.com')]:
            declaration = target()
            declaration[field] = invalid
            with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                adapters.validate_target(declaration)

    def test_submit_is_a_single_async_inline_statement_without_retry_token(self):
        content = "COMMENT ON TABLE `analytics`.`gold`.`orders` IS 'Semi; colon and O\\'Brien';"
        with patch('builtins.open', side_effect=AssertionError('No filesystem')), patch('subprocess.run', side_effect=AssertionError('No execution')):
            operation = plan([artifact(content)])['operations'][0]
        self.assertEqual(operation['method'], 'POST')
        self.assertEqual(operation['url'], 'https://example.cloud.databricks.com/api/2.0/sql/statements')
        self.assertEqual(operation['body'], {'statement': content, 'warehouse_id': 'abcdef0123456789',
                          'catalog': 'analytics', 'schema': 'gold', 'disposition': 'INLINE', 'format': 'JSON_ARRAY', 'wait_timeout': '0s'})
        self.assertEqual(operation['auth'], {'scheme': 'bearer', 'env': 'DATABRICKS_TOKEN'})
        self.assertNotIn('row_limit', operation['body'])
        self.assertNotIn('idempotency_token', operation['body'])
        self.assertIn('never', operation['resubmission_policy'])

    def test_statement_sequence_remains_ordered_and_pinned(self):
        built = plan([artifact(), artifact('SELECT 1', 'validation_sql', 'read.sql')])
        self.assertEqual(built['operations'][1]['depends_on'], ['sql-1'])
        self.assertEqual(built['operations'][1]['phase'], 'verify')
        self.assertEqual(built['operations'][1]['artifact']['sha256'], hashlib.sha256(b'SELECT 1').hexdigest())
        self.assertEqual(built, plan([artifact(), artifact('SELECT 1', 'validation_sql', 'read.sql')]))

    def test_exact_native_status_mapping_and_no_principal_claim(self):
        for native, expected in [('PENDING', 'submitted'), ('RUNNING', 'running'), ('SUCCEEDED', 'succeeded'),
                                  ('FAILED', 'failed'), ('CANCELED', 'cancelled'), ('CLOSED', 'unknown')]:
            with self.subTest(native=native):
                receipt = self.normalize(response(native))
                self.assertEqual(receipt['state'], expected)
                self.assertEqual(receipt['native_id'], STATEMENT)
                self.assertEqual(receipt['native_state'], native)
                self.assertFalse(receipt['principal_verified'])
                self.assertFalse(receipt['namespace_verified'])
                self.assertFalse(receipt['result_complete'])
        self.assertEqual(self.normalize(response('CLOSED'))['result_state'], 'unavailable')

    def test_complete_inline_result_is_evidence_available_but_not_independent_validation(self):
        operation = plan([artifact('SELECT 1', 'validation_sql')])['operations'][0]
        receipt = self.normalize(complete_response(), operation)
        self.assertEqual(receipt['state'], 'succeeded')
        self.assertTrue(receipt['result_complete'])
        self.assertEqual(receipt['result_summary'], {'row_count': 2, 'column_count': 2})
        self.assertEqual(receipt['qualification'], 'native_execution_only')
        self.assertNotIn('data_array', json.dumps(receipt))
        self.assertNotIn('Independent description', json.dumps(receipt))
        self.assertEqual(self.normalize(complete_response([]), operation)['state'], 'succeeded')

    def test_success_without_result_cannot_pass_readback(self):
        for change in ({'phase': 'verify'}, {'effect': 'read'}):
            operation = dict(self.operation, **change)
            receipt = self.normalize(response('SUCCEEDED'), operation)
            self.assertEqual(receipt['state'], 'unknown')
            self.assertFalse(receipt['result_complete'])
            self.assertIn('do not resubmit', receipt['reason'])

    def test_status_and_results_only_poll_original_id_on_original_origin(self):
        receipt = self.normalize(response('RUNNING'))
        for action in ('status', 'results'):
            follow = adapters.build_followup(self.plan, receipt, action)
            self.assertEqual(follow['method'], 'GET')
            self.assertEqual(follow['url'], 'https://example.cloud.databricks.com/api/2.0/sql/statements/' + STATEMENT)
            self.assertNotIn('body', follow)
            self.assertEqual(follow['expected_native_id'], STATEMENT)
            self.assertEqual(follow['target_sha256'], self.operation['target_sha256'])
            self.assertEqual(follow['effect'], 'read')
            self.assertEqual(self.normalize(complete_response(), follow)['operation_id'], 'sql-1')

    def test_timeout_or_missing_id_has_no_automatic_retry_or_status_target(self):
        for envelope in ({'timed_out': True}, {'status_code': 200, 'body': {}}, {'status_code': 503, 'body': {}}):
            receipt = self.normalize(envelope)
            self.assertEqual(receipt['state'], 'unknown')
            self.assertIsNone(receipt['native_id'])
            with self.assertRaisesRegex(ValueError, 'reconciliation'):
                adapters.build_followup(self.plan, receipt)
        with self.assertRaisesRegex(ValueError, 'Unsupported follow-up'):
            adapters.build_followup(self.plan, self.normalize(response()), 'retry')

    def test_wrong_id_cannot_be_recast_as_complete_result(self):
        follow = adapters.build_followup(self.plan, self.normalize(response()))
        envelope = complete_response()
        envelope['body']['statement_id'] = OTHER_STATEMENT
        receipt = self.normalize(envelope, follow)
        self.assertEqual(receipt['state'], 'failed')
        self.assertFalse(receipt['identity_verified'])
        self.assertFalse(receipt['result_complete'])
        self.assertIn('mismatch', receipt['reason'])

    def test_target_receipt_drift_and_unsafe_ids_block_followup(self):
        receipt = self.normalize(response())
        for field, value in [('target_sha256', 'b' * 64), ('adapter', 'databricks_job'),
                             ('operation_id', 'unrelated'), ('native_id', '../another')]:
            altered = dict(receipt, **{field: value})
            with self.assertRaises(ValueError):
                adapters.build_followup(self.plan, altered)
        changed = copy.deepcopy(self.plan)
        changed['target']['base_url'] = 'https://other.cloud.databricks.com'
        with self.assertRaises(ValueError):
            adapters.build_followup(changed, receipt)

    def test_cancel_acknowledgement_is_not_terminal_cancellation(self):
        follow = adapters.build_followup(self.plan, self.normalize(response('RUNNING')), 'cancel')
        self.assertEqual(follow['method'], 'POST')
        self.assertTrue(follow['url'].endswith('/' + STATEMENT + '/cancel'))
        self.assertEqual(follow['body'], {})
        receipt = self.normalize({'status_code': 200, 'body': {}}, follow)
        self.assertEqual(receipt['state'], 'submitted')
        self.assertFalse(receipt['result_complete'])
        wrong = self.normalize({'status_code': 200, 'body': {'statement_id': OTHER_STATEMENT}}, follow)
        self.assertEqual(wrong['state'], 'failed')
        malformed = self.normalize({'status_code': 200, 'body': {'error_code': 'DENIED'}}, follow)
        self.assertEqual(malformed['state'], 'unknown')

    def test_malformed_status_or_duplicate_json_remains_unknown_without_error_echo(self):
        bodies = [[], None, {'statement_id': 8, 'status': {'state': 'SUCCEEDED'}},
                  {'statement_id': '../unsafe', 'status': {'state': 'RUNNING'}},
                  {'statement_id': STATEMENT, 'status': 'SUCCEEDED'},
                  {'statement_id': STATEMENT, 'status': {'state': []}},
                  {'statement_id': STATEMENT, 'status': {'state': 'NEW_UNKNOWN_STATE'}},
                  '{"statement_id":"' + STATEMENT + '","status":{"state":"FAILED","state":"SUCCEEDED"}}']
        for body in bodies:
            with self.subTest(body=body):
                receipt = self.normalize({'status_code': 200, 'body': body})
                self.assertEqual(receipt['state'], 'unknown')
                self.assertFalse(receipt['result_complete'])
        envelope = response('FAILED')
        envelope['body']['status']['error'] = {'message': 'Customer secret must not be echoed'}
        self.assertNotIn('Customer secret', json.dumps(self.normalize(envelope)))

    def test_truncation_chunking_and_external_links_never_claim_completeness(self):
        changes = [lambda b: b['manifest'].update(truncated=True),
                   lambda b: b['manifest'].pop('truncated'),
                   lambda b: b['manifest'].update(total_chunk_count=2),
                   lambda b: b['manifest'].update(format='ARROW_STREAM'),
                   lambda b: b['result'].update(next_chunk_index=1),
                   lambda b: b['result'].update(next_chunk_internal_link='https://evil.example/collect'),
                   lambda b: b['result'].update(external_links=[{'external_link': 'https://example?secret=token'}])]
        for change in changes:
            envelope = complete_response()
            change(envelope['body'])
            receipt = self.normalize(envelope)
            self.assertEqual(receipt['state'], 'unknown')
            self.assertFalse(receipt['result_complete'])
            self.assertNotIn('secret=token', json.dumps(receipt))
            self.assertNotIn('evil.example', json.dumps(receipt))

    def test_row_and_schema_mismatch_cannot_pass_readback(self):
        changes = [lambda b: b['manifest'].update(total_row_count=999),
                   lambda b: b['manifest']['schema'].update(column_count=1),
                   lambda b: b['manifest']['schema']['columns'][1].update(position=0),
                   lambda b: b['manifest']['schema']['columns'][1].update(name='table_name'),
                   lambda b: b['manifest']['schema']['columns'][1].pop('type_text'),
                   lambda b: b['result'].update(row_offset=1),
                   lambda b: b['result'].update(row_count=1),
                   lambda b: b['result']['data_array'].append(['unexpected']),
                   lambda b: b['result']['data_array'][0].__setitem__(0, 4),
                   lambda b: b['manifest']['chunks'][0].update(row_count=1),
                   lambda b: b['status'].update(error={'message': 'Secret inconsistent native error'}),
                   lambda b: b.update(result=[])]
        for change in changes:
            envelope = complete_response()
            change(envelope['body'])
            receipt = self.normalize(envelope)
            self.assertEqual(receipt['state'], 'unknown')
            self.assertFalse(receipt['result_complete'])
            self.assertNotIn('Secret inconsistent', json.dumps(receipt))

    def test_http_failure_cannot_be_native_success(self):
        for code in (408, 409, 429, 500, 503):
            envelope = complete_response()
            envelope['status_code'] = code
            receipt = self.normalize(envelope)
            self.assertEqual(receipt['state'], 'unknown')
            self.assertFalse(receipt['result_complete'])
        envelope = complete_response()
        envelope['status_code'] = 403
        self.assertEqual(self.normalize(envelope)['state'], 'failed')


class MetadataNamespaceTargetTests(unittest.TestCase):
    def test_native_scopes_accept_exact_multiple_layers_without_mutating_input(self):
        declarations = [target()] + [existing_target(adapter) for adapter in
                       ('snowflake_sql', 'bigquery_sql', 'redshift_sql', 'clickhouse_sql', 'motherduck_sql')]
        for declaration in declarations:
            adapter = declaration['adapter']
            fields = adapters.METADATA_NAMESPACE_FIELDS[adapter]
            scopes = [{field: layer if field in ('schema', 'dataset') else 'warehouse_database' for field in fields}
                      for layer in ('bronze', 'silver', 'gold', 'raw')]
            if adapter == 'clickhouse_sql':
                scopes = [{'database': layer} for layer in ('bronze', 'silver', 'gold', 'raw')]
            declaration['metadata_namespaces'] = scopes
            original = copy.deepcopy(declaration)
            normalized = adapters.validate_target(declaration)
            self.assertEqual(normalized['metadata_namespaces'], scopes)
            self.assertEqual(declaration, original)

    def test_metadata_scope_defaults_absent_preserve_legacy_target_shape(self):
        for adapter in ('snowflake_sql', 'bigquery_sql', 'redshift_sql', 'clickhouse_sql', 'motherduck_sql'):
            normalized = adapters.validate_target(existing_target(adapter))
            self.assertNotIn('metadata_namespaces', normalized)

    def test_ambiguous_duplicate_or_non_native_scopes_are_refused(self):
        for scopes in ([], {}, [target()['namespace'], target()['namespace']], [{'catalog': 'analytics'}],
                       [{'catalog': 'analytics', 'schema': 'gold', 'database': 'extra'}],
                       [{'catalog': 'analytics', 'schema': ''}], [{'catalog': 'analytics', 'schema': 4}]):
            declaration = target()
            declaration['metadata_namespaces'] = scopes
            with self.assertRaises(ValueError):
                adapters.validate_target(declaration)
        for adapter in ('dbt_platform', 'databricks_job', 'databricks_bundle', 'coalesce', 'dataform', 'github_workflow'):
            declaration = existing_target(adapter)
            declaration['metadata_namespaces'] = [{'database': 'warehouse', 'schema': 'gold'}]
            with self.assertRaisesRegex(ValueError, 'Unknown target fields'):
                adapters.validate_target(declaration)


if __name__ == '__main__':
    unittest.main()
