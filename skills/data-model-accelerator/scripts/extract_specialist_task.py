#!/usr/bin/env python3
"""Bridge offline parser evidence into the existing specialist result contract.

The coordinator invokes this on approved local evidence before agent dispatch.
It does not run an agent, authorize disclosure, approve placement or deploy.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from source_adapters.base import MAX_FILES, MAX_TOTAL_BYTES, read_json, sha
from source_adapters.filesystem import new_json_output, read_assigned
from source_adapters.registry import parse
from verify_specialist_results import inside, read_json as read_file


def load_task(plan_path, task_id):
    plan_path = Path(plan_path).resolve(strict=True)
    plan = read_file(plan_path)
    inv_path = inside(plan_path.parent, plan['inventory_path'])
    snapshot = hashlib.sha256(inv_path.read_bytes()).hexdigest()
    if snapshot != plan['source_snapshot_sha256']:
        raise ValueError('source.stale_inventory')
    inv = read_file(inv_path)
    tasks = [t for t in plan['tasks'] if t['task_id'] == task_id]
    if len(tasks) != 1:
        raise ValueError('source.unknown_or_duplicate_task')
    task = tasks[0]
    root = Path(inv['repository']['root'])
    if root.is_symlink() or root.resolve() != root:
        raise ValueError('source.redirected_root')
    by_id = {a['asset_id']: a for a in inv['assets']}
    files, path_ids = {}, {}
    if len(task['asset_ids']) > MAX_FILES:
        raise ValueError('source.file_limit')
    total = 0
    for aid in task['asset_ids']:
        a = by_id[aid]
        if a['status'] != 'readable':
            raise ValueError('source.unreadable_assigned_asset')
        raw = read_assigned(root, a['path'])
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('source.byte_limit')
        if hashlib.sha256(raw).hexdigest() != a['sha256']:
            raise ValueError('source.changed_asset')
        files[a['path']] = raw.decode('utf-8')
        path_ids[a['path']] = aid
    return task, snapshot, files, path_ids


def to_specialist(contract, task_id, snapshot, path_ids):
    def evidence(e):
        return [{'asset_id': path_ids[e['path']], 'locator': e['locator']}]
    objects = [{'object_id': o['id'], 'native_id': o['native_id'], 'kind': o['kind'], 'name': o['name'],
                'evidence': evidence(o['evidence']), 'source_details': o['details'],
                'grain': {'status': 'unknown', 'description': 'Source declarations do not prove physical or business grain.'}}
               for o in contract['objects']]
    file_objects = {}
    rules = []
    for expression in contract['expressions']:
        if not expression['text'].strip():
            continue
        owner = expression['object_id']
        path = expression['evidence']['path']
        if owner is None:
            if path not in file_objects:
                identity = contract['source'] + ':artifact:' + sha(path)[:24]
                file_objects[path] = identity
                objects.append({'object_id': identity, 'native_id': None, 'kind': 'source_artifact', 'name': path,
                                'evidence': evidence(expression['evidence']),
                                'grain': {'status': 'unknown', 'description': 'Unbound source expression.'}})
            owner = file_objects[path]
        refs = sorted({d['target'] for d in contract['dependencies'] if d['source_id'] == expression['object_id']})
        rules.append({'rule_id': expression['id'], 'kind': expression['details'].get('expression_kind', 'source_expression'),
                      'language': expression['language'], 'expression': expression['text'], 'output_object_id': owner,
                      'source_details': copy.deepcopy(expression['details']),
                      **({'source_occurrence_id': expression['occurrence_id']} if 'occurrence_id' in expression else {}),
                      'input_refs': [{'reference': r, 'status': 'unresolved'} for r in refs],
                      'context': {'evaluation_grain': 'unknown', 'filters': [], 'security': 'unknown'},
                      'evidence': evidence(expression['evidence']),
                      'placement_candidate': {'destination': 'unresolved', 'rationale': 'Requires scoped warehouse and semantic review.'}})
    return {'schema_version': 1, 'task_id': task_id, 'source_snapshot_sha256': snapshot,
            'asset_coverage': [{'asset_id': path_ids[f['path']], 'status': f['status'],
                               'reason': f['reason'] or 'Bounded adapter coverage; export completeness and business interpretation are separate.'}
                              for f in contract['source_files']],
            'objects': objects, 'rules': rules,
            'unresolved_references': [{'reference': ref, 'reason': 'Native reference retained; physical binding requires catalogue and scope reconciliation.'}
                                      for ref in sorted({d['target'] for d in contract['dependencies']})],
            'gaps': contract['gaps'] + [{'code': 'source.export_completeness_unverified', 'message': 'Independent source inventory and native validation still required.'}],
            'source_adapter_contract': contract}


def extract(plan_path, task_id):
    task, snapshot, files, path_ids = load_task(plan_path, task_id)
    result = to_specialist(parse(task['source_type'], files), task_id, snapshot, path_ids)
    if 'specialist_profile' in task:
        # Bind this candidate to the planned instructions, not to an agent invocation.
        result['specialist_profile_sha256'] = task['specialist_profile']['sha256']
    if task['source_type'] == 'looker':
        from looker_source import is_looker_dashboard, parse_dashboard
        dashboards = {}
        for path, text in files.items():
            if not path.endswith('.json'):
                continue
            try:
                data = read_json(text)
            except ValueError:
                continue
            if is_looker_dashboard(data):
                dashboards[path_ids[path]] = parse_dashboard(data)
        result['dashboard_contracts'] = dashboards
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        output = a.output.absolute()
        plan_path = a.plan.resolve(strict=True)
        plan = read_file(plan_path)
        inv = read_file(inside(plan_path.parent, plan['inventory_path']))
        root = Path(inv['repository']['root']).resolve(strict=True)
        if output == root or root in output.parents:
            raise ValueError('source.output_inside_input')
        with new_json_output(output) as write:
            result = extract(a.plan, a.task)
            write(result)
        print(json.dumps({'task_id': a.task, 'objects': len(result['objects']), 'rules': len(result['rules']), 'status': 'requires_review'}))
        return 0
    except (OSError, ValueError, KeyError, UnicodeError, ImportError):
        print('Source extraction failed: check the pinned task scope, input format and dependencies.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
