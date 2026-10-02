"""Offline native contract fixtures; no live-platform qualification is claimed."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import deployment_adapters as adapters

COMMIT = 'a' * 40
WORKFLOW_COMMIT = 'b' * 40
COMMON = {'framework': 'native_sql', 'warehouse': 'snowflake', 'environment': 'test',
          'namespace': {'database': 'TEST_DB', 'schema': 'GOLD'}, 'identity': 'service_principal',
          'runtime_version': 'pinned-runtime-1'}
# These are synthetic configuration examples, not discovered accounts or IDs.
TARGET_EXAMPLES = {
    'github_workflow': {'framework': 'github', 'owner': 'example', 'repo': 'models', 'workflow_id': 123,
                        'workflow_ref': 'approved-release', 'workflow_sha': WORKFLOW_COMMIT, 'auth_env': {'token': 'GITHUB_TOKEN'}},
    'dbt_platform': {'framework': 'dbt', 'base_url': 'https://cloud.getdbt.com', 'account_id': 1, 'project_id': 2,
                     'environment_id': 3, 'job_id': 4, 'auth_env': {'token': 'DBT_TOKEN'}},
    'coalesce': {'framework': 'coalesce', 'base_url': 'https://app.coalescesoftware.io', 'environment_id': 3,
                 'job_id': 4, 'profile': 'test', 'auth_env': {'config': 'COA_CONFIG'}},
    'snowflake_sql': {'base_url': 'https://example.snowflakecomputing.com', 'role': 'MODELER', 'compute': 'TEST_WH', 'auth_env': {'token': 'SNOWFLAKE_TOKEN'}},
    'databricks_bundle': {'framework': 'bundle', 'warehouse': 'databricks', 'base_url': 'https://example.cloud.databricks.com',
                          'profile': 'test', 'bundle_name': 'models', 'bundle_target': 'test', 'workspace_root': '/Workspace/models/test',
                          'auth_env': {'token': 'DATABRICKS_TOKEN'}},
    'databricks_job': {'warehouse': 'databricks', 'base_url': 'https://example.cloud.databricks.com', 'job_id': 42, 'auth_env': {'token': 'DATABRICKS_TOKEN'}},
    'bigquery_sql': {'warehouse': 'bigquery', 'namespace': {'dataset': 'gold'}, 'project': 'example-project', 'location': 'US', 'auth_env': {'token': 'GCP_TOKEN'}},
    'dataform': {'framework': 'dataform', 'warehouse': 'bigquery', 'namespace': {'dataset': 'gold'}, 'project': 'example-project', 'location': 'us-central1',
                 'repository': 'models', 'service_account': 'modeler@example-project.iam.gserviceaccount.com', 'auth_env': {'token': 'GCP_TOKEN'}},
    'redshift_sql': {'warehouse': 'redshift', 'region': 'us-east-1', 'workgroup_name': 'test-workgroup', 'auth_env': {'credentials': 'AWS_SHARED_CREDENTIALS_FILE'}},
    'clickhouse_sql': {'warehouse': 'clickhouse', 'base_url': 'https://example.clickhouse.cloud:8443', 'auth_env': {'password': 'CLICKHOUSE_PASSWORD'}},
    'motherduck_sql': {'warehouse': 'motherduck', 'namespace': {'database': 'test_db'}, 'auth_env': {'token': 'motherduck_token'}},
}


def target(adapter):
    return dict(copy.deepcopy(COMMON), adapter=adapter, **copy.deepcopy(TARGET_EXAMPLES[adapter]))


def artifact(path='models/order.sql', content='SELECT 1', role='model_sql'):
    return {'path': path, 'role': role, 'sha256': hashlib.sha256(content.encode()).hexdigest(), 'content': content}


def plan(adapter, files=None):
    if files is None:
        files = [artifact()]
        if adapter == 'coalesce':
            files.append(artifact('coa-plan.json', '{}', 'deployment_plan'))
        if adapter == 'databricks_bundle':
            files.append(artifact('databricks.yml', 'bundle:\n  name: models\n', 'project_file'))
    return adapters.build_plan(target(adapter), files, release_id='review-123', commit_sha=COMMIT)


def nested(expected):
    out = {}
    for path, value in expected.items():
        node = out
        parts = path.split('.')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


def normalize(operation, body=None, **kwargs):
    envelope = {'body': body}
    envelope.update({'status_code': 200} if operation['transport'] == 'http' else {'exit_code': 0})
    envelope.update(kwargs)
    return adapters.normalize_response(operation, envelope)


class DeploymentAdapterTests(unittest.TestCase):
    def test_all_routes_generate_real_descriptors_without_io_or_secrets(self):
        with patch('subprocess.run', side_effect=AssertionError('no execution')), patch('builtins.open', side_effect=AssertionError('no filesystem')):
            for adapter in TARGET_EXAMPLES:
                with self.subTest(adapter=adapter):
                    built = plan(adapter)
                    self.assertEqual(built['status'], 'planned')
                    self.assertTrue(built['operations'])
                    for op in built['operations']:
                        self.assertIn(op['transport'], ('http', 'process'))
                        self.assertIn(op['effect'], ('read', 'write'))
                        self.assertEqual(op['qualification'], 'native_execution_only')
                        if op['transport'] == 'process':
                            self.assertIsInstance(op['argv'], list)
                            self.assertNotIn(op['argv'][0], ('sh', 'bash', 'python'))
                            self.assertEqual(op['cwd'], {'$artifact_root': True})
                        else:
                            self.assertTrue(op['url'].startswith('https://'))
                    self.assertNotIn('deployed_verified', json.dumps(built['operations']))

    def test_unknown_secret_and_mismatched_config_fails_closed(self):
        mutations = [('password', 'a-secret'), ('argv', ['sh']), ('runtime_version', ''), ('unknown', True)]
        for key, value in mutations:
            t = target('snowflake_sql')
            t[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                adapters.validate_target(t)
        for origin in ('http://example.com', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?token=x'):
            t = target('snowflake_sql')
            t['base_url'] = origin
            with self.assertRaises(ValueError):
                adapters.validate_target(t)
        t = target('clickhouse_sql')
        t['warehouse'] = 'snowflake'
        with self.assertRaises(ValueError):
            adapters.validate_target(t)
        t = target('dbt_platform')
        t['job_id'] = True
        with self.assertRaises(ValueError):
            adapters.validate_target(t)

    def test_dbt_platform_rejects_unqualified_hosting_even_when_core_adapter_exists(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift'):
            configured = target('dbt_platform')
            configured['warehouse'] = warehouse
            self.assertEqual(adapters.validate_target(configured)['warehouse'], warehouse)
        for warehouse in ('clickhouse', 'motherduck', 'duckdb', 'unlisted'):
            configured = target('dbt_platform')
            configured['warehouse'] = warehouse
            with self.subTest(warehouse=warehouse), self.assertRaises(ValueError):
                adapters.validate_target(configured)

    def test_artifact_hashes_paths_roles_and_commit_are_pinned(self):
        for bad in ('../x.sql', '/tmp/x.sql', 'a/./b.sql', 'a\\b.sql', 'a//b.sql'):
            with self.assertRaises(ValueError):
                plan('snowflake_sql', [artifact(bad)])
        item = artifact()
        item['content'] = 'DROP DATABASE other'
        with self.assertRaises(ValueError):
            plan('snowflake_sql', [item])
        with self.assertRaises(ValueError):
            plan('snowflake_sql', [artifact(), artifact()])
        with self.assertRaises(ValueError):
            adapters.build_plan(target('snowflake_sql'), [artifact()], release_id='x', commit_sha='main')
        self.assertEqual(plan('snowflake_sql'), plan('snowflake_sql'))

    def test_validation_queries_preserve_approved_order_and_sql_hash(self):
        built = plan('bigquery_sql', [artifact(), artifact('checks.sql', 'SELECT count(*) FROM gold.orders', 'validation_sql')])
        self.assertEqual([o['phase'] for o in built['operations']], ['execute', 'verify'])
        self.assertEqual(built['operations'][1]['depends_on'], ['sql-1'])
        self.assertEqual(built['operations'][1]['body']['configuration']['query']['query'], 'SELECT count(*) FROM gold.orders')
        self.assertFalse(built['operations'][1]['body']['configuration']['query']['useLegacySql'])

    def test_plain_http_or_exit_success_is_never_terminal_native_success(self):
        for adapter in TARGET_EXAMPLES:
            for op in plan(adapter)['operations']:
                with self.subTest(adapter=adapter, op=op['id']):
                    self.assertNotEqual(normalize(op, {})['state'], 'succeeded')
                    self.assertEqual(normalize(op, {}, timed_out=True)['state'], 'unknown')

    def test_github_requires_run_identity_and_separates_workflow_from_artifact_sha(self):
        op = plan('github_workflow')['operations'][0]
        self.assertEqual(op['body']['inputs']['artifact_commit'], COMMIT)
        self.assertEqual(op['expected_identity']['head_sha'], WORKFLOW_COMMIT)
        self.assertEqual(normalize(op, None, status_code=204)['state'], 'unknown')
        body = dict(nested(op['expected_identity']), id=999, status='completed', conclusion='success')
        self.assertEqual(normalize(op, body)['state'], 'succeeded')
        body['conclusion'] = 'skipped'
        self.assertEqual(normalize(op, body)['state'], 'unknown')
        body.update(conclusion='success', head_sha=COMMIT)
        self.assertEqual(normalize(op, body)['state'], 'failed')

    def test_dbt_status_identity_missing_and_wrong_ids(self):
        built = plan('dbt_platform')
        op = built['operations'][0]
        body = dict(nested(op['expected_identity']), id=80, status=10)
        good = normalize(op, {'data': body})
        self.assertEqual(good['state'], 'succeeded')
        self.assertTrue(good['identity_verified'])
        follow = adapters.build_followup(built, good)
        self.assertTrue(follow['url'].endswith('/runs/80/'))
        for status, expected in [(1, 'submitted'), (3, 'running'), (20, 'failed'), (30, 'cancelled')]:
            self.assertEqual(normalize(op, {'data': dict(body, status=status)})['state'], expected)
        self.assertEqual(normalize(follow, {'data': dict(body, id=81)})['state'], 'failed')
        self.assertEqual(normalize(op, {'data': {'id': 80, 'status': 10}})['state'], 'unknown')
        body['environment_id'] = 999
        self.assertEqual(normalize(op, {'data': body})['state'], 'failed')

    def test_coalesce_uses_reviewed_plan_then_scoped_refresh_and_partial_evidence(self):
        built = plan('coalesce')
        deploy, refresh = built['operations']
        self.assertIn({'$artifact': 'coa-plan.json'}, deploy['argv'])
        self.assertIn('--jobID', refresh['argv'])
        self.assertNotIn('--gitsha', deploy['argv'])
        self.assertNotIn('--forceIgnoreEnvironmentStatus', refresh['argv'])
        body = {'runID': 11, 'environmentID': 3, 'runType': 'deploy', 'runStatus': 'completed', 'runResults': []}
        self.assertEqual(normalize(deploy, body)['state'], 'succeeded')
        body['runResults'] = [{'status': 'failed', 'error': 'PRIVATE ERROR'}]
        result = normalize(deploy, body)
        self.assertEqual(result['state'], 'partial')
        self.assertNotIn('PRIVATE ERROR', json.dumps(result))
        with self.assertRaises(ValueError):
            plan('coalesce', [artifact()])

    def test_coalesce_cancel_pins_domain_and_status_results_fail_before_transport(self):
        configured = target('coalesce')
        configured['base_url'] = 'https://app.eu.coalescesoftware.io'
        built = adapters.build_plan(configured, [artifact('coa-plan.json', '{}', 'deployment_plan')],
                                    release_id='review-123', commit_sha=COMMIT)
        receipt = normalize(built['operations'][0], {
            'runID': 42, 'environmentID': 3, 'runType': 'deploy', 'runStatus': 'running', 'runResults': []})
        cancelled = adapters.build_followup(built, receipt, action='cancel')
        self.assertEqual(cancelled['argv'], ['coa', '--json', 'cancel', '42', '--profile', 'test',
            '--domain', 'https://app.eu.coalescesoftware.io', '--environmentID', '3'])
        with patch('subprocess.Popen') as process:
            for action in ('status', 'results'):
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'profile-domain binding'):
                    adapters.build_followup(built, receipt, action=action)
            process.assert_not_called()

    def test_snowflake_native_sql_state_and_wrong_statement_handle(self):
        built = plan('snowflake_sql')
        op = built['operations'][0]
        self.assertEqual(op['query']['async'], 'true')
        self.assertEqual(op['body']['parameters']['MULTI_STATEMENT_COUNT'], '1')
        running = normalize(op, {'statementHandle': 'handle-1', 'code': '333334'}, status_code=202)
        self.assertEqual(running['state'], 'running')
        poll = adapters.build_followup(built, running)
        success = {'statementHandle': 'handle-1', 'code': '090001', 'sqlState': '00000'}
        self.assertEqual(normalize(poll, success)['state'], 'succeeded')
        polled = normalize(poll, {'statementHandle': 'handle-1', 'code': '333334'}, status_code=202)
        self.assertEqual(polled['operation_id'], op['id'])
        again = adapters.build_followup(built, polled)
        self.assertEqual(again['url'], poll['url'])
        self.assertEqual(normalize(poll, dict(success, statementHandle='wrong'))['state'], 'failed')
        self.assertEqual(normalize(poll, dict(success, sqlState='42000'))['state'], 'failed')
        self.assertEqual(normalize(poll, dict(success, statementHandles=['child']))['state'], 'partial')

    def test_databricks_pins_git_job_before_running_and_detects_partial_tasks(self):
        built = plan('databricks_job')
        preflight, op = built['operations']
        self.assertEqual(preflight['effect'], 'read')
        self.assertEqual(preflight['expected_identity']['settings.git_source.git_commit'], COMMIT)
        self.assertEqual(len(op['body']['idempotency_token']), 64)
        body = dict(nested(op['expected_identity']), run_id=44, state={'life_cycle_state': 'TERMINATED', 'result_state': 'SUCCESS'})
        self.assertEqual(normalize(op, body)['state'], 'succeeded')
        body['tasks'] = [{'state': {'result_state': 'FAILED'}}]
        self.assertEqual(normalize(op, body)['state'], 'partial')
        body['state'] = {'life_cycle_state': 'TERMINATING'}
        self.assertEqual(normalize(op, body)['state'], 'running')

    def test_bundle_cli_completion_requires_target_resource_summary(self):
        deploy, summary = plan('databricks_bundle')['operations']
        self.assertEqual(normalize(deploy, {})['state'], 'submitted')
        body = dict(nested(summary['expected_identity']), resources={'jobs': {'models': {'id': '42'}}})
        self.assertEqual(normalize(summary, body)['state'], 'succeeded')
        body['workspace']['host'] = 'https://other.cloud.databricks.com'
        self.assertEqual(normalize(summary, body)['state'], 'failed')

    def test_bigquery_done_with_error_and_wrong_location_are_not_success(self):
        op = plan('bigquery_sql')['operations'][0]
        body = dict(nested(op['expected_identity']), status={'state': 'DONE'})
        self.assertEqual(normalize(op, body)['state'], 'succeeded')
        self.assertEqual(normalize(op, dict(body, status={'state': 'DONE', 'errorResult': {'reason': 'invalidQuery'}}))['state'], 'failed')
        body['jobReference']['location'] = 'EU'
        self.assertEqual(normalize(op, body)['state'], 'failed')

    def test_dataform_compilation_pins_exact_resource_and_rejects_foreign_resource(self):
        built = plan('dataform')
        compile_op, invoke = built['operations']
        self.assertEqual(compile_op['body']['gitCommitish'], COMMIT)
        native = 'projects/example-project/locations/us-central1/repositories/models/compilationResults/123'
        receipt = normalize(compile_op, {'name': native, 'resolvedGitCommitSha': COMMIT})
        self.assertEqual(receipt['state'], 'succeeded')
        resolved = adapters.resolve_operation(invoke, {'compile': receipt})
        self.assertEqual(resolved['body']['compilationResult'], native)
        self.assertEqual(resolved['expected_identity']['resolvedCompilationResult'], native)
        self.assertEqual(normalize(compile_op, {'name': native, 'resolvedGitCommitSha': COMMIT, 'compilationErrors': [{'message': 'x'}]})['state'], 'failed')
        self.assertEqual(normalize(compile_op, {'name': native.replace('example-project', 'other'), 'resolvedGitCommitSha': COMMIT})['state'], 'failed')
        with self.assertRaises(ValueError):
            adapters.resolve_operation(invoke, {'compile': dict(receipt, state='failed')})
        with self.assertRaises(ValueError):
            adapters.resolve_operation(invoke, {'compile': dict(receipt, operation_id='other')})
        result = normalize(resolved, {'name': native.replace('compilationResults', 'workflowInvocations'), 'resolvedCompilationResult': native, 'state': 'CANCELING'})
        self.assertEqual(result['state'], 'running')

    def test_redshift_uuid_and_environment_and_partial_substatements(self):
        built = plan('redshift_sql')
        op = built['operations'][0]
        self.assertIn('--client-token', op['argv'])
        body = {'Id': 'id-1', 'Database': 'TEST_DB', 'WorkgroupName': 'test-workgroup', 'Status': 'FINISHED'}
        receipt = normalize(op, body)
        self.assertEqual(receipt['state'], 'succeeded')
        follow = adapters.build_followup(built, receipt)
        self.assertIn('describe-statement', follow['argv'])
        self.assertEqual(normalize(follow, dict(body, Id='id-2'))['state'], 'failed')
        body['SubStatements'] = [{'Status': 'FINISHED'}, {'Status': 'FAILED'}]
        self.assertEqual(normalize(op, body)['state'], 'partial')
        t = target('redshift_sql')
        t['cluster_identifier'] = 'another'
        with self.assertRaises(ValueError):
            adapters.validate_target(t)

    def test_clickhouse_200_empty_and_late_error_require_native_reconciliation(self):
        built = plan('clickhouse_sql')
        op = built['operations'][0]
        native = op['expected_native_id']
        headers = {'X-ClickHouse-Query-Id': native}
        receipt = normalize(op, '', headers=headers)
        self.assertEqual(receipt['state'], 'submitted')
        self.assertEqual(normalize(op, 'rows\nCode: 395. DB::Exception: late failure', headers=headers)['state'], 'failed')
        self.assertEqual(normalize(op, {'meta': [], 'data': [], 'rows': 0}, headers=headers)['state'], 'succeeded')
        self.assertEqual(normalize(op, {'meta': [], 'data': [], 'rows': 0}, headers={'x-clickhouse-query-id': 'wrong'})['state'], 'failed')
        poll = adapters.build_followup(built, receipt)
        self.assertIn('Connected node only', poll['coverage'])
        self.assertEqual(normalize(poll, {'data': []})['state'], 'unknown')
        self.assertEqual(normalize(poll, {'data': [{'query_id': native, 'type': 'QueryFinish', 'exception_code': 0}]})['state'], 'succeeded')

    def test_motherduck_requires_explicit_md_database_and_observed_identity(self):
        built = plan('motherduck_sql')
        op = built['operations'][0]
        self.assertEqual(op['argv'][:3], ['duckdb', 'md:test_db', '-json'])
        response = {'exit_code': 0, 'stdout': '[{"database":"test_db"}]\n[{"one":1}]\n'}
        result = adapters.normalize_response(op, response)
        self.assertEqual(result['state'], 'succeeded')
        self.assertIsNone(result['native_id'])
        self.assertIn('no durable remote job ID', result['identity_scope'])
        response['stdout'] = '[{"database":"local"}]\n[{"one":1}]'
        self.assertEqual(adapters.normalize_response(op, response)['state'], 'failed')
        with self.assertRaises(ValueError):
            adapters.build_followup(built, result)

    def test_native_receipt_never_promotes_configured_actor_or_namespace(self):
        op = plan('snowflake_sql')['operations'][0]
        body = {'statementHandle': 'handle-1', 'code': '090001', 'sqlState': '00000'}
        receipt = normalize(op, body)
        self.assertEqual(receipt['state'], 'succeeded')
        self.assertTrue(receipt['identity_verified'])
        self.assertEqual(receipt['identity_scope'], 'native_response_fields_only')
        self.assertFalse(receipt['principal_verified'])
        self.assertFalse(receipt['namespace_verified'])
        self.assertEqual(receipt['observed_identity'], {})
        self.assertNotIn(COMMON['identity'], json.dumps(receipt))
        self.assertEqual(adapters.normalize_response(op, {'body': body})['state'], 'unknown')
        bq = plan('bigquery_sql')['operations'][0]
        bq_body = dict(nested(bq['expected_identity']), status={'state': 'DONE', 'errors': [{'reason': 'nonfatal'}]})
        self.assertEqual(normalize(bq, bq_body)['state'], 'partial')

    def test_malformed_vendor_shapes_remain_unknown_and_never_raise(self):
        malformed = [[], None, {'status': []}, {'Status': {}}, {'runStatus': []},
                     {'state': {'life_cycle_state': []}}, {'state': []},
                     {'tasks': 42}, {'SubStatements': 42}]
        for adapter in TARGET_EXAMPLES:
            for op in plan(adapter)['operations']:
                for body in malformed:
                    with self.subTest(adapter=adapter, body=body):
                        self.assertIn(normalize(op, body)['state'], adapters.STATES)
        op = plan('snowflake_sql')['operations'][0]
        self.assertEqual(normalize(op, {'statementHandle': 'unsafe\\nID', 'code': '090001', 'sqlState': '00000'})['state'], 'unknown')

    def test_followup_does_not_trust_cross_target_or_cancel_ack_as_terminal(self):
        built = plan('snowflake_sql')
        op = built['operations'][0]
        receipt = normalize(op, {'statementHandle': 'handle-1', 'code': '333334'}, status_code=202)
        cancel = adapters.build_followup(built, receipt, 'cancel')
        self.assertEqual(cancel['method'], 'POST')
        self.assertEqual(normalize(cancel, {})['state'], 'submitted')
        receipt['target_sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            adapters.build_followup(built, receipt)


if __name__ == '__main__':
    unittest.main()
