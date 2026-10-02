#!/usr/bin/env python3
"""Bounded, non-executing source inventory and independent target readiness.

Python 3.9+, standard library. No git, subprocess, YAML constructors, Jinja,
credentials, input imports, network, or file writes. Static signals are not
native parsing, lineage completeness, generation, or qualified execution.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raw_csv_source import inspect_csv

from platform_matrix import WAREHOUSES, adapter_registry, get_pairing

ADAPTER_REGISTRY = adapter_registry()
DEFAULT_LIMITS = {'max_files': 5000, 'max_file_bytes': 10 * 1024 * 1024,
                  'max_total_bytes': 64 * 1024 * 1024, 'max_entries': 20000, 'max_depth': 40}
IGNORED_DIRS = {'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '__pycache__',
                '.pytest_cache', '.mypy_cache', '.ruff_cache', 'target', 'logs', 'dbt_packages',
                'dist', 'build', '.terraform', '.cache'}
GENERATED_EVIDENCE = {'target', 'dbt_packages'}
SECRET_NAME = re.compile(r'(?:^|[._-])(?:credentials?|secrets?|tokens?|service[._-]?account|private[._-]?key)(?:[._-]|$)', re.I)
TEXT_EXTENSIONS = {'.sql', '.sqlx', '.yml', '.yaml', '.json', '.toml', '.j2', '.jinja', '.py', '.sh'}


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _secret(name):
    value = name.lower()
    return (value in {'profiles.yml', 'profiles.yaml', 'connections.toml', '.npmrc', '.pypirc',
                      '.env', '.aws', '.azure', '.ssh', '.dbt', '.config', '.snowflake', '.gcloud',
                      '.netrc', '.databrickscfg', '.boto', '.motherduck', '.clickhouse-client', '.pgpass', '.pg_service.conf', 'id_rsa', 'id_ed25519', 'oauth.json'}
            or value.startswith('.env.') or bool(SECRET_NAME.search(value))
            or bool(re.search(r'(?:^|[._-])profiles?(?:[._-]|$)', value))
            or Path(value).suffix in {'.pem', '.key', '.p12', '.pfx'})


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('include_paths must contain canonical relative paths')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise ValueError('include_paths must contain canonical relative paths')
    if any((part in IGNORED_DIRS and part not in GENERATED_EVIDENCE) or _secret(part) for part in path.parts):
        raise ValueError('include_paths cannot override control or credential exclusions')
    return value


def _open_root(repo):
    """Open every absolute path component without following symlinks (POSIX)."""
    path = Path(repo).absolute()
    if '..' in path.parts or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise ValueError('A canonical repository path and POSIX no-follow filesystem support are required')
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError:
        os.close(fd)
        raise ValueError('Repository must be a readable directory without symlink components') from None


def _read_regular_file(parent_fd, name, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('non_regular_file')
        if before.st_size > maximum:
            raise ValueError('file_size_limit')
        chunks, count = [], 0
        while count <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if count > maximum:
            raise ValueError('file_size_limit')
        if identity(before) != identity(after) or count != after.st_size:
            raise ValueError('file_changed_during_read')
        return b''.join(chunks)
    finally:
        os.close(fd)


def _scan(repo, limits, includes):
    files, texts, exclusions, gaps = [], {}, [], []
    totals = {'entries': 0, 'bytes': 0}
    seen = set()

    def gap(path, reason):
        gaps.append({'path': path or '.', 'reason': reason})

    def included(path):
        return any(path == item or path.startswith(item + '/') or item.startswith(path + '/') for item in includes)

    def walk(fd, prefix, depth):
        if depth > limits['max_depth']:
            gap(prefix, 'depth_limit')
            return
        entries = []
        try:
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    totals['entries'] += 1
                    if totals['entries'] > limits['max_entries']:
                        gap(prefix, 'directory_entry_limit')
                        return  # Do not choose an arbitrary partial listing.
                    entries.append(entry.name)
        except OSError:
            gap(prefix, 'unreadable_directory')
            return
        for name in sorted(entries):
            relative = prefix + '/' + name if prefix else name
            seen.add(relative)
            if any(part in GENERATED_EVIDENCE for part in PurePosixPath(relative).parts[:-1]) and not included(relative):
                exclusions.append({'path': relative, 'reason': 'generated_evidence_not_selected'})
                continue
            if _secret(name):
                exclusions.append({'path': relative, 'reason': 'credential_path_not_read'})
                continue
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    exclusions.append({'path': relative, 'reason': 'symlink_not_followed'})
                    gap(relative, 'symlink_not_followed')
                elif stat.S_ISDIR(info.st_mode):
                    if name in IGNORED_DIRS and not included(relative):
                        exclusions.append({'path': relative, 'reason': 'generated_or_environment_directory'})
                        if name in GENERATED_EVIDENCE:
                            gap(relative, 'generated_dependency_evidence_not_inspected')
                        continue
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, relative, depth + 1)
                    finally:
                        os.close(child)
                elif not stat.S_ISREG(info.st_mode):
                    gap(relative, 'non_regular_file')
                elif len(files) >= limits['max_files']:
                    gap(relative, 'file_count_limit')
                elif info.st_size > limits['max_file_bytes']:
                    gap(relative, 'file_size_limit')
                elif info.st_size > limits['max_total_bytes'] - totals['bytes']:
                    gap(relative, 'total_byte_limit')
                else:
                    data = _read_regular_file(fd, name, min(limits['max_file_bytes'], limits['max_total_bytes'] - totals['bytes']))
                    totals['bytes'] += len(data)
                    item = {'path': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    files.append(item)
                    if Path(name).suffix.lower() == '.csv':
                        item['raw_csv'] = inspect_csv(data)
                        for issue in item['raw_csv']['gaps']:
                            gap(relative, 'raw_csv_' + issue['code'])
                    if Path(name).suffix.lower() in TEXT_EXTENSIONS:
                        try:
                            texts[relative] = data.decode('utf-8')
                        except UnicodeError:
                            gap(relative, 'text_not_utf8')
            except OSError:
                gap(relative, 'unreadable_or_changed_path')
            except ValueError as error:
                gap(relative, str(error))
    root = _open_root(repo)
    try:
        walk(root, '', 0)
    finally:
        os.close(root)
    for item in includes:
        if item not in seen:
            gap(item, 'requested_include_not_observed')
    files.sort(key=lambda item: item['path'])
    exclusions.sort(key=lambda item: (item['path'], item['reason']))
    gaps.sort(key=lambda item: (item['path'], item['reason']))
    coverage = {'complete': not gaps, 'scanned_files': len(files), 'scanned_bytes': totals['bytes'],
                'limits': limits, 'exclusions': exclusions, 'gaps': gaps}
    fingerprint = {'algorithm': 'sha256', 'value': _json_hash({'files': files, 'exclusions': exclusions, 'gaps': gaps, 'limits': limits, 'include_paths': sorted(includes)}),
                   'scope': 'bounded_nonsecret_repository', 'complete': not gaps}
    return fingerprint, coverage, files, texts


def _coalesce_contract_valid(contract, warehouse, observed):
    """Check declaration completeness only; never claim native schema validation."""
    if not isinstance(contract, dict) or contract.get('warehouse') != warehouse:
        return False
    if not isinstance(contract.get('project_format_version'), str) or not contract['project_format_version'].strip():
        return False
    for key in ('representative_paths', 'node_ids', 'column_ids', 'node_types'):
        value = contract.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
            return False
    if not all(value in observed for value in contract['representative_paths']):
        return False
    return isinstance(contract.get('storage_mappings'), dict) and bool(contract['storage_mappings'])


def assess_repository(repo, framework, warehouse, **options):
    """Return JSON-safe readiness; see references/platform-adapters.md for schema.

    Options: max_files, max_file_bytes, max_total_bytes, max_entries, max_depth,
    include_paths (generated evidence opt-in), coalesce_contract. None selections
    permit assessment; gcp requires an explicit product answer. No files written.
    """
    if framework not in (None, *ADAPTER_REGISTRY['frameworks']):
        raise ValueError('framework must be dbt, coalesce, native_sql, or None')
    if warehouse not in (None, 'gcp', *ADAPTER_REGISTRY['warehouses']):
        raise ValueError('warehouse must be an explicit registered product, gcp, or None')
    unknown = set(options) - set(DEFAULT_LIMITS) - {'include_paths', 'coalesce_contract'}
    if unknown:
        raise ValueError('Unknown readiness options')
    limits = {key: options.get(key, default) for key, default in DEFAULT_LIMITS.items()}
    if not all(type(value) is int and value > 0 for value in limits.values()):
        raise ValueError('Scan limits must be positive integers')
    raw_includes = options.get('include_paths', [])
    if not isinstance(raw_includes, (list, tuple)):
        raise ValueError('include_paths must be a list of relative paths')
    includes = {_relative(value) for value in raw_includes}
    fingerprint, coverage, files, texts = _scan(repo, limits, includes)
    paths = {item['path'] for item in files}
    sources, findings, questions = {}, {}, []

    def source(kind, path):
        sources.setdefault(kind, set()).add(path)

    def finding(key, severity, summary, action, path=None, blocks=()):
        value = findings.setdefault(key, {'id': key, 'severity': severity, 'summary': summary,
                                         'next_action': action, 'paths': [], 'blocks': list(blocks)})
        if path is not None and path not in value['paths']:
            value['paths'].append(path)

    route = 'Preserve this input; review execution in existing customer CI or an authorized operator environment. Keep unsupported receipts explicitly unqualified.'
    dbt_roots = {str(PurePosixPath(p).parent) for p in paths if PurePosixPath(p).name in {'dbt_project.yml', 'dbt_project.yaml'}}
    raw_csv_inventory = []
    for item in files:
        if 'raw_csv' not in item:
            continue
        path = item['path']
        dbt_owned = any(root == '.' or path.startswith(root + '/') for root in dbt_roots)
        owner = 'dbt' if dbt_owned else 'raw_csv'
        raw_csv_inventory.append({'path': path, 'source_owner': owner, **item['raw_csv']})
        source(owner, path)
    # Preserve recognized CSV candidates that could not be read; a suffix is a
    # routing clue, never permission to follow a link or invent a hash/count.
    inspected_csv = {item['path'] for item in raw_csv_inventory}
    unread_csv = {}
    for issue in coverage['gaps']:
        path = issue['path']
        if PurePosixPath(path).suffix.lower() == '.csv' and path not in inspected_csv:
            unread_csv.setdefault(path, []).append({'code': issue['reason']})
    for path, issues in sorted(unread_csv.items()):
        owner = 'dbt' if any(root == '.' or path.startswith(root + '/') for root in dbt_roots) else 'raw_csv'
        raw_csv_inventory.append({'path': path, 'source_owner': owner, 'kind': 'raw_csv_metadata',
                                  'sha256': None, 'size_bytes': None, 'row_count': None,
                                  'columns': [], 'metadata_complete': False,
                                  'native_types_verified': False, 'source_platform': 'unknown', 'gaps': issues})
        source(owner, path)
    raw_csv_inventory.sort(key=lambda item: item['path'])
    for path, text in texts.items():
        name = PurePosixPath(path).name.lower()
        parent = PurePosixPath(path).parent
        is_dbt = any(root == '.' or path.startswith(root + '/') for root in dbt_roots)
        if name in {'dbt_project.yml', 'dbt_project.yaml'}:
            source('dbt', path)
        if name in {'coalesce.yml', 'coalesce.yaml'} or (name == 'data.yml' and
                any(p == str(parent / 'locations.yml') or p.startswith(str(parent / 'nodes') + '/') or p.startswith(str(parent / 'Nodes') + '/') for p in paths)):
            source('coalesce', path)
        if name in {'snowflake.yml', 'snowflake.yaml'}:
            source('snowflake', path)
        if name in {'databricks.yml', 'databricks.yaml'} and re.search(r'(?m)^bundle\s*:', text):
            source('databricks', path)
        if name in {'workflow_settings.yaml', 'workflow_settings.yml'} and re.search(r'(?m)^defaultProject\s*:', text) and re.search(r'(?m)^defaultDataset\s*:', text):
            source('bigquery', path)
        if name == 'dataform.json':
            try:
                dataform = json.loads(text)
                if isinstance(dataform, dict) and (dataform.get('warehouse') == 'bigquery' or (
                        'warehouse' not in dataform and isinstance(dataform.get('defaultDatabase'), str) and isinstance(dataform.get('defaultSchema'), str))):
                    source('bigquery', path)
            except (ValueError, RecursionError):
                finding('source.invalid_dataform', 'warning', 'A supplied Dataform configuration could not be read as bounded JSON.', 'Obtain a valid native artifact; source classification remains unresolved.', path)
        for kind in WAREHOUSES:
            if re.search(r'(?im)^\s*(?:type|adapter|adapter_type|warehouse)\s*:\s*[\"\']?' + kind + r'[\"\']?\s*(?:#.*)?$', text):
                source(kind, path)
        if name.endswith(('.sql', '.sqlx')):
            source('generic_sql', path)
        if name == 'manifest.json':
            try:
                manifest = json.loads(text)
                metadata = manifest.get('metadata', {}) if isinstance(manifest, dict) else {}
                if isinstance(metadata, dict) and 'dbt_schema_version' in metadata:
                    source('dbt', path)
                    adapter = metadata.get('adapter_type')
                    if isinstance(adapter, str) and adapter in ADAPTER_REGISTRY['warehouses']:
                        source(adapter, path)
                    if metadata.get('dbt_version') != '1.12.4' or metadata.get('dbt_schema_version') != 'https://schemas.getdbt.com/dbt/manifest/v12.json':
                        finding('dbt.artifact_version', 'warning', 'Supplied dbt artifact is outside the bundled native evidence version contract.', route, path, ['execution'])
                    finding('dbt.artifact_provenance', 'warning', 'A manifest is present; source revision and environment association remain unverified.', 'Bind original artifacts to the reviewed source and execution identity; dependency maps do not prove column lineage.', path)
                    root_package = metadata.get('project_name')
                    for key in ('nodes', 'macros'):
                        members = manifest.get(key, {})
                        if isinstance(members, dict) and isinstance(root_package, str):
                            allowed = {root_package} if key == 'nodes' else {root_package, 'dbt', 'dbt_' + str(adapter)}
                            if any(isinstance(member, dict) and member.get('package_name') not in allowed for member in members.values()):
                                finding('dbt.packages', 'warning', 'Dependency declarations need review; external resource/macro packages are outside bundled execution qualification.', route, path, ['execution'])
                    for key in ('unit_tests', 'functions'):
                        if manifest.get(key):
                            finding('dbt.' + key, 'warning', 'Supplied manifest contains resources outside bundled native evidence qualification.', route, path, ['execution'])
            except (ValueError, RecursionError):
                finding('source.invalid_json', 'warning', 'A supplied manifest could not be read as bounded JSON.', 'Obtain a valid versioned artifact; keep native lineage unresolved.', path)
        if not is_dbt:
            continue
        rules = [
            ('dbt.hooks', r'(?im)(?:[+\"\']?\b(?:pre[-_]hook|post[-_]hook|on[-_]run[-_]start|on[-_]run[-_]end)[\"\']?\s*[:=])', 'Hook configuration is present; bundled execution rejects nonempty hooks.'),
            ('dbt.flags', r'(?m)^flags\s*:', 'Project flags are present; bundled execution rejects nonempty flags.'),
            ('dbt.vars', r'\bvar\s*\(|(?m:^vars\s*:)', 'Variable-dependent configuration needs a reviewed effective environment; CLI vars are outside the bundled execution contract.'),
            ('dbt.environment', r'\benv_var\s*\(', 'Environment-dependent configuration is present; values and credentials were not resolved.'),
            ('dbt.dispatch', r'\b(?:adapter\.)?dispatch\s*\(|(?m:^dispatch\s*:)', 'Macro dispatch requires package and adapter review before compilation.'),
            ('dbt.introspection', r'\brun_query\s*\(|\badapter\.(?:get_|list_|execute)', 'Database-introspection or execution macros require separately reviewed compilation.'),
            ('dbt.incremental', r'\bis_incremental\s*\(|\bincremental_strategy\b|(?:materialized[\"\']?\s*[:=]\s*[\"\']?incremental\b)', 'Incremental behavior requires multi-run state, late-update, deletion and recovery evidence.'),
            ('dbt.unit_tests', r'(?m)^\s*unit_tests\s*:', 'Unit-test resources require separate native evidence qualification.'),
            ('dbt.functions', r'(?m)^\s*functions\s*:', 'Function resources require separate native evidence qualification.'),
            ('dbt.selection', r'--(?:select|exclude|selector|state|defer|vars)\b|\bDBT_(?:SELECT|VARS|STATE)\b', 'Selected/state/deferred/vars execution is outside the bundled full-project evidence contract.'),
        ]
        for key, pattern, summary in rules:
            if re.search(pattern, text):
                finding(key, 'warning', summary, route, path, ['execution'])
        if name in {'packages.yml', 'packages.yaml', 'dependencies.yml', 'dependencies.yaml', 'package-lock.yml'}:
            finding('dbt.packages', 'warning', 'Dependency declarations need review; external resource/macro packages are outside bundled execution qualification.', route, path, ['execution'])
        if re.search(r'{%[-+]?\s*snapshot\b', text) or (name.endswith(('.yaml', '.yml')) and re.search(r'(?m)^snapshots\s*:', text) and not name.startswith('dbt_project')):
            finding('dbt.snapshots', 'warning', 'Snapshot history requires stateful validation; YAML snapshot resources are outside bundled execution qualification.', route, path, ['execution'])
        if '{%' in text and re.search(r'{%[-+]?\s*macro\b', text):
            finding('dbt.macros', 'warning', 'Project macro definitions require review; static scanning does not execute or expand them.', route, path, ['execution'])
        if re.search(r'(?m)^require-dbt-version\s*:', text):
            finding('dbt.version_requirement', 'warning', 'A source dbt version requirement must be reconciled with the pinned Core 1.12.4 native evidence lane.', route, path, ['execution'])

    if not coverage['complete']:
        finding('coverage.incomplete', 'blocker', 'Some source or dependency evidence could not be inspected within the selected bounds.', 'Resolve listed gaps or explicitly revise the source scope; never treat partial inventory as complete.', blocks=['generation', 'execution'])
    if any(item['reason'] == 'credential_path_not_read' for item in coverage['exclusions']):
        finding('security.credentials_excluded', 'info', 'Credential/profile paths were excluded without reading or hashing their contents.', 'Keep credentials outside the evidence bundle; an operator must review profile templates and effective identity separately.')
    if 'dbt' in sources:
        finding('dbt.runtime_unverified', 'info', 'Effective profile, installed adapter/packages, CLI vars, runtime flags and artifact/source association are unverified.', 'Have the operator confirm nonsecret execution identity and configuration in the existing environment. Profiles were not read; templated profiles and DBT option overrides have separate bundled-runner restrictions.')
    if not sources:
        finding('source.unrecognized', 'warning', 'No supported source fingerprint was recognized; files were still inventoried.', 'Confirm source format and provide representative native artifacts; static absence is not proof of an empty model.')
    if 'generic_sql' in sources:
        finding('source.sql_dialect', 'info', 'SQL files are inventoried without assigning a dialect from generic syntax.', 'Confirm each SQL source dialect and preserve ambiguity when multiple platforms occur.')
    if 'raw_csv' in sources:
        finding('source.raw_csv_snapshot', 'info', 'CSV headers, exact file hashes and bounded logical row counts describe supplied snapshots only; fields remain lexical text.', 'Confirm source extraction scope, warehouse catalogue, identity/null/type rules and business definitions separately. Do not fabricate a source dbt project or treat CSV data as Excel/report logic.')
    if framework is None:
        questions.append({'id': 'framework', 'prompt': 'Which transformation framework should the target use?', 'choices': list(ADAPTER_REGISTRY['frameworks'])})
    if warehouse in (None, 'gcp'):
        questions.append({'id': 'warehouse', 'prompt': 'Does GCP mean BigQuery, or another warehouse product?' if warehouse == 'gcp' else 'Which warehouse should the target use?', 'choices': list(ADAPTER_REGISTRY['warehouses'])})
    selected = framework is not None and warehouse in ADAPTER_REGISTRY['warehouses']
    pairing = get_pairing(framework, warehouse) if selected else None
    generation = 'agent_assisted' if selected else 'needs_selection'
    reason = 'Agent-assisted candidate authoring after discovery, physical bindings and behavioral contracts; this collector emits no target code.'
    if not selected:
        reason = 'Complete independent framework and warehouse choices; read-only assessment can continue.'
    elif pairing['status'] == 'unsupported':
        generation = 'unsupported'
        reason = pairing['reason']
        finding('platform.unsupported_pairing', 'blocker', reason,
                'Choose a documented framework/warehouse route; a native contract cannot override unsupported platform compatibility.',
                blocks=['generation', 'execution'])
    elif framework == 'coalesce' and not _coalesce_contract_valid(options.get('coalesce_contract'), warehouse, paths):
        generation = 'requires_contract'
        reason = 'Native Coalesce generation needs a representative versioned project, node/column IDs, node types and target storage mappings.'
        finding('coalesce.native_contract', 'blocker', reason, 'Supply a nonsecret native contract and representative inspected files. SQL alone is not a native Coalesce project.', blocks=['generation'])
    elif framework == 'coalesce':
        reason = 'Declared native contract is present for agent-assisted authoring; native schema/import compatibility and platform support still require operator validation.'
    execution = 'requires_operator_validation' if selected else 'needs_selection'
    if selected and (pairing['status'] == 'unsupported' or not coverage['complete'] or (framework == 'dbt' and any('execution' in f['blocks'] for f in findings.values()))):
        execution = 'blocked'
    execution_reason = 'No target execution was performed. Use authorized existing CI/operator validation and original receipts; static readiness never qualifies a run.'
    if framework == 'dbt' and warehouse == 'snowflake':
        execution_reason += ' The existing bounded runner/evidence verifier still enforces Core 1.12.4 and its narrower full-project contract.'
    elif selected:
        execution_reason += ' No bundled native executor is qualified for this selected path.'
    for item in findings.values():
        item['paths'].sort()
    return {'schema_version': 1, 'kind': 'platform_readiness', 'source_fingerprint': fingerprint,
            'selection': {'framework': framework, 'warehouse': warehouse}, 'coverage': coverage,
            'platform_pairing': pairing,
            'detected_sources': [{'type': key, 'paths': sorted(value), 'confidence': 'static_signal'} for key, value in sorted(sources.items())],
            'raw_csv_inventory': raw_csv_inventory,
            'findings': sorted(findings.values(), key=lambda item: item['id']), 'questions': questions,
            'capabilities': {'assessment': {'status': 'supported' if coverage['complete'] else 'partial', 'reason': 'Bounded static inventory and compatibility signals only; no native parser, complete lineage, or business validation claim.'},
                             'generation': {'status': generation, 'reason': reason},
                             'execution': {'status': execution, 'reason': execution_reason}},
            'native_semantics_parsed': False, 'execution_performed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    parser.add_argument('--framework', choices=tuple(ADAPTER_REGISTRY['frameworks']))
    parser.add_argument('--warehouse', choices=tuple(ADAPTER_REGISTRY['warehouses']) + ('gcp',))
    parser.add_argument('--include-path', action='append', default=[])
    for name, default in DEFAULT_LIMITS.items():
        parser.add_argument('--' + name.replace('_', '-'), type=int, default=default)
    args = parser.parse_args(argv)
    try:
        options = {key: getattr(args, key) for key in DEFAULT_LIMITS}
        result = assess_repository(args.repo, args.framework, args.warehouse, include_paths=args.include_path, **options)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result['coverage']['complete'] else 2
    except (OSError, ValueError) as error:
        print('Readiness assessment failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
