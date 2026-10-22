"""Bounded, immutable storage for large logical schema-v1 engagement states.

This storage envelope is not a new engagement schema. Public workflow loaders
hydrate it before validation or use. It grants no review/execution authority.
"""
import copy
import hashlib
import re

INLINE_STATE_BYTES = 4 * 1024 * 1024
MAX_LOGICAL_BYTES = 128 * 1024 * 1024
MAX_COMPONENT_BYTES = 1024 * 1024
INLINE_VALUE_BYTES = 4096
MAX_REFERENCES = 20000
MAX_DEPTH = 64
MAX_NODES = 2000000
KIND = 'guided_engagement_index'
SHA = re.compile(r'[0-9a-f]{64}')


def _guided():
    import guided_workflow
    return guided_workflow


def _structure(value):
    guided = _guided()
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop(); count += 1
        guided._require(count <= MAX_NODES and depth <= MAX_DEPTH, 'Engagement logical structure exceeds its bounded storage scope')
        if isinstance(node, dict):
            guided._require(all(type(key) is str for key in node), 'Engagement keys must be strings')
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
        else:
            guided._require(node is None or type(node) in (str, int, float, bool), 'Engagement must contain JSON values')


def is_index(value):
    return type(value) is dict and value.get('kind') == KIND


def _index(value):
    guided = _guided()
    required = {'schema_version', 'kind', 'storage_version', 'engagement_id', 'revision',
                'state_sha256', 'logical_bytes', 'tree', 'index_sha256'}
    guided._require(type(value) is dict and set(value) == required and value['kind'] == KIND
                    and type(value['schema_version']) is int and value['schema_version'] == 1
                    and type(value['storage_version']) is int and value['storage_version'] == 1,
                    'Unsupported engagement storage index')
    guided._require(type(value['logical_bytes']) is int and 0 < value['logical_bytes'] <= MAX_LOGICAL_BYTES,
                    'Engagement logical size exceeds 128 MiB; explicitly partition the scope')
    guided._require(value['index_sha256'] == guided._digest({k: v for k, v in value.items() if k != 'index_sha256'}),
                    'Engagement storage index integrity differs')


def _object_path(run_dir, reference):
    guided = _guided()
    guided._require(type(reference) is dict and set(reference) == {'path', 'sha256', 'bytes'}
                    and type(reference['sha256']) is str and SHA.fullmatch(reference['sha256'])
                    and type(reference['bytes']) is int and 0 < reference['bytes'] <= MAX_COMPONENT_BYTES,
                    'Invalid engagement component reference')
    expected = 'state-store/objects/' + reference['sha256'] + '.json'
    guided._require(reference['path'] == expected, 'Engagement component path must match its immutable digest')
    return guided._path(guided._path(run_dir) / expected)


def _read_object(run_dir, reference):
    guided = _guided()
    path = _object_path(run_dir, reference)
    guided._require(path.stat().st_size == reference['bytes'], 'Engagement component size differs')
    value, digest = guided._json_with_hash(path)
    guided._require(digest == reference['sha256'], 'Engagement component integrity differs')
    _structure(value)
    return value


def encode(run_dir, state):
    """Write immutable components first; caller atomically publishes the head."""
    guided = _guided()
    _structure(state)
    payload = guided._bytes(state)
    guided._require(len(payload) <= MAX_LOGICAL_BYTES,
                    'Engagement logical size exceeds 128 MiB; explicitly partition the scope without discarding history')
    if len(payload) <= INLINE_STATE_BYTES:
        return payload
    root = guided._path(run_dir)
    folder = root / 'state-store'; guided._path(folder); folder.mkdir(exist_ok=True)
    objects = folder / 'objects'; guided._path(objects); objects.mkdir(exist_ok=True)
    references, written = 0, set()

    def blob(value, raw=None):
        nonlocal references
        raw = guided._bytes(value) if raw is None else raw
        guided._require(len(raw) <= MAX_COMPONENT_BYTES, 'Engagement component exceeds its bounded size')
        references += 1
        guided._require(references <= MAX_REFERENCES, 'Engagement component reference count exceeds its bound')
        digest = hashlib.sha256(raw).hexdigest()
        ref = {'path': 'state-store/objects/' + digest + '.json', 'sha256': digest, 'bytes': len(raw)}
        path = _object_path(root, ref)
        if digest not in written:
            if path.exists():
                _read_object(root, ref)
            else:
                guided._atomic_write(path, raw, replace=False)
            written.add(digest)
        return {'type': 'blob', 'reference': ref}

    def node(value):
        raw = guided._bytes(value)
        if len(raw) <= INLINE_VALUE_BYTES:
            return {'type': 'inline', 'value': value}
        if len(raw) <= MAX_COMPONENT_BYTES:
            return blob(value, raw)
        if isinstance(value, str):
            # JSON escaping uses at most six bytes per Unicode character.
            width = MAX_COMPONENT_BYTES // 8
            return {'type': 'string', 'parts': [blob(value[i:i + width]) for i in range(0, len(value), width)]}
        guided._require(type(value) in (dict, list), 'Oversized engagement scalar cannot be stored')
        mapping = type(value) is dict
        parts, group, size = [], {} if mapping else [], 3

        def flush():
            nonlocal group, size
            if group:
                parts.append({'type': 'chunk', 'node': blob(group)})
                group, size = {} if mapping else [], 3

        entries = sorted(value.items()) if mapping else enumerate(value)
        for key, child in entries:
            item_size = len(guided._bytes({key: child} if mapping else [child]))
            if item_size > MAX_COMPONENT_BYTES - 8:
                flush()
                part = {'type': 'item', 'node': node(child)}
                if mapping: part['key'] = key
                parts.append(part)
            else:
                if size + item_size > MAX_COMPONENT_BYTES - 8: flush()
                if mapping: group[key] = child
                else: group.append(child)
                size += item_size
        flush()
        return {'type': 'dict' if mapping else 'list', 'parts': parts}

    # Always separate workflow's direct components once compact storage starts.
    tree = {'type': 'dict', 'parts': []}
    for key, value in sorted(state.items()):
        if key == 'workflow' and type(value) is dict:
            child = {'type': 'dict', 'parts': [
                {'type': 'item', 'key': k, 'node': node(v)} for k, v in sorted(value.items())]}
        else:
            child = node(value)
        tree['parts'].append({'type': 'item', 'key': key, 'node': child})
    index = {'schema_version': 1, 'kind': KIND, 'storage_version': 1,
             'engagement_id': state['engagement_id'], 'revision': state['revision'],
             'state_sha256': state['state_sha256'], 'logical_bytes': len(payload), 'tree': tree}
    index['index_sha256'] = guided._digest(index)
    encoded = guided._bytes(index)
    guided._require(len(encoded) <= guided.MAX_JSON_BYTES, 'Engagement storage index exceeds 16 MiB; explicitly partition the scope')
    return encoded


def hydrate(run_dir, stored):
    """Decode only the typed index, never interpret marker-shaped user data."""
    if not is_index(stored):
        return stored
    guided = _guided(); _index(stored)
    budget, references, cache = 0, 0, {}

    def decode(node, depth=0):
        nonlocal budget, references
        guided._require(type(node) is dict and depth <= MAX_DEPTH, 'Invalid engagement storage tree')
        kind = node.get('type')
        if kind == 'inline':
            guided._require(set(node) == {'type', 'value'}, 'Invalid inline engagement value')
            raw = guided._bytes(node['value'])
            guided._require(len(raw) <= INLINE_VALUE_BYTES, 'Inline engagement value exceeds its bound')
            budget += len(raw)
            result = copy.deepcopy(node['value'])
        elif kind == 'blob':
            guided._require(set(node) == {'type', 'reference'}, 'Invalid engagement blob')
            ref = node['reference']; _object_path(run_dir, ref)
            references += 1; budget += ref['bytes']
            guided._require(references <= MAX_REFERENCES and budget <= MAX_LOGICAL_BYTES + MAX_REFERENCES * 8,
                            'Engagement expansion exceeds its bounded scope')
            if ref['sha256'] not in cache:
                cache[ref['sha256']] = (ref['bytes'], _read_object(run_dir, ref))
            size, value = cache[ref['sha256']]
            guided._require(size == ref['bytes'], 'Repeated engagement component size differs')
            result = copy.deepcopy(value)
        elif kind in ('dict', 'list', 'string'):
            guided._require(set(node) == {'type', 'parts'} and type(node['parts']) is list
                            and len(node['parts']) <= MAX_NODES, 'Invalid engagement container')
            result = {} if kind == 'dict' else []
            for part in node['parts']:
                if kind == 'string':
                    item = decode(part, depth + 1)
                    guided._require(type(item) is str, 'Invalid engagement string chunk')
                    result.append(item); continue
                guided._require(type(part) is dict, 'Invalid engagement container part')
                if part.get('type') == 'chunk':
                    guided._require(set(part) == {'type', 'node'}, 'Invalid engagement chunk')
                    item = decode(part['node'], depth + 1)
                    guided._require(type(item) is (dict if kind == 'dict' else list), 'Engagement chunk type differs')
                    if kind == 'dict':
                        guided._require(not set(result) & set(item), 'Duplicate engagement component key')
                        result.update(item)
                    else: result.extend(item)
                else:
                    guided._require(part.get('type') == 'item' and set(part) == ({'type', 'node', 'key'} if kind == 'dict' else {'type', 'node'}),
                                    'Invalid engagement component item')
                    item = decode(part['node'], depth + 1)
                    if kind == 'dict':
                        guided._require(type(part['key']) is str and part['key'] not in result, 'Duplicate engagement component key')
                        result[part['key']] = item
                    else: result.append(item)
            if kind == 'string': result = ''.join(result)
        else:
            raise ValueError('Unsupported engagement storage node')
        guided._require(budget <= MAX_LOGICAL_BYTES + MAX_REFERENCES * 8, 'Engagement expansion exceeds its bounded scope')
        return result

    state = decode(stored['tree']); _structure(state)
    guided._require(type(state) is dict and len(guided._bytes(state)) == stored['logical_bytes']
                    and all(state.get(k) == stored[k] for k in ('engagement_id', 'revision', 'state_sha256')),
                    'Hydrated engagement identity or logical size differs')
    return state


def load_revision(run_dir, revision):
    """Read a logical revision; evidence JSON pointers apply after hydration."""
    guided = _guided()
    guided._require(type(revision) is int and revision > 0, 'Invalid engagement revision number')
    root = guided._path(run_dir)
    return guided._validate_state(root, guided._json(root / 'revisions' / ('%06d.json' % revision)))


def storage_stats(run_dir):
    """Read storage accounting separately from logical state/freshness hashes."""
    guided = _guided(); root = guided._path(run_dir)
    stored = guided._json(root / 'state.json')
    state = guided._validate_state(root, stored)
    refs = []
    if is_index(stored):
        pending = [stored['tree']]
        while pending:
            node = pending.pop()
            if node['type'] == 'blob': refs.append(node['reference'])
            elif node['type'] in ('dict', 'list'):
                pending.extend(part['node'] for part in node['parts'])
            elif node['type'] == 'string': pending.extend(node['parts'])
    unique = {r['sha256']: r['bytes'] for r in refs}
    return {'format': 'sidecar_index' if is_index(stored) else 'inline',
            'logical_bytes': len(guided._bytes(state)), 'index_bytes': len(guided._bytes(stored)),
            'component_references': len(refs), 'unique_components': len(unique),
            'unique_component_bytes': sum(unique.values()), 'logical_limit_bytes': MAX_LOGICAL_BYTES,
            'qualification': 'Storage integrity/accounting only; no input freshness, review or execution authority.'}
