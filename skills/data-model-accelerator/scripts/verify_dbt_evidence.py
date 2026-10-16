#!/usr/bin/env python3
"""Read-only native dbt build evidence association, not execution or approval.

Qualified artifact contract: dbt-core 1.12.4, manifest/v12, run-results/v6.
Version 2 receipts separately qualify dbt/dbt-oss 2.0.8 local DuckDB builds;
they bind installed runtime and driver pins, the raw request/version output,
exact commands and effective analysis mode. Identical artifact schema versions
do not identify the engine. No version 1 check is relaxed for those artifacts.
Use snapshot_project(project_root) before execution and expected_nodes(preflight)
to freeze the full runnable denominator. Store a receipt with schema_version 1,
kind native_dbt_build_evidence, project_root, validation_scope (local or target),
expected_adapter_type, expected_dbt_version, expected_target_name,
project_snapshot, expected_node_ids, execution {exit_code,started_at,finished_at},
and preflight_manifest/manifest/run_results associations {path,sha256}. Evidence
paths are relative to the receipt directory. Capture files before the build;
never create a passing receipt by refreshing a stale snapshot after execution.

Manifest and run-results schemas: https://schemas.getdbt.com/dbt/manifest/v12.json
and https://schemas.getdbt.com/dbt/run-results/v6.json. dbt 1.12.4 source-file
checksums compact whitespace; seed checksums strip surrounding whitespace.
Generic YAML tests have generated raw_code and checksum none: their definitions
must match preflight, and their complete YAML files remain byte-hash-bound.

This is a self-attested receipt. It does not authenticate a process, principal,
account, approval, dependency installation or data correctness. Built-in macros
are version-bound, not authenticated here. External package resources, unit
tests, functions and operation hooks need separate qualification. No repository
code, dbt command, network request or warehouse query is executed by this tool.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

SHA = re.compile(r'[0-9a-f]{64}\Z')
RESOURCE_TYPES = {'model', 'test', 'seed', 'snapshot'}
IGNORED_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'target', 'logs'}
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 5000, 10 * 1024 * 1024, 100 * 1024 * 1024
MANIFEST_SCHEMA = 'https://schemas.getdbt.com/dbt/manifest/v12.json'
RESULTS_SCHEMA = 'https://schemas.getdbt.com/dbt/run-results/v6.json'
DBT_VERSION = '1.12.4'
TEST_RUNTIME_MACROS = {'macro.dbt.' + name for name in (
    'get_where_subquery', 'get_limit_subquery_sql', 'should_store_failures', 'statement')}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def canonical(path):
    path = Path(path).absolute()
    need(not any(p.is_symlink() for p in (path,) + tuple(path.parents)), 'Symlinked evidence/project path')
    need(path.resolve(strict=True) == path, 'Noncanonical evidence/project path')
    return path


def relative_path(value):
    need(nonempty(value) and '\\' not in value and '\x00' not in value, 'Invalid relative evidence/project path')
    path = PurePosixPath(value)
    need(not path.is_absolute() and '..' not in path.parts and path.as_posix() == value and value != '.', 'Path must remain within its declared root')
    return path


def read_json(path):
    path = canonical(path)
    need(path.is_file() and path.stat().st_size <= MAX_TOTAL_BYTES, 'Missing/oversized evidence file')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def instant(value, label):
    need(nonempty(value), 'Missing timestamp: ' + label)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid timestamp: ' + label) from error
    need(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'Naive timestamp: ' + label)
    return parsed


def _project_files(project_root):
    root = canonical(project_root)
    need(root.is_dir(), 'project_root must be a directory')
    files, total = [], 0
    for base, dirs, names in os.walk(str(root), followlinks=False):
        # Even ignored directory symlinks are rejected, never traversed.
        for name in dirs + names:
            need(not (Path(base) / name).is_symlink(), 'Project contains a symlink')
        dirs[:] = sorted(name for name in dirs if name not in IGNORED_DIRS)
        for name in sorted(names):
            path = Path(base) / name
            need(path.is_file(), 'Nonregular project entry')
            # Profiles/secrets must be held outside this reviewable project copy.
            need(name != 'profiles.yml' and not name.startswith('.env') and path.suffix.lower() not in {'.pem', '.key'}, 'Credential/profile file must remain outside reviewed project')
            size = path.stat().st_size
            need(size <= MAX_FILE_BYTES, 'Project file byte limit exceeded')
            total += size
            need(total <= MAX_TOTAL_BYTES and len(files) < MAX_FILES, 'Project inventory limit exceeded')
            files.append({'path': path.relative_to(root).as_posix(), 'sha256': digest(path.read_bytes())})
    need(any(f['path'] == 'dbt_project.yml' for f in files), 'Reviewed project lacks dbt_project.yml')
    return sorted(files, key=lambda item: item['path'])


def snapshot_project(project_root):
    """Capture byte hashes before execution; does not invoke dbt or inspect secrets."""
    files = _project_files(project_root)
    return {'captured_at': datetime.now(timezone.utc).isoformat(), 'files': files}


def expected_nodes(manifest):
    """Return full enabled runnable IDs; ephemeral models need compilation only."""
    need(isinstance(manifest, dict) and isinstance(manifest.get('nodes'), dict), 'Manifest nodes must be an object')
    need(not manifest.get('unit_tests') and not manifest.get('functions'), 'Unit tests/functions require separate qualification')
    ids = []
    for uid, node in manifest['nodes'].items():
        need(isinstance(node, dict) and node.get('unique_id') == uid and nonempty(uid), 'Invalid manifest node identity')
        resource = node.get('resource_type')
        need(resource in RESOURCE_TYPES | {'analysis'}, 'Unsupported manifest resource: ' + str(resource))
        config = node.get('config', {})
        need(isinstance(config, dict), 'Invalid node configuration')
        if resource in RESOURCE_TYPES and config.get('enabled', True) is not False and not (resource == 'model' and config.get('materialized') == 'ephemeral'):
            ids.append(uid)
    need(ids, 'Empty native dbt execution denominator')
    return sorted(ids)


def definition(node):
    """Exclude compilation/run diagnostics while retaining parsed semantics."""
    keys = ('unique_id', 'resource_type', 'package_name', 'original_file_path', 'checksum',
            'raw_code', 'config', 'depends_on', 'database', 'schema', 'alias', 'language',
            'test_metadata', 'column_name', 'patch_path', 'contract', 'constraints')
    return {key: node[key] for key in keys if key in node}


def same_definition(before, after, preflight, manifest):
    """dbt adds a few built-in execution wrappers to test dependencies at build."""
    left, right = definition(before), definition(after)
    if after.get('resource_type') == 'test':
        old = left.get('depends_on', {}).get('macros', [])
        new = right.get('depends_on', {}).get('macros', [])
        need(isinstance(old, list) and isinstance(new, list) and all(nonempty(x) for x in old + new), 'Invalid test macro dependencies')
        additions = set(new) - set(old)
        if additions <= TEST_RUNTIME_MACROS and set(old) <= set(new):
            for uid in additions:
                prior, current = preflight.get('macros', {}).get(uid), manifest.get('macros', {}).get(uid)
                need(isinstance(prior, dict) and isinstance(current, dict), 'Missing built-in test execution macro')
                fields = ('unique_id', 'package_name', 'original_file_path', 'macro_sql')
                need(prior.get('package_name') == 'dbt' and nonempty(prior.get('macro_sql')) and
                     {k: prior.get(k) for k in fields} == {k: current.get(k) for k in fields}, 'Built-in test execution macro changed')
            if 'depends_on' in right:
                right['depends_on'] = dict(right['depends_on'], macros=old)
    return left == right


def _runtime_receipt(receipt, root, result):
    """Version 2 observations substitute only fields absent in native v2 artifacts."""
    from dbt_runtime import driver_contract, observed_version, runtime_argv, runtime_contract, validate_selection
    runtime = receipt.get('runtime')
    need(type(runtime) is dict and set(runtime) == {'selection', 'identity', 'observed', 'driver', 'effective_analysis_mode'},
         'Missing versioned runtime observations')
    selection = validate_selection(runtime['selection'])
    need(selection == runtime['selection'] and selection['distribution'] in ('dbt', 'dbt_oss') and
         runtime_contract(selection, receipt['expected_adapter_type'])['execution']['qualified'], 'Unqualified selected runtime contract')
    need(receipt['validation_scope'] == 'local' and receipt['expected_adapter_type'] == 'duckdb', 'v2 execution is qualified only for local DuckDB')
    need(runtime['effective_analysis_mode'] == selection['analysis_mode'], 'Effective analysis mode mismatch')
    observed = runtime['observed']
    need(type(observed) is dict and observed == observed_version(observed.get('version_output', ''), selection),
         'Observed runtime distribution/version mismatch')
    output = receipt.get('version_output')
    need(type(output) is dict and set(output) == {'path', 'sha256'}, 'Missing native version output association')
    version_path = canonical(root / relative_path(output['path']))
    need(version_path.is_file() and version_path.stat().st_size <= 4096, 'Missing/oversized native version output')
    version_bytes = version_path.read_bytes()
    need(digest(version_bytes) == output['sha256'] and observed_version(version_bytes.decode('utf-8'), selection) == observed,
         'Native version output association mismatch')
    association = receipt.get('request')
    need(type(association) is dict and set(association) == {'path', 'sha256'}, 'Missing execution request association')
    request_path = canonical(root / relative_path(association['path']))
    request = read_json(request_path)
    need(digest(request_path.read_bytes()) == association['sha256'], 'Execution request hash mismatch')
    need(type(request) is dict and request.get('schema_version') == 2 and validate_selection(request.get('dbt_runtime')) == selection,
         'Request runtime selection mismatch')
    identity = runtime['identity']
    need(type(identity) is dict and set(identity) == {'distribution', 'version', 'package', 'files'} and
         identity['distribution'] == selection['distribution'] and identity['version'] == selection['version'] and
         identity['package'] == ('dbt' if selection['distribution'] == 'dbt' else 'dbt-oss') and request.get('runtime_identity') == identity,
         'Runtime identity differs from requested pin')
    files = identity.get('files')
    need(type(files) is list and 5 <= len(files) <= 1004, 'Missing runtime file identities')
    paths = set()
    for item in files:
        need(type(item) is dict and set(item) == {'path', 'sha256'} and nonempty(item['path']) and
             Path(item['path']).is_absolute() and '..' not in Path(item['path']).parts and item['path'] not in paths and
             type(item['sha256']) is str and SHA.fullmatch(item['sha256']), 'Invalid runtime file identity')
        paths.add(item['path'])
    need(any(Path(p).name.startswith('_core.') for p in paths) and any(Path(p).name == 'METADATA' for p in paths),
         'Native implementation/package identity missing')
    driver = runtime['driver']
    need(type(driver) is dict and set(driver) == {'path', 'sha256', 'version', 'platform'} and type(driver['platform']) is str,
         'Missing driver identity')
    platform_parts = driver['platform'].split('/')
    need(len(platform_parts) == 2, 'Invalid driver platform')
    contract = driver_contract(*platform_parts)
    need(driver['sha256'] == contract['sha256'] and driver['version'] == contract['version'] and
         request.get('driver') == {k: driver[k] for k in ('path', 'sha256', 'version')}, 'Unqualified driver pin')
    need(request.get('adapter_type') == receipt['expected_adapter_type'] and request.get('target') == receipt['expected_target_name'],
         'Request adapter/target mismatch')
    commands = receipt.get('commands')
    need(type(commands) is dict and set(commands) == {'version', 'parse', 'build'}, 'Missing version/parse/build command evidence')
    original_project = Path(receipt['project_root'])
    executable = files[0]['path']
    expected_args = {'version': [executable, '--version']}
    for verb, folder in (('parse', 'preflight'), ('build', 'build')):
        expected_args[verb] = runtime_argv(executable, verb, original_project, request['profiles_dir'], request['profile'],
                                          request['target'], original_project.parent / folder, selection)
    previous = None
    for verb in ('version', 'parse', 'build'):
        step = commands[verb]
        need(type(step) is dict and set(step) == {'args', 'exit_code', 'started_at', 'finished_at'} and
             step['args'] == expected_args[verb] and type(step['exit_code']) is int and step['exit_code'] == 0,
             'Unqualified/failed native command: ' + verb)
        start, end = instant(step['started_at'], verb + ' start'), instant(step['finished_at'], verb + ' finish')
        need(start <= end and (previous is None or previous <= start), 'Command chronology mismatch')
        previous = end
    need(receipt['execution'] == {k: commands['build'][k] for k in ('exit_code', 'started_at', 'finished_at')},
         'Build execution/command mismatch')
    need(type(receipt.get('profile_sha256')) is str and SHA.fullmatch(receipt['profile_sha256']), 'Profile byte pin missing')
    result.update(runtime_distribution=selection['distribution'], runtime_selection=selection,
                  effective_analysis_mode=selection['analysis_mode'], driver_version=driver['version'])
    return selection, request, commands


def _same_definition_v2(before, after, preflight, manifest, selection):
    if selection['analysis_mode'] == 'none':
        after = copy.deepcopy(after)
        config = after.get('config', {})
        need(config.get('static_analysis') == 'off' and after.get('static_analysis_off_reason') == 'configuredoff',
             'OSS effective analysis configuration mismatch')
        config['static_analysis'] = before.get('config', {}).get('static_analysis')
    return same_definition(before, after, preflight, manifest)


def _verify(receipt_path, result, project_root=None):
    receipt_path = canonical(receipt_path)
    root = receipt_path.parent
    receipt = read_json(receipt_path)
    result['receipt_sha256'] = digest(receipt_path.read_bytes())
    need(isinstance(receipt, dict) and type(receipt.get('schema_version')) is int and receipt['schema_version'] in (1, 2) and receipt.get('kind') == 'native_dbt_build_evidence', 'Expected version 1 or 2 native_dbt_build_evidence receipt')
    v2 = receipt['schema_version'] == 2
    scope, adapter = receipt.get('validation_scope'), receipt.get('expected_adapter_type')
    need(scope in ('local', 'target') and nonempty(adapter), 'Invalid validation scope/adapter')
    need(adapter != 'duckdb' or scope == 'local', 'DuckDB native execution cannot establish target warehouse validation')
    selection, request, commands = _runtime_receipt(receipt, root, result) if v2 else (None, None, None)
    version = selection['version'] if v2 else DBT_VERSION
    need(receipt.get('expected_dbt_version') == version, 'Unqualified dbt artifact/checksum version')
    need(nonempty(receipt.get('expected_target_name')), 'Expected target name is required')
    need(nonempty(receipt.get('project_root')) and Path(receipt['project_root']).is_absolute(), 'project_root must be absolute')
    project = canonical(receipt['project_root'] if project_root is None else project_root)
    result.update(declared_project_root=receipt['project_root'], verified_project_root=str(project))
    result.update(validation_scope=scope, adapter_type=adapter, dbt_version=version)
    associations, evidence_paths = {}, set()
    for name in ('preflight_manifest', 'manifest', 'run_results'):
        association = receipt.get(name)
        need(isinstance(association, dict) and set(association) == {'path', 'sha256'}, 'Missing evidence association: ' + name)
        path = canonical(root / relative_path(association['path']))
        need(path != receipt_path and path not in evidence_paths, 'Evidence associations must reference distinct files')
        need(path.is_file() and path.stat().st_size <= MAX_TOTAL_BYTES, 'Missing/oversized evidence file')
        evidence_paths.add(path)
        need(isinstance(association['sha256'], str) and SHA.fullmatch(association['sha256']) and digest(path.read_bytes()) == association['sha256'], 'Changed evidence hash: ' + name)
        associations[name] = read_json(path)
    preflight, manifest, runs = (associations[name] for name in ('preflight_manifest', 'manifest', 'run_results'))
    if v2:
        from run_dbt_project import validate_preflight
        validate_preflight(preflight, request)
    metas = []
    for name, document, schema in [('preflight', preflight, MANIFEST_SCHEMA), ('manifest', manifest, MANIFEST_SCHEMA), ('run_results', runs, RESULTS_SCHEMA)]:
        need(isinstance(document, dict) and isinstance(document.get('metadata'), dict), 'Missing metadata: ' + name)
        meta = document['metadata']; metas.append(meta)
        need(meta.get('dbt_schema_version') == schema and meta.get('dbt_version') == version, 'Artifact schema/dbt version mismatch: ' + name)
        need(nonempty(meta.get('invocation_id')), 'Missing invocation identity: ' + name)
    pm, mm, rm = metas
    need(pm.get('adapter_type') == mm.get('adapter_type') == adapter, 'Manifest adapter mismatch')
    need(nonempty(pm.get('project_name')) and pm.get('project_name') == mm.get('project_name'), 'Manifest project mismatch')
    need(mm['invocation_id'] == rm['invocation_id'], 'Manifest/run_results invocation mismatch')
    result['invocation_id'] = mm['invocation_id']
    snapshot, execution = receipt.get('project_snapshot'), receipt.get('execution')
    need(isinstance(snapshot, dict) and isinstance(execution, dict), 'Pre-execution snapshot and execution receipt required')
    need(type(execution.get('exit_code')) is int and execution['exit_code'] == 0, 'Native process did not exit successfully')
    captured = instant(snapshot.get('captured_at'), 'snapshot')
    started = instant(execution.get('started_at'), 'execution start')
    finished = instant(execution.get('finished_at'), 'execution finish')
    invocation = instant(mm.get('invocation_started_at'), 'manifest invocation start')
    if not v2 or rm.get('invocation_started_at') is not None:
        need(invocation == instant(rm.get('invocation_started_at'), 'run_results invocation start'), 'Invocation start mismatch')
    need(captured <= started <= invocation <= instant(mm.get('generated_at'), 'manifest generated') <= finished, 'Snapshot/build/manifest chronology mismatch')
    need(invocation <= instant(rm.get('generated_at'), 'run_results generated') <= finished, 'Stale run_results chronology')
    need(instant(pm.get('generated_at'), 'preflight generated') <= started, 'Preflight must precede build')
    if v2:
        need(pm['invocation_id'] != mm['invocation_id'], 'Preflight and build must be separate invocations')
        need(instant(commands['parse']['started_at'], 'parse start') <= instant(pm.get('invocation_started_at'), 'parse invocation') <=
             instant(pm['generated_at'], 'parse generated') <= instant(commands['parse']['finished_at'], 'parse finish') <= captured,
             'Preflight command/invocation chronology mismatch')
    files = snapshot.get('files')
    need(isinstance(files, list) and files, 'Snapshot file inventory required')
    declared = {}
    for item in files:
        need(isinstance(item, dict) and set(item) == {'path', 'sha256'}, 'Invalid snapshot file')
        path = relative_path(item['path']).as_posix()
        need(path not in declared and isinstance(item['sha256'], str) and SHA.fullmatch(item['sha256']), 'Duplicate/invalid snapshot file')
        declared[path] = item['sha256']
    current = {item['path']: item['sha256'] for item in _project_files(project)}
    need(declared == current, 'Project file inventory/content drift since pre-execution snapshot')
    if v2:
        # ae_common.snapshot hashes the sorted byte inventory, independently of
        # this verifier's captured_at wrapper.
        inventory_hash = digest(json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())
        need(request.get('project_sha256') == inventory_hash, 'Request project pin mismatch')
    result['project_snapshot_sha256'] = digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
    expected = receipt.get('expected_node_ids')
    need(isinstance(expected, list) and expected and all(nonempty(uid) for uid in expected) and len(set(expected)) == len(expected), 'Expected node IDs must be unique and nonempty')
    need(sorted(expected) == expected_nodes(preflight) == expected_nodes(manifest), 'Expected/preflight/executed manifest node denominator mismatch')
    need(set(preflight['nodes']) == set(manifest['nodes']), 'Manifest node inventory changed after preflight')
    for uid, node in manifest['nodes'].items():
        same = (_same_definition_v2(preflight['nodes'][uid], node, preflight, manifest, selection) if v2 else
                same_definition(preflight['nodes'][uid], node, preflight, manifest))
        need(same, 'Parsed node definition changed after preflight: ' + uid)
        if v2:
            config = node.get('config', {})
            need(node['resource_type'] != 'snapshot' and
                 (node['resource_type'] != 'model' or config.get('materialized') in ('table', 'view', 'ephemeral')) and
                 not config.get('contract', {}).get('enforced') and not node.get('version'), 'Unqualified v2 resource/feature')
            need(config.get('static_analysis') == ('off' if selection['analysis_mode'] == 'none' else 'baseline'),
                 'Manifest effective analysis mode mismatch')
        need(node.get('package_name') == mm['project_name'], 'External package resources require separate file mapping qualification')
        path = relative_path(node.get('original_file_path')).as_posix()
        need(path in declared, 'Manifest source file missing from snapshot: ' + path)
        text = (project / path).read_text(encoding='utf-8').strip()
        resource, checksum = node.get('resource_type'), node.get('checksum')
        if resource == 'test' and isinstance(node.get('test_metadata'), dict):
            need(Path(path).suffix.lower() in ('.yml', '.yaml') and checksum == {'name': 'none', 'checksum': ''} and nonempty(node.get('raw_code')), 'Unsupported generic test source/checksum')
        elif resource == 'snapshot' and Path(path).suffix.lower() in ('.yml', '.yaml'):
            raise ValueError('YAML snapshots require separate artifact/source binding qualification')
        else:
            normalized = text if resource == 'seed' else ' '.join(text.split())
            need(checksum == {'name': 'sha256', 'checksum': digest(normalized.encode())}, 'Manifest checksum differs from source file: ' + uid)
            if resource != 'seed':
                need(node.get('raw_code') == text, 'Manifest raw_code differs from source file: ' + uid)
        if uid in expected and resource in ('model', 'test', 'snapshot'):
            need(node.get('compiled') is True and nonempty(node.get('compiled_code')), 'Runnable node lacks compiled code: ' + uid)
    # Keep source YAML declarations and project macros bound to the same preflight.
    for group in ('sources', 'macros'):
        before, after = preflight.get(group, {}), manifest.get(group, {})
        need(isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after), 'Manifest ' + group + ' inventory changed')
        for uid, value in after.items():
            need(isinstance(value, dict), 'Invalid manifest ' + group + ' entry')
            if value.get('package_name') == mm['project_name']:
                stable = lambda record: {key: cell for key, cell in record.items() if key != 'created_at'}
                need(stable(value) == stable(before[uid]), 'Project ' + group + ' definition changed after preflight')
                path = relative_path(value.get('original_file_path')).as_posix()
                need(path in declared, 'Manifest ' + group + ' file missing from project snapshot')
                if group == 'macros':
                    need(nonempty(value.get('macro_sql')) and value['macro_sql'].strip() in (project / path).read_text(encoding='utf-8'), 'Macro SQL differs from reviewed file')
    args = runs.get('args')
    need(isinstance(args, dict) and args.get('which') == 'build', 'Native evidence must come from dbt build')
    if v2:
        need(args == {'command': 'build', 'which': 'build', 'full_refresh': False,
                      'static_analysis': 'Off' if selection['analysis_mode'] == 'none' else 'Baseline'},
             'Unqualified native v2 arguments/effective analysis mode')
    else:
        need(args.get('target') == receipt['expected_target_name'], 'dbt execution target mismatch')
    for option in ('select', 'exclude', 'selector', 'resource_types', 'exclude_resource_types', 'state', 'defer_state', 'vars'):
        need(args.get(option) in (None, [], {}, ''), 'Selected/state/vars build is not qualified full-project execution: ' + option)
    for option in ('empty', 'defer', 'favor_state'):
        need(args.get(option) in (None, False), 'Partial/deferred/empty build is not qualified: ' + option)
    records = runs.get('results')
    need(isinstance(records, list) and records, 'Native run_results is empty')
    seen, counts = set(), {resource: 0 for resource in sorted(RESOURCE_TYPES)}
    for record in records:
        need(isinstance(record, dict) and nonempty(record.get('unique_id')), 'Result requires unique_id')
        uid = record['unique_id']
        need(uid not in seen and uid in expected, 'Duplicate/unknown native result: ' + uid)
        seen.add(uid)
        resource = manifest['nodes'][uid]['resource_type']; counts[resource] += 1
        need(record.get('status') == ('pass' if resource == 'test' else 'success'), 'Native node did not pass/succeed: ' + uid)
        timings = record.get('timing')
        need(isinstance(timings, list) and all(isinstance(t, dict) for t in timings), 'Missing native execution timing: ' + uid)
        executed = [t for t in timings if t.get('name') == 'execute']
        need(len(executed) == 1, 'Native node requires one execution interval: ' + uid)
        need(invocation <= instant(executed[0].get('started_at'), 'node execute start') <=
             instant(executed[0].get('completed_at'), 'node execute finish') <=
             instant(rm.get('generated_at'), 'run_results generated'), 'Native node execution timing is outside invocation: ' + uid)
        if resource in ('model', 'test', 'snapshot'):
            compiled = (record.get('compiled') is None or record.get('compiled') is True) if v2 else record.get('compiled') is True
            need(compiled and record.get('compiled_code') == manifest['nodes'][uid]['compiled_code'], 'Compiled execution code differs from manifest: ' + uid)
        failures = record.get('failures')
        need((type(failures) is int and failures == 0) if resource == 'test' else failures is None or (type(failures) is int and failures == 0), 'Native result failures must be zero: ' + uid)
        batches = record.get('batch_results')
        need(batches is None or isinstance(batches, dict), 'Invalid microbatch result')
        need(not batches or not batches.get('failed'), 'Native microbatch failures remain: ' + uid)
    need(seen == set(expected), 'Native result denominator incomplete')
    result['counts'] = dict(counts, runnable_nodes=len(expected), project_files=len(files))


def verify(receipt_path, project_root=None):
    """Verify an archived receipt; optional root override changes only file resolution.

    This supports an identical reviewed project copied to another checkout. The
    original receipt, timestamps, byte hashes and evidence paths remain intact.
    """
    result = {'schema_version': 1, 'kind': 'dbt_evidence_verification', 'evidence_complete': False,
              'errors': [], 'validation_scope': None, 'adapter_type': None, 'dbt_version': None,
              'invocation_id': None, 'counts': {}, 'declared_project_root': None, 'verified_project_root': None, 'limitations': [
                  'Self-attested artifact association; does not authenticate native execution, warehouse identity, data correctness, dependency installation or human approval.',
                  'DuckDB evidence is local only. Full root-project builds only; external package resources, unit tests, functions, operation hooks and YAML snapshots are unqualified.',
                  'Current byte hashes detect drift relative to the supplied pre-execution snapshot; trusted execution controls must establish when that snapshot was actually captured.',
                  'Built-in macro implementation is version-bound here, not authenticated; profiles, environment variables and live database state require separate execution controls.']}
    try:
        _verify(receipt_path, result, project_root=project_root)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        result['errors'].append(str(error))
    result['evidence_complete'] = not result['errors']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('--project-root', type=Path, help='Verify an identical relocated project without changing archived receipt/evidence')
    args = parser.parse_args()
    result = verify(args.receipt, project_root=args.project_root)
    print(json.dumps(result, indent=2))
    return 0 if result['evidence_complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
