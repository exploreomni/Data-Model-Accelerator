"""Run an explicitly authorized, pinned dbt project in a separate working copy.

The destination preflight is not a sandbox: reviewed macros/SQL can have side
effects during parse or build. Profiles and identities are not authenticated by
this runner. No dependency installation, deployment or cutover is performed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from ae_common import hash_file, load_json, require, snapshot, write_json
from verify_dbt_evidence import (DBT_VERSION, MANIFEST_SCHEMA, canonical,
                                 expected_nodes, snapshot_project, verify)

REQUEST_FIELDS = {'schema_version', 'project_sha256', 'adapter_type', 'profile', 'target',
                  'profiles_dir', 'allowed_destinations', 'expected_profile', 'timeout_seconds'}
SHA = re.compile(r'[0-9a-f]{64}\Z')


def _text(value, label):
    require(type(value) is str and value and value == value.strip() and
            not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid ' + label)
    return value


def _runtime_environment():
    for name, value in os.environ.items():
        if name.startswith('DBT_') and value and name != 'DBT_SEND_ANONYMOUS_USAGE_STATS':
            require(name.startswith(('DBT_ENV_CUSTOM_ENV_', 'DBT_ENV_SECRET_')),
                    'Unqualified dbt runtime environment variable: ' + name)


def _hooks(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lstrip('+').replace('_', '-') in ('pre-hook', 'post-hook', 'on-run-start', 'on-run-end'):
                require(item in (None, [], ''), 'Operation/pre/post hooks require separate qualification')
            _hooks(item)
    elif isinstance(value, list):
        for item in value:
            _hooks(item)


def _destinations(request):
    entries = request.get('allowed_destinations')
    require(type(entries) is list and entries, 'allowed_destinations must be nonempty')
    result = set()
    for entry in entries:
        require(type(entry) is dict and set(entry) == {'database', 'schema'}, 'Invalid destination fields')
        key = (_text(entry['database'], 'destination database'), _text(entry['schema'], 'destination schema'))
        require(key not in result, 'Duplicate allowed destination')
        result.add(key)
    return result


def validate_preflight(manifest, request):
    """Reject incompatible resources/destinations before build; return node IDs."""
    require(type(manifest) is dict and type(manifest.get('metadata')) is dict, 'Missing preflight metadata')
    meta = manifest['metadata']
    version = request['dbt_runtime']['version'] if request.get('schema_version') == 2 else DBT_VERSION
    require(meta.get('dbt_version') == version and meta.get('dbt_schema_version') == MANIFEST_SCHEMA,
            'Unqualified preflight version/schema')
    require(meta.get('adapter_type') == request['adapter_type'], 'Preflight adapter mismatch')
    project_name = _text(meta.get('project_name'), 'manifest project_name')
    ids = expected_nodes(manifest)
    allowed = _destinations(request)
    _hooks(manifest.get('nodes', {}))
    for node in manifest['nodes'].values():
        require(node.get('package_name') == project_name, 'External resource packages require separate qualification')
        kind, config = node['resource_type'], node.get('config', {})
        if request.get('schema_version') == 2:
            require(kind != 'snapshot' and (kind != 'model' or config.get('materialized') in ('table', 'view', 'ephemeral')),
                    'v2 qualification covers table/view/ephemeral models, seeds and data tests only')
            require(not config.get('contract', {}).get('enforced') and not node.get('version'),
                    'v2 contracts/model versions require separate qualification')
        if kind == 'snapshot':
            require(Path(node.get('original_file_path', '')).suffix.lower() not in ('.yml', '.yaml'), 'YAML snapshots require separate qualification')
        if config.get('enabled', True) is False:
            continue
        writes = kind in ('seed', 'snapshot') or kind == 'model' and config.get('materialized') != 'ephemeral'
        if kind == 'test':
            store = config.get('store_failures')
            store_as = config.get('store_failures_as')
            require(store is None or type(store) is bool, 'Invalid store_failures setting')
            require(store_as in (None, 'table', 'view', 'ephemeral'), 'Unqualified store_failures_as setting')
            writes = store is True or store_as in ('table', 'view')
        if writes:
            destination = (node.get('database'), node.get('schema'))
            require(all(type(value) is str and value for value in destination) and destination in allowed,
                    'Destination not allowed for ' + node['unique_id'])
    for macro in manifest.get('macros', {}).values():
        require(macro.get('package_name') in (project_name, 'dbt', 'dbt_' + request['adapter_type']),
                'External macro packages require separate qualification')
    return ids


def _yaml(path):
    try:
        import yaml
    except ImportError as error:
        raise ValueError('Install PyYAML in the runner environment before execution') from error
    class Loader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            require(type(key) in (str, int, bool) and key not in result, 'Duplicate or invalid YAML mapping key')
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        return yaml.load(path.read_text(encoding='utf-8'), Loader=Loader)
    except yaml.YAMLError as error:
        raise ValueError('Invalid YAML; original content is not logged') from error


def _literal(value):
    if isinstance(value, str):
        require('{{' not in value and '{%' not in value, 'Templated profile values are not supported; use a reviewed literal profile')
    elif isinstance(value, dict):
        for item in value.values():
            _literal(item)
    elif isinstance(value, list):
        for item in value:
            _literal(item)


def _request(path, project, output):
    request = load_json(path)
    v2 = type(request) is dict and type(request.get('schema_version')) is int and request['schema_version'] == 2
    fields = REQUEST_FIELDS | {'dbt_runtime', 'runtime_identity', 'driver'} if v2 else REQUEST_FIELDS
    require(type(request) is dict and set(request) == fields, 'Missing or unknown execution request fields')
    require(type(request['schema_version']) is int and request['schema_version'] in (1, 2), 'Unsupported request schema_version')
    if v2:
        from dbt_runtime import runtime_contract, validate_selection
        request['dbt_runtime'] = validate_selection(request['dbt_runtime'])
        require(request['dbt_runtime']['distribution'] in ('dbt', 'dbt_oss') and request['adapter_type'] == 'duckdb' and
                runtime_contract(request['dbt_runtime'], request['adapter_type'])['execution']['qualified'],
                'Unqualified runtime/adapter/mode/features execution contract')
    require(type(request['project_sha256']) is str and SHA.fullmatch(request['project_sha256']) is not None, 'Invalid project_sha256')
    require(request['adapter_type'] in ('duckdb', 'snowflake'), 'Only duckdb and snowflake are supported')
    for field in ('profile', 'target', 'profiles_dir'):
        _text(request[field], field)
    require(Path(request['profiles_dir']).is_absolute(), 'profiles_dir must be absolute')
    profiles = canonical(request['profiles_dir'])
    require(profiles.is_dir() and profiles != project and project not in profiles.parents and
            profiles != output and output not in profiles.parents, 'Profiles must stay outside source and output')
    require(type(request['timeout_seconds']) is int and 0 < request['timeout_seconds'] <= 3600, 'timeout_seconds must be 1..3600')
    _destinations(request)
    fields = {'account', 'role', 'warehouse'} if request['adapter_type'] == 'snowflake' else {'path'}
    expected = request['expected_profile']
    require(type(expected) is dict and set(expected) == fields, 'Invalid expected_profile fields')
    for key, value in expected.items():
        _text(value, 'expected_profile ' + key)
        _literal(value)
    profile_file = canonical(profiles / 'profiles.yml')
    profile_hash = hash_file(profile_file)
    data = _yaml(profile_file)
    require(type(data) is dict and type(data.get(request['profile'])) is dict, 'Requested profile is missing')
    outputs = data[request['profile']].get('outputs')
    require(type(outputs) is dict and type(outputs.get(request['target'])) is dict, 'Requested profile target is missing')
    selected = outputs[request['target']]
    if v2:
        require(set(selected) <= {'type', 'path', 'schema', 'threads'}, 'Extended DuckDB profile settings require separate qualification')
        database = Path(expected['path']).absolute()
        require(Path(expected['path']).is_absolute() and not database.exists() and not database.is_symlink(),
                'v2 local qualification requires a new absolute DuckDB file')
        canonical(database.parent)
        require(project != database.parent and project not in database.parents and output not in database.parents,
                'DuckDB data must remain outside source and execution output')
    _literal(selected)
    require(selected.get('type') == request['adapter_type'], 'Profile adapter mismatch')
    require(all(type(selected.get(key)) is str and selected[key] == value for key, value in expected.items()), 'Profile identity differs from expected_profile')
    require(hash_file(profile_file) == profile_hash, 'Profile changed while being read')
    return request, profile_file, profile_hash


def run_step(args, output, timeout_seconds, process=subprocess.run, cwd=None):
    """Run one argv list and always retain ordinary failure/timeout diagnostics."""
    require(type(args) is list and args and all(type(arg) is str for arg in args), 'Process arguments must be a nonempty string list')
    require(type(timeout_seconds) is int and 0 < timeout_seconds <= 3600, 'Invalid process timeout')
    output = Path(output)
    output.mkdir()
    started = datetime.now(timezone.utc).isoformat()
    def decoded(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
    try:
        result = process(args, capture_output=True, text=True, timeout=timeout_seconds, cwd=cwd,
                         env=dict(os.environ, DBT_SEND_ANONYMOUS_USAGE_STATS='false', DO_NOT_TRACK='1'))
        code, stdout, stderr = result.returncode, decoded(result.stdout), decoded(result.stderr)
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr = 124, decoded(error.stdout), decoded(error.stderr) + '\nNative dbt step timed out\n'
    except OSError as error:
        code, stdout, stderr = 127, '', str(error)
    finished = datetime.now(timezone.utc).isoformat()
    for name, content in (('stdout.txt', stdout), ('stderr.txt', stderr)):
        with (output / name).open('x', encoding='utf-8') as stream:
            stream.write(content)
    summary = {'args': args, 'exit_code': code, 'started_at': started, 'finished_at': finished}
    write_json(output / 'step-summary.json', summary)
    return summary


def run_project(project, request_path, output, dbt_executable, execute=False, process=subprocess.run):
    require(execute is True, 'Explicit --execute authorization is required before any process runs')
    initial = load_json(request_path)
    if type(initial) is dict and initial.get('schema_version') == 2:
        return _run_project_v2(project, request_path, output, dbt_executable, process)
    _runtime_environment()
    project, request_path = canonical(project), canonical(request_path)
    output = Path(output).absolute()
    require('..' not in output.parts and not output.exists() and not output.is_symlink(), 'Output must be a new canonical directory')
    canonical(output.parent)
    require(output != project and project not in output.parents, 'Output must be outside source project')
    executable = canonical(dbt_executable)
    require(executable.is_file(), 'dbt executable must be a file')
    request_hash = hash_file(request_path)
    request, profile_file, profile_hash = _request(request_path, project, output)
    source = snapshot(project)
    require(source['sha256'] == request['project_sha256'], 'Source project differs from requested pin')
    require(not any(item['path'].split('/')[0] in ('.git', 'target', 'logs') for item in source['files']),
            'Unqualified control-file snapshot; use a project copy without Git control files')
    project_config = _yaml(project / 'dbt_project.yml')
    require(type(project_config) is dict and project_config.get('flags') in (None, {}),
            'Project runtime flags require separate qualification')
    _hooks(project_config)
    output.mkdir()
    summary = {'schema_version': 1, 'kind': 'reviewed_dbt_execution', 'evidence_complete': False,
               'errors': [], 'receipt_path': None, 'request_sha256': request_hash,
               'project_sha256': source['sha256'], 'profile_sha256': profile_hash,
               'validation_scope': 'local' if request['adapter_type'] == 'duckdb' else 'target', 'steps': []}
    copied = output / 'project'
    def pins():
        require(snapshot(project) == source, 'Original project drift')
        require(snapshot(copied) == source, 'Copied project drift')
        require(hash_file(profile_file) == profile_hash, 'Profile drift')
        require(hash_file(request_path) == request_hash, 'Execution request drift')
    def command(verb, directory):
        return [str(executable), '--no-use-colors', '--no-send-anonymous-usage-stats', '--no-partial-parse', verb,
                '--project-dir', str(copied), '--profiles-dir', request['profiles_dir'], '--profile', request['profile'],
                '--target', request['target'], '--target-path', str(directory), '--log-path', str(directory / 'logs')]
    try:
        copied.mkdir()
        for item in source['files']:
            destination = copied / item['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / item['path'], destination)
        pins()
        preflight_dir, build_dir = output / 'preflight', output / 'build'
        preflight = run_step(command('parse', preflight_dir), preflight_dir, request['timeout_seconds'], process, str(copied))
        summary['steps'].append(preflight)
        pins()
        require(preflight['exit_code'] == 0, 'Native parse failed; inspect retained diagnostics')
        preflight_path = preflight_dir / 'manifest.json'
        preflight_hash = hash_file(preflight_path)
        ids = validate_preflight(load_json(preflight_path), request)
        captured = snapshot_project(copied)
        pins()
        build = run_step(command('build', build_dir), build_dir, request['timeout_seconds'], process, str(copied))
        summary['steps'].append(build)
        pins()
        require(hash_file(preflight_path) == preflight_hash, 'Preflight evidence drift')
        receipt = {'schema_version': 1, 'kind': 'native_dbt_build_evidence', 'project_root': str(copied),
                   'validation_scope': summary['validation_scope'], 'expected_adapter_type': request['adapter_type'],
                   'expected_dbt_version': DBT_VERSION, 'expected_target_name': request['target'],
                   'project_snapshot': captured, 'expected_node_ids': ids,
                   'execution': {key: build[key] for key in ('exit_code', 'started_at', 'finished_at')}}
        for name, path in (('preflight_manifest', preflight_path), ('manifest', build_dir / 'manifest.json'),
                           ('run_results', build_dir / 'run_results.json')):
            receipt[name] = {'path': path.relative_to(output).as_posix(), 'sha256': hash_file(path)}
        receipt_path = output / 'receipt.json'
        write_json(receipt_path, receipt)
        summary['receipt_path'] = str(receipt_path)
        verification = verify(receipt_path, project_root=copied)
        write_json(output / 'evidence-verification.json', verification)
        summary['errors'].extend(verification['errors'])
        summary['evidence_complete'] = verification['evidence_complete']
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        summary['errors'].append(str(error))
        summary['evidence_complete'] = False
    write_json(output / 'run-summary.json', summary)
    return summary


def _private_json(path, value):
    from source_adapters.filesystem import new_json_output
    with new_json_output(path) as write:
        write(value)


def _native_step(args, directory, timeout, environment, process, cwd):
    """Bound native disk output and duration; never inherit credential/config env."""
    import resource
    directory.mkdir(mode=0o700)
    started = datetime.now(timezone.utc).isoformat()
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
    with (directory / 'stdout.txt').open('xb') as stdout, (directory / 'stderr.txt').open('xb') as stderr:
        os.fchmod(stdout.fileno(), 0o600)
        os.fchmod(stderr.fileno(), 0o600)
        try:
            completed = process(args, stdout=stdout, stderr=stderr, timeout=timeout,
                                cwd=str(cwd), env=environment, preexec_fn=limits)
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError:
            code = 127
    result = {'args': args, 'exit_code': code, 'started_at': started,
              'finished_at': datetime.now(timezone.utc).isoformat()}
    _private_json(directory / 'step-summary.json', result)
    return result


def _run_project_v2(project, request_path, output, dbt_executable, process):
    """Separate opt-in 2.0.8 contract; no alteration of version 1 receipts."""
    from dbt_runtime import _file_pin, driver_contract, observed_version, runtime_argv, runtime_identity
    from source_adapters.filesystem import _open_directory
    project, request_path, executable = canonical(project), canonical(request_path), canonical(dbt_executable)
    output = Path(output).absolute()
    require('..' not in output.parts and not output.exists() and not output.is_symlink(), 'Output must be a new canonical directory')
    require(project not in output.parents and project != output, 'Output must be outside source project')
    canonical(output.parent)
    request_hash = hash_file(request_path)
    request, profile_file, profile_hash = _request(request_path, project, output)
    selection = request['dbt_runtime']
    identity = runtime_identity(executable, selection)
    require(request['runtime_identity'] == identity, 'Installed runtime bytes differ from authorized runtime identity')
    driver = request['driver']
    contract = driver_contract()
    require(type(driver) is dict and set(driver) == {'path', 'sha256', 'version'} and
            driver['sha256'] == contract['sha256'] and driver['version'] == contract['version'], 'Unqualified driver identity')
    driver_path = canonical(driver['path'])
    require(_file_pin(driver_path)['sha256'] == driver['sha256'], 'Preinstalled driver differs from authorized pin')
    source = snapshot(project)
    require(source['sha256'] == request['project_sha256'], 'Source project differs from requested pin')
    require(not any(item['path'].split('/')[0] in ('.git', 'target', 'logs', 'dbt_packages', '.dbt') for item in source['files']),
            'Unqualified control/package-file snapshot')
    config = _yaml(project / 'dbt_project.yml')
    require(type(config) is dict and config.get('flags') in (None, {}), 'Project runtime flags require separate qualification')
    _hooks(config)
    parent_fd, parent_ids = _open_directory(output.parent)
    output_fd = None
    summary = {'schema_version': 2, 'kind': 'reviewed_dbt_execution', 'evidence_complete': False,
               'errors': [], 'receipt_path': None, 'request_sha256': request_hash,
               'project_sha256': source['sha256'], 'profile_sha256': profile_hash,
               'validation_scope': 'local', 'dbt_runtime': selection, 'steps': []}
    try:
        os.mkdir(output.name, mode=0o700, dir_fd=parent_fd)
        output_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        output_id = (os.fstat(output_fd).st_dev, os.fstat(output_fd).st_ino)
        def boundary():
            check_fd, check_ids = _open_directory(output.parent)
            os.close(check_fd)
            current = os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
            require(check_ids == parent_ids and (current.st_dev, current.st_ino) == output_id and not output.is_symlink(),
                    'Execution output directory changed')
        copied, home = output / 'project', output / 'runtime-home'
        copied.mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        for item in source['files']:
            boundary()
            destination = copied / item['path']
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with destination.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write((project / item['path']).read_bytes())
        cached_driver = home / contract['cache_relative_path']
        cached_driver.parent.mkdir(parents=True, mode=0o700)
        with cached_driver.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(driver_path.read_bytes())
        # Keep the exact approved request bytes, including an omitted default
        # mode/features selection. Normalization affects commands, not evidence.
        request_fd = os.open('request.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=output_fd)
        with os.fdopen(request_fd, 'wb') as stream:
            with request_path.open('rb') as original:
                request_bytes = original.read(10 * 1024 * 1024 + 1)
            require(len(request_bytes) <= 10 * 1024 * 1024, 'Execution request byte limit exceeded')
            stream.write(request_bytes)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'XDG_CONFIG_HOME': str(home),
                       'XDG_CACHE_HOME': str(home / '.cache'), 'DO_NOT_TRACK': '1',
                       'DBT_SEND_ANONYMOUS_USAGE_STATS': 'false', 'PYTHONNOUSERSITE': '1',
                       'PYTHONDONTWRITEBYTECODE': '1'}
        def pins():
            boundary()
            require(snapshot(project) == source and snapshot(copied) == source, 'Source/copied project drift')
            require(hash_file(profile_file) == profile_hash and hash_file(request_path) == request_hash, 'Profile/request drift')
            require(runtime_identity(executable, selection) == identity, 'Runtime identity drift')
            require(_file_pin(driver_path)['sha256'] == _file_pin(cached_driver)['sha256'] == driver['sha256'], 'Driver identity drift')
        pins()
        version_dir = output / 'version'
        version = _native_step([str(executable), '--version'], version_dir, min(request['timeout_seconds'], 30), environment, process, home)
        summary['steps'].append(version)
        pins()
        require(version['exit_code'] == 0 and (version_dir / 'stdout.txt').stat().st_size <= 4096,
                'Runtime version probe failed')
        observed = observed_version((version_dir / 'stdout.txt').read_text(encoding='utf-8'), selection)
        commands = {'version': version}
        preflight_dir, build_dir = output / 'preflight', output / 'build'
        preflight = _native_step(runtime_argv(executable, 'parse', copied, request['profiles_dir'], request['profile'],
                                            request['target'], preflight_dir, selection),
                                preflight_dir, request['timeout_seconds'], environment, process, copied)
        summary['steps'].append(preflight)
        commands['parse'] = preflight
        pins()
        require(preflight['exit_code'] == 0, 'Native parse failed; inspect retained private diagnostics')
        preflight_path = preflight_dir / 'manifest.json'
        preflight_hash = hash_file(preflight_path)
        ids = validate_preflight(load_json(preflight_path), request)
        captured = snapshot_project(copied)
        build = _native_step(runtime_argv(executable, 'build', copied, request['profiles_dir'], request['profile'],
                                        request['target'], build_dir, selection),
                            build_dir, request['timeout_seconds'], environment, process, copied)
        commands['build'] = build
        summary['steps'].append(build)
        pins()
        require(hash_file(preflight_path) == preflight_hash, 'Preflight evidence drift')
        receipt = {'schema_version': 2, 'kind': 'native_dbt_build_evidence', 'project_root': str(copied),
                   'validation_scope': 'local', 'expected_adapter_type': request['adapter_type'],
                   'expected_dbt_version': selection['version'], 'expected_target_name': request['target'],
                   'project_snapshot': captured, 'expected_node_ids': ids,
                   'execution': {key: build[key] for key in ('exit_code', 'started_at', 'finished_at')},
                   'runtime': {'selection': selection, 'identity': identity, 'observed': observed,
                               'driver': dict(driver, platform=contract['platform']),
                               'effective_analysis_mode': selection['analysis_mode']}, 'commands': commands,
                   'request': {'path': 'request.json', 'sha256': request_hash},
                   'version_output': {'path': 'version/stdout.txt', 'sha256': hash_file(version_dir / 'stdout.txt')},
                   'profile_sha256': profile_hash}
        require(hash_file(output / 'request.json') == request_hash, 'Archived request differs from approved bytes')
        for name, path in (('preflight_manifest', preflight_path), ('manifest', build_dir / 'manifest.json'),
                           ('run_results', build_dir / 'run_results.json')):
            receipt[name] = {'path': path.relative_to(output).as_posix(), 'sha256': hash_file(path)}
        receipt_path = output / 'receipt.json'
        boundary()
        _private_json(receipt_path, receipt)
        summary['receipt_path'] = str(receipt_path)
        verification = verify(receipt_path, project_root=copied)
        _private_json(output / 'evidence-verification.json', verification)
        summary['errors'].extend(verification['errors'])
        summary['evidence_complete'] = verification['evidence_complete']
        pins()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        summary['errors'].append(str(error))
        summary['evidence_complete'] = False
    finally:
        try:
            if output_fd is not None:
                boundary()
                _private_json(output / 'run-summary.json', summary)
                boundary()
        finally:
            if output_fd is not None:
                os.close(output_fd)
            os.close(parent_fd)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'request', 'output', 'dbt'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        summary = run_project(args.project, args.request, args.output, args.dbt, execute=args.execute)
        print(json.dumps(summary, indent=2))
        return 0 if summary['evidence_complete'] else 1
    except (OSError, ValueError) as error:
        print('Native dbt execution refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
