#!/usr/bin/env python3
"""Bounded offline SQL/configuration checks; never render project templates.

SQLFluff runs in a private temporary directory with a fixed raw-templater policy.
Reports bind declared execution units and source mappings; hashes are integrity
evidence, not authentication or proof of native/business correctness.
"""
import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

from ae_common import require, load_json, _json_bytes, hash_json

SQLFLUFF_VERSION = '4.3.0'
DIALECTS = {'snowflake': 'snowflake', 'databricks': 'databricks', 'bigquery': 'bigquery',
            'redshift': 'redshift', 'clickhouse': 'clickhouse', 'duckdb': 'duckdb', 'motherduck': 'duckdb'}
SQL_ROLES = {'model_sql', 'script_sql', 'generated_ddl', 'generated_dml', 'hook_sql', 'test_sql', 'materialization_sql'}
SOURCE_ROLES = {'dbt_model', 'macro', 'hook_template', 'materialization_template', 'coalesce_node', 'template'}
CONFIG_ROLES = {'project_config', 'semantic_config'}
STATUSES = {'checked', 'failed', 'unsupported', 'skipped'}
DEFAULT_LIMITS = {'max_files': 500, 'max_file_bytes': 1024 * 1024, 'max_total_bytes': 10 * 1024 * 1024,
                  'timeout_seconds': 60, 'max_output_bytes': 8 * 1024 * 1024}
AMBIENT_CONFIG = {'.sqlfluff', '.sqlfluffignore', 'pyproject.toml', 'setup.cfg', 'tox.ini', 'pep8.ini'}
TEMPLATE = re.compile(r'\{\{|\{%|\{#|\$\{')
INLINE_CONFIG = re.compile(r'(?im)^\s*--\s*sqlfluff\s*:')
NOQA = re.compile(r'(?im)--[^\n]*\bnoqa\b')
HEX = re.compile(r'[a-f0-9]{64}\Z')
STYLE_EXCEPTION_RULES = {'CP02', 'RF04', 'RF06', 'ST06', 'LT01', 'LT02', 'LT05', 'LT13', 'LT15'}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(value, *, exists=True):
    path = Path(value).expanduser().absolute()
    require('..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink/traversal input path')
    if exists:
        require(path.exists(), 'Input path is unavailable')
    return path


def _relative(value):
    require(type(value) is str and value and not any(ord(c) < 32 for c in value)
            and not any(c in value for c in '\\:*?[]'), 'Invalid manifest path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/'))
            and str(path) == value, 'Manifest path must be canonical and relative')
    return value


def _limits(value=None):
    value = {} if value is None else value
    require(type(value) is dict and set(value) <= set(DEFAULT_LIMITS), 'Unknown lint limit')
    result = dict(DEFAULT_LIMITS, **value)
    require(all(type(v) is int and 1 <= v <= DEFAULT_LIMITS[k] for k, v in result.items()), 'Invalid lint bounds')
    return result


def _target(value):
    require(type(value) is dict and value.get('warehouse') in DIALECTS, 'Unsupported lint warehouse')
    _json_bytes(value)
    return DIALECTS[value['warehouse']]


def _manifest(manifest, limits):
    require(type(manifest) is dict and set(manifest) <= {'schema_version', 'kind', 'files', 'expected_execution_units', 'physical_models', 'style_exceptions', 'omni_context'}, 'Invalid lint manifest')
    require(type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1
            and manifest.get('kind') == 'sql_lint_manifest', 'Unsupported lint manifest')
    files, units = manifest.get('files'), manifest.get('expected_execution_units')
    require(type(files) is list and 0 < len(files) <= limits['max_files'], 'Nonempty bounded file inventory required')
    require(type(units) is list and bool(units) and len(units) <= limits['max_files'] * 100, 'Nonempty execution-unit denominator required')
    require(all(type(u) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', u) for u in units)
            and len(set(units)) == len(units), 'Invalid or duplicate execution unit')
    paths, declared = set(), []
    for item in files:
        require(type(item) is dict and set(item) == {'path', 'sha256', 'role', 'format', 'execution_units', 'source_paths'}, 'Invalid lint file fields')
        path = _relative(item['path'])
        require(path not in paths, 'Duplicate lint file path')
        paths.add(path)
        require(type(item['sha256']) is str and HEX.fullmatch(item['sha256']), 'Invalid source digest')
        require(item['role'] in SQL_ROLES | SOURCE_ROLES | CONFIG_ROLES, 'Unsupported file role')
        require(item['format'] in {'sql', 'compiled_sql', 'jinja', 'json', 'yaml'}, 'Unsupported file format')
        require(type(item['execution_units']) is list and type(item['source_paths']) is list, 'Invalid execution/source mapping')
        require(all(type(u) is str and u in units for u in item['execution_units']), 'Undeclared execution unit')
        require(len(set(item['source_paths'])) == len(item['source_paths']), 'Duplicate source mapping')
        for source in item['source_paths']:
            _relative(source)
        if item['role'] in SQL_ROLES:
            require(item['format'] in {'sql', 'compiled_sql'} and item['execution_units'], 'Executable SQL needs execution units')
            require(bool(item['source_paths']) == (item['format'] == 'compiled_sql'), 'Compiled SQL requires source mappings; plain SQL must not claim rendering')
        else:
            require(not item['execution_units'] and not item['source_paths'], 'Only SQL outputs own execution units/source mappings')
            require(item['format'] in ({'jinja', 'yaml', 'json'} if item['role'] in SOURCE_ROLES else {'yaml', 'json'}), 'Role/format mismatch')
        declared.extend(item['execution_units'])
    require(Counter(declared) == Counter(units), 'Execution-unit denominator has missing or multiply assigned units')
    by_path = {item['path']: item for item in files}
    for item in files:
        require(all(p in by_path and by_path[p]['role'] in SOURCE_ROLES | CONFIG_ROLES for p in item['source_paths']), 'Compiled source is missing or is another SQL output')
    models = manifest.get('physical_models', [])
    require(type(models) is list and len(models) <= limits['max_files'], 'Invalid physical-model inventory')
    for model in models:
        require(type(model) is dict and type(model.get('id')) is str and model['id']
                and model.get('path') in by_path and by_path[model['path']]['role'] in SQL_ROLES, 'Physical model requires an inventoried SQL path')
    require(len({m['id'] for m in models}) == len(models), 'Duplicate physical-model identity')
    _style_exceptions(manifest, by_path)
    return by_path


def _style_exceptions(manifest, by_path):
    """Normalize exact policy declarations, binding the existing file digest.

    The reason explains a convention exception; it is not an approval receipt.
    SQLFluff still executes every rule. Syntax/coverage/runtime findings can
    never be declared here, and a declaration without a current finding fails.
    """
    declarations = manifest.get('style_exceptions', [])
    require(type(declarations) is list and len(declarations) <= len(by_path) * len(STYLE_EXCEPTION_RULES),
            'Invalid or unbounded style exceptions')
    normalized, seen = [], set()
    for entry in declarations:
        require(type(entry) is dict and set(entry) == {'path', 'rule', 'reason'}, 'Invalid style exception fields')
        path = _relative(entry['path'])
        require(path in by_path and by_path[path]['role'] in SQL_ROLES
                and by_path[path]['format'] in {'sql', 'compiled_sql'}, 'Style exception requires an exact executable SQL path')
        rule, reason = entry['rule'], entry['reason']
        require(type(rule) is str and rule in STYLE_EXCEPTION_RULES, 'Style exception rule is not allowed')
        require(type(reason) is str and 0 < len(reason.strip()) <= 2000
                and not any(ord(c) < 32 for c in reason), 'Style exception needs a nonempty plain-text reason')
        require((path, rule) not in seen, 'Duplicate path/rule style exception')
        seen.add((path, rule))
        normalized.append({'path': path, 'rule': rule, 'reason': reason.strip(), 'sha256': by_path[path]['sha256']})
    return sorted(normalized, key=lambda e: (e['path'], e['rule']))


def _read(path, maximum):
    path = _path(path)
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), 'Input must be a regular file')
        if before.st_size > maximum:
            raise OverflowError('File exceeds configured byte limit')
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after) and len(data) == after.st_size, 'Input changed during reading')
    return data


def _native_semantic_path(path):
    """Omni uses YAML with native suffixes and two exact extensionless names."""
    return Path(path).suffix.lower() in {'.view', '.topic'} or Path(path).name in {'model', 'relationships'}


def _inventory(root, limits):
    relevant, ambient, visited = [], [], 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort(); files.sort()
        for name in dirs + files:
            visited += 1
            require(visited <= limits['max_files'] * 4, 'Directory inventory limit exceeded')
            path = Path(directory) / name
            require(not path.is_symlink(), 'Symlink in lint scope')
        for name in files:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if name in AMBIENT_CONFIG:
                ambient.append({'path': relative, 'sha256': _sha(_read(Path(directory) / name, limits['max_file_bytes'])),
                                'reason': 'Ambient linter configuration is intentionally disabled.'})
            elif name.lower().endswith(('.sql', '.sql.j2', '.dml', '.ddl', '.jinja', '.j2', '.yaml', '.yml', '.json')) or _native_semantic_path(name):
                relevant.append(relative)
    return {'relevant_paths': sorted(relevant), 'ignored_configuration': ambient, 'visited_entries': visited}


def _run(executable, arguments, cwd, timeout, maximum):
    """Trusted interpreter only; bounded output/time, no inherited credentials."""
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(cwd), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
           'XDG_CONFIG_HOME': str(cwd), 'TMPDIR': str(cwd), 'NO_COLOR': '1'}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        child = subprocess.Popen([str(executable), '-I', *arguments], cwd=str(cwd), env=env,
                                 stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Static lint exceeded its time limit')
                if os.fstat(stdout.fileno()).st_size > maximum or os.fstat(stderr.fileno()).st_size > maximum:
                    raise OverflowError('Static lint exceeded its output limit')
                try:
                    child.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise
        stdout.seek(0); stderr.seek(0)
        out, err = stdout.read(maximum + 1), stderr.read(maximum + 1)
        require(len(out) <= maximum and len(err) <= maximum, 'Static lint output limit exceeded')
        return child.returncode, out, err


RUNTIME_PROBE = r'''
import hashlib, importlib.metadata as m, json, pathlib, platform, sys
d = m.distribution('sqlfluff')
files = []
for p in sorted(d.files or [], key=str):
    if str(p).startswith('sqlfluff/') and p.suffix in ('.py', '.cfg', '.ini', '.json'):
        files.append([str(p), hashlib.sha256(d.locate_file(p).read_bytes()).hexdigest()])
packages, plugins = [], []
for dist in m.distributions():
    name = dist.metadata['Name']
    packages.append([name, dist.version, hashlib.sha256((dist.read_text('RECORD') or '').encode()).hexdigest()])
    for ep in dist.entry_points:
        if ep.group == 'sqlfluff':
            plugins.append([name, ep.name, ep.value])
print(json.dumps({'sqlfluff_version': d.version, 'python_version': platform.python_version(),
    'implementation': platform.python_implementation(), 'sqlfluff_files': files,
    'packages': sorted(packages), 'plugins': sorted(plugins)}))
'''


def inspect_runtime(python_executable, *, timeout_seconds=30):
    # Venv launchers are commonly symlinks: preserve their launch path while
    # separately pinning resolved interpreter bytes and the venv configuration.
    executable = Path(python_executable).expanduser().absolute()
    require('..' not in executable.parts and executable.is_file(), 'Trusted Python executable is unavailable')
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 60, 'Invalid runtime probe timeout')
    with tempfile.TemporaryDirectory(prefix='dma-lint-runtime-') as folder:
        code, out, _ = _run(executable, ['-c', RUNTIME_PROBE], Path(folder).resolve(), timeout_seconds, DEFAULT_LIMITS['max_output_bytes'])
    require(code == 0, 'Pinned SQLFluff runtime is unavailable')
    runtime = json.loads(out)
    require(runtime.get('sqlfluff_version') == SQLFLUFF_VERSION, 'SQLFluff runtime version differs from pinned 4.3.0')
    require(runtime.get('sqlfluff_files'), 'SQLFluff implementation inventory is empty')
    require(all(p[0].lower().replace('_', '-') == 'sqlfluff' for p in runtime['plugins']), 'Third-party SQLFluff plugins are not allowed in the static lane')
    runtime['python_executable'] = str(executable)
    runtime['resolved_executable'] = str(executable.resolve())
    runtime['executable_sha256'] = _sha(executable.read_bytes())
    venv = executable.parent.parent / 'pyvenv.cfg'
    runtime['venv_configuration_sha256'] = _sha(venv.read_bytes()) if venv.is_file() else None
    return runtime


def configuration(target, limits=None):
    dialect, limits = _target(target), _limits(limits)
    return ('[sqlfluff]\n'
            'dialect = ' + dialect + '\n'
            'templater = raw\nrules = all\nexclude_rules =\nignore =\nwarnings =\n'
            'encoding = utf-8\ndisable_noqa = True\nignore_templated_areas = False\n'
            'large_file_skip_byte_limit = ' + str(limits['max_file_bytes']) + '\n'
            'large_file_skip_char_limit = 0\nlarge_file_skip_fail = True\n'
            'render_variant_limit = 1\nprocesses = 1\nuse_rust_parser = False\nuse_rust_rules = False\n'
            'max_parse_depth = 600\nmax_parse_nodes = 100000\n')


YAML_CHECK = r'''
import json, sys, yaml
from pathlib import Path
class Strict(yaml.SafeLoader):
    pass
def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError('Duplicate or non-string YAML key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result
Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
results = {}
for name in sys.argv[1:]:
    try:
        text = Path(name).read_text(encoding='utf-8')
        if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
            results[name] = 'unsupported_alias'
        else:
            data = yaml.load(text, Loader=Strict)
            results[name] = 'valid' if isinstance(data, (dict, list)) else 'invalid_structure'
    except Exception:
        results[name] = 'invalid_structure'
print(json.dumps(results))
'''


def _finding(code, severity, path, message, *, line=None, column=None):
    return {'code': code, 'severity': severity, 'path': path, 'line': line, 'column': column, 'message': message}


def _omni_files(manifest, target):
    return [f for f in manifest['files'] if f['role'] == 'semantic_config' and (
        target.get('semantic_target') == 'omni' or Path(f['path']).name in {'model', 'relationships'}
        or f['path'].endswith(('.view', '.topic')))]


def _omni_check(runtime, work, manifest, target, source_data, results, limits):
    """Run the trusted bounded checker against captured bytes, never source code."""
    expected = _omni_files(manifest, target)
    if not expected:
        return None
    report = {'status': 'failed', 'native_verified': False}
    script = Path(__file__).resolve().parent / 'omni_contract.py'
    try:
        context = manifest.get('omni_context')
        require(context is None or type(context) is dict and context.get('warehouse') == target['warehouse'],
                'Omni catalogue context differs from selected warehouse')
        names = [Path(f['path']).name for f in expected]
        require(len(set(names)) == len(names), 'Multiple Omni models need separate lint scopes')
        inputs = {Path(f['path']).name: source_data[f['path']].decode('utf-8') for f in expected}
        request = {'files': inputs, 'context': context}
        (work / 'omni-input.json').write_bytes(_json_bytes(request))
        trusted_scripts = str(script.parent)
        code = ('import sys,json; from pathlib import Path; sys.path.insert(0,' + repr(trusted_scripts)
                + '); from omni_contract import check_model; p=json.loads(Path("omni-input.json").read_text()); '
                  'print(json.dumps(check_model(p["files"],p["context"])))')
        exit_code, out, _ = _run(runtime['python_executable'], ['-I', '-c', code], work,
                                 limits['timeout_seconds'], limits['max_output_bytes'])
        observed = json.loads(out)
        require(exit_code == 0 and type(observed) is dict and observed.get('status') in
                {'passed', 'failed', 'unsupported'} and observed.get('native_verified') is False,
                'Omni checker response invalid')
        report = observed
    except (ValueError, OSError, TimeoutError, OverflowError, KeyError, UnicodeError):
        pass
    report['checker_sha256'] = _sha(script.read_bytes())
    report['context_sha256'] = hash_json(manifest.get('omni_context'))
    report['files_sha256'] = hash_json({f['path']: f['sha256'] for f in expected})
    if report['status'] != 'passed':
        for item in results:
            if item['path'] in {f['path'] for f in expected} and item['status'] == 'checked':
                item.update(status='unsupported' if report['status'] == 'unsupported' else 'failed',
                            check_type='omni_contract', reason='Omni contract has unresolved or invalid definitions; inspect bounded diagnostics.')
    return report


def modeling_findings(manifest, target):
    """Review prompts over explicit model declarations, never inferred data proof."""
    results = []
    models = manifest.get('physical_models', [])
    if not models:
        return [_finding('MODEL_DECLARATIONS_PENDING', 'review', None,
                         'Grain, keys, layer placement and physical design have not been declared for modeling review.')]
    for model in models:
        path = model['path']
        for field in ('description', 'grain', 'keys', 'lineage'):
            if not model.get(field):
                results.append(_finding('MODEL_' + field.upper(), 'review', path, 'Declare the model ' + field + ' for independent review.'))
        if model.get('layer') not in {'bronze', 'silver', 'gold', 'staging', 'intermediate', 'mart'}:
            results.append(_finding('MODEL_LAYER', 'review', path, 'Record approved layer placement or an explicit existing-name exception.'))
        if target['warehouse'] == 'clickhouse':
            if not model.get('engine'):
                results.append(_finding('CLICKHOUSE_ENGINE', 'review', path, 'Choose an explicit ClickHouse engine and update strategy.'))
            elif 'mergetree' in str(model['engine']).lower():
                if not model.get('order_by'):
                    results.append(_finding('CLICKHOUSE_ORDER_KEY', 'review', path, 'Declare the MergeTree ordering key.'))
                results.append(_finding('CLICKHOUSE_UNIQUENESS', 'review', path, 'MergeTree keys do not prove row uniqueness; validate the data and replacement visibility.'))
        if target['warehouse'] == 'redshift':
            for field in ('distribution', 'sort_strategy'):
                if not model.get(field):
                    results.append(_finding('REDSHIFT_' + field.upper(), 'review', path, 'Declare Redshift ' + field + ', including AUTO if selected.'))
            results.append(_finding('REDSHIFT_INFORMATIONAL_KEYS', 'review', path, 'Declared Redshift keys need independent integrity tests.'))
        if target['warehouse'] == 'motherduck':
            results.append(_finding('MOTHERDUCK_REMOTE_BINDING', 'review', path, 'Verify the actual remote database, attachments and access; DuckDB lint is local syntax evidence.'))
        if model.get('incremental') and not all(model.get(k) for k in ('incremental_key', 'late_arrivals', 'deletes', 'replay')):
            results.append(_finding('INCREMENTAL_CONTRACT', 'review', path, 'Declare incremental keys, late arrivals, deletes and replay behavior.'))
    return results


def scaffold_manifest(root, *, limits=None):
    """Inventory bytes for operator review, without inventing rendered lineage.

    Returned manifests containing only templates or compiled files with missing
    source mappings are intentionally not runnable until the operator completes
    the execution-unit contract. This helper never renders anything.
    """
    root, limits = _path(root), _limits(limits)
    inventory = _inventory(root, limits)
    files, units, unresolved = [], [], []
    require(len(inventory['relevant_paths']) <= limits['max_files'], 'Manifest scaffold file bound exceeded')
    for path in inventory['relevant_paths']:
        data = _read(root / path, limits['max_file_bytes'])
        text = data.decode('utf-8')
        suffix = Path(path).suffix.lower()
        role, format_name, execution = 'model_sql', 'sql', [path]
        if _native_semantic_path(path):
            role, format_name, execution = 'semantic_config', 'yaml', []
        elif suffix in {'.json', '.yaml', '.yml'}:
            role, format_name, execution = 'project_config', 'json' if suffix == '.json' else 'yaml', []
        elif TEMPLATE.search(text) or suffix in {'.j2', '.jinja'}:
            role, format_name, execution = ('macro' if 'macros' in PurePosixPath(path).parts else 'template'), 'jinja', []
            unresolved.append({'path': path, 'reason': 'Provide rendered SQL, execution units and explicit source mappings.'})
        elif any(part in {'compiled', 'generated', 'target'} for part in PurePosixPath(path).parts[:-1]):
            format_name = 'compiled_sql'
            unresolved.append({'path': path, 'reason': 'Review generated output role and map its original sources.'})
        files.append({'path': path, 'sha256': _sha(data), 'role': role, 'format': format_name,
                      'execution_units': execution, 'source_paths': []})
        units.extend(execution)
    return {'manifest': {'schema_version': 1, 'kind': 'sql_lint_manifest', 'files': files,
                         'expected_execution_units': units}, 'review_required': True,
            'unresolved_sources': unresolved, 'inventory': inventory}


def _coverage(manifest, files):
    counts = Counter(item['status'] for item in files)
    units = [{'id': unit, 'path': item['path'], 'status': item['status']}
             for item in files for unit in item['execution_units']]
    unit_counts = Counter(item['status'] for item in units)
    return {'files': dict(expected=len(manifest['files']), **{s: counts[s] for s in sorted(STATUSES)}),
            'execution_units': dict(expected=len(manifest['expected_execution_units']),
                                    **{s: unit_counts[s] for s in sorted(STATUSES)}),
            'complete': bool(units) and counts['checked'] == len(files)
                        and unit_counts['checked'] == len(manifest['expected_execution_units'])}, units


def _apply_style_exceptions(manifest, files):
    """Pure normalization used identically by the runner and report verifier.

    Retain raw statuses/findings. Only successful SQLFluff receipts with no
    independent blocker may convert a convention-only failure to checked.
    Hash integrity is not report issuer authentication or human approval.
    """
    declarations = _style_exceptions(manifest, {f['path']: f for f in manifest['files']})
    by_path = {}
    for declaration in declarations:
        by_path.setdefault(declaration['path'], []).append(declaration)
    normalized, used, converted = [], [], 0
    for original in files:
        item = copy.deepcopy(original)
        raw_status = item.get('raw_status', item['status'])
        require(raw_status in STATUSES, 'Invalid raw lint status')
        item.update(status=raw_status, raw_status=raw_status, style_exception_applications=[])
        findings = item['findings']
        require(type(findings) is list, 'Invalid raw lint findings')
        for finding in findings:
            require(type(finding) is dict and set(finding) == {'code', 'severity', 'path', 'line', 'column', 'message'}
                    and type(finding['code']) is str and finding['severity'] == 'error'
                    and finding['path'] == item['path'], 'Invalid raw lint finding')
        require(not findings or raw_status != 'checked', 'Raw checked status contradicts lint findings')
        eligible = (item['role'] in SQL_ROLES and item.get('check_type') == 'sql_lint'
                    and raw_status == 'failed' and not item.get('reason')
                    and item.get('inline_noqa_count') == 0
                    and type(item.get('tool_output_sha256')) is str
                    and HEX.fullmatch(item['tool_output_sha256']))
        covered = set()
        if eligible:
            for declaration in by_path.get(item['path'], []):
                indices = [i for i, f in enumerate(findings) if f['code'] == declaration['rule']]
                if indices:
                    application = dict(declaration, finding_indices=indices, finding_count=len(indices))
                    item['style_exception_applications'].append(application)
                    used.append(application)
                    covered.update(indices)
            if findings and len(covered) == len(findings):
                item['status'] = 'checked'
                converted += 1
        normalized.append(item)
    used = sorted(used, key=lambda e: (e['path'], e['rule']))
    used_keys = {(e['path'], e['rule']) for e in used}
    unused = [e for e in declarations if (e['path'], e['rule']) not in used_keys]
    blockers = [_finding('UNUSED_STYLE_EXCEPTION', 'error', e['path'],
                        'Style exception ' + e['rule'] + ' has no eligible current finding; remove or review the stale declaration.')
                for e in unused]
    summary = {'policy': 'exact_file_convention_exceptions_v1', 'declarations': declarations,
               'declared_count': len(declarations), 'used_count': len(used), 'unused_count': len(unused),
               'excepted_finding_count': sum(e['finding_count'] for e in used),
               'files_converted_to_checked': converted, 'applications': used,
               'human_approval': False, 'native_correctness_proven': False}
    return normalized, summary, blockers


def lint_delivery(root, manifest, target, *, python_executable, limits=None):
    """Lint manifest-declared plain/rendered SQL without importing project code."""
    root, limits = _path(root), _limits(limits)
    require(root.is_dir(), 'Lint root must be a directory')
    dialect = _target(target)
    by_path = _manifest(manifest, limits)
    inventory = _inventory(root, limits)
    undeclared = set(inventory['relevant_paths']) - set(by_path)
    global_findings = [_finding('UNDECLARED_INPUT', 'error', path, 'Declare this SQL/template/configuration file in the lint inventory.') for path in sorted(undeclared)]
    runtime = inspect_runtime(python_executable, timeout_seconds=min(limits['timeout_seconds'], 30))
    config = configuration(target, limits)
    files, source_data, total = [], {}, 0
    with tempfile.TemporaryDirectory(prefix='dma-static-lint-') as folder:
        work = Path(folder).resolve()
        (work / 'lint.cfg').write_text(config, encoding='utf-8')
        sql_names, yaml_names = {}, {}
        for index, item in enumerate(manifest['files']):
            result = dict(item, status='checked', check_type='source_mapping', findings=[], inline_noqa_count=0)
            files.append(result)
            try:
                data = _read(root / item['path'], limits['max_file_bytes'])
                require(_sha(data) == item['sha256'], 'Input hash differs from the manifest')
                total += len(data)
                if total > limits['max_total_bytes']:
                    raise OverflowError('Total input byte limit exceeded')
                text = data.decode('utf-8')
                require('\x00' not in text, 'NUL bytes are not supported')
                source_data[item['path']] = data
            except OverflowError:
                result.update(status='skipped', reason='Configured input bound exceeded; no pass is claimed.')
                continue
            except (ValueError, OSError, UnicodeError):
                result.update(status='failed', reason='Missing, changed, nonregular or invalid UTF-8 input.')
                continue
            if item['format'] in {'sql', 'compiled_sql'}:
                result['check_type'] = 'sql_lint'
                result['inline_noqa_count'] = len(NOQA.findall(text))
                if TEMPLATE.search(text):
                    result.update(status='unsupported', reason='Unrendered template markers; provide compiled SQL and source mapping.')
                elif INLINE_CONFIG.search(text):
                    result.update(status='unsupported', reason='Inline SQLFluff configuration is not permitted in the isolated static lane.')
                elif not re.sub(r'/\*.*?\*/|--[^\n]*', '', text, flags=re.S).strip():
                    result.update(status='failed', reason='Empty SQL cannot satisfy an execution unit.')
                else:
                    name = 'sql-%04d.sql' % index
                    (work / name).write_bytes(data)
                    sql_names[name] = result
            elif item['format'] == 'json':
                result['check_type'] = 'json_structure'
                try:
                    captured = work / ('config-%04d.json' % index)
                    captured.write_bytes(data)
                    value = load_json(captured, max_bytes=limits['max_file_bytes'])
                    require(type(value) in (dict, list), 'Structured JSON object/array required')
                except (ValueError, UnicodeError):
                    result.update(status='failed', reason='Invalid JSON structure, duplicate keys or nonfinite values.')
            elif item['format'] == 'yaml':
                result['check_type'] = 'yaml_structure'
                name = 'config-%04d.yaml' % index
                (work / name).write_bytes(data)
                yaml_names[name] = result
        if sql_names:
            args = ['-m', 'sqlfluff', 'lint', '--format', 'json', '--nocolor', '--disable-progress-bar',
                    '--ignore-local-config', '--config', 'lint.cfg', '--dialect', dialect, '--templater', 'raw',
                    '--library-path', 'none', '--disable-noqa', '--disregard-sqlfluffignores', *sql_names]
            _lint_sql(runtime['python_executable'], args, work, sql_names, limits)
        if yaml_names:
            try:
                code, out, _ = _run(runtime['python_executable'], ['-c', YAML_CHECK, *yaml_names], work,
                                    limits['timeout_seconds'], limits['max_output_bytes'])
                observed = json.loads(out)
                require(code == 0 and type(observed) is dict and set(observed) == set(yaml_names), 'Incomplete YAML checker output')
                for name, result in yaml_names.items():
                    if observed[name] != 'valid':
                        result.update(status='unsupported' if observed[name] == 'unsupported_alias' else 'failed',
                                      reason='YAML aliases/anchors require native review.' if observed[name] == 'unsupported_alias'
                                      else 'Invalid YAML structure, duplicate keys or unsafe tags.')
            except (ValueError, OSError, TimeoutError, OverflowError):
                for result in yaml_names.values():
                    result.update(status='failed', reason='YAML structural checker unavailable or incomplete.')
        omni_report = _omni_check(runtime, work, manifest, target, source_data, files, limits)
        mapped = {path for item in manifest['files'] for path in item['source_paths']}
        indexed = {item['path']: item for item in files}
        for result in files:
            if result['role'] in SOURCE_ROLES and result['path'] not in mapped and result['status'] == 'checked':
                result.update(status='unsupported', reason='Source template has no declared rendered execution consumer.')
            if result['source_paths'] and any(indexed[p]['status'] != 'checked' for p in result['source_paths']):
                result.update(status='failed', reason='Rendered SQL source evidence is incomplete.')
        # Recheck every captured input after the child finishes. No candidate data
        # or templates ever run inside the child process.
        for result in files:
            if result['path'] in source_data:
                try:
                    require(_read(root / result['path'], limits['max_file_bytes']) == source_data[result['path']], 'Input drift')
                except (ValueError, OSError, OverflowError):
                    result.update(status='failed', reason='Input changed while linting.')
    try:
        require(_inventory(root, limits) == inventory, 'Scope changed')
        require(inspect_runtime(python_executable, timeout_seconds=min(limits['timeout_seconds'], 30)) == runtime,
                'Runtime changed')
    except (ValueError, OSError, TimeoutError, OverflowError):
        global_findings.append(_finding('LINT_CONTEXT_DRIFT', 'error', None,
            'Input inventory or trusted runtime changed during linting; rerun against a stable snapshot.'))
    files, style_exceptions, exception_blockers = _apply_style_exceptions(manifest, files)
    global_findings.extend(exception_blockers)
    coverage, units = _coverage(manifest, files)
    complete = coverage['complete'] and not global_findings
    coverage['complete'] = complete
    report = {'schema_version': 1, 'kind': 'sql_lint_report', 'created_at': datetime.now(timezone.utc).isoformat(),
              'status': 'passed' if complete else 'failed', 'assurance': 'static_lint_integrity_only',
              'target': target, 'target_sha256': hash_json(target), 'dialect': dialect,
              'manifest': manifest, 'manifest_sha256': hash_json(manifest), 'limits': limits,
              'configuration': config, 'config_sha256': _sha(config.encode()),
              'runtime': runtime, 'runtime_sha256': hash_json(runtime), 'inventory': inventory,
              'files': files, 'execution_units': units, 'coverage': coverage,
              'style_exceptions': style_exceptions,
              'findings': global_findings, 'modeling_findings': modeling_findings(manifest, target),
              'limitations': ['Static lint is not native execution, model acceptance or deployment authority.',
                  'Source-to-rendered mappings are declared provenance; faithful compilation is a separate check.',
                  'Parser errors can reflect invalid SQL or unsupported vendor grammar; neither is a pass.',
                  'Configuration checks validate basic structure only, not native schemas or semantic correctness.',
                  'Exact convention exceptions retain raw findings and explain policy choices; they are not human approval or proof of correctness.',
                  'The configured interpreter and installed runtime are trusted; no project templates or third-party lint plugins run.']}
    if omni_report is not None:
        report['omni_contract'] = omni_report
    report['report_sha256'] = hash_json(report)
    return report


def _lint_sql(executable, args, work, expected, limits):
    try:
        code, out, err = _run(executable, args, work, limits['timeout_seconds'], limits['max_output_bytes'])
        observed = json.loads(out)
        require(code in (0, 1) and type(observed) is list, 'Invalid SQLFluff response')
        seen = set()
        for item in observed:
            require(type(item) is dict and type(item.get('filepath')) is str, 'Invalid file receipt')
            name = item['filepath']
            if name.startswith(str(work) + os.sep):
                name = name[len(str(work)) + 1:]
            require(name in expected and name not in seen, 'Unexpected or duplicate SQLFluff file receipt')
            seen.add(name)
            result = expected[name]
            violations = item.get('violations')
            require(type(violations) is list and len(violations) <= 10000, 'Invalid violations')
            for finding in violations:
                rule = finding.get('code')
                require(type(rule) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{1,30}', rule), 'Invalid rule code')
                line, column = finding.get('start_line_no'), finding.get('start_line_pos')
                require((line is None or type(line) is int) and (column is None or type(column) is int), 'Invalid diagnostic position')
                # Vendor descriptions may quote source literals; retain codes and
                # locations with a safe explanation instead of emitting SQL/data.
                message = ('SQL could not be parsed; resolve invalid syntax or document a dialect grammar gap.'
                           if rule in {'PRS', 'LXR', 'TMP'} else 'SQLFluff rule ' + rule + ' needs correction or a separately reviewed exception.')
                result['findings'].append(_finding(rule, 'error', result['path'], message, line=line, column=column))
            result['status'] = 'failed' if violations else 'checked'
            result['tool_output_sha256'] = _sha(out)
        for name in set(expected) - seen:
            expected[name].update(status='skipped', reason='SQLFluff omitted this declared file; coverage is incomplete.')
        require(code == (1 if any(item['findings'] for item in expected.values()) else 0), 'SQLFluff exit status disagrees with findings')
        if err.strip():
            # Unexpected diagnostics can disclose skipped parser/runtime work.
            raise ValueError('SQLFluff emitted diagnostics outside structured output')
    except (ValueError, OSError, TimeoutError, OverflowError, KeyError, TypeError):
        for result in expected.values():
            result.update(status='failed', reason='SQLFluff failed, timed out or returned incomplete/unexpected evidence.')


def verify_report(report, root, target=None, manifest=None, *, runtime=None):
    """Recompute integrity/coverage and file pins. Does not authenticate a report.

    A caller may supply a freshly inspected trusted runtime. No executable path
    inside a report is launched by this verifier.
    """
    require(type(report) is dict and type(report.get('schema_version')) is int and report['schema_version'] == 1
            and report.get('kind') == 'sql_lint_report', 'Unsupported lint report')
    require(report.get('report_sha256') == hash_json({k: v for k, v in report.items() if k != 'report_sha256'}), 'Lint report integrity failed')
    root = _path(root)
    limits = _limits(report['limits'])
    current_manifest = report['manifest'] if manifest is None else manifest
    current_target = report['target'] if target is None else target
    by_path = _manifest(current_manifest, limits)
    omni_files = _omni_files(current_manifest, current_target)
    if omni_files:
        contract = report.get('omni_contract', {})
        checker = Path(__file__).resolve().parent / 'omni_contract.py'
        require(contract.get('status') == 'passed' and contract.get('native_verified') is False
                and contract.get('checker_sha256') == _sha(checker.read_bytes())
                and contract.get('context_sha256') == hash_json(current_manifest.get('omni_context'))
                and contract.get('files_sha256') == hash_json({f['path']: f['sha256'] for f in omni_files}),
                'Current Omni contract evidence required; YAML-only receipts are insufficient')
    require(hash_json(current_manifest) == report['manifest_sha256'] == hash_json(report['manifest']), 'Lint manifest drift')
    require(hash_json(current_target) == report['target_sha256'] == hash_json(report['target']), 'Lint target drift')
    require(_target(current_target) == report['dialect'], 'Lint dialect drift')
    config = configuration(current_target, limits)
    require(report['configuration'] == config and report['config_sha256'] == _sha(config.encode()), 'Lint configuration drift')
    require(report['runtime']['sqlfluff_version'] == SQLFLUFF_VERSION
            and hash_json(report['runtime']) == report['runtime_sha256'], 'Lint runtime drift')
    if runtime is not None:
        require(hash_json(runtime) == report['runtime_sha256'], 'Observed runtime changed')
    require(_inventory(root, limits) == report['inventory'], 'Lint scope or ambient-configuration drift')
    require(not (set(report['inventory']['relevant_paths']) - set(by_path)), 'Uninventoried lint inputs')
    files = report['files']
    require(type(files) is list and len(files) == len(by_path)
            and {f['path'] for f in files} == set(by_path), 'Lint file denominator mismatch')
    declarations = _style_exceptions(current_manifest, by_path)
    exception_paths = {e['path'] for e in declarations}
    for item in files:
        require(item['status'] in STATUSES and all(item[k] == by_path[item['path']][k] for k in by_path[item['path']]), 'Lint file declaration drift')
        data = _read(root / item['path'], limits['max_file_bytes'])
        require(_sha(data) == item['sha256'], 'Lint source content drift')
        if item['path'] in exception_paths:
            text = data.decode('utf-8')
            require(not NOQA.search(text) and not INLINE_CONFIG.search(text) and not TEMPLATE.search(text),
                    'Style exception cannot cover noqa, inline configuration or unrendered templates')
    if 'style_exceptions' in report:
        require(all('raw_status' in f and 'style_exception_applications' in f for f in files),
                'Style exception evidence is incomplete')
        replayed, summary, blockers = _apply_style_exceptions(current_manifest, files)
        require(replayed == files and summary == report['style_exceptions'] and not blockers,
                'Style exception normalization or application drift')
        require(all(f['status'] == 'checked' for f in files), 'Lint has failed, skipped or unsupported files')
    else:
        # Previously issued strict reports remain verifiable; they cannot carry
        # exception declarations or claim converted findings without new evidence.
        require(not declarations and all('raw_status' not in f and 'style_exception_applications' not in f for f in files),
                'Missing style exception evidence')
        require(all(f['status'] == 'checked' and not f['findings'] for f in files),
                'Lint has failed, skipped or unsupported files')
        summary = None
    coverage, units = _coverage(current_manifest, files)
    require(coverage == report['coverage'] and units == report['execution_units'] and coverage['complete'], 'Lint execution-unit coverage is incomplete')
    require(report['status'] == 'passed' and not report['findings'], 'Lint report has blocking findings')
    verified = {'status': 'verified', 'assurance': 'static_lint_integrity_only', 'report_sha256': report['report_sha256'],
            'coverage': coverage, 'runtime_reverified': runtime is not None, 'native_verified': False,
            'business_approved': False, 'execution_authorized': False}
    if summary is not None:
        verified['style_exceptions'] = summary
    return verified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--target')
    parser.add_argument('--python', dest='python_executable')
    parser.add_argument('--scaffold', action='store_true', help='Write a provisional manifest; rendered mappings require review')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        output, root = _path(args.output, exists=False), _path(args.root)
        require(root != output and root not in output.parents and not output.exists(), 'Report must be a new file outside source scope')
        if args.scaffold:
            proposed = scaffold_manifest(root)
            with output.open('xb') as stream:
                stream.write(_json_bytes(proposed['manifest']) + b'\n')
            print(json.dumps({'status': 'manifest_requires_review', 'unresolved_sources': proposed['unresolved_sources'],
                              'files': len(proposed['manifest']['files'])}))
            return 0
        require(args.manifest and args.target and args.python_executable, 'Lint needs --manifest, --target and --python')
        report = lint_delivery(root, load_json(args.manifest), load_json(args.target), python_executable=args.python_executable)
        with output.open('xb') as stream:
            stream.write(_json_bytes(report) + b'\n')
        print(json.dumps({'status': report['status'], 'coverage': report['coverage'], 'report_sha256': report['report_sha256']}))
        return 0 if report['status'] == 'passed' else 1
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        print('Static lint refused: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
