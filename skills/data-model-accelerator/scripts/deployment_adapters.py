"""Pure deployment plans and conservative native receipts (Python 3.9 stdlib).

No network, subprocess, filesystem reads, credential resolution, or approval here.
The coordinator MUST verify authorization, snapshot ALL pinned artifacts, enforce
its target/tool policy, resolve artifact references, record before dispatch, and
retain bounded transport responses. A succeeded receipt is native execution,
never independent validation or deployed_verified. Source contracts are linked
in DOCS. Unknown response shapes deliberately remain unknown.
"""
import copy
import hashlib
import json
import re
import uuid
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from platform_matrix import get_pairing


DOCS = {
    'github_workflow': 'https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event',
    'dbt_platform': 'https://raw.githubusercontent.com/dbt-labs/dbt-cloud-openapi-spec/master/openapi-v2.yaml',
    'coalesce': 'https://docs.coalesce.io/docs/coa/version-733-and-above/coa-commands',
    'snowflake_sql': 'https://docs.snowflake.com/en/developer-guide/sql-api/reference',
    'databricks_bundle': 'https://docs.databricks.com/aws/en/dev-tools/cli/bundle-commands',
    'databricks_job': 'https://docs.databricks.com/api/workspace/jobs',
    'databricks_sql': 'https://docs.databricks.com/api/statement-execution/v1/execute-statement',
    'bigquery_sql': 'https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs',
    'dataform': 'https://cloud.google.com/dataform/reference/rest/v1/projects.locations.repositories.workflowInvocations',
    'redshift_sql': 'https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html',
    'clickhouse_sql': 'https://clickhouse.com/docs/interfaces/http',
    'motherduck_sql': 'https://motherduck.com/docs/getting-started/connect-query-from-python/installation/',
}
COMMON_REQUIRED = {'adapter', 'framework', 'warehouse', 'environment', 'namespace',
                   'identity', 'runtime_version'}
# Only enumerated knobs are executable. No arbitrary argv, headers, URLs or code.
TARGET_FIELDS = {
    'github_workflow': ({'owner', 'repo', 'workflow_id', 'workflow_ref', 'workflow_sha'}, set()),
    'dbt_platform': ({'base_url', 'account_id', 'project_id', 'environment_id', 'job_id'}, set()),
    'coalesce': ({'base_url', 'profile', 'environment_id', 'job_id'}, set()),
    'snowflake_sql': ({'base_url', 'role', 'compute'}, set()),
    'databricks_bundle': ({'base_url', 'profile', 'bundle_name', 'bundle_target', 'workspace_root'}, set()),
    'databricks_job': ({'base_url', 'job_id'}, set()),
    'databricks_sql': ({'base_url', 'warehouse_id'}, set()),
    'bigquery_sql': ({'project', 'location'}, set()),
    'dataform': ({'project', 'location', 'repository', 'service_account'}, {'included_tags'}),
    'redshift_sql': ({'region'}, {'cluster_identifier', 'workgroup_name', 'db_user', 'secret_arn'}),
    'clickhouse_sql': ({'base_url'}, set()),
    'motherduck_sql': (set(), set()),
}
SQL_ADAPTERS = {'snowflake_sql', 'databricks_sql', 'bigquery_sql', 'redshift_sql', 'clickhouse_sql', 'motherduck_sql'}
METADATA_NAMESPACE_FIELDS = {
    'snowflake_sql': {'database', 'schema'}, 'databricks_sql': {'catalog', 'schema'},
    'bigquery_sql': {'dataset'}, 'redshift_sql': {'database', 'schema'},
    'clickhouse_sql': {'database'}, 'motherduck_sql': {'database', 'schema'},
}
ROLES = {'model_sql', 'validation_sql', 'deployment_plan', 'project_file', 'project', 'documentation', 'semantic'}
STATES = {'submitted', 'running', 'succeeded', 'failed', 'cancelled', 'partial', 'unknown'}
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_COMMIT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
_ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
_NATIVE = re.compile(r'[A-Za-z0-9_:.\-/]+\Z')
_STATEMENT_ID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, field):
    _require(type(value) is str and value and value == value.strip()
             and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid ' + field)
    return value


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('Non-JSON or nonfinite value') from None


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _relative(value):
    _text(value, 'artifact path')
    _require(not any(c in value for c in '\\:*?[]') and
             all(p not in ('', '.', '..') for p in value.split('/')) and
             not PurePosixPath(value).is_absolute(), 'Artifact path must be canonical and relative')
    return value


def _url(value):
    _text(value, 'base_url')
    parsed = urlsplit(value)
    _require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
             not parsed.password and not parsed.query and not parsed.fragment and
             parsed.path in ('', '/') and parsed.port in (None, 443, 8443),
             'base_url must be an HTTPS origin; trust is enforced by external target policy')
    return value.rstrip('/')


def _segment(value):
    return quote(str(value), safe='')


def validate_target(target):
    """Strict, nonsecret declaration validation. Does not authenticate identity."""
    _require(type(target) is dict, 'target must be an object')
    adapter = target.get('adapter')
    _require(adapter in TARGET_FIELDS, 'Unsupported deployment adapter')
    required, optional = TARGET_FIELDS[adapter]
    optional = optional | {'physical_destination'} | ({'metadata_namespaces'} if adapter in SQL_ADAPTERS else set())
    _require(COMMON_REQUIRED | required <= set(target), 'Missing target fields')
    _require(set(target) <= COMMON_REQUIRED | required | optional | {'auth_env'}, 'Unknown target fields')
    out = copy.deepcopy(target)
    for name in (COMMON_REQUIRED | required | optional) - {'namespace', 'included_tags', 'metadata_namespaces'}:
        if name not in out:
            continue
        if name.endswith('_id') and name not in {'identity', 'warehouse_id'}:
            _require(type(out[name]) is int and out[name] > 0, name + ' must be a positive integer')
        else:
            _text(out[name], name)
    _require(out['framework'] in ('native_sql', 'dbt', 'coalesce', 'dataform', 'bundle', 'github'), 'Unsupported framework')
    _require(type(out['namespace']) is dict and out['namespace'], 'namespace must be nonempty')
    _require(set(out['namespace']) <= {'database', 'schema', 'catalog', 'dataset'}, 'Unsupported namespace field')
    for k, v in out['namespace'].items():
        _text(v, k)
    if 'metadata_namespaces' in out:
        scopes = out['metadata_namespaces']
        _require(type(scopes) is list and scopes and len(scopes) <= 128, 'metadata_namespaces must be a bounded nonempty list')
        seen = set()
        for namespace in scopes:
            _require(type(namespace) is dict and set(namespace) == METADATA_NAMESPACE_FIELDS[adapter], 'Exact platform metadata namespace fields required')
            for key, value in namespace.items():
                _text(value, 'metadata namespace ' + key)
            key = _json(namespace)
            _require(key not in seen, 'Duplicate metadata namespace')
            seen.add(key)
    auth = out.setdefault('auth_env', {})
    _require(type(auth) is dict and all(type(k) is str and _ENV.fullmatch(k) and
             type(v) is str and _ENV.fullmatch(v) for k, v in auth.items()), 'auth_env contains env names only')
    _require(len(set(auth.values())) == len(auth), 'Duplicate auth env reference')
    if 'base_url' in out:
        out['base_url'] = _url(out['base_url'])
    if adapter in {'github_workflow', 'dbt_platform', 'snowflake_sql', 'databricks_job', 'databricks_sql', 'bigquery_sql', 'dataform'}:
        _require(set(auth) == {'token'}, 'This HTTP route requires only auth_env.token')
    if adapter == 'clickhouse_sql':
        _require(set(auth) == {'password'}, 'ClickHouse requires auth_env.password; user is identity')
    if adapter == 'motherduck_sql':
        _require(auth == {'token': 'motherduck_token'}, 'MotherDuck uses the motherduck_token environment variable')
    if adapter in SQL_ADAPTERS:
        _require(out['framework'] == 'native_sql', 'SQL route requires native_sql framework')
        expected = adapter.replace('_sql', '')
        _require(out['warehouse'] == expected, 'SQL route/warehouse mismatch')
        primary = {'bigquery_sql': 'dataset', 'databricks_sql': 'catalog'}.get(adapter, 'database')
        _require(primary in out['namespace'], 'Missing destination namespace')
    if adapter == 'snowflake_sql':
        _require('schema' in out['namespace'], 'Snowflake schema is required')
    if adapter == 'databricks_sql':
        _require(set(out['namespace']) == {'catalog', 'schema'}, 'Databricks SQL requires exact catalog/schema namespace')
        _require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', out['warehouse_id']) is not None, 'warehouse_id must be a native warehouse ID string')
    if adapter == 'dbt_platform':
        _require(out['framework'] == 'dbt', 'dbt route requires dbt framework')
        pairing = get_pairing('dbt_platform', out['warehouse'])
        _require(pairing['status'] != 'unsupported', pairing['reason'])
    if adapter == 'coalesce':
        _require(out['framework'] == 'coalesce', 'Unsupported Coalesce target')
        _require(get_pairing('coalesce', out['warehouse'])['status'] != 'unsupported', 'Unsupported Coalesce target')
    if adapter.startswith('databricks_'):
        _require(out['warehouse'] == 'databricks', 'Databricks target required')
    if adapter == 'dataform':
        _require(out['framework'] == 'dataform' and out['warehouse'] == 'bigquery' and 'dataset' in out['namespace'], 'Dataform requires BigQuery dataset')
        _require(type(out.get('included_tags', [])) is list and
                 all(type(v) is str and v and not any(ord(c) < 32 for c in v) for v in out.get('included_tags', [])), 'Invalid included_tags')
    if adapter == 'redshift_sql':
        _require(('cluster_identifier' in out) != ('workgroup_name' in out), 'Choose exactly one Redshift cluster or workgroup')
        _require(not ('db_user' in out and 'workgroup_name' in out), 'Serverless identity derives from IAM; db_user is unsupported')
    if adapter == 'github_workflow':
        _require(_COMMIT.fullmatch(out['workflow_sha']) is not None, 'workflow_sha must pin workflow code')
        for key in ('owner', 'repo'):
            _require(re.fullmatch(r'[A-Za-z0-9_.-]+', out[key]) is not None and not out[key].startswith('-'), 'Invalid GitHub ' + key)
    if adapter == 'motherduck_sql':
        _require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', out['namespace']['database']) is not None,
                 'MotherDuck initial route requires a simple database identifier')
    return out


def _artifacts(artifacts):
    _require(type(artifacts) is list and artifacts, 'Nonempty approved artifact inventory required')
    result, seen = [], set()
    for item in artifacts:
        _require(type(item) is dict and {'path', 'sha256', 'role'} <= set(item) <= {'path', 'sha256', 'role', 'content'}, 'Invalid artifact fields')
        path = _relative(item['path'])
        _require(path not in seen, 'Duplicate artifact path')
        seen.add(path)
        _require(type(item['sha256']) is str and _SHA256.fullmatch(item['sha256']) is not None, 'Invalid artifact digest')
        _require(item['role'] in ROLES, 'Unsupported artifact role')
        if 'content' in item:
            _require(type(item['content']) is str and '\x00' not in item['content'], 'Artifact content must be UTF-8 text without NUL')
            _require(hashlib.sha256(item['content'].encode()).hexdigest() == item['sha256'], 'Artifact content differs from pin')
        result.append(copy.deepcopy(item))
    return result


def _http(op, target, method, url, body=None, query=None):
    op.update(transport='http', method=method, url=url, headers={'Accept': 'application/json'})
    if body is not None:
        op['body'] = body
        op['headers']['Content-Type'] = 'application/json'
    if query:
        op['query'] = query
    if target['adapter'] == 'clickhouse_sql':
        op['auth'] = {'scheme': 'basic', 'username': target['identity'], 'env': target['auth_env']['password']}
    elif 'token' in target['auth_env']:
        op['auth'] = {'scheme': 'token' if target['adapter'] == 'dbt_platform' else 'bearer', 'env': target['auth_env']['token']}
    return op


def _process(op, target, argv):
    op.update(transport='process', argv=argv, cwd={'$artifact_root': True},
              auth_env=sorted(target['auth_env'].values()))
    return op


def _operation(target, op_id, phase, contract, effect='write', expected=None):
    return {'id': op_id, 'adapter': target['adapter'], 'phase': phase, 'effect': effect,
            'contract': contract, 'expected_identity': expected or {}, 'depends_on': [],
            'target_sha256': _hash(target), 'qualification': 'native_execution_only'}


def build_plan(target, artifacts, *, release_id, commit_sha):
    """Create transport-ready ordered operations; input order is deployment order.

    $artifact/$artifact_root are resolved only by the trusted coordinator.
    SQL routes require each model_sql/validation_sql artifact to contain one
    native statement (no parser is claimed here). Native endpoint limits apply.
    """
    target, artifacts = validate_target(target), _artifacts(artifacts)
    _text(release_id, 'release_id')
    _require(type(commit_sha) is str and _COMMIT.fullmatch(commit_sha) is not None, 'Immutable commit SHA required')
    adapter, ops = target['adapter'], []
    manifest = [{k: a[k] for k in ('path', 'sha256', 'role')} for a in artifacts]
    context = {'target': target, 'release_id': release_id, 'commit_sha': commit_sha, 'artifacts': manifest}
    plan = {'schema_version': 1, **context, 'artifact_set_sha256': _hash(manifest), 'operations': ops,
            'status': 'planned', 'qualification': 'No approval, credentials, deployment or independent verification is conferred.'}

    def add(op):
        if ops:
            op['depends_on'] = [ops[-1]['id']]
        ops.append(op)
        return op

    def op(name, phase, contract, effect='write', expected=None):
        return _operation(target, name, phase, contract, effect, expected)

    if adapter == 'github_workflow':
        base = 'https://api.github.com/repos/' + target['owner'] + '/' + target['repo']
        item = op('dispatch', 'execute', 'github_run', expected={'repository.full_name': target['owner'] + '/' + target['repo'],
                      'workflow_id': target['workflow_id'], 'head_sha': target['workflow_sha'], 'event': 'workflow_dispatch'})
        item['artifact_commit_requires_workflow_attestation'] = True
        add(_http(item, target, 'POST', base + '/actions/workflows/' + str(target['workflow_id']) + '/dispatches',
                  {'ref': target['workflow_ref'], 'inputs': {'artifact_commit': commit_sha, 'release_id': release_id,
                   'target_sha256': _hash(target), 'artifact_set_sha256': _hash(manifest)}}))
    elif adapter == 'dbt_platform':
        expected = {'account_id': target['account_id'], 'project_id': target['project_id'],
                    'environment_id': target['environment_id'], 'job_definition_id': target['job_id'], 'git_sha': commit_sha}
        add(_http(op('dbt-run', 'execute', 'dbt_run', expected=expected), target, 'POST',
                  target['base_url'] + '/api/v2/accounts/%s/jobs/%s/run/' % (target['account_id'], target['job_id']),
                  {'cause': 'Approved release ' + release_id, 'git_sha': commit_sha}))
    elif adapter == 'coalesce':
        plans = [a for a in artifacts if a['role'] == 'deployment_plan']
        _require(len(plans) == 1, 'Coalesce requires exactly one previously approved native deployment_plan')
        common = ['--profile', target['profile'], '--domain', target['base_url'], '--environmentID', str(target['environment_id'])]
        add(_process(op('coalesce-deploy', 'deploy', 'coalesce_run', expected={'environmentID': target['environment_id'], 'runType': 'deploy'}), target,
                     ['coa', '--json', 'deploy', '--plan', {'$artifact': plans[0]['path']}] + common))
        add(_process(op('coalesce-refresh', 'execute', 'coalesce_run', expected={'environmentID': target['environment_id'], 'runType': 'refresh'}), target,
                     ['coa', '--json', 'refresh', '--jobID', str(target['job_id'])] + common))
    elif adapter == 'databricks_bundle':
        _require(any(PurePosixPath(a['path']).name in ('databricks.yml', 'databricks.yaml') for a in artifacts), 'Pinned bundle configuration required')
        args = ['--target', target['bundle_target'], '--profile', target['profile'], '--output', 'json']
        add(_process(op('bundle-deploy', 'deploy', 'bundle_deploy'), target,
                     ['databricks', 'bundle', 'deploy', '--auto-approve'] + args))
        summary = op('bundle-summary', 'observe', 'bundle_summary', 'read',
                     {'bundle.name': target['bundle_name'], 'bundle.target': target['bundle_target'],
                      'workspace.host': target['base_url'], 'workspace.root_path': target['workspace_root']})
        summary['prerequisite_states'] = {'bundle-deploy': ['submitted']}
        add(_process(summary, target, ['databricks', 'bundle', 'summary'] + args))
    elif adapter == 'databricks_job':
        add(_http(op('job-definition', 'preflight', 'databricks_definition', 'read',
                     {'job_id': target['job_id'], 'settings.git_source.git_commit': commit_sha}), target, 'GET',
                  target['base_url'] + '/api/2.2/jobs/get', query={'job_id': target['job_id']}))
        add(_http(op('job-run', 'execute', 'databricks_run', expected={'job_id': target['job_id'],
                          'git_source.git_snapshot.used_commit': commit_sha}), target, 'POST',
                  target['base_url'] + '/api/2.2/jobs/run-now', {'job_id': target['job_id'], 'idempotency_token': _hash(context)}))
    elif adapter == 'dataform':
        parent = 'projects/%s/locations/%s/repositories/%s' % tuple(_segment(target[k]) for k in ('project', 'location', 'repository'))
        base = 'https://dataform.googleapis.com/v1/' + parent
        add(_http(op('compile', 'deploy', 'dataform_compilation', expected={'resolvedGitCommitSha': commit_sha}), target, 'POST',
                  base + '/compilationResults', {'gitCommitish': commit_sha, 'codeCompilationConfig': {
                      'defaultDatabase': target['project'], 'defaultSchema': target['namespace']['dataset'], 'defaultLocation': target['location']}}))
        ops[-1]['expected_native_prefix'] = parent + '/compilationResults/'
        cfg = {'serviceAccount': target['service_account']}
        if 'included_tags' in target:
            cfg['includedTags'] = target['included_tags']
        add(_http(op('invoke', 'execute', 'dataform_invocation', expected={'resolvedCompilationResult': {'$binding': 'compile.native_id'}}),
                  target, 'POST', base + '/workflowInvocations', {'compilationResult': {'$binding': 'compile.native_id'}, 'invocationConfig': cfg}))
        ops[-1]['expected_native_prefix'] = parent + '/workflowInvocations/'
    else:
        sql = [a for a in artifacts if a['role'] in ('model_sql', 'validation_sql')]
        _require(sql and all('content' in a and a['content'].strip() for a in sql), 'SQL routes require pinned nonempty SQL content')
        for index, artifact in enumerate(sql):
            name = 'sql-%d' % (index + 1)
            native_token = str(uuid.uuid5(uuid.NAMESPACE_URL, _hash(context) + ':' + name))
            item = op(name, 'verify' if artifact['role'] == 'validation_sql' else 'execute', adapter)
            item['artifact'] = {k: artifact[k] for k in ('path', 'sha256', 'role')}
            statement = artifact['content']
            if adapter == 'snowflake_sql':
                body = {'statement': statement, 'database': target['namespace']['database'],
                        'schema': target['namespace']['schema'], 'role': target['role'], 'warehouse': target['compute'],
                        'parameters': {'MULTI_STATEMENT_COUNT': '1'}}
                add(_http(item, target, 'POST', target['base_url'] + '/api/v2/statements', body,
                          {'async': 'true', 'requestId': native_token}))
            elif adapter == 'databricks_sql':
                item['resubmission_policy'] = 'never; reconcile an unknown submission externally, then poll its original statement_id'
                body = {'statement': statement, 'warehouse_id': target['warehouse_id'],
                        'catalog': target['namespace']['catalog'], 'schema': target['namespace']['schema'],
                        'disposition': 'INLINE', 'format': 'JSON_ARRAY', 'wait_timeout': '0s'}
                add(_http(item, target, 'POST', target['base_url'] + '/api/2.0/sql/statements', body))
            elif adapter == 'bigquery_sql':
                job_id = 'dma_' + native_token.replace('-', '_')
                item['expected_identity'] = {'jobReference.projectId': target['project'], 'jobReference.location': target['location'], 'jobReference.jobId': job_id}
                item['expected_native_id'] = job_id
                add(_http(item, target, 'POST', 'https://bigquery.googleapis.com/bigquery/v2/projects/' + _segment(target['project']) + '/jobs',
                          {'jobReference': {'projectId': target['project'], 'location': target['location'], 'jobId': job_id},
                           'configuration': {'query': {'query': statement, 'useLegacySql': False, 'defaultDataset': {
                               'projectId': target['project'], 'datasetId': target['namespace']['dataset']}}}}))
            elif adapter == 'redshift_sql':
                args = ['aws', 'redshift-data', 'execute-statement', '--region', target['region'], '--database', target['namespace']['database'],
                        '--sql', statement, '--client-token', native_token, '--output', 'json']
                for key in ('cluster_identifier', 'workgroup_name', 'db_user', 'secret_arn'):
                    if key in target:
                        args += ['--' + key.replace('_', '-'), target[key]]
                item['expected_identity'] = {'Database': target['namespace']['database']}
                if 'workgroup_name' in target:
                    item['expected_identity']['WorkgroupName'] = target['workgroup_name']
                else:
                    item['expected_identity']['ClusterIdentifier'] = target['cluster_identifier']
                add(_process(item, target, args))
            elif adapter == 'clickhouse_sql':
                item['expected_native_id'] = native_token
                add(_http(item, target, 'POST', target['base_url'] + '/', query={'database': target['namespace']['database'],
                          'query_id': native_token, 'wait_end_of_query': '1', 'default_format': 'JSON'}))['text'] = statement
            elif adapter == 'motherduck_sql':
                # The actual client has no durable native job ID. Identity evidence
                # is an explicit query in the SAME connection before reviewed SQL.
                item['contract'] = 'motherduck_sync'
                item['observed_database_query'] = 'SELECT current_database() AS database;'
                add(_process(item, target, ['duckdb', 'md:' + target['namespace']['database'], '-json', '-bail', '-c',
                    'SELECT current_database() AS database;\n' + statement]))
                item['expected_identity'] = {'database': target['namespace']['database']}
    plan['plan_sha256'] = _hash(plan)
    return plan


def _get(value, path):
    for part in path.split('.'):
        if type(value) is not dict or part not in value:
            return None
        value = value[part]
    return value


def resolve_operation(operation, receipts):
    """Resolve receipt data only; never eval strings or dereference local files."""
    def visit(value):
        if type(value) is list:
            return [visit(v) for v in value]
        if type(value) is not dict:
            return value
        if '$binding' in value:
            _require(set(value) == {'$binding'} and type(value['$binding']) is str, 'Invalid response binding')
            source, sep, field = value['$binding'].partition('.')
            _require(sep and field == 'native_id' and source in receipts, 'Missing native identity binding')
            receipt = receipts[source]
            _require(receipt.get('operation_id') == source and receipt.get('state') not in ('failed', 'cancelled', 'partial', 'unknown'), 'Untrusted response binding')
            result = receipt.get(field)
            _require(type(result) in (str, int) and type(result) is not bool and _NATIVE.fullmatch(str(result)) is not None, 'Invalid bound native ID')
            return result
        if '$join' in value:
            _require(set(value) == {'$join'} and type(value['$join']) is list, 'Invalid URL binding')
            return ''.join(str(visit(v)) for v in value['$join'])
        return {k: visit(v) for k, v in value.items()}
    return visit(copy.deepcopy(operation))


def build_followup(plan, receipt, action='status'):
    """Observe/cancel exact native ID; no broad latest-run search or retry."""
    _require(action in ('status', 'cancel', 'results'), 'Unsupported follow-up action')
    target = validate_target(plan['target'])
    source = next((o for o in plan['operations'] if o['id'] == receipt.get('operation_id')), None)
    _require(source is not None and receipt.get('adapter') == target['adapter']
             and receipt.get('target_sha256') == _hash(target), 'Receipt does not belong to plan')
    native = receipt.get('native_id')
    _require(type(native) in (str, int) and type(native) is not bool and _NATIVE.fullmatch(str(native)) is not None, 'Missing or unsafe native ID; reconciliation required')
    adapter, native = target['adapter'], str(native)
    follow = copy.deepcopy(source)
    for key in ('body', 'text', 'argv', 'query', 'url', 'cwd', 'auth_env', 'auth', 'headers', 'artifact'):
        follow.pop(key, None)
    follow.update(id=source['id'] + '-' + action, origin_id=source['id'], phase='cancel' if action == 'cancel' else 'observe',
                  effect='write' if action == 'cancel' else 'read', depends_on=[], expected_native_id=native)
    if action == 'cancel':
        follow['contract'] = 'cancel_ack'
    if adapter == 'github_workflow':
        _require(action != 'results', 'GitHub artifacts require a separately scoped download operation')
        url = 'https://api.github.com/repos/%s/%s/actions/runs/%s' % (target['owner'], target['repo'], _segment(native))
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', url + ('/cancel' if action == 'cancel' else ''))
    if adapter == 'dbt_platform':
        _require(action != 'results', 'Select a specific dbt run artifact/step separately')
        url = target['base_url'] + '/api/v2/accounts/%s/runs/%s/' % (target['account_id'], _segment(native))
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', url + ('cancel/' if action == 'cancel' else ''))
    if adapter == 'coalesce':
        # runs get/list-results offer a profile but no domain override in the
        # documented CLI. Do not silently follow a mutable profile's default.
        _require(action == 'cancel', 'Automatic Coalesce status/results are unavailable until profile-domain binding is qualified')
        return _process(follow, target, ['coa', '--json', 'cancel', native, '--profile', target['profile'],
            '--domain', target['base_url'], '--environmentID', str(target['environment_id'])])
    if adapter == 'snowflake_sql':
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', target['base_url'] + '/api/v2/statements/' + _segment(native) + ('/cancel' if action == 'cancel' else ''))
    if adapter == 'databricks_sql':
        _require(_STATEMENT_ID.fullmatch(native) is not None, 'Invalid Databricks statement ID; reconciliation required')
        url = target['base_url'] + '/api/2.0/sql/statements/' + _segment(native)
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', url + ('/cancel' if action == 'cancel' else ''),
                     {} if action == 'cancel' else None)
    if adapter == 'databricks_job':
        endpoint = 'cancel' if action == 'cancel' else 'get-output' if action == 'results' else 'get'
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', target['base_url'] + '/api/2.2/jobs/runs/' + endpoint,
                     {'run_id': int(native)} if action == 'cancel' else None, None if action == 'cancel' else {'run_id': int(native)})
    if adapter == 'bigquery_sql':
        suffix = '/cancel' if action == 'cancel' else ''
        path = '/queries/' if action == 'results' else '/jobs/'
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', 'https://bigquery.googleapis.com/bigquery/v2/projects/' + _segment(target['project']) + path + _segment(native) + suffix, query={'location': target['location']})
    if adapter == 'dataform':
        prefix = 'projects/%s/locations/%s/repositories/%s/' % tuple(target[k] for k in ('project', 'location', 'repository'))
        _require(native.startswith(prefix) and '..' not in native, 'Dataform resource outside target repository')
        suffix = ':cancel' if action == 'cancel' else ':query' if action == 'results' else ''
        return _http(follow, target, 'POST' if action == 'cancel' else 'GET', 'https://dataform.googleapis.com/v1/' + native + suffix,
                     {} if action == 'cancel' else None)
    if adapter == 'redshift_sql':
        name = {'status': 'describe-statement', 'cancel': 'cancel-statement', 'results': 'get-statement-result'}[action]
        return _process(follow, target, ['aws', 'redshift-data', name, '--id', native, '--region', target['region'], '--output', 'json'])
    if adapter == 'clickhouse_sql':
        _require(action != 'results', 'ClickHouse query_log does not retain query result rows')
        if action == 'cancel':
            statement = "KILL QUERY WHERE query_id = '%s' SYNC FORMAT JSON" % native
        else:
            statement = ("SELECT query_id, type, exception_code FROM system.query_log WHERE query_id = '%s' "
                         "AND type IN ('QueryFinish', 'ExceptionBeforeStart', 'ExceptionWhileProcessing') ORDER BY event_time_microseconds DESC LIMIT 1 FORMAT JSON") % native
            follow['contract'] = 'clickhouse_log'
        result = _http(follow, target, 'POST', target['base_url'] + '/', query={'database': target['namespace']['database'], 'wait_end_of_query': '1'})
        result['text'] = statement
        result['coverage'] = 'Connected node only; cluster/Cloud completeness requires separately scoped per-replica evidence.'
        return result
    raise ValueError('No native durable status/cancellation interface is qualified for this route')


def _parse_body(response, strict=False):
    body = response.get('body', response.get('stdout'))
    if type(body) is str:
        try:
            if strict:
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError('Duplicate response key')
                        result[key] = value
                    return result
                def nonfinite(value):
                    raise ValueError('Nonfinite response value')
                return json.loads(body, object_pairs_hook=pairs, parse_constant=nonfinite)
            return json.loads(body)
        except (ValueError, TypeError):
            return None
    return body


def _databricks_result(payload):
    """Bounded INLINE first-chunk completeness, never implicit pagination.

    Missing optional vendor fields remain a coverage gap. No external links or
    next-chunk URLs are followed, returned, or copied into the normalized receipt.
    """
    if 'manifest' not in payload and 'result' not in payload:
        return 'missing', 'Native execution status has no current result evidence', None
    manifest, result = payload.get('manifest'), payload.get('result')
    if type(manifest) is not dict or type(result) is not dict:
        return 'invalid', 'Malformed native result envelope', None
    if manifest.get('format') != 'JSON_ARRAY':
        return 'invalid', 'Native result format differs from requested JSON_ARRAY', None
    if manifest.get('truncated') is not False:
        return 'incomplete', 'Native truncation state is true, missing or unrecognized', None
    total, chunk_count = manifest.get('total_row_count'), manifest.get('total_chunk_count')
    if type(total) is not int or total < 0 or type(chunk_count) is not int or chunk_count not in (0, 1):
        return 'incomplete', 'Native result totals are missing or require separately qualified chunk collection', None
    if chunk_count == 0 and total != 0:
        return 'invalid', 'Native result count is inconsistent', None
    if any(result.get(key) is not None for key in ('external_links', 'next_chunk_index', 'next_chunk_internal_link')):
        return 'incomplete', 'Native result needs external or additional chunk retrieval', None
    schema = manifest.get('schema')
    if type(schema) is not dict or type(schema.get('column_count')) is not int or schema['column_count'] < 0 or type(schema.get('columns')) is not list:
        return 'invalid', 'Malformed native result schema', None
    columns = schema['columns']
    if len(columns) != schema['column_count'] or any(
            type(column) is not dict or type(column.get('position')) is not int or column['position'] != i
            or type(column.get('name')) is not str or not column['name']
            or type(column.get('type_text')) is not str or not column['type_text']
            for i, column in enumerate(columns)):
        return 'invalid', 'Native result column schema is inconsistent', None
    if len({column['name'] for column in columns}) != len(columns):
        return 'invalid', 'Duplicate native result column names require explicit normalization', None
    rows = result.get('data_array')
    if type(rows) is not list or len(rows) != total or any(type(row) is not list or len(row) != len(columns)
            or any(value is not None and type(value) is not str for value in row) for row in rows):
        return 'invalid', 'Native result row width, type or count is inconsistent', None
    if any(type(result.get(key)) is not int or result[key] != wanted
           for key, wanted in (('chunk_index', 0), ('row_offset', 0), ('row_count', total))):
        return 'invalid', 'Native result chunk offset/count is inconsistent', None
    chunks = manifest.get('chunks')
    if type(chunks) is not list or len(chunks) != chunk_count:
        return 'incomplete', 'Native chunk manifest is incomplete', None
    if chunks and (type(chunks[0]) is not dict or any(type(chunks[0].get(key)) is not int or chunks[0][key] != wanted
            for key, wanted in (('chunk_index', 0), ('row_offset', 0), ('row_count', total)))
            or any(chunks[0].get(key) is not None for key in ('next_chunk_index', 'next_chunk_internal_link'))):
        return 'invalid', 'Native chunk manifest disagrees with observed result', None
    return 'complete', 'Complete bounded INLINE result; independent validation pending', {'row_count': total, 'column_count': len(columns)}


def normalize_response(operation, response, *, expected=None):
    """Normalize native payload; no arbitrary message/SQL/credential echo.

    response is trusted-transport envelope: body or stdout plus status_code or
    exit_code, optional headers and timed_out. expected can supply native_id to
    correlate a status poll. Caller must preserve response separately for data
    validation. Identity verification here covers listed native response fields,
    not authentication of the declared principal or business correctness.
    principal_verified/namespace_verified stay False: the coordinator requires
    signed external validation tied to actual native identity-query results.
    """
    _require(type(operation) is dict and type(response) is dict, 'Invalid response contract')
    adapter, contract = operation['adapter'], operation['contract']
    out = {'operation_id': operation.get('origin_id', operation['id']), 'observation_id': operation['id'], 'adapter': adapter, 'state': 'unknown', 'native_id': None,
           'identity_verified': False, 'identity_scope': 'native_response_fields_only', 'observed_identity': {},
           'principal_verified': False, 'namespace_verified': False,
           'qualification': 'native_execution_only', 'target_sha256': operation.get('target_sha256'),
           'reason': 'No recognized native terminal receipt'}
    if adapter == 'databricks_sql':
        out.update(result_complete=False, result_state='missing', native_state=None,
                   identity_scope='statement_id correlation only; target routing pinned separately; principal/namespace unverified')
    if response.get('timed_out') is True:
        out['reason'] = 'Transport timeout; reconcile before any retry'
        return out
    code = response.get('status_code')
    transport_code = code if operation.get('transport') == 'http' else response.get('exit_code')
    if type(transport_code) is not int:
        out['reason'] = 'Missing native transport completion metadata'
        return out
    if operation.get('transport') == 'process' and response.get('exit_code') not in (None, 0):
        out.update(state='failed', reason='Native process reported failure; partial effects may remain')
        return out
    data = _parse_body(response, strict=adapter == 'databricks_sql')
    payload = data
    if adapter == 'dbt_platform' and type(data) is dict:
        payload = data.get('data')
    payload = payload if type(payload) is dict else {}
    # Vendor schema drift and malformed envelopes are evidence gaps, not crashes.
    shapes = {
        'github_run': {'status': str, 'conclusion': str},
        'dbt_run': {'status': int},
        'coalesce_run': {'runStatus': str, 'runResults': list},
        'databricks_run': {'state': dict, 'tasks': list},
        'databricks_sql': {'statement_id': str, 'status': dict, 'manifest': dict, 'result': dict},
        'dataform_invocation': {'state': str},
        'dataform_compilation': {'compilationErrors': list},
        'snowflake_sql': {'code': str, 'sqlState': str, 'statementHandles': list},
        'bigquery_sql': {'status': dict},
        'redshift_sql': {'Status': str, 'SubStatements': list},
        'clickhouse_log': {'data': list},
    }
    if any(key in payload and payload[key] is not None and type(payload[key]) is not kind
           for key, kind in shapes.get(contract, {}).items()):
        out['reason'] = 'Unrecognized native response field types'
        return out
    if contract in ('databricks_run', 'bigquery_sql'):
        detail = payload.get('state' if contract == 'databricks_run' else 'status') or {}
        if any(key in detail and detail[key] is not None and type(detail[key]) is not str
               for key in ('life_cycle_state', 'result_state', 'state')):
            out['reason'] = 'Unrecognized native status field types'
            return out
    native = None
    state = 'unknown'
    if contract == 'cancel_ack':
        if adapter == 'databricks_sql':
            # Cancellation returns an empty object, never terminal success. If
            # an ID is supplied, it still must match the existing statement.
            native = payload.get('statement_id', operation.get('expected_native_id'))
            if type(data) is not dict or payload.get('error') or payload.get('error_code') or type(native) is not str or _STATEMENT_ID.fullmatch(native) is None:
                out['reason'] = 'Malformed Databricks cancellation acknowledgement'
                return out
            if native != operation.get('expected_native_id'):
                out.update(state='failed', reason='Native identity mismatch: statement_id')
                return out
        # Acknowledged cancellation is not terminal cancellation or rollback.
        if (type(code) is int and 200 <= code < 300) or response.get('exit_code') == 0:
            out.update(state='submitted', native_id=operation.get('expected_native_id'), reason='Cancellation requested; observe terminal state')
        return out
    if contract == 'github_run':
        native = payload.get('id', payload.get('workflow_run_id'))
        status = payload.get('status')
        state = {'queued': 'submitted', 'requested': 'submitted', 'waiting': 'submitted', 'pending': 'submitted', 'in_progress': 'running'}.get(status, 'unknown')
        if status == 'completed':
            state = {'success': 'succeeded', 'cancelled': 'cancelled', 'failure': 'failed', 'timed_out': 'failed', 'action_required': 'failed', 'startup_failure': 'failed'}.get(payload.get('conclusion'), 'unknown')
        elif native is not None:
            state = 'submitted'
    elif contract == 'dbt_run':
        native = payload.get('id')
        state = {1: 'submitted', 2: 'running', 3: 'running', 10: 'succeeded', 20: 'failed', 30: 'cancelled'}.get(payload.get('status'), 'unknown')
    elif contract == 'coalesce_run':
        native = payload.get('runID')
        state = {'waitingToRun': 'submitted', 'running': 'running', 'completed': 'succeeded', 'failed': 'failed', 'canceled': 'cancelled'}.get(payload.get('runStatus'), 'unknown')
        results = payload.get('runResults')
        if type(results) is list and any(type(r) is dict and (r.get('error') or r.get('status') in ('failed', 'error')) for r in results):
            state = 'partial'
    elif contract == 'bundle_deploy':
        if response.get('exit_code') == 0:
            out.update(state='submitted', reason='CLI completed; resource summary and target verification still required')
        return out
    elif contract == 'bundle_summary':
        native = _get(payload, 'workspace.root_path')
        state = 'succeeded' if type(payload.get('resources')) is dict and payload['resources'] else 'unknown'
    elif contract == 'databricks_definition':
        native, state = payload.get('job_id'), 'succeeded'
    elif contract == 'databricks_run':
        native = payload.get('run_id')
        detail = payload.get('state', {})
        detail = detail if type(detail) is dict else {}
        lifecycle, result = detail.get('life_cycle_state'), detail.get('result_state')
        if lifecycle in ('PENDING', 'QUEUED', 'BLOCKED', 'WAITING_FOR_RETRY'):
            state = 'submitted'
        elif lifecycle in ('RUNNING', 'TERMINATING'):
            state = 'running'
        elif lifecycle in ('TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'):
            state = {'SUCCESS': 'succeeded', 'CANCELED': 'cancelled', 'FAILED': 'failed', 'TIMEDOUT': 'failed'}.get(result, 'failed' if lifecycle == 'INTERNAL_ERROR' else 'unknown')
        elif native is not None:
            state = 'submitted'
        tasks = payload.get('tasks') or []
        if state == 'succeeded' and any(type(t) is not dict or type(t.get('state')) is not dict or t['state'].get('result_state') != 'SUCCESS' for t in tasks):
            state = 'partial'
    elif contract == 'databricks_sql':
        native, detail = payload.get('statement_id'), payload.get('status')
        if type(native) is not str or _STATEMENT_ID.fullmatch(native) is None or type(detail) is not dict or type(detail.get('state')) is not str:
            out['reason'] = 'Missing or malformed Databricks statement identity/status'
            return out
        native_state = detail['state']
        if native_state not in {'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED', 'CLOSED'}:
            out['reason'] = 'Unrecognized Databricks statement state'
            return out
        out['native_state'] = native_state
        state = {'PENDING': 'submitted', 'RUNNING': 'running', 'SUCCEEDED': 'succeeded',
                 'FAILED': 'failed', 'CANCELED': 'cancelled', 'CLOSED': 'unknown'}[native_state]
        if native_state == 'CLOSED':
            out.update(result_state='unavailable', result_issue='Statement is CLOSED; current result evidence is no longer available')
        elif native_state == 'SUCCEEDED':
            result_state, issue, summary = _databricks_result(payload)
            out.update(result_state=result_state, result_issue=issue)
            if detail.get('error') or detail.get('sql_state') not in (None, '00000'):
                state = 'unknown'
                out['result_issue'] = 'Successful state conflicts with native error metadata'
            elif result_state == 'complete':
                out.update(result_complete=True, result_summary=summary)
            elif result_state != 'missing' or operation.get('phase') == 'verify' or operation.get('effect') == 'read':
                state = 'unknown'
        elif payload.get('manifest') is not None or payload.get('result') is not None:
            state = 'unknown'
            out['result_issue'] = 'Non-successful state contains inconsistent result claims'
    elif contract == 'dataform_compilation':
        native = payload.get('name')
        state = 'failed' if payload.get('compilationErrors') else 'succeeded' if native else 'unknown'
    elif contract == 'dataform_invocation':
        native = payload.get('name')
        state = {'RUNNING': 'running', 'SUCCEEDED': 'succeeded', 'FAILED': 'failed', 'CANCELLED': 'cancelled', 'CANCELING': 'running'}.get(payload.get('state'), 'submitted' if native else 'unknown')
    elif contract == 'snowflake_sql':
        native = payload.get('statementHandle')
        if payload.get('code') == '333334':
            state = 'running'
        elif payload.get('code') == '090001' and payload.get('sqlState') == '00000':
            state = 'succeeded'
        elif payload.get('sqlState') not in (None, '00000'):
            state = 'failed'
        if payload.get('statementHandles'):
            state = 'partial'  # This route deliberately submits one statement.
    elif contract == 'bigquery_sql':
        native = _get(payload, 'jobReference.jobId')
        detail = payload.get('status', {})
        detail = detail if type(detail) is dict else {}
        state = {'PENDING': 'submitted', 'RUNNING': 'running', 'DONE': 'succeeded'}.get(detail.get('state'), 'unknown')
        if detail.get('errorResult'):
            state = 'failed'
        elif detail.get('errors'):
            state = 'partial'  # BigQuery can report nonfatal errors separately.
    elif contract == 'redshift_sql':
        native = payload.get('Id')
        state = {'SUBMITTED': 'submitted', 'PICKED': 'submitted', 'STARTED': 'running', 'FINISHED': 'succeeded', 'FAILED': 'failed', 'ABORTED': 'cancelled'}.get(payload.get('Status'), 'submitted' if native else 'unknown')
        if payload.get('Error'):
            state = 'failed'
        children = payload.get('SubStatements') or []
        if children and any(type(s) is not dict or s.get('Status') != 'FINISHED' or s.get('Error') for s in children):
            state = 'partial'
    elif contract == 'clickhouse_sql':
        raw_headers = response.get('headers') or {}
        if type(raw_headers) is not dict or not all(type(k) is str for k in raw_headers):
            out['reason'] = 'Invalid native response headers'
            return out
        headers = {k.lower(): v for k, v in raw_headers.items()}
        native = headers.get('x-clickhouse-query-id')
        raw = response.get('body', '')
        if headers.get('x-clickhouse-exception-code') not in (None, '0', 0) or (type(raw) is str and re.search(r'(?:^|\n)Code: \d+.*DB::Exception', raw)) or payload.get('exception'):
            state = 'failed'
        elif type(payload.get('data')) is list and type(payload.get('meta')) is list and type(payload.get('rows')) is int:
            state = 'succeeded'  # Complete structured SELECT result, not mere 200.
        elif native:
            state = 'submitted'  # DDL commonly returns empty body; query_log is required.
    elif contract == 'clickhouse_log':
        rows = payload.get('data')
        if type(rows) is list and len(rows) == 1 and type(rows[0]) is dict:
            row = rows[0]
            native = row.get('query_id')
            state = 'succeeded' if row.get('type') == 'QueryFinish' and row.get('exception_code') == 0 else 'failed' if row.get('type') in ('ExceptionBeforeStart', 'ExceptionWhileProcessing') else 'unknown'
    elif contract == 'motherduck_sync':
        # DuckDB -json emits one JSON value per result. Parse the complete stream,
        # preserving the leading identity result; an empty stdout is never proof.
        raw = response.get('stdout', '')
        values = []
        if type(raw) is str:
            decoder, offset = json.JSONDecoder(), 0
            try:
                while raw[offset:].strip():
                    offset += len(raw[offset:]) - len(raw[offset:].lstrip())
                    value, offset = decoder.raw_decode(raw, offset)
                    values.append(value)
            except ValueError:
                values = []
        if values and type(values[0]) is list and len(values[0]) == 1 and type(values[0][0]) is dict:
            payload = values[0][0]
            state = 'succeeded' if response.get('exit_code') == 0 else 'unknown'
            out['identity_scope'] = 'synchronous_client_database_observation; no durable remote job ID'
        native = None
    else:
        raise ValueError('Unknown native receipt contract')

    wanted = operation.get('expected_native_id')
    if expected is not None:
        _require(type(expected) is dict and set(expected) <= {'native_id'}, 'Unsupported expected receipt fields')
        wanted = expected.get('native_id', wanted)
    if native is not None and (type(native) not in (str, int) or type(native) is bool or
                               _NATIVE.fullmatch(str(native)) is None):
        state, native = 'unknown', None
    out['native_id'] = native
    prefix = operation.get('expected_native_prefix')
    if native is not None and prefix and (not str(native).startswith(prefix) or '..' in str(native)):
        out.update(state='failed', reason='Native resource outside approved target')
        return out
    checks, missing, mismatches = operation.get('expected_identity', {}), [], []
    for path, value in checks.items():
        actual = _get(payload, path)
        if actual is None:
            missing.append(path)
        elif type(value) is dict:
            missing.append(path)  # unresolved binding is never an equality proof.
        elif actual != value:
            mismatches.append(path)
        else:
            out['observed_identity'][path] = actual
    if wanted is not None:
        if native is None:
            missing.append('native_id')
        elif str(native) != str(wanted):
            mismatches.append('native_id')
    if mismatches:
        out.update(state='failed', reason='Native identity mismatch: ' + ', '.join(mismatches))
        if adapter == 'databricks_sql':
            out['result_complete'] = False
        return out
    if state == 'succeeded' and (missing or (native is None and contract != 'motherduck_sync')):
        state = 'unknown'
    if type(code) is int and not 200 <= code < 300:
        state = 'unknown' if code in (408, 409, 429) or code >= 500 else 'failed'
    if adapter == 'databricks_sql' and state != 'succeeded':
        out['result_complete'] = False
    out.update(state=state, identity_verified=not missing and (native is not None or contract == 'motherduck_sync'))
    out['reason'] = ('Missing identity fields: ' + ', '.join(missing)) if missing else {
        'succeeded': 'Native terminal success; independent verification pending',
        'failed': 'Native failure; partial effects may remain', 'partial': 'Partial or inconsistent native completion',
        'cancelled': 'Native cancellation; rollback is not implied', 'submitted': 'Native request identified; terminal evidence pending',
        'running': 'Native execution is active', 'unknown': 'Native receipt incomplete; reconciliation required'}[state]
    if adapter == 'databricks_sql' and state == 'unknown' and out.get('result_issue'):
        out['reason'] = out['result_issue'] + '; do not resubmit'
    return out
