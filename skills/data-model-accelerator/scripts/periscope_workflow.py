#!/usr/bin/env python3
"""Offline CDT discovery plus canonical extraction; never executes source code.

The wrapper is additive: source-adapter and specialist schemas remain unchanged.
An explicit profile selects evidence, not native validity or migration readiness.
"""
import argparse
import hashlib
import json
from pathlib import Path

from plan_specialists import git_identity, plan_repository
from source_adapters.base import MAX_FILES, bounded, read_json
from source_adapters.filesystem import new_json_output, read_assigned
from source_adapters.registry import component_fingerprint, parse
from specialist_profiles import profile_binding


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _write(path, value):
    with new_json_output(path) as write:
        write(value)


def _identity(value, root, projects):
    value = {} if value is None else bounded(value)
    if not isinstance(value, dict) or set(value) - {'repository_id', 'space_ids'}:
        raise ValueError('periscope.invalid_source_identity')
    repository = value.get('repository_id')
    spaces = value.get('space_ids', {})
    if repository is not None and (not isinstance(repository, str) or not repository.strip()):
        raise ValueError('periscope.invalid_repository_identity')
    if not isinstance(spaces, dict) or any(not isinstance(v, str) or not v.strip() for v in spaces.values()):
        raise ValueError('periscope.invalid_space_identity')
    if set(spaces) - set(projects):
        raise ValueError('periscope.unknown_space_root')
    records, gaps, used = [], [], {}
    for project in projects:
        space = spaces.get(project)
        supplied = bool(repository and space)
        namespace = 'periscope:' + ('space:' if supplied else 'local:') + _hash(
            [repository, space] if supplied else [repository or str(root), project])[:24]
        record = {'project_root': project, 'namespace': namespace, 'repository_id': repository,
                  'space_id': space, 'basis': 'caller_supplied_repository_and_space' if supplied else 'local_root_and_project',
                  'cross_checkout_stability': supplied, 'identity_verified': False}
        if namespace in used:
            gaps.append({'code': 'periscope.source_identity_conflict', 'project_roots': [used[namespace], project],
                         'message': 'Two project roots claim the same Space namespace; reconcile before combining evidence.'})
        used[namespace] = project
        records.append(record)
    return {'projects': records, 'caller_record': value}, gaps


def _dialects(values, projects):
    """Record caller-supplied verification evidence without asserting authenticity."""
    if not isinstance(values, (list, tuple)) or len(values) > 128:
        raise ValueError('periscope.invalid_connection_mappings')
    records, gaps, seen = [], [], {}
    for value in values:
        if not isinstance(value, dict) or set(value) != {'project_root', 'connection_name', 'dialect', 'evidence'}:
            raise ValueError('periscope.invalid_connection_mapping')
        if value['project_root'] not in projects or any(not isinstance(value[k], str) or not value[k].strip()
                                                      for k in ('connection_name', 'dialect', 'evidence')):
            raise ValueError('periscope.unverified_connection_mapping')
        key = (value['project_root'], value['connection_name'])
        item = dict(value, status='verification_evidence_recorded', evidence_authentication='not_performed',
                    applied_to_canonical_parser=False)
        if key in seen and seen[key] != value['dialect']:
            item['status'] = 'conflict'
            for previous in records:
                if (previous['project_root'], previous['connection_name']) == key:
                    previous['status'] = 'conflict'
            gaps.append({'code': 'periscope.connection_dialect_conflict', 'project_root': key[0],
                         'connection_name': key[1], 'message': 'Conflicting verified mapping records remain unresolved.'})
        seen[key] = value['dialect']
        if item not in records:
            records.append(item)
    return records, gaps


def _read_files(root, assets):
    files, failures = {}, []
    for asset in assets:
        if asset['status'] != 'readable':
            continue
        try:
            raw = read_assigned(root, asset['path'])
            if hashlib.sha256(raw).hexdigest() != asset['sha256']:
                raise ValueError('source.changed_asset')
            files[asset['path']] = raw.decode('utf-8')
        except (OSError, ValueError, UnicodeError):
            failures.append({'code': 'periscope.input_changed_or_unreadable', 'path': asset['path'],
                             'message': 'Assigned evidence could not be reread with its inventory hash; not extracted.'})
    return files, failures


def run_periscope_workflow(source_root, output_dir, *, source_profiles=(), source_identity=None,
                           verified_connection_dialects=(), inspect_git=True, max_files=2000,
                           max_file_bytes=1048576, max_total_bytes=33554432):
    """Discover and extract once into a new directory outside the source checkout.

    source_identity: optional {repository_id: str, space_ids: {project_root: str}}.
    verified_connection_dialects: records with project_root, connection_name,
    dialect and an attributable evidence string. They do not authorize execution.
    Returns the JSON-safe report also saved as periscope-workflow.json. Canonical
    contracts are at extraction[].contract_path relative to output_dir.
    """
    source = Path(source_root).expanduser().absolute()
    output = Path(output_dir).expanduser().absolute()
    if source.resolve() != source or output.resolve() != output:
        raise ValueError('periscope.redirected_workflow_path')
    if output == source or source in output.parents or output in source.parents:
        raise ValueError('periscope.output_overlaps_source')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('periscope.output_not_empty')
    plan = plan_repository(source, output / 'discovery', source_profiles=source_profiles,
                           inspect_git=inspect_git, max_files=max_files, max_file_bytes=max_file_bytes,
                           max_total_bytes=max_total_bytes, require_source_adapters=True)
    inventory = read_json((output / 'discovery/inventory.json').read_text())
    tasks = [t for t in plan['tasks'] if t['source_type'] == 'periscope']
    projects = sorted(t['project_root'] for t in tasks)
    identity, gaps = _identity(source_identity, source, projects)
    dialects, dialect_gaps = _dialects(verified_connection_dialects, projects)
    gaps.extend(dialect_gaps)
    by_id = {a['asset_id']: a for a in inventory['assets']}
    namespaces = {p['project_root']: p['namespace'] for p in identity['projects']}
    adapter_fingerprint = component_fingerprint('periscope')
    extraction, file_results, selected_ids, binding_review = [], {}, set(), []
    for task in tasks:
        selected = [by_id[aid] for aid in task['asset_ids']]
        selected_ids.update(task['asset_ids'])
        files, failures = _read_files(source, selected)
        gaps.extend(failures)
        item = {'task_id': task['task_id'], 'project_root': task['project_root'],
                'namespace': namespaces[task['project_root']], 'status': 'not_run',
                'assigned_files': len(selected), 'readable_files': len(files), 'contract_path': None,
                'qualified_objects': [], 'specialist_profile': task['specialist_profile']}
        item['freshness_bindings'] = {
            'source_files_sha256': _hash([(a['path'], a['sha256'], a['status']) for a in sorted(selected, key=lambda a: a['path'])]),
            'namespace': item['namespace'], 'adapter_component_sha256': adapter_fingerprint,
            'specialist_profile_sha256': task['specialist_profile']['sha256']}
        item['freshness_sha256'] = _hash(item['freshness_bindings'])
        extraction.append(item)
        if not files:
            item['status'] = 'no_readable_evidence'
            continue
        if len(files) > MAX_FILES:
            item['status'] = 'bounded_out'
            gaps.append({'code': 'periscope.extraction_file_limit', 'project_root': task['project_root'],
                         'message': 'Project exceeds canonical adapter file bound; select a smaller scope with dependency closure.',
                         'limit': MAX_FILES})
            continue
        try:
            contract = parse('periscope', files)
        except (ValueError, ImportError):
            item['status'] = 'failed'
            gaps.append({'code': 'periscope.extraction_failed', 'project_root': task['project_root'],
                         'message': 'Canonical extraction rejected this snapshot or a pinned dependency is missing.'})
            continue
        relative = 'contracts/' + task['task_id'] + '.json'
        (output / 'contracts').mkdir(exist_ok=True)
        _write(output / relative, contract)
        item.update(status='partial' if contract['gaps'] else 'subset_parsed', contract_path=relative,
                    contract_sha256=hashlib.sha256((output / relative).read_bytes()).hexdigest(),
                    object_count=len(contract['objects']), gap_count=len(contract['gaps']))
        gaps.extend(dict(g, project_root=task['project_root']) for g in contract['gaps'])
        for entry in contract['source_files']:
            file_results[entry['path']] = entry
        native_seen = {}
        for obj in contract['objects']:
            native = obj['native_id']
            qualified = item['namespace'] + ':' + (obj['kind'] + ':' + native if native is not None else obj['id'])
            item['qualified_objects'].append({'object_id': obj['id'], 'qualified_id': qualified,
                                              'basis': 'native_token' if native is not None else 'source_occurrence'})
            if native is not None and qualified in native_seen:
                gaps.append({'code': 'periscope.native_identity_conflict', 'qualified_id': qualified,
                             'object_ids': [native_seen[qualified], obj['id']],
                             'message': 'Distinct source objects share a native identity; neither is discarded.'})
            native_seen[qualified] = obj['id']
        for expression in contract['expressions']:
            if expression['language'] == 'periscope_template':
                binding_review.append({'project_root': task['project_root'], 'expression_id': expression['id'],
                                       'expression': expression['text'], 'evidence': expression['evidence'],
                                       'status': 'unresolved', 'code': 'periscope.binding_native_meaning_unverified',
                                       'reason': 'Git bracket text alone cannot prove snippet versus filter/view/identifier meaning or parameter bindings; no substitution performed.'})
    failure_paths = {g['path'] for g in gaps if g['code'] == 'periscope.input_changed_or_unreadable'}
    rows = []
    for asset in inventory['assets']:
        selected = asset['asset_id'] in selected_ids
        if asset['path'] in failure_paths or asset['status'] in ('unreadable', 'unreadable_limit'):
            status, reason = 'unreadable', 'Evidence not read within the configured boundary or changed before extraction.'
        elif asset['status'] == 'unsupported_binary':
            status, reason = 'unsupported', 'Binary or non-UTF-8 evidence retained by inventory hash; not interpreted.'
        elif not selected:
            status, reason = 'excluded', 'Not assigned to a Periscope project; original routing retained.'
        elif asset['path'] in file_results:
            status = file_results[asset['path']]['status']
            reason = file_results[asset['path']]['reason']
        else:
            status, reason = 'unsupported', 'Selected file was not extracted; inspect extraction status and gaps.'
        rows.append({'path': asset['path'], 'sha256': asset['sha256'], 'status': status, 'reason': reason,
                     'periscope_selected': selected, 'source_types': asset['source_types'],
                     'classification_evidence': asset['classification_evidence']})
    for excluded in inventory['exclusions']:
        if excluded['scope'] == 'file':
            rows.append({'path': excluded['path'], 'sha256': None, 'status': 'excluded',
                         'reason': excluded['reason'], 'periscope_selected': False, 'source_types': [],
                         'classification_evidence': []})
    rows.sort(key=lambda row: row['path'])
    counts = {key: sum(row['status'] == key for row in rows)
              for key in ('parsed', 'partial', 'unsupported', 'excluded', 'unreadable')}
    subtrees = [dict(e, file_count=None) for e in inventory['exclusions'] if e['scope'] == 'directory']
    incomplete = any(g['kind'] in ('file_count_limit', 'directory_unreadable') for g in inventory['gaps'])
    if not tasks:
        gaps.append({'code': 'periscope.discovery_unresolved',
                     'message': 'No corroborated CDT project was found. An explicit periscope:RELATIVE_ROOT profile can select a known snapshot; selection does not validate its format.'})
    report = {'kind': 'periscope_workflow', 'schema_version': 1,
              'status': 'no_periscope_detected' if not tasks else 'partial' if gaps or inventory['gaps'] else 'subset_extracted',
              'version': {'workflow': 1, 'workflow_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          'planner_sha256': hashlib.sha256((Path(__file__).parent / 'plan_specialists.py').read_bytes()).hexdigest(),
                          'adapter_component_sha256': adapter_fingerprint,
                          'specialist_profile': profile_binding('periscope'),
                          'installed_repository': git_identity(Path(__file__).resolve().parents[3], inspect_git)},
              'input': dict(inventory['repository'], snapshot_sha256=plan['source_snapshot_sha256']),
              'profiles': inventory['source_profiles'], 'source_identity': identity, 'extraction': extraction,
              'connection_dialects': dialects, 'binding_review': binding_review,
              'coverage': {'files': rows, 'counts': counts, 'known_file_denominator': len(rows),
                           'selected_file_denominator': len(selected_ids), 'excluded_subtrees': subtrees,
                           'repository_file_denominator': len(rows) if not subtrees and not incomplete else None,
                           'enumeration_complete': not incomplete, 'limits': inventory['limits'],
                           'scan_gaps': inventory['gaps'], 'export_completeness': 'not_established'},
              'gaps': gaps, 'execution_performed': False, 'network_calls': 0, 'native_validation': 'not_run',
              'discovery_plan_path': 'discovery/dispatch-plan.json'}
    _write(output / 'periscope-workflow.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-profile', action='append', default=[])
    parser.add_argument('--source-identity', type=Path, help='Caller supplied identity JSON; never read implicitly from source')
    parser.add_argument('--verified-connection-dialects', type=Path, help='Caller supplied verification evidence JSON')
    parser.add_argument('--no-git', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run_periscope_workflow(args.root, args.output, source_profiles=args.source_profile,
                    source_identity=read_json(args.source_identity.read_text()) if args.source_identity else None,
                    verified_connection_dialects=read_json(args.verified_connection_dialects.read_text()) if args.verified_connection_dialects else (),
                    inspect_git=not args.no_git)
        print(json.dumps({'status': result['status'], 'coverage': result['coverage']['counts'],
                          'report': str(args.output / 'periscope-workflow.json'), 'native_validation': 'not_run'}))
        return 2 if result['status'] != 'subset_extracted' else 0
    except (ValueError, OSError, ImportError):
        print('Periscope workflow failed: check source/output boundary, explicit metadata and pinned dependencies.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
