"""Conservative observations of retained legacy code, never a correctness score."""
import hashlib
from pathlib import Path
import re

from ae_common import require, safe_relative, _path

MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024


def inspect_task(state, task, artifact_root):
    from migration_context import task_contracts
    from migration_intent import _roles_for
    from deliverable_contract import entity_artifacts
    from source_roots import resolve
    from deployment_workflow import _stable_bytes
    contracts = {c['domain_id']: c for c in task_contracts(state, task['entity_ids'])
                 if c['intent']['structural_objective'] == 'refactor'}
    if not contracts or task['stage'] != 'implementation':
        return []
    root = _path(artifact_root)
    models = {e['id']: e for e in state['workflow']['design']['entities']}
    from migration_intent import _models
    by_model = {key: c for d, c in contracts.items() for key in _models(state, d)}
    mappings = entity_artifacts(state, task)
    observations, cache, total = [], {}, 0

    def read(path):
        nonlocal total
        path = _path(path)
        if path not in cache:
            size = path.stat().st_size
            require(size <= MAX_FILE and total + size <= MAX_TOTAL, 'Refactor observation byte budget exceeded')
            total += size
            cache[path] = _stable_bytes(path)
            require(len(cache[path]) <= MAX_FILE, 'Refactor observation byte budget exceeded')
        return cache[path]

    for key, outputs in mappings.items():
        if key not in by_model:
            continue
        model = models[key]; intent = by_model[key]['intent']
        refs = [p for p in model['source_paths'] if 'legacy_baseline' in _roles_for(state, intent, p)
                and 'raw_staging' not in _roles_for(state, intent, p)]
        legacy = {}
        for reference in refs:
            try:
                body = read(resolve(state, reference))
                legacy[reference] = hashlib.sha256(body).hexdigest()
            except (OSError, ValueError):
                observations.append({'model_id': key, 'code': 'legacy_evidence_unavailable', 'path': reference})
        names = {Path(p).stem for p in refs}
        for relative in outputs:
            if Path(relative).suffix.lower() not in {'.sql', '.sqlx', '.py'}:
                continue
            try:
                path = _path(root / safe_relative(relative)); require(root in path.parents, 'Output escaped artifact root')
                body = read(path); digest = hashlib.sha256(body).hexdigest()
                matching = sorted(p for p, pin in legacy.items() if pin == digest)
                if matching:
                    observations.append({'model_id': key, 'code': 'exact_legacy_copy', 'path': relative,
                                         'source_refs': matching, 'sha256': digest})
                    continue
                # Narrow, non-executing heuristic only. Complex SQL stays unproven.
                sql = body.decode('utf-8')
                sql = re.sub(r'/\*.*?\*/|--[^\n]*', '', sql, flags=re.S).strip().rstrip(';').strip()
                match = re.fullmatch(r"select\s+\*\s+from\s+\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", sql, re.I)
                if match and match[1] in names:
                    observations.append({'model_id': key, 'code': 'possible_legacy_wrapper', 'path': relative,
                                         'source_refs': sorted(refs), 'sha256': digest})
            except (OSError, ValueError, UnicodeError):
                observations.append({'model_id': key, 'code': 'candidate_observation_unavailable', 'path': relative})
    return observations


def summary(state, selected=None):
    wf = state.get('workflow') or {}
    if not wf.get('migration_intents'):
        return {'status': 'unassessed', 'findings': [], 'qualification': 'No migration intent configured.'}
    allowed = set(selected) if selected is not None else None
    findings = []
    inspected_tasks = 0
    for task in wf.get('tasks', []):
        if task['stage'] != 'implementation' or (allowed is not None and not set(task['entity_ids']) & allowed):
            continue
        inspected_tasks += 1
        try:
            findings.extend(r for r in inspect_task(state, task, wf.get('artifact_root'))
                            if allowed is None or r['model_id'] in allowed)
        except (ValueError, OSError, TypeError, KeyError):
            findings.extend({'model_id': key, 'code': 'candidate_observation_unavailable'} for key in task['entity_ids'] if allowed is None or key in allowed)
    return {'status': 'observations' if findings else 'no_retention_detected' if inspected_tasks else 'unassessed',
            'inspected_task_count': inspected_tasks, 'findings': findings,
            'qualification': 'Bounded exact-byte and simple-wrapper checks only. Absence of a match does not establish refactoring, SQL accuracy or behavioral parity.'}


def require_complete(state, selected=None):
    from migration_intent import summary as intent_summary
    value = summary(state, selected)
    domains = {r['domain_id']: r for r in intent_summary(state)['domains']}
    exceptions = set()
    for domain, row in domains.items():
        record = state['workflow']['migration_intents'][domain]
        if row.get('refactor_complete') and not any(o.get('kind') == 'eliminate_legacy_dependencies' for o in record['intent']['objectives']):
            exceptions.update(e['model_id'] for e in record.get('assessment', {}).get('request', {}).get('legacy_exceptions', []))
    unresolved = [r for r in value['findings'] if r['model_id'] not in exceptions
                  or r['code'] in {'legacy_evidence_unavailable', 'candidate_observation_unavailable'}]
    require(not unresolved, 'Refactor candidate retains legacy code or has unverified retention: '
            + ', '.join(sorted({r['model_id'] for r in unresolved}))
            + '. Resolve the design or review an explicit retained-legacy exception; provisional files remain available.')
    return value


def require_promotion(state, action, mode):
    """A production refactor claim cannot inherit file-only completion evidence."""
    if action != 'promote' or mode != 'live':
        return
    from migration_intent import require_complete as require_intent
    require_intent(state)
    require_complete(state)
