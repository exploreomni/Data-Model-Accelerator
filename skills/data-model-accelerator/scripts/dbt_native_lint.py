"""Supplemental dbt v2 lint of bounded plain SQL; never load source projects.

The existing SQLFluff delivery report remains the release lint contract. Native
lint is separate evidence, not SQL validation, a dbt build or business acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from dbt_runtime import observed_version, runtime_identity, validate_selection
from lint_delivery import (_inventory, _limits, _manifest, _path, _read, DIALECTS,
                           INLINE_CONFIG, NOQA, TEMPLATE)
from ae_common import hash_json, load_json, require


def _run(argv, work, *, timeout=30, maximum=8 * 1024 * 1024):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(work), 'XDG_CONFIG_HOME': str(work),
           'XDG_CACHE_HOME': str(work), 'TMPDIR': str(work), 'LANG': 'C.UTF-8',
           'NO_COLOR': '1', 'DBT_DISABLE_VERSION_CHECK': 'true',
           'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
        end = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if time.monotonic() >= end or max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > maximum:
                    raise ValueError('dbt.native_lint_execution_limit')
                try:
                    child.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(maximum + 1), err.read(maximum + 1)
        require(max(len(stdout), len(stderr)) <= maximum, 'dbt.native_lint_output_limit')
        return child.returncode, stdout, stderr


def lint_native(root, manifest, selection, warehouse, *, executable, execute=False):
    selected = validate_selection(selection)
    require(warehouse in DIALECTS, 'dbt.native_lint_unknown_dialect')
    limits = _limits()
    root = _path(root)
    by_path = _manifest(manifest, limits)
    inventory = _inventory(root, limits)
    undeclared = sorted(set(inventory['relevant_paths']) - set(by_path))
    result = {'schema_version': 1, 'kind': 'dbt_native_lint', 'selection': selected,
              'warehouse': warehouse, 'manifest_sha256': hash_json(manifest),
              'status': 'not_run', 'files': [], 'undeclared_files': undeclared,
              'execution_performed': False, 'project_validity': 'not_run',
              'warehouse_validation': 'not_run', 'data_accuracy': 'not_run',
              'limitations': ['Plain SQL only; source Jinja, project configuration and dependencies are never loaded.',
                             'Fixed CP01/LT01 conventions only; this does not replace the SQLFluff delivery report.',
                             'Exit code zero does not mean zero violations. Runtime byte hashes are not authentication.']}
    if not execute:
        return result
    if selected['distribution'] != 'dbt' or selected['version'] != '2.0.8':
        result.update(status='unsupported', reason='Native lint is qualified only for the full dbt 2.0.8 distribution.')
        return result
    identity = runtime_identity(executable, selected)
    total = 0
    with tempfile.TemporaryDirectory(prefix='dma-dbt-lint-') as folder:
        work = Path(folder).resolve()
        code, version, _ = _run([str(executable), '--version'], work)
        require(code == 0, 'dbt.native_lint_version_probe_failed')
        result['observed_runtime'] = observed_version(version.decode('utf-8'), selected)
        result['runtime_identity_sha256'] = hash_json(identity)
        (work / 'models').mkdir()
        (work / 'dbt_project.yml').write_text('name: dma_lint\nversion: "1.0"\nconfig-version: 2\nprofile: dma_lint\n')
        (work / 'profiles.yml').write_text('dma_lint:\n  target: local\n  outputs:\n    local:\n      type: duckdb\n      path: ":memory:"\n')
        config = ('[sqlfluff]\ndialect = ' + DIALECTS[warehouse] + '\ntemplater = dbt\nrules = CP01,LT01\n'
                  '[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = upper\n')
        (work / '.sqlfluff').write_text(config)
        result['configuration_sha256'] = hashlib.sha256(config.encode()).hexdigest()
        names = {}
        for index, item in enumerate(manifest['files']):
            row = {'path': item['path'], 'sha256': item['sha256'], 'status': 'unsupported', 'violations': []}
            result['files'].append(row)
            data = _read(root / item['path'], limits['max_file_bytes'])
            require(hashlib.sha256(data).hexdigest() == item['sha256'], 'dbt.native_lint_changed_input')
            total += len(data)
            require(total <= limits['max_total_bytes'], 'dbt.native_lint_byte_limit')
            body = data.decode('utf-8')
            if item['format'] not in {'sql', 'compiled_sql'} or TEMPLATE.search(body) or INLINE_CONFIG.search(body) or NOQA.search(body):
                row['reason'] = 'Only plain SQL without templates, inline overrides or suppression directives is eligible.'
                continue
            if '\x00' in body or not re.sub(r'/\*.*?\*/|--[^\n]*', '', body, flags=re.S).strip():
                row.update(status='failed', reason='Empty or invalid SQL cannot pass lint.')
                continue
            name = 'models/model_%04d.sql' % index
            (work / name).write_bytes(data)
            names[name] = row
        if names:
            argv = [str(executable), 'lint', *names, '--project-dir', str(work), '--profiles-dir', str(work),
                    '--config', str(work / '.sqlfluff'), '--format', 'json', '--jinja-render-mode', 'turbo',
                    '--quiet', '--no-manage-state', '--no-send-anonymous-usage-stats', '--no-version-check']
            code, stdout, stderr = _run(argv, work)
            result.update(execution_performed=True, command_sha256=hash_json(argv), exit_code=code,
                          stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())
            try:
                from source_adapters.base import read_json
                rows = read_json(stdout.decode('utf-8'))
                require(isinstance(rows, list) and len(rows) == len(names), 'dbt.native_lint_incomplete_results')
                seen = set()
                for native in rows:
                    name = native.get('filepath')
                    require(name in names and name not in seen, 'dbt.native_lint_unexpected_result')
                    seen.add(name)
                    violations = native.get('violations')
                    require(isinstance(violations, list) and len(violations) <= 10000, 'dbt.native_lint_invalid_results')
                    projected = []
                    for v in violations:
                        require(isinstance(v, dict) and isinstance(v.get('code'), str) and re.fullmatch(r'[A-Z][A-Z0-9]{1,12}', v['code']), 'dbt.native_lint_invalid_violation')
                        projected.append({'code': v['code'], **{k: v[k] for k in ('start_line_no', 'start_line_pos') if type(v.get(k)) is int and v[k] > 0}})
                    names[name].update(status='failed' if code != 0 or projected else 'checked', violations=projected)
            except (ValueError, UnicodeError, TypeError, AttributeError):
                for row in names.values():
                    row.update(status='failed', reason='Native output was incomplete or did not match the pinned lint contract.')
        require(runtime_identity(executable, selected) == identity, 'dbt.native_lint_runtime_changed')
    for item in manifest['files']:
        require(hashlib.sha256(_read(root / item['path'], limits['max_file_bytes'])).hexdigest() == item['sha256'], 'dbt.native_lint_changed_input')
    require(_inventory(root, limits) == inventory, 'dbt.native_lint_inventory_changed')
    states = [r['status'] for r in result['files']]
    result['coverage'] = {key: states.count(key) for key in ('checked', 'failed', 'unsupported')}
    result['status'] = 'failed' if undeclared or 'failed' in states else 'partial' if 'unsupported' in states else 'passed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path, help='Nonsecret runtime selection JSON')
    parser.add_argument('--warehouse', required=True, choices=tuple(DIALECTS))
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    source = _path(args.root)
    output = _path(args.output, exists=False)
    require(output != source and source not in output.parents and not output.exists(), 'dbt.native_lint_new_external_output_required')
    from source_adapters.filesystem import new_json_output
    with new_json_output(output) as write:
        result = lint_native(source, load_json(args.manifest), load_json(args.runtime), args.warehouse,
                             executable=args.executable, execute=args.execute)
        write(result)
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
