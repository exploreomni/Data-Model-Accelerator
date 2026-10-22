"""Explicit read-only repository roots; no relocation, Git calls or source execution.

Unqualified paths retain the original repository. Named references are opt-in
``@sources/<id>/<relative-path>``. Registration is additive and names cannot be
rebound. Byte observation is independent of host-declared revision metadata.
"""
import copy
import hashlib
from pathlib import Path
import re

from ae_common import hash_json, require, safe_relative

MAX_ROOTS = 16  # Includes the original primary root.
PREFIX = '@sources/'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_REVISION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def _rows(state):
    source = state['inputs']['source']
    registered = source.get('roots', [])
    require(type(registered) is list and len(registered) < MAX_ROOTS, 'Too many registered source roots')
    rows = [{'id': 'primary', 'path': source['path']}, *registered]
    seen = set()
    for row in rows:
        require(type(row) is dict and {'id', 'path'} <= set(row) <= {'id', 'path', 'revision', 'dirty'}, 'Invalid registered source root')
        require(type(row['id']) is str and _ID.fullmatch(row['id']) and row['id'] not in seen, 'Invalid or duplicate source root ID')
        require(type(row['path']) is str and Path(row['path']).is_absolute(), 'Source roots must be absolute')
        require('revision' not in row or (type(row['revision']) is str and _REVISION.fullmatch(row['revision'])), 'Revision must be a bounded opaque ID, not a path or expression')
        require('dirty' not in row or row['dirty'] in ('clean', 'dirty', 'unknown'), 'Invalid host-declared dirty state')
        seen.add(row['id'])
    return rows


def approved_roots(state):
    """Private host API, including primary; does not authorize disclosure."""
    import guided_workflow as guided
    return tuple(guided._path(row['path']) for row in _rows(state))


def ensure_output(state, path):
    """Reject output roots/files overlapping any source, including ancestors."""
    import guided_workflow as guided
    output = guided._path(path)
    for source in approved_roots(state):
        require(output != source and source not in output.parents and output not in source.parents,
                'Output must be separate from every registered read-only source root')
    return output


def register(state, request, run_dir):
    import guided_workflow as guided
    from engagement_stages import fields
    fields(request, {'schema_version', 'roots'})
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported source registry schema')
    require(type(request['roots']) is list and 0 < len(request['roots']) < MAX_ROOTS, 'Supply one to 15 named source roots')
    guided._secrets(request)
    previous = _rows(state)
    incoming = {row['id']: copy.deepcopy(row) for row in previous[1:]}
    ids = set()
    for row in request['roots']:
        fields(row, {'id', 'path'}, {'revision', 'dirty'})
        key = row['id']
        require(type(key) is str and _ID.fullmatch(key) and key != 'primary' and key not in ids, 'Invalid or duplicate named source root')
        ids.add(key)
        require(type(row['path']) is str and Path(row['path']).is_absolute(), 'Supply an explicit absolute source root')
        path = guided._path(row['path'])
        require(path.is_dir(), 'Registered source root must be an existing directory')
        require(not any(p.name.lower() in guided.SECRET_FILES or p.name.lower().startswith('.env')
                        or guided.SECRET_PATH.search(p.name) for p in (path, *path.parents)), 'Credential directories cannot be source roots')
        if 'revision' in row:
            require(type(row['revision']) is str and _REVISION.fullmatch(row['revision']), 'Revision must be a bounded opaque ID, not a path or expression')
        if 'dirty' in row:
            require(row['dirty'] in ('clean', 'dirty', 'unknown'), 'Invalid host-declared dirty state')
        normalized = {**copy.deepcopy(row), 'path': str(path)}
        if key in incoming:
            require(incoming[key]['path'] == normalized['path'], 'Source root IDs cannot be rebound; add a new ID')
        incoming[key] = normalized
    require(len(incoming) < MAX_ROOTS, 'Combined source roots exceed the bound')
    primary = guided._path(state['inputs']['source']['path'])
    require(not (primary / '@sources').exists() and not (primary / '@sources').is_symlink(),
            'Named source namespace collides with an existing primary path')
    roots = [primary, *(guided._path(row['path']) for row in incoming.values())]
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(roots) for b in roots[i + 1:]), 'Source roots cannot overlap or alias each other')
    guarded = [guided._path(run_dir)]
    workflow = state.get('workflow') or {}
    if workflow.get('artifact_root'):
        guarded.append(guided._path(workflow['artifact_root']))
    for attempt in state.get('operations', {}).get('attempts', []):
        if attempt.get('artifact_root'):
            guarded.append(guided._path(attempt['artifact_root']))
    require(all(output != root and root not in output.parents and output not in root.parents
                for root in roots for output in guarded), 'Source roots cannot overlap existing run or artifact output locations')
    result = sorted(incoming.values(), key=lambda row: row['id'])
    source = state['inputs']['source']
    if source.get('roots') != result:
        source['roots'] = result
        source['roots_revision'] = source.get('roots_revision', 0) + 1
    return public_summary(state)


def split_reference(state, reference):
    safe_relative(reference)
    if reference.startswith(PREFIX) and state['inputs']['source'].get('roots'):
        parts = reference.split('/', 2)
        require(len(parts) == 3 and parts[1] != 'primary', 'Named source reference needs a root ID and file path')
        row = next((row for row in _rows(state)[1:] if row['id'] == parts[1]), None)
        require(row is not None, 'Unknown named source root')
        return Path(row['path']), safe_relative(parts[2])
    return Path(state['inputs']['source']['path']), reference


def resolve(state, reference):
    """Resolve one exact private input path; no fallback between repositories."""
    import guided_workflow as guided
    root, relative = split_reference(state, reference)
    root = guided._path(root)
    path = guided._path(root / relative)
    require(root in path.parents, 'Source reference escapes its registered root')
    require(not any(part.lower() in guided.SECRET_FILES or part.lower().startswith('.env')
                    or guided.SECRET_PATH.search(part) or Path(part).suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}
                    for part in Path(relative).parts), 'Credential files cannot be source references')
    return path


def reference_bindings(state, references):
    """Pin identity/declared revision only for named roots actually referenced."""
    if not state['inputs']['source'].get('roots'):
        return {}
    selected = set()
    for reference in references:
        if reference.startswith(PREFIX):
            split_reference(state, reference)
            selected.add(reference.split('/', 2)[1])
    return {row['id']: hash_json(row) for row in _rows(state) if row['id'] in selected}


def capture(state, references):
    """Exact content hashes via descriptor-relative, bounded no-follow reads."""
    from source_adapters.filesystem import read_assigned
    from authoring_evidence import capture as legacy_capture
    if not state['inputs']['source'].get('roots'):
        return legacy_capture(state['inputs']['source']['path'], references)
    result = {}
    require(type(references) is list and len(references) <= 512 and len(set(references)) == len(references), 'Source work packet exceeds its bound')
    total = 0
    for reference in references:
        resolve(state, reference)
        if not reference.startswith(PREFIX):
            # Adding another repository must not narrow an unchanged primary
            # worker packet or change its existing fingerprint contract.
            result.update(legacy_capture(state['inputs']['source']['path'], [reference]))
            continue
        root, relative = split_reference(state, reference)
        raw = read_assigned(root, relative)
        total += len(raw)
        require(total <= 32 * 1024 * 1024, 'Source work packet exceeds 32 MiB; select a smaller scoped packet')
        result[reference] = hashlib.sha256(raw).hexdigest()
    return result


def observe(state, primary, assessor, framework, warehouse, options):
    """Reuse the bounded static collector for each root; no implicit Git scan."""
    source = state['inputs']['source']
    if not source.get('roots'):
        return primary  # Preserve the legacy fingerprint and readiness exactly.
    result = copy.deepcopy(primary)
    observations = {}
    all_complete = True
    for row in _rows(state):
        try:
            if row['id'] == 'primary':
                assessment = primary
            else:
                root = approved_roots({'inputs': {'source': {'path': row['path']}}})[0]
                require(root.is_dir(), 'Source root unavailable')
                assessment = assessor(str(root), framework, warehouse, **options)
            fingerprint = assessment['source_fingerprint']
            require(type(fingerprint) is dict and re.fullmatch(r'[a-f0-9]{64}', fingerprint.get('value', '')), 'Invalid source fingerprint')
            count = assessment.get('coverage', {}).get('scanned_files', 0)
            require(type(count) is int and count >= 0, 'Invalid file count')
            complete = fingerprint.get('complete') is True and assessment.get('coverage', {}).get('complete') is True
            observations[row['id']] = {'fingerprint': copy.deepcopy(fingerprint), 'file_count': count, 'complete': complete}
            if row['id'] != 'primary':
                def qualified(records):
                    rows = copy.deepcopy(records)
                    for item in rows:
                        if 'path' in item:
                            item['path'] = PREFIX + row['id'] + '/' + item['path']
                        if 'paths' in item:
                            item['paths'] = [PREFIX + row['id'] + '/' + path for path in item['paths']]
                    return rows
                # Retain per-root blockers and omission context instead of
                # reporting aggregate completeness from filenames alone.
                findings = qualified(assessment.get('findings', []))
                for finding in findings:
                    finding['id'] = 'source.' + row['id'] + '.' + finding['id']
                result.setdefault('findings', []).extend(findings)
                for category in ('gaps', 'exclusions'):
                    result['coverage'].setdefault(category, []).extend(qualified(assessment.get('coverage', {}).get(category, [])))
                if 'scanned_bytes' in assessment.get('coverage', {}):
                    result['coverage']['scanned_bytes'] = result['coverage'].get('scanned_bytes', 0) + assessment['coverage']['scanned_bytes']
                result.setdefault('detected_sources', []).extend(qualified(assessment.get('detected_sources', [])))
        except (OSError, ValueError):
            observations[row['id']] = {'fingerprint': None, 'file_count': 0, 'complete': False}
            complete = False
        all_complete = all_complete and complete
    source['root_observations'] = observations
    aggregate = {'algorithm': 'sha256', 'value': hash_json({'roots': _rows(state), 'observations': observations}),
                 'scope': 'bounded_registered_source_roots', 'complete': all_complete}
    result['source_fingerprint'] = aggregate
    result['coverage']['complete'] = all_complete
    result['coverage']['scanned_files'] = sum(row['file_count'] for row in observations.values())
    if not all_complete:
        result.setdefault('findings', []).append({'id': 'registered_source_incomplete', 'severity': 'blocker',
            'blocks': ['generation'], 'summary': 'A registered source has incomplete or unavailable bounded coverage.',
            'next_action': 'Restore the named root or provide a coherent bounded source scope; no source was moved or executed.'})
    return result


def public_summary(state):
    source = state.get('inputs', {}).get('source') or {}
    if not source.get('roots'):
        return None
    observed = source.get('root_observations', {})
    return {'schema_version': 1, 'registry_revision': source.get('roots_revision', 0), 'count': len(_rows(state)),
        'roots': [{'id': row['id'], 'revision': row.get('revision'), 'dirty': row.get('dirty', 'unknown'),
                   'revision_assurance': 'host_declared_not_git_verified',
                   'file_count': observed.get(row['id'], {}).get('file_count'),
                   'fingerprint': ({k: observed[row['id']]['fingerprint'][k] for k in ('algorithm', 'value', 'complete')
                                    if k in observed[row['id']]['fingerprint']}
                                   if observed.get(row['id'], {}).get('fingerprint') else None),
                   'coverage_complete': observed.get(row['id'], {}).get('complete', False)} for row in _rows(state)],
        'qualification': 'Bounded local byte observations only. Git revision and dirty state are not independently verified; no source code executes.'}
