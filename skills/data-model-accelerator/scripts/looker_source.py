"""Bounded, read-only Looker API 4 dashboard extraction.

This is a source-behavior inventory, not an executable translation or native
validation. All source strings (including SQL, HTML and instructions) are data.
The CLI writes a private candidate and emits only a value-free summary.

Supported wrapper: {schema_version: 1, kind: "looker_dashboard_export",
api_version: "4.0", dashboard: {...}, queries: [...], looks: [...],
provenance: {...}}. Expected coverage is a SEPARATE input, never a wrapper field.
"""
import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 150000
MAX_ITEMS = 5000
SHA = re.compile(r'[0-9a-f]{64}\Z')
API4 = re.compile(r'4\.0(?:\.\d+)*\Z')
QUERY_ARRAYS = ('fields', 'pivots', 'sorts', 'fill_fields', 'subtotals')
TEXT_FIELDS = ('title', 'subtitle_text', 'body_text', 'body_text_as_html',
               'title_text', 'note_text', 'note_text_as_html', 'note_display', 'note_state')
REFERENCES = ('query_id', 'look_id', 'merge_result_id', 'sql_query_id')
DOCS = 'https://cloud.google.com/looker/docs/reference/looker-api/latest/methods/Dashboard/dashboard'


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _bounded(value):
    """Validate JSON types/depth before copying, hashing or walking caller objects."""
    stack, count, strings = [(value, 0, frozenset())], 0, 0
    while stack:
        item, depth, ancestors = stack.pop()
        count += 1
        _require(depth <= MAX_DEPTH and count <= MAX_NODES, 'source.structure_limit')
        if type(item) is str:
            strings += len(item.encode('utf-8'))
            _require(strings <= MAX_BYTES, 'source.byte_limit')
        elif item is None or type(item) in (bool, int):
            pass
        elif type(item) is float:
            _require(math.isfinite(item), 'source.nonfinite_number')
        else:
            _require(type(item) in (list, dict), 'source.non_json_type')
            _require(id(item) not in ancestors, 'source.cyclic_object')
            seen = ancestors | {id(item)}
            if type(item) is dict:
                _require(all(type(k) is str for k in item), 'source.non_string_key')
                children = [part for pair in item.items() for part in pair]
            else:
                children = item
            _require(count + len(children) <= MAX_NODES, 'source.structure_limit')
            stack.extend((child, depth + 1, seen) for child in children)


def _bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('source.invalid_json_value') from None


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _decode(payload):
    original = None
    if type(payload) in (str, bytes):
        raw = payload.encode('utf-8') if type(payload) is str else payload
        _require(len(raw) <= MAX_BYTES, 'source.byte_limit')
        original = hashlib.sha256(raw).hexdigest()

        def pairs(items):
            result = {}
            for key, value in items:
                _require(key not in result, 'source.duplicate_json_key')
                result[key] = value
            return result

        def constant(_):
            raise ValueError('source.nonfinite_number')

        try:
            payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                                 parse_constant=constant)
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError('source.invalid_or_duplicate_json') from None
    _bounded(payload)
    _require(len(_bytes(payload)) <= MAX_BYTES, 'source.byte_limit')
    return copy.deepcopy(payload), original


def _id(value):
    if type(value) is int and value >= 0:
        return str(value)
    if (type(value) is str and value and len(value) <= 512
            and value == value.strip() and not any(ord(c) < 32 for c in value)):
        return value
    return None


def is_looker_dashboard(obj):
    """Recognize a structural signature, never a filename or generic JSON title.

    Malformed values with the full signature still route to the parser, which
    rejects or records them; detection is not a validity/coverage assertion.
    """
    if type(obj) is not dict:
        return False
    if obj.get('kind') == 'looker_dashboard_export':
        return True
    return (_id(obj.get('id')) is not None and type(obj.get('title')) is str
            and 'dashboard_elements' in obj
            and ('dashboard_filters' in obj or 'dashboard_layouts' in obj))


def _date(value):
    if type(value) is not str:
        return False
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is not None
    except ValueError:
        return False


def _pagination(value):
    """Require positive evidence, including no remaining page/cursor."""
    return (type(value) is dict and value.get('complete') is True
            and type(value.get('pages_observed')) is int and value['pages_observed'] > 0
            and type(value.get('pages_expected')) is int
            and value['pages_observed'] == value['pages_expected']
            and value.get('next_page') in (None, '') and value.get('next_cursor') in (None, '')
            and value.get('has_more') in (None, False))


def _coverage(expected, provenance, dashboard_id, tile_ids, filter_ids, hashes):
    result = {'status': 'unknown', 'basis': 'none', 'independence_authenticated': False,
              'observed': {'dashboard_id': dashboard_id, 'tile_ids': tile_ids,
                           'filter_ids': filter_ids, 'tile_count': len(tile_ids),
                           'filter_count': len(filter_ids)},
              'checks': [], 'limitations': [
                  'An external inventory declaration is not authenticated source execution evidence.',
                  'Inventory agreement does not resolve LookML, query, visualization or business behavior gaps.']}

    def check(code, passed):
        result['checks'].append({'code': code, 'passed': bool(passed)})

    if expected is None:
        check('coverage.expected_inventory_missing', False)
        return result
    _require(type(expected) is dict, 'coverage.invalid_expected_inventory')
    _require(expected.get('schema_version') == 1 and type(expected.get('schema_version')) is int
             and expected.get('kind') == 'looker_dashboard_inventory', 'coverage.unsupported_inventory')
    result['expected_sha256'] = _hash(expected)
    basis = expected.get('basis')
    result['basis'] = basis if basis in ('source_observed', 'operator_declared', 'same_export') else 'unknown'
    check('coverage.dashboard_identity', _id(expected.get('dashboard_id')) == dashboard_id)
    for noun, observed in [('tile', tile_ids), ('filter', filter_ids)]:
        ids, count = expected.get(noun + '_ids'), expected.get(noun + '_count')
        supplied = ids is not None or count is not None
        check('coverage.' + noun + '_denominator_present', supplied)
        if ids is not None:
            _require(type(ids) is list and len(ids) <= MAX_ITEMS and all(_id(v) is not None for v in ids),
                     'coverage.invalid_expected_ids')
            ids = [_id(v) for v in ids]
            _require(len(set(ids)) == len(ids), 'coverage.duplicate_expected_id')
            check('coverage.' + noun + '_ids_match', set(ids) == set(observed) and None not in observed)
        if count is not None:
            _require(type(count) is int and 0 <= count <= MAX_ITEMS, 'coverage.invalid_expected_count')
            check('coverage.' + noun + '_count_match', count == len(observed))
    capture = expected.get('capture', {})
    check('coverage.capture_record', type(capture) is dict and _date(capture.get('captured_at'))
          and type(capture.get('reference')) is str and bool(capture['reference'].strip())
          and type(capture.get('revision')) is str and bool(capture['revision'].strip()))
    evidence_hash = capture.get('artifact_sha256') if type(capture) is dict else None
    independently_supplied = (basis in ('source_observed', 'operator_declared')
        and type(evidence_hash) is str and SHA.fullmatch(evidence_hash)
        and evidence_hash not in hashes and expected.get('derived_from_export') is not True
        and not (set(expected.get('derived_from_sha256', [])) & hashes
                 if type(expected.get('derived_from_sha256', [])) is list
                 and all(type(x) is str for x in expected.get('derived_from_sha256', [])) else True))
    check('coverage.separate_inventory_evidence', independently_supplied)
    check('coverage.inventory_pagination_complete', _pagination(expected.get('pagination')))
    check('coverage.export_pagination_complete', _pagination(provenance.get('pagination')))
    check('coverage.export_capture_record', _date(provenance.get('captured_at'))
          and type(provenance.get('capture_reference')) is str and bool(provenance['capture_reference'].strip())
          and type(provenance.get('revision')) is str and bool(provenance['revision'].strip())
          and type(provenance.get('api_version')) is str and bool(API4.fullmatch(provenance['api_version'])))
    check('coverage.capture_revision_match', type(capture) is dict
          and type(capture.get('revision')) is str and capture['revision'] == provenance.get('revision'))
    check('coverage.source_instance_match', type(capture) is dict
          and type(capture.get('source_instance')) is str and bool(capture['source_instance'].strip())
          and capture['source_instance'] == provenance.get('source_instance'))
    identity_failed = any(not c['passed'] for c in result['checks']
                          if c['code'].endswith(('_ids_match', '_count_match', 'dashboard_identity')))
    incomplete_page = any(type(v) is dict and (v.get('complete') is False
        or v.get('has_more') is True or v.get('next_page') not in (None, '')
        or v.get('next_cursor') not in (None, '')
        or (type(v.get('pages_observed')) is int and type(v.get('pages_expected')) is int
            and v['pages_observed'] != v['pages_expected']))
        for v in (expected.get('pagination'), provenance.get('pagination')))
    if identity_failed or incomplete_page:
        result['status'] = 'failed'
    elif all(c['passed'] for c in result['checks']):
        result['status'] = 'source_observed_match' if basis == 'source_observed' else 'operator_declared_match'
    return result


def parse_dashboard(payload, provenance=None, expected=None):
    """Extract a schema-1 canonical_dashboard with exact source behavior.

    `source`, `tiles`, `filters`, `layouts`, and `dependencies` depend only on the
    export, so a verifier can re-extract them independently. Provenance and the
    external denominator affect only top-level provenance/coverage/gaps.
    """
    payload, original_hash = _decode(payload)
    _require(is_looker_dashboard(payload), 'source.not_looker_dashboard')
    wrapped = payload.get('kind') == 'looker_dashboard_export'
    if wrapped:
        _require(type(payload.get('schema_version')) is int and payload['schema_version'] == 1,
                 'source.unsupported_wrapper_version')
        dashboard = payload.get('dashboard')
        _require(type(dashboard) is dict and is_looker_dashboard(dashboard)
                 and dashboard.get('kind') != 'looker_dashboard_export', 'source.invalid_wrapped_dashboard')
    else:
        dashboard = payload
    _require(type(dashboard.get('dashboard_elements')) is list
             and len(dashboard['dashboard_elements']) <= MAX_ITEMS, 'source.invalid_dashboard_elements')
    prefix = '/dashboard' if wrapped else ''
    gaps, dependencies, tiles, filters, layouts = [], [], [], [], []

    def gap(code, path):
        item = {'code': code, 'source_path': path}
        if item not in gaps:
            gaps.append(item)

    def records(value, path):
        if value is None:
            gap('source.collection_missing', path)
            return []
        if type(value) is not list or len(value) > MAX_ITEMS:
            gap('source.unsupported_collection_shape', path)
            return []
        return value

    def identities(rows, path):
        seen = set()
        for i, row in enumerate(rows):
            identity = _id(row.get('id')) if type(row) is dict else None
            if identity is None:
                gap('source.identity_missing', path + '/' + str(i))
            else:
                _require(identity not in seen, 'source.duplicate_id')
                seen.add(identity)

    def preserved(row, path):
        return {'id': _id(row.get('id')) if type(row) is dict else None,
                'source_path': path, 'source_payload_sha256': _hash(row), 'source_payload': row}

    def dependency(kind, identity, path, resolved=False, content=None):
        dependencies.append({'kind': kind, 'id': identity, 'source_path': path,
                             'status': 'embedded' if resolved else 'unresolved',
                             'source_payload_sha256': _hash(content) if content is not None else None})
        if not resolved:
            gap('dependency.' + kind + '_unresolved', path)

    registry = {'queries': {}, 'looks': {}}
    if wrapped:
        for collection in registry:
            rows = records(payload.get(collection, []), '/' + collection)
            identities(rows, '/' + collection)
            for i, row in enumerate(rows):
                if type(row) is dict and _id(row.get('id')) is not None:
                    registry[collection][_id(row['id'])] = (row, '/' + collection + '/' + str(i))
    # Conflicting embedded identities cannot silently pick a different query.
    query_hashes, look_hashes = {}, {}

    def register(row, table):
        identity = _id(row.get('id'))
        if identity:
            digest = _hash(row)
            _require(identity not in table or table[identity] == digest, 'source.conflicting_reference_id')
            table[identity] = digest

    for row, _ in registry['queries'].values():
        register(row, query_hashes)
    for row, _ in registry['looks'].values():
        register(row, look_hashes)
    # Index all embedded definitions first: API4 commonly puts query_id on the
    # element and the actual query under result_maker. Array order cannot turn
    # that complete reference into a false missing-dependency gap.
    query_owners = list(registry['looks'].values())
    for i, element in enumerate(dashboard['dashboard_elements']):
        if type(element) is not dict:
            continue
        ep = prefix + '/dashboard_elements/' + str(i)
        query_owners.append((element, ep))
        if type(element.get('result_maker')) is dict:
            query_owners.append((element['result_maker'], ep + '/result_maker'))
        if type(element.get('look')) is dict:
            look = element['look']
            register(look, look_hashes)
            if _id(look.get('id')) is not None:
                registry['looks'].setdefault(_id(look['id']), (look, ep + '/look'))
            query_owners.append((look, ep + '/look'))
    for owner, owner_path in query_owners:
        query = owner.get('query')
        if type(query) is dict:
            register(query, query_hashes)
            if _id(query.get('id')) is not None:
                registry['queries'].setdefault(_id(query['id']), (query, owner_path + '/query'))
    filter_rows = records(dashboard.get('dashboard_filters'), prefix + '/dashboard_filters')
    identities(filter_rows, prefix + '/dashboard_filters')
    for i, row in enumerate(filter_rows):
        path = prefix + '/dashboard_filters/' + str(i)
        item = preserved(row, path)
        if type(row) is not dict:
            gap('filter.unsupported_shape', path)
        else:
            if type(row.get('name')) is not str or not row['name']:
                gap('filter.name_missing', path)
            if row.get('dashboard_id') is not None and _id(row['dashboard_id']) != _id(dashboard['id']):
                gap('filter.dashboard_mismatch', path)
        filters.append(item)
    filter_names = {x.get('name') for x in filter_rows if type(x) is dict and type(x.get('name')) is str}
    identities(dashboard['dashboard_elements'], prefix + '/dashboard_elements')
    for i, element in enumerate(dashboard['dashboard_elements']):
        path = prefix + '/dashboard_elements/' + str(i)
        tile = preserved(element, path)
        tile.update(kind='unsupported', query=None, query_source_path=None, calculations=[],
                    filter_listeners=[], visualizations=[], text={}, references={})
        tiles.append(tile)
        if type(element) is not dict:
            gap('tile.unsupported_shape', path)
            continue
        if element.get('dashboard_id') is not None and _id(element['dashboard_id']) != _id(dashboard['id']):
            gap('tile.dashboard_mismatch', path)
        tile['text'] = {k: element[k] for k in TEXT_FIELDS if k in element}
        tile['references'] = {k: element[k] for k in REFERENCES if k in element}
        maker = element.get('result_maker')
        if maker is not None and type(maker) is not dict:
            gap('tile.unsupported_result_maker', path + '/result_maker')
            maker = None
        candidates = []

        def query_candidate(owner, owner_path):
            if type(owner) is not dict:
                return
            query = owner.get('query')
            reference = _id(owner.get('query_id'))
            qpath = owner_path + '/query'
            if query is not None and type(query) is not dict:
                gap('query.unsupported_shape', qpath)
            elif type(query) is dict:
                if reference and _id(query.get('id')) != reference:
                    gap('query.reference_mismatch', qpath)
                register(query, query_hashes)
                candidates.append((query, qpath))
                dependency('query', reference or _id(query.get('id')), qpath, True, query)
            elif reference:
                found = registry['queries'].get(reference)
                dependency('query', reference, owner_path + '/query_id', bool(found), found[0] if found else None)
                if found:
                    candidates.append(found)

        query_candidate(element, path)
        query_candidate(maker, path + '/result_maker')
        look = element.get('look')
        look_id = _id(element.get('look_id'))
        look_path = path + '/look'
        if look is not None and type(look) is not dict:
            gap('look.unsupported_shape', look_path)
        if type(look) is not dict and look_id in registry['looks']:
            look, look_path = registry['looks'][look_id]
        if type(look) is dict:
            register(look, look_hashes)
            if look_id and _id(look.get('id')) != look_id:
                gap('look.reference_mismatch', look_path)
            dependency('look', look_id or _id(look.get('id')), look_path, True, look)
            query_candidate(look, look_path)
        elif look_id:
            dependency('look', look_id, path + '/look_id')
        merged = any(type(owner) is dict and owner.get('merge_result_id') is not None for owner in (element, maker))
        sql_runner = any(type(owner) is dict and owner.get('sql_query_id') is not None for owner in (element, maker))
        if merged:
            gap('tile.merged_query_requires_adapter', path)
        if sql_runner:
            gap('tile.sql_runner_requires_adapter', path)
        is_text = element.get('type') in ('text', 'text_tile') or (not candidates and not merged and not sql_runner
                    and not any(type(owner) is dict and owner.get(k) is not None
                                for owner in (element, maker) for k in ('query_id', 'look_id'))
                    and any(element.get(k) is not None for k in ('body_text', 'body_text_as_html', 'subtitle_text')))
        tile['kind'] = 'text' if is_text else 'data'
        if candidates:
            tile['query'], tile['query_source_path'] = candidates[0]
            if len({_hash(q) for q, _ in candidates}) > 1:
                gap('query.multiple_conflicting_candidates', path)
            if is_text:
                gap('tile.text_with_query', path)
        elif not is_text:
            gap('query.definition_missing', path)
        owners = [(element, path)] + ([(maker, path + '/result_maker')] if maker else []) + candidates
        for owner, owner_path in owners:
            if 'dynamic_fields' in owner and owner['dynamic_fields'] is not None:
                dynamic = owner['dynamic_fields']
                parsed = None
                try:
                    parsed, _ = _decode(dynamic)
                    if type(parsed) is not list or any(type(v) is not dict for v in parsed):
                        raise ValueError('shape')
                except ValueError:
                    gap('calculation.invalid_dynamic_fields', owner_path + '/dynamic_fields')
                tile['calculations'].append({'source_path': owner_path + '/dynamic_fields', 'raw': dynamic, 'parsed': parsed})
            if 'vis_config' in owner and owner['vis_config'] is not None:
                config = owner['vis_config']
                tile['visualizations'].append({'source_path': owner_path + '/vis_config', 'value': config})
                if type(config) is not dict or ('type' in config and type(config['type']) is not str):
                    gap('visualization.unsupported_shape', owner_path + '/vis_config')
            if 'listen' in owner:
                listen = owner['listen']
                tile['filter_listeners'].append({'source_path': owner_path + '/listen', 'value': listen})
                if type(listen) is not dict:
                    gap('filter.unsupported_listen_shape', owner_path + '/listen')
                else:
                    for name, field in listen.items():
                        if name not in filter_names or type(field) is not str:
                            gap('filter.listen_unresolved', owner_path + '/listen')
        if maker and maker.get('filterables') is not None:
            for fi, filterable in enumerate(records(maker['filterables'], path + '/result_maker/filterables')):
                fp = path + '/result_maker/filterables/' + str(fi)
                tile['filter_listeners'].append({'source_path': fp, 'value': filterable})
                if type(filterable) is not dict or type(filterable.get('listen')) is not list:
                    gap('filter.unsupported_listen_shape', fp)
                    continue
                for listener in filterable['listen']:
                    if (type(listener) is not dict or type(listener.get('dashboard_filter_name')) is not str
                            or listener['dashboard_filter_name'] not in filter_names
                            or type(listener.get('field')) is not str):
                        gap('filter.listen_unresolved', fp)
        for query, qpath in candidates:
            if not query.get('fields'):
                gap('query.fields_missing', qpath + '/fields')
            for field in QUERY_ARRAYS:
                if field in query and query[field] is not None and (type(query[field]) is not list
                        or any(type(v) is not str for v in query[field])):
                    gap('query.unsupported_' + field, qpath + '/' + field)
            if query.get('filters') is not None and type(query['filters']) is not dict:
                gap('query.unsupported_filters', qpath + '/filters')
            if query.get('filter_config') is not None:
                gap('query.opaque_filter_config_requires_review', qpath + '/filter_config')
            for field in ('filter_expression', 'query_timezone'):
                if query.get(field) is not None and type(query[field]) is not str:
                    gap('query.unsupported_' + field, qpath + '/' + field)
            for field in ('limit', 'column_limit'):
                if query.get(field) is not None and type(query[field]) not in (str, int):
                    gap('query.unsupported_' + field, qpath + '/' + field)
            if type(query.get('model')) is not str or type(query.get('view')) is not str:
                gap('query.lookml_identity_missing', qpath)
            else:
                dependency('lookml_explore', {'model': query['model'], 'explore': query['view']}, qpath)
    layout_rows = records(dashboard.get('dashboard_layouts'), prefix + '/dashboard_layouts')
    identities(layout_rows, prefix + '/dashboard_layouts')
    tile_ids = [x['id'] for x in tiles]
    for i, row in enumerate(layout_rows):
        path = prefix + '/dashboard_layouts/' + str(i)
        item = preserved(row, path)
        layouts.append(item)
        if type(row) is not dict:
            gap('layout.unsupported_shape', path)
            continue
        components = records(row.get('dashboard_layout_components'), path + '/dashboard_layout_components')
        identities(components, path + '/dashboard_layout_components')
        for ci, component in enumerate(components):
            cp = path + '/dashboard_layout_components/' + str(ci)
            if type(component) is not dict or _id(component.get('dashboard_element_id')) not in tile_ids:
                gap('layout.tile_reference_unresolved', cp)
            elif any(type(component.get(k)) is not int or component[k] < (1 if k in ('width', 'height') else 0)
                     for k in ('row', 'column', 'width', 'height')):
                gap('layout.invalid_geometry', cp)
    if provenance is None:
        provenance = copy.deepcopy(payload.get('provenance', {})) if wrapped else {}
    else:
        provenance, _ = _decode(provenance)
    _require(type(provenance) is dict, 'source.invalid_provenance')
    if wrapped and 'api_version' in payload:
        if 'api_version' in provenance and provenance['api_version'] != payload['api_version']:
            gap('source.api_version_conflict', '/api_version')
        provenance.setdefault('api_version', payload['api_version'])
    if type(provenance.get('api_version')) is not str or not API4.fullmatch(provenance['api_version']):
        gap('source.api_version_unverified', '/provenance/api_version')
    if wrapped and 'expected' in payload:
        gap('coverage.embedded_expectations_not_independent', '/expected')
    if expected is not None:
        expected, _ = _decode(expected)
    payload_hash, dashboard_hash = _hash(payload), _hash(dashboard)
    coverage = _coverage(expected, provenance, _id(dashboard['id']), tile_ids,
                         [x['id'] for x in filters], {payload_hash, dashboard_hash, original_hash})
    if coverage['status'] != 'source_observed_match':
        gap('coverage.' + coverage['status'], '/coverage')
    return {'schema_version': 1, 'kind': 'canonical_dashboard',
            'source': {'platform': 'looker', 'format': 'looker_api_dashboard',
                       'dashboard_id': _id(dashboard['id']), 'source_path': prefix or '/',
                       'payload_sha256': payload_hash, 'dashboard_sha256': dashboard_hash,
                       'hash_encoding': 'canonical_json', 'contract_reference': DOCS},
            'input_integrity': {'original_bytes_sha256': original_hash},
            'source_payload': payload, 'provenance': provenance,
            'tiles': tiles, 'filters': filters, 'layouts': layouts,
            'dependencies': dependencies, 'gaps': gaps, 'coverage': coverage,
            'assurance': 'Read-only source extraction; no execution, translation, approval or native qualification.'}


def _read(path):
    path = Path(path).absolute()
    _require(path.resolve() == path, 'source.noncanonical_path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'source.file_bounds')
        content = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _require(identity(before) == identity(after) and len(content) == after.st_size, 'source.changed_during_read')
    return content


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--provenance', type=Path)
    parser.add_argument('--expected', type=Path)
    args = parser.parse_args(argv)
    created = False
    try:
        result = parse_dashboard(_read(args.input), _read(args.provenance) if args.provenance else None,
                                 _read(args.expected) if args.expected else None)
        output = args.output.absolute()
        _require(output.resolve() == output and output.parent.is_dir(), 'output.noncanonical_path')
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_bytes(result) + b'\n')
        print(json.dumps({'status': 'private_candidate', 'tile_count': len(result['tiles']),
                          'filter_count': len(result['filters']), 'gap_count': len(result['gaps']),
                          'coverage': result['coverage']['status'], 'native_qualification': 'pending'}))
        return 0
    except (ValueError, OSError, TypeError, RecursionError, UnicodeError):
        if created:
            args.output.unlink(missing_ok=True)
        print(json.dumps({'status': 'blocked', 'reason': 'source.invalid_or_unavailable_input'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
