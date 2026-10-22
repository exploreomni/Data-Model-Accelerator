"""Optional expected-design scope, separate from proposals and approvals.

``record`` accepts schema_version, sources, objects, consumers and assignments.
Observations are cumulative: replacement requests cannot erase known inventory.
Local bytes and repository file names are independently checked; parser results,
external inventory completeness and reviewer attribution remain supplied claims.
This module never executes source code, approves a design or requires a layer.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import stat
import unicodedata

from ae_common import hash_json, require, safe_relative
from engagement_stages import fields, identifier, ids, text, SHA
from review_assurance import load_document

MAX_ROWS = 20000
MAX_FILES = 20000
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ENTRIES = 80000
MAX_DEPTH = 48
MAX_STRUCTURE_DEPTH = 48
MAX_NODES = 1000000
QUALIFICATION = ('Coverage of the supplied, bounded source inventory only. File hashes establish local '
                 'integrity, not authenticated provenance; parser results, external completeness and '
                 'review attribution are host-declared. Coverage is not semantic correctness, design '
                 'approval, execution evidence or business acceptance.')


def _safe(value):
    import guided_workflow as guided
    # Coverage inventories are metadata, not parser input packets. Keep their
    # own node bound so large exact inventories need not be copied or truncated.
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop(); count += 1
        require(count <= MAX_NODES and depth <= MAX_STRUCTURE_DEPTH, 'Design coverage structure exceeds its bounded scope')
        if isinstance(item, dict):
            require(all(type(k) is str for k in item), 'Coverage keys must be strings')
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
        else:
            require(item is None or type(item) in (str, bool, int, float), 'Coverage must contain JSON values')
            require(type(item) is not float or math.isfinite(item), 'Coverage numbers must be finite')
    guided._secrets(value)
    require(len(guided._bytes(value)) <= guided.MAX_JSON_BYTES, 'Design coverage exceeds 16 MiB; partition the engagement')


def _rows(value, name):
    require(type(value) is list and len(value) <= MAX_ROWS and all(type(r) is dict for r in value),
            name + ' must be a bounded object list')
    ids([r.get('id') for r in value])
    return value


def _version(value):
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1,
            'Unsupported design coverage schema')


def _relative(value):
    import guided_workflow as guided
    from plan_specialists import IGNORED_DIRS
    path = safe_relative(value)
    require(not any(p.lower() in guided.SECRET_FILES or p.lower().startswith('.env')
                    or p in IGNORED_DIRS
                    or guided.SECRET_PATH.search(p) or Path(p).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}
                    for p in Path(path).parts), 'Credential files cannot be coverage inputs')
    return path


def _root(value):
    import guided_workflow as guided
    require(type(value) is str and Path(value).is_absolute(), 'Source root must be explicitly supplied and absolute')
    path = guided._path(value)
    require(not any(p.name.lower() in guided.SECRET_FILES or p.name.lower().startswith('.env')
                    or guided.SECRET_PATH.search(p.name) for p in (path, *path.parents)),
            'Credential directories cannot be source roots')
    return path


def _validate(request):
    fields(request, {'schema_version', 'sources', 'objects', 'consumers', 'assignments'})
    _version(request); _safe(request)
    sources = {r['id']: r for r in _rows(request['sources'], 'sources')}
    objects = {r['id']: r for r in _rows(request['objects'], 'objects')}
    consumers = {r['id']: r for r in _rows(request['consumers'], 'consumers')}
    namespaces, native = set(), set()
    file_count = 0
    for source in sources.values():
        fields(source, {'id', 'namespace', 'role', 'kind', 'status', 'domain_ids', 'inventory'}, {'root'})
        text(source['namespace']); text(source['role']); ids(source['domain_ids'])
        require(source['namespace'] not in namespaces, 'Duplicate source namespace'); namespaces.add(source['namespace'])
        require(source['kind'] in {'repository', 'external_inventory'} and source['status'] in
                {'available', 'missing', 'unavailable'}, 'Invalid source status or kind')
        require(source['status'] != 'available' or 'root' in source, 'Available input needs an explicit source root')
        if 'root' in source:
            # Syntax only on reload: inaccessible roots must become visible gaps.
            require(type(source['root']) is str and Path(source['root']).is_absolute(), 'Invalid source root')
        inv = source['inventory']
        fields(inv, {'status', 'reference', 'files'}); text(inv['reference'])
        require(inv['status'] in {'complete', 'partial', 'not_supplied'}, 'Invalid inventory status')
        require(type(inv['files']) is list and len(inv['files']) <= MAX_FILES, 'File inventory exceeds the 20,000-file bound')
        file_count += len(inv['files'])
        require(file_count <= MAX_FILES, 'Combined source file inventory exceeds the 20,000-file bound')
        paths = set()
        for item in inv['files']:
            fields(item, {'path', 'sha256', 'status', 'object_ids'})
            _relative(item['path'])
            normalized = unicodedata.normalize('NFC', item['path']).casefold()
            require(normalized not in paths, 'Duplicate or ambiguous inventory path'); paths.add(normalized)
            require(item['status'] in {'parsed', 'partial', 'unsupported', 'unreadable'}, 'Invalid file parsing status')
            require(item['sha256'] is None or (type(item['sha256']) is str and SHA.fullmatch(item['sha256'])), 'Invalid source hash')
            require(item['sha256'] is not None or item['status'] == 'unreadable', 'Readable evidence needs its declared hash')
            ids(item['object_ids'])  # Unknown IDs are coverage gaps, not silently discarded.
    for obj in objects.values():
        fields(obj, {'id', 'source_id', 'native_id', 'kind', 'status', 'domain_ids', 'evidence_paths', 'depends_on'})
        identifier(obj['source_id']); text(obj['native_id']); ids(obj['domain_ids'])
        require(obj['source_id'] in sources, 'Object has no declared source')
        identity = (obj['source_id'], obj['native_id'])
        require(identity not in native, 'Duplicate native source object identity'); native.add(identity)
        require(obj['kind'] in {'table', 'view', 'model', 'report', 'metric', 'interface', 'other'}
                and obj['status'] in {'parsed', 'partial', 'unsupported'}, 'Invalid object observation')
        require(type(obj['evidence_paths']) is list and len(set(obj['evidence_paths'])) == len(obj['evidence_paths']), 'Invalid object evidence paths')
        for path in obj['evidence_paths']: _relative(path)
        require(type(obj['depends_on']) is list and len(obj['depends_on']) <= MAX_ROWS, 'Invalid dependency references')
        for dep in obj['depends_on']:
            fields(dep, {'reference'}, {'object_id'}); text(dep['reference'])
            if 'object_id' in dep: identifier(dep['object_id'])
    for consumer in consumers.values():
        fields(consumer, {'id', 'source_id', 'object_ids', 'domain_ids', 'evidence_paths', 'description'})
        require(consumer['source_id'] in sources, 'Consumer has no declared source')
        ids(consumer['object_ids']); ids(consumer['domain_ids']); text(consumer['description'])
        require(type(consumer['evidence_paths']) is list and len(set(consumer['evidence_paths'])) == len(consumer['evidence_paths']), 'Invalid consumer evidence paths')
        for path in consumer['evidence_paths']: _relative(path)
    for assignment in _rows(request['assignments'], 'assignments'):
        fields(assignment, {'id', 'object_ids', 'consumer_ids', 'model_ids', 'kind', 'reason'}, {'review'})
        ids(assignment['object_ids'], objects); ids(assignment['consumer_ids'], consumers); ids(assignment['model_ids'])
        require(assignment['object_ids'] or assignment['consumer_ids'], 'Assignment needs an observed scope')
        require(assignment['kind'] in {'implementation', 'interface', 'excluded'}, 'Invalid assignment kind')
        require(bool(assignment['model_ids']) == (assignment['kind'] != 'excluded'), 'Only exclusions may have no target')
        text(assignment['reason'])
        if 'review' in assignment:
            fields(assignment['review'], {'reviewer', 'reference'})
            text(assignment['review']['reviewer']); text(assignment['review']['reference'])
        require(assignment['kind'] != 'excluded' or 'review' in assignment, 'Exclusion requires explicit host-attributed review')


def _models(state):
    return {m['id']: m for m in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def _domain_models(state, domains):
    labels = {d.casefold() for d in domains}
    shared = set()
    for domain in (state.get('workflow', {}).get('domain_journey') or {}).get('domains', []):
        if domain['id'] in domains:
            labels.add(domain['name'].casefold()); shared.update(domain.get('shared_dependency_ids', []))
    return {m['id'] for m in _models(state).values() if m.get('domain', '').casefold() in labels} | shared


def _associations(request):
    result = {}
    objects = {r['id']: r for r in request['objects']}
    consumers = {r['id']: r for r in request['consumers']}
    for assignment in request['assignments']:
        for key in assignment['model_ids']:
            scope = result.setdefault(key, {'object_ids': [], 'consumer_ids': [], 'source_ids': []})
            scope['object_ids'] = sorted(set(scope['object_ids']) | set(assignment['object_ids']))
            scope['consumer_ids'] = sorted(set(scope['consumer_ids']) | set(assignment['consumer_ids']))
            scope['source_ids'] = sorted(set(scope['source_ids']) | {objects[x]['source_id'] for x in assignment['object_ids']}
                                         | {consumers[x]['source_id'] for x in assignment['consumer_ids']})
    return result


def _ledger(state):
    value = state.get('workflow', {}).get('design_coverage')
    if value is not None:
        fields(value, {'schema_version', 'document', 'prior_scope'}); _version(value)
        require(type(value['prior_scope']) is dict, 'Invalid historical coverage scope')
        for key, scope in value['prior_scope'].items():
            identifier(key); fields(scope, {'object_ids', 'consumer_ids', 'source_ids'})
            for values in scope.values(): ids(values)
    return value


def load(state):
    """Return the private, structurally validated snapshot, without changing state.

    Source freshness is reported by summarize, not falsely asserted by loading.
    Absolute roots and evidence paths are intentionally private to host helpers.
    """
    value = _ledger(state)
    if value is None: return None
    doc = load_document(value['document'])
    fields(doc, {'schema_version', 'kind', 'request', 'omitted', 'request_sha256'})
    _version(doc); require(doc['kind'] == 'design_coverage', 'Wrong coverage evidence kind')
    require(doc['request_sha256'] == hash_json(doc['request']), 'Coverage request changed')
    _validate(doc['request']); fields(doc['omitted'], {'sources', 'objects', 'consumers', 'files'})
    for kind in ('sources', 'objects', 'consumers'):
        ids(doc['omitted'][kind], {r['id'] for r in doc['request'][kind]})
    require(type(doc['omitted']['files']) is dict, 'Invalid omitted file inventory')
    for source_id, paths in doc['omitted']['files'].items():
        require(source_id in {r['id'] for r in doc['request']['sources']} and type(paths) is list, 'Invalid omitted source files')
        for path in paths: _relative(path)
    _safe(doc)
    return doc


def record(state, document, run_dir):
    """Record a full replacement proposal while retaining omitted observations."""
    import guided_workflow as guided
    require(type(state.get('workflow')) is dict, 'Adopt stages before recording coverage')
    _validate(document)
    previous = load(state)
    request = copy.deepcopy(document)
    omitted = {'sources': [], 'objects': [], 'consumers': [], 'files': {}}
    if previous:
        for kind in ('sources', 'objects', 'consumers'):
            incoming = {r['id']: r for r in request[kind]}
            for old in previous['request'][kind]:
                if old['id'] not in incoming:
                    request[kind].append(copy.deepcopy(old)); omitted[kind].append(old['id'])
                else:
                    keys = ('namespace', 'kind') if kind == 'sources' else (('source_id', 'native_id') if kind == 'objects' else ('source_id',))
                    require(all(old[k] == incoming[old['id']][k] for k in keys), 'Stable coverage identity cannot be reassigned')
            if kind == 'sources':
                old_sources = {r['id']: r for r in previous['request']['sources']}
                for source in request['sources']:
                    old_files = old_sources.get(source['id'], {}).get('inventory', {}).get('files', [])
                    paths = {f['path'] for f in source['inventory']['files']}
                    missing = [f for f in old_files if f['path'] not in paths]
                    if missing:
                        source['inventory']['files'].extend(copy.deepcopy(missing))
                        omitted['files'][source['id']] = [f['path'] for f in missing]
    _validate(request)
    run = guided._path(run_dir)
    folder = run / 'design-coverage'
    primary = state.get('inputs', {}).get('source', {}).get('path')
    if primary:
        from source_roots import ensure_output
        ensure_output(state, run); ensure_output(state, folder)
    for source in request['sources']:
        if 'root' in source:
            root = _root(source['root']); guided._outside(run, root); guided._outside(folder, root)
    # Capture the independent repository filename denominator in the immutable
    # revision. Removing an unlisted file later cannot erase this observation.
    from source_adapters.filesystem import read_assigned
    budget = 0
    for source in request['sources']:
        if source['status'] != 'available' or source['kind'] != 'repository': continue
        root = _root(source['root'])
        if not root.is_dir(): continue
        discovered, problems = _scan_paths(root)
        if problems:
            source['inventory']['status'] = 'partial'
        supplied = {f['path'] for f in source['inventory']['files']}
        for path in sorted(discovered - supplied):
            digest = None
            try:
                require(budget < MAX_TOTAL_BYTES, 'Coverage byte bound reached')
                raw = read_assigned(root, _relative(path)); budget += len(raw)
                require(budget <= MAX_TOTAL_BYTES, 'Coverage byte bound reached')
                digest = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError): pass
            source['inventory']['files'].append({'path': path, 'sha256': digest,
                'status': 'unsupported' if digest else 'unreadable', 'object_ids': []})
    _validate(request)
    # Store only observations and hashes, never source bytes or parser excerpts.
    doc = {'schema_version': 1, 'kind': 'design_coverage', 'request': request,
           'omitted': omitted, 'request_sha256': hash_json(request)}
    _safe(doc)
    require(not folder.is_symlink(), 'Coverage output cannot be a symlink')
    folder.mkdir(exist_ok=True)
    raw = guided._bytes(doc); digest = hashlib.sha256(raw).hexdigest()
    ref = {'path': str(folder / (digest + '.json')), 'sha256': digest, 'bytes': len(raw)}
    if Path(ref['path']).exists(): require(load_document(ref) == doc, 'Coverage evidence differs')
    else: guided._atomic_write(Path(ref['path']), raw, replace=False)
    prior = copy.deepcopy((_ledger(state) or {}).get('prior_scope', {}))
    for model, scope in _associations(request).items():
        old = prior.setdefault(model, {'object_ids': [], 'consumer_ids': [], 'source_ids': []})
        for key in old: old[key] = sorted(set(old[key]) | set(scope[key]))
    state['workflow']['design_coverage'] = {'schema_version': 1, 'document': ref, 'prior_scope': prior}
    return summarize(state)


def _scan_paths(root):
    """Bounded, descriptor-relative filename inventory; never follow symlinks."""
    from plan_specialists import IGNORED_DIRS, ADMIN_NAMES, is_secret
    from source_adapters.filesystem import _open_directory
    found, problems, entries = set(), [], 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    def walk(fd, prefix='', depth=0):
        nonlocal entries
        if depth >= MAX_DEPTH:
            problems.append('inventory_depth_limit'); return
        names = []
        with os.scandir(fd) as iterator:
            for entry in iterator:
                entries += 1
                if entries > MAX_ENTRIES:
                    problems.append('inventory_entry_limit'); return
                names.append(entry.name)
        for name in sorted(names):
            if len(found) > MAX_FILES or entries > MAX_ENTRIES:
                return
            path = Path(name)
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    problems.append('inventory_symlink'); continue
                if stat.S_ISDIR(info.st_mode):
                    if name in IGNORED_DIRS or is_secret(path): continue
                    child = os.open(name, flags, dir_fd=fd)
                    try: walk(child, prefix + name + '/', depth + 1)
                    finally: os.close(child)
                elif name.lower() not in ADMIN_NAMES and not is_secret(path):
                    found.add(prefix + name)
                    if len(found) > MAX_FILES: problems.append('inventory_limit')
            except OSError:
                problems.append('inventory_unreadable')
    fd, _ = _open_directory(root)
    try:
        try: walk(fd)
        except OSError: problems.append('inventory_unreadable')
    finally: os.close(fd)
    return found, problems


def _observe(source, budget):
    """One bounded freshness pass per source per operation; no persistent cache."""
    from source_adapters.filesystem import read_assigned
    result = {'files': {}, 'extra_files': [], 'problems': []}
    if source['status'] != 'available':
        result['problems'].append('source_missing'); return result
    try:
        root = _root(source['root'])
        require(root.is_dir(), 'Missing source root')
        if source['kind'] == 'repository':
            found, problems = _scan_paths(root)
            result['extra_files'] = sorted(found - {f['path'] for f in source['inventory']['files']})
            result['problems'].extend(problems)
        for item in source['inventory']['files']:
            try:
                if budget['bytes'] >= MAX_TOTAL_BYTES: raise ValueError('source.byte_limit')
                raw = read_assigned(root, _relative(item['path']))
                budget['bytes'] += len(raw)
                if budget['bytes'] > MAX_TOTAL_BYTES: raise ValueError('source.byte_limit')
                result['files'][item['path']] = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError): result['files'][item['path']] = None
    except (OSError, ValueError): result['problems'].append('source_unavailable')
    return result


def _evaluate(state, doc):
    request = doc['request']; models = _models(state)
    sources = {r['id']: r for r in request['sources']}
    objects = {r['id']: r for r in request['objects']}
    consumers = {r['id']: r for r in request['consumers']}
    budget = {'bytes': 0}
    observed = {key: _observe(source, budget) for key, source in sources.items()}
    assignments = request['assignments']; findings = []
    prior = (_ledger(state) or {}).get('prior_scope', {})
    association = _associations(request)
    linked_rows = {'object': {}, 'consumer': {}}
    for assignment in assignments:
        for kind in linked_rows:
            for key in assignment[kind + '_ids']:
                linked_rows[kind].setdefault(key, []).append(assignment)
    files_by_source = {key: {f['path']: f for f in source['inventory']['files']} for key, source in sources.items()}

    def scope(kind, row):
        relevant = {model for model, binding in prior.items() if row['id'] in binding[kind + '_ids']}
        relevant.update(model for model, binding in association.items() if row['id'] in binding[kind + '_ids'])
        domains = set(row.get('domain_ids', []))
        # Known object/consumer associations are narrower than the source's
        # business domain. Unknown source scope still affects the full domain.
        if kind == 'source' or not relevant:
            relevant.update(_domain_models(state, domains))
        return sorted(relevant), sorted(domains)

    def add(code, message, kind, row):
        model_ids, domain_ids = scope(kind, row)
        findings.append({'code': code, 'message': message, 'model_ids': model_ids, 'domain_ids': domain_ids})

    def add_file(code, message, source, item):
        known = [objects[key] for key in item['object_ids'] if key in objects
                 and objects[key]['source_id'] == source['id'] and item['path'] in objects[key]['evidence_paths']]
        if known and len(known) == len(item['object_ids']):
            for obj in known: add(code, message, 'object', obj)
        else:
            add(code, message, 'source', source)

    if not sources:
        findings.append({'code': 'inventory_not_supplied', 'message': 'Expected source scope has not been supplied.',
                         'model_ids': [], 'domain_ids': []})

    for source in sources.values():
        inv = source['inventory']; obs = observed[source['id']]
        if source['id'] in doc['omitted']['sources']: add('source_omitted', 'A previously observed source was omitted.', 'source', source)
        for problem in obs['problems']: add(problem, 'Source inventory could not be fully and safely observed.', 'source', source)
        if obs['extra_files']: add('files_uninventoried', 'Repository files are absent from the supplied inventory.', 'source', source)
        if inv['status'] != 'complete' or not inv['files']:
            add('inventory_incomplete', 'A required source inventory is incomplete or not supplied.', 'source', source)
        for item in inv['files']:
            if item['path'] in doc['omitted']['files'].get(source['id'], []): add_file('file_omitted', 'A previously inventoried file was omitted.', source, item)
            if obs['files'].get(item['path']) is None: add_file('file_unreadable', 'An inventoried source file is unavailable or unreadable.', source, item)
            elif obs['files'][item['path']] != item['sha256']: add_file('source_stale', 'Source evidence differs from its recorded snapshot.', source, item)
            if item['status'] != 'parsed': add_file('file_partial', 'An inventoried file has partial, unsupported or failed extraction.', source, item)
            if not item['object_ids']: add('file_objects_unknown', 'An inventoried file has no object inventory.', 'source', source)
            for key in item['object_ids']:
                if key not in objects or objects[key]['source_id'] != source['id'] or item['path'] not in objects[key]['evidence_paths']:
                    add('inventory_object_missing', 'A file inventory reference has no matching observed object.', 'source', source)
    counts = {'sources': len(sources), 'files': sum(len(s['inventory']['files']) for s in sources.values()),
              'objects': len(objects), 'consumers': len(consumers),
              'assigned': 0, 'excluded': 0, 'unresolved': 0, 'interfaces': 0, 'findings': 0}
    row_status = {'object': {}, 'consumer': {}}
    for kind, rows in (('object', objects), ('consumer', consumers)):
        for row in rows.values():
            source = sources[row['source_id']]
            file_rows = files_by_source[source['id']]
            linked = linked_rows[kind].get(row['id'], [])
            excluded = [a for a in linked if a['kind'] == 'excluded']
            implemented = [a for a in linked if a['kind'] == 'implementation' and all(
                model in models and models[model].get('object_kind', 'model') == 'model' for model in a['model_ids'])]
            if excluded and len(linked) > len(excluded): add('assignment_conflict', 'Observed scope is both excluded and assigned.', kind, row)
            status = 'excluded' if excluded and len(linked) == len(excluded) else ('assigned' if implemented else 'unresolved')
            row_status[kind][row['id']] = status; counts[status] += 1
            if any(a['kind'] == 'interface' for a in linked): counts['interfaces'] += 1
            if row['id'] in doc['omitted'][kind + 's']: add('observation_omitted', 'A previously observed scope item was omitted.', kind, row)
            if status == 'unresolved': add('scope_unassigned', 'Observed scope has no implemented target or reviewed exclusion.', kind, row)
            for assignment in linked:
                if any(key not in models for key in assignment['model_ids']): add('target_missing', 'An assigned target is absent from the current design.', kind, row)
                if assignment['kind'] == 'implementation' and any(models.get(key, {}).get('object_kind') in {'source', 'interface'} for key in assignment['model_ids']):
                    add('interface_only', 'Source or interface nodes do not establish implementation coverage.', kind, row)
            if not row['evidence_paths'] or any(path not in file_rows for path in row['evidence_paths']):
                add('observation_evidence_missing', 'An observation has no matching inventoried evidence.', kind, row)
            if kind == 'object':
                if any(row['id'] not in file_rows.get(path, {}).get('object_ids', []) for path in row['evidence_paths']):
                    add('object_inventory_missing', 'An object is absent from its declared file inventory.', kind, row)
                if row['status'] != 'parsed' and status != 'excluded': add('object_partial', 'An observed object has incomplete or unsupported extraction.', kind, row)
                for dep in row['depends_on']:
                    if dep.get('object_id') not in objects:
                        add('dependency_unresolved', 'A source dependency reference remains unresolved.', kind, row)
            else:
                if not row['object_ids'] or any(key not in objects for key in row['object_ids']):
                    add('consumer_reference_unknown', 'A consumer requirement refers to unknown source scope.', kind, row)
                elif status == 'assigned' and any(row_status['object'].get(key) != 'assigned' for key in row['object_ids']):
                    add('consumer_objects_uncovered', 'A consumer requirement depends on source scope without implementation coverage.', kind, row)
    # Retain source dependency obligations independently of a proposed target
    # graph. Folding both objects into one model is legitimate; dropping a
    # known dependency between different target closures is still a gap.
    closures = {}
    def closure(model_ids):
        key = tuple(sorted(model_ids))
        if key not in closures:
            reached, pending = set(), list(key)
            while pending:
                model = pending.pop()
                if model not in reached:
                    reached.add(model)
                    pending.extend(models.get(model, {}).get('depends_on', []))
            closures[key] = reached
        return closures[key]
    def targets(kind, key):
        return {m for a in linked_rows[kind].get(key, []) if a['kind'] == 'implementation' for m in a['model_ids']}
    for obj in objects.values():
        if row_status['object'][obj['id']] != 'assigned': continue
        reached = closure(targets('object', obj['id']))
        for dep in obj['depends_on']:
            key = dep.get('object_id')
            if key in objects and row_status['object'][key] != 'assigned':
                add('dependency_uncovered', 'An assigned object depends on source scope without implementation coverage.', 'object', obj)
            elif key in objects and not (targets('object', key) & reached):
                add('dependency_target_missing', 'A known source dependency has no corresponding target dependency path.', 'object', obj)
    for consumer in consumers.values():
        if row_status['consumer'][consumer['id']] != 'assigned': continue
        reached = closure(targets('consumer', consumer['id']))
        if any(key in objects and not (targets('object', key) & reached) for key in consumer['object_ids']):
            add('consumer_target_missing', 'A consumer target has no dependency path to its required source scope.', 'consumer', consumer)
    # Duplicate codes across files remain countable findings but never expose paths.
    counts['findings'] = len(findings)
    return counts, findings, observed, row_status


def _selected(selected):
    if selected is None: return None
    values = sorted(set(selected)); ids(values); return set(values)


def summarize(state, selected=None):
    allowed = _selected(selected)
    empty = {'sources': 0, 'files': 0, 'objects': 0, 'consumers': 0, 'assigned': 0, 'excluded': 0, 'unresolved': 0, 'interfaces': 0, 'findings': 0}
    result = {'schema_version': 1, 'status': 'unassessed', 'counts': empty, 'findings': [], 'qualification': QUALIFICATION}
    if state.get('workflow', {}).get('design_coverage') is None: return result
    try:
        doc = load(state); counts, findings, _, row_status = _evaluate(state, doc)
        if allowed is not None:
            selected_domains = {m.get('domain', '').casefold() for key, m in _models(state).items() if key in allowed}
            domain_ids = {d['id'] for d in (state.get('workflow', {}).get('domain_journey') or {}).get('domains', [])
                          if d['name'].casefold() in selected_domains or d['id'].casefold() in selected_domains}
            domain_ids |= selected_domains
            findings = [{**f, 'model_ids': sorted(set(f['model_ids']) & allowed),
                         'domain_ids': [d for d in f['domain_ids'] if d in domain_ids]}
                        for f in findings if (set(f['model_ids']) & allowed or
                            (not f['model_ids'] and (not f['domain_ids'] or set(f['domain_ids']) & domain_ids)))] if allowed else []
            bindings = (_ledger(state) or {}).get('prior_scope', {})
            kept = {kind: {key for model, binding in bindings.items() if model in allowed for key in binding[kind + '_ids']}
                    for kind in ('source', 'object', 'consumer')}
            for kind in ('source', 'object', 'consumer'):
                associated = {key for binding in bindings.values() for key in binding[kind + '_ids']}
                kept[kind].update(r['id'] for r in doc['request'][kind + 's'] if r['id'] not in associated
                                 and _domain_models(state, r['domain_ids']) & allowed)
            counts = {**empty, 'sources': len(kept['source']), 'objects': len(kept['object']), 'consumers': len(kept['consumer']),
                      'files': sum(len(s['inventory']['files']) for s in doc['request']['sources'] if s['id'] in kept['source'])}
            for kind in ('object', 'consumer'):
                for key in kept[kind]:
                    if key in row_status[kind]: counts[row_status[kind][key]] += 1
            counts['interfaces'] = sum(1 for a in doc['request']['assignments'] if a['kind'] == 'interface' and set(a['model_ids']) & allowed)
        counts['findings'] = len(findings)
        result.update(status='partial' if findings else 'complete', counts=counts, findings=findings)
    except (OSError, ValueError, KeyError, TypeError):
        result.update(status='unavailable', findings=[{'code': 'coverage_unavailable', 'message': 'Coverage evidence is missing, changed or unsupported; re-register it.',
                                                      'model_ids': sorted(allowed) if allowed is not None else [], 'domain_ids': []}])
        result['counts']['findings'] = 1
    return result


def scope_bindings(state):
    """Pin only associated models, retaining old associations after removal."""
    if state.get('workflow', {}).get('design_coverage') is None: return {}
    value = _ledger(state)
    try:
        doc = load(state); _, findings, observed, _ = _evaluate(state, doc)
        result = {}
        for model, scope in value['prior_scope'].items():
            # Keep scoped observations and source metadata; unrelated object
            # changes in the same source do not stale this target's approval.
            rows = {kind: [r for r in doc['request'][kind + 's'] if r['id'] in scope[kind + '_ids']]
                    for kind in ('object', 'consumer')}
            paths = {source: {p for group in rows.values() for r in group if r['source_id'] == source for p in r['evidence_paths']}
                     for source in scope['source_ids']}
            source_pins = []
            for source in doc['request']['sources']:
                if source['id'] in paths:
                    current = observed[source['id']]
                    source_pins.append({'id': source['id'], 'namespace': source['namespace'], 'kind': source['kind'], 'status': source['status'],
                        'role': source['role'], 'domain_ids': source['domain_ids'],
                        'inventory_status': source['inventory']['status'], 'reference': source['inventory']['reference'],
                        'files': [f for f in source['inventory']['files'] if f['path'] in paths[source['id']]],
                        'observed': {p: current['files'].get(p) for p in sorted(paths[source['id']])},
                        'problems': current['problems'], 'extra_files': current['extra_files']})
            related = [a for a in doc['request']['assignments'] if set(a['object_ids']) & set(scope['object_ids'])
                       or set(a['consumer_ids']) & set(scope['consumer_ids'])]
            result[model] = hash_json({'version': 1, 'rows': rows, 'sources': source_pins, 'assignments': related,
                'omitted': {kind: sorted(set(doc['omitted'][kind + 's']) & set(scope[kind + '_ids'])) for kind in ('source', 'object', 'consumer')},
                'findings': [f for f in findings if model in f['model_ids']]})
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {model: hash_json({'version': 1, 'status': 'unavailable', 'scope': scope}) for model, scope in value['prior_scope'].items()}


def gaps(state, selected):
    """Reviewed-stage diagnostic only; callers keep provisional generation open."""
    summary = summarize(state, selected)
    return sorted(set('Design coverage: ' + f['message'] for f in summary['findings']))
