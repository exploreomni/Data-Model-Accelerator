"""Build an accountable Omni dashboard candidate from reviewed native mappings.

This is a deterministic build specification, not an automatic Looker-expression
translator or a native grammar certificate. Nothing here calls a tenant API.
"""
import argparse
import copy
import json
import re
from pathlib import Path

from ae_common import hash_json, load_json, require, _json_bytes
from looker_source import parse_dashboard
from sensitive_data import scan_bytes

VERSION = 'omni-dashboard-v1-2026-10-05'
SHA = re.compile(r'[a-f0-9]{64}\Z')
UUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z')
CORE = ('source', 'source_payload', 'tiles', 'filters', 'layouts', 'dependencies')
ACTIVE = re.compile(r'<\s*/?\s*[a-zA-Z][^>]*>|(?:https?|javascript|data|file):', re.I)


def pointer(value, path):
    require(type(path) is str and path.startswith('/') and len(path) <= 1000,
            'Native JSON pointer required')
    for raw in path[1:].split('/'):
        require(not re.search(r'~(?![01])', raw), 'Invalid JSON pointer escape')
        key = raw.replace('~1', '/').replace('~0', '~')
        if type(value) is dict:
            require(key in value, 'Native mapping pointer does not resolve')
            value = value[key]
        elif type(value) is list:
            require(re.fullmatch(r'0|[1-9][0-9]*', key) is not None and int(key) < len(value),
                    'Native mapping array pointer does not resolve')
            value = value[int(key)]
        else:
            raise ValueError('Native mapping pointer does not resolve')
    return value


def facets(item, kind):
    if kind == 'tile':
        return {k: item.get(k) for k in ('query', 'calculations', 'filter_listeners',
                                        'visualizations', 'text', 'source_payload')}
    return {'source_payload': item['source_payload']}


def _source(contract):
    require(type(contract) is dict and type(contract.get('schema_version')) is int and contract.get('schema_version') == 1
            and contract.get('kind') == 'canonical_dashboard', 'Canonical source required')
    fresh = parse_dashboard(contract['source_payload'], provenance=contract.get('provenance'))
    require(all(contract.get(k) == fresh.get(k) for k in CORE),
            'Canonical source differs from deterministic extraction')
    require(0 < len(contract['tiles']) <= 200 and len(contract['filters']) <= 100,
            'Dashboard inventory exceeds supported bounds')
    require(type(contract.get('gaps')) is list and all(type(g) is dict and type(g.get('code')) is str
            for g in contract['gaps']), 'Canonical source gaps required')
    core_gaps = lambda value: [g for g in value if not g['code'].startswith('coverage.')]
    require(core_gaps(contract['gaps']) == core_gaps(fresh['gaps']),
            'Canonical source gaps differ from deterministic extraction')
    return fresh


def template(contract, candidate_sha256, target_model_id):
    """Produce a complete work list; unfilled entries stay explicitly manual."""
    _source(contract)
    require(type(candidate_sha256) is str and SHA.fullmatch(candidate_sha256), 'Candidate hash required')
    require(type(target_model_id) is str and UUID.fullmatch(target_model_id), 'Target model UUID required')
    mapping = {'schema_version': 1, 'kind': 'omni_dashboard_mapping',
               'source_sha256': hash_json(contract), 'candidate_sha256': candidate_sha256,
               'target_model_id': target_model_id,
               'native_payload': {'modelId': target_model_id, 'name': 'Migration candidate',
                                  'queryPresentations': {'data': {}, 'order': []},
                                  'controls': {'data': {}, 'order': []}, 'containers': []},
               'tiles': {}, 'filters': {}, 'layout': {'status': 'manual',
                  'source_sha256': hash_json(contract['layouts']), 'reason': 'Review native layout mapping'},
               'review': {'status': 'pending', 'reference': None, 'mapping_sha256': None}}
    for collection, kind in (('tiles', 'tile'), ('filters', 'filter')):
        for item in contract[collection]:
            mapping[collection][item['id']] = {'status': 'manual', 'source_sha256': hash_json(item),
                'reason': 'Translate and review this source item', 'behavior': {
                    key: {'status': 'manual', 'source_sha256': hash_json(value),
                          'reason': 'Review source behavior'} for key, value in facets(item, kind).items()}}
    scan = scan_bytes(_json_bytes(mapping), 'mapping.json')
    require(scan['status'] == 'clear' and scan['coverage']['complete'], 'Mapping disclosure scan did not clear')
    return mapping


def _entry(entry, source, native, manual, label):
    require(type(entry) is dict and entry.get('source_sha256') == hash_json(source),
            'Mapping source version mismatch')
    require(entry.get('status') in ('mapped', 'manual'), 'Explicit mapping disposition required')
    if entry['status'] == 'manual':
        require(type(entry.get('reason')) is str and entry['reason'].strip(), 'Manual mapping needs a reason')
        manual.append({'item': label, 'reason': entry['reason']})
        return None
    fragment = pointer(native, entry.get('target_pointer'))
    require(fragment is not None and entry.get('target_sha256') == hash_json(fragment),
            'Mapped native fragment changed')
    return entry['target_pointer']


def _native(payload):
    require(type(payload) is dict and set(payload) <= {'modelId', 'name', 'description', 'summary',
            'queryPresentations', 'controls', 'settings', 'containers'}, 'Unsupported native document parameter')
    require(type(payload.get('name')) is str and 0 < len(payload['name']) <= 254, 'Native document name required')
    for key in ('queryPresentations', 'controls'):
        value = payload.get(key)
        require(type(value) is dict and set(value) == {'data', 'order'} and type(value['data']) is dict
                and type(value['order']) is list and len(value['order']) == len(set(value['order']))
                and set(value['order']) == set(value['data']), 'Complete native tile/control order required')
        require(all(type(x) is str and x and type(v) is dict for x, v in value['data'].items()),
                'Native deletes and null placeholders are not supported')
    require(len(payload['queryPresentations']['data']) <= 48, 'Native patch exceeds 48 tiles')
    require(all(re.fullmatch(r'[1-9][0-9]*', x) for x in payload['queryPresentations']['data']),
            'Native tile keys must be positive integer strings')
    for tile in payload['queryPresentations']['data'].values():
        require(tile.get('type') in ('query', 'blank'), 'Native tile type requires additional qualification')
        require(not any(k in tile for k in ('miniUuid', 'model_extension_id', 'fileUploadId')),
                'Server-owned tile identities and uploads are not supported')
        if tile['type'] == 'query':
            require(type(tile.get('query')) is dict and type(tile['query'].get('fields')) is list
                    and tile['query']['fields'] and all(type(f) is str and f for f in tile['query']['fields'])
                    and type(tile.get('topicName')) is str and tile['topicName'] and tile.get('isSql') in (None, False),
                    'Modeled query tile requires fields and topic')
            require(not any(k in tile['query'] for k in ('modelId', 'model_id', 'sql')),
                    'Workbook anchors and raw SQL cannot replace modeled queries')
    require(type(payload.get('containers')) is list, 'Explicit native layout required')
    def inspect(value, depth=0):
        require(depth <= 32, 'Native payload nesting limit exceeded')
        if type(value) is str:
            require(not ACTIVE.search(value), 'Active markup and external content require a manual review route')
        elif type(value) in (list, dict):
            for child in (value.values() if type(value) is dict else value):
                inspect(child, depth + 1)
    inspect(payload)


def build(contract, mapping):
    _source(contract)
    require(type(mapping) is dict and type(mapping.get('schema_version')) is int and mapping.get('schema_version') == 1
            and mapping.get('kind') == 'omni_dashboard_mapping', 'Versioned dashboard mapping required')
    require(set(mapping) == {'schema_version', 'kind', 'source_sha256', 'candidate_sha256', 'target_model_id',
                            'native_payload', 'tiles', 'filters', 'layout', 'review'}, 'Unknown dashboard mapping fields')
    require(mapping['source_sha256'] == hash_json(contract), 'Source contract changed')
    require(type(mapping['candidate_sha256']) is str and SHA.fullmatch(mapping['candidate_sha256']), 'Model candidate hash required')
    require(type(mapping['target_model_id']) is str and UUID.fullmatch(mapping['target_model_id']), 'Target model UUID required')
    native = mapping['native_payload']; _native(native)
    require(native.get('modelId') == mapping['target_model_id'], 'Native model differs from reviewed target')
    manual, tile_paths, filter_paths = [], [], []
    for gap in contract['gaps']:
        if not gap['code'].startswith('coverage.') and gap['code'] not in (
                'dependency.lookml_explore_unresolved', 'source.api_version_unverified'):
            manual.append({'item': 'source_feature', 'reason': gap['code']})
    for collection, kind, paths in (('tiles', 'tile', tile_paths), ('filters', 'filter', filter_paths)):
        indexed = {item['id']: item for item in contract[collection]}
        require(type(mapping[collection]) is dict and set(mapping[collection]) == set(indexed),
                'Every source tile and filter needs exactly one disposition')
        for ordinal, (identity, item) in enumerate(indexed.items()):
            entry = mapping[collection][identity]
            label = collection + ':' + str(ordinal)
            path = _entry(entry, item, native, manual, label)
            if path is not None:
                prefix = '/queryPresentations/data/' if kind == 'tile' else '/controls/data/'
                require(path.startswith(prefix) and '/' not in path[len(prefix):], 'Map a whole native tile or control')
                require(path not in paths, 'Two source items cannot share a native target')
                paths.append(path)
                fragment = pointer(native, path)
                if kind == 'tile':
                    require(fragment.get('type') == ('query' if item['kind'] == 'data' else 'blank'),
                            'Source data and text tile kinds must remain distinct')
            expected = facets(item, kind)
            require(type(entry.get('behavior')) is dict and set(entry['behavior']) == set(expected),
                    'Every source behavior facet requires a disposition')
            for facet, value in expected.items():
                facet_path = _entry(entry['behavior'][facet], value, native, manual, label + ':' + facet)
                if facet_path is not None and path is not None:
                    require(facet_path == path or facet_path.startswith(path + '/'), 'Behavior evidence must belong to its mapped item')
    _entry(mapping['layout'], contract['layouts'], native, manual, 'layout')
    if mapping['layout']['status'] == 'mapped':
        require(mapping['layout']['target_pointer'] == '/containers' and native['containers'], 'Native dashboard layout cannot be empty')
    require(set(tile_paths) == {'/queryPresentations/data/' + k for k in native['queryPresentations']['data']},
            'Native tile inventory contains unmapped items')
    require(set(filter_paths) == {'/controls/data/' + k for k in native['controls']['data']},
            'Native control inventory contains unmapped items')
    review = mapping['review']
    require(type(review) is dict and review.get('status') in ('pending', 'approved'), 'Explicit mapping review state required')
    if review['status'] == 'approved':
        require(type(review.get('reference')) is str and review['reference'].strip()
                and review.get('mapping_sha256') == hash_json({k: v for k, v in mapping.items() if k != 'review'}),
                'Mapping review is stale or lacks its reference')
    else:
        manual.append({'item': 'review', 'reason': 'Review the exact mapping before native construction'})
    for value in (contract, mapping):
        scan = scan_bytes(_json_bytes(value), 'dashboard.json')
        require(scan['status'] == 'clear' and scan['coverage']['complete'], 'Dashboard disclosure scan did not clear')
    result = {'schema_version': 1, 'kind': 'omni_dashboard_build', 'contract_version': VERSION,
              'status': 'incomplete' if manual else 'complete', 'source_sha256': hash_json(contract),
              'candidate_sha256': mapping['candidate_sha256'], 'target_model_id': mapping['target_model_id'],
              'source_contract': copy.deepcopy(contract), 'mapping': copy.deepcopy(mapping),
              'native_payload': copy.deepcopy(native), 'manual_steps': manual,
              'coverage': {'tiles': len(contract['tiles']), 'data_tiles': sum(t['kind'] == 'data' for t in contract['tiles']),
                           'text_tiles': sum(t['kind'] == 'text' for t in contract['tiles']), 'filters': len(contract['filters'])},
              'source_gaps': copy.deepcopy(contract['gaps']), 'source_coverage_authenticated': False,
              'native_verified': False, 'acceptance_ready': False,
              'assurance': 'Complete means accounted for in a reviewed mapping, not source completeness, native grammar, behavior or business acceptance.'}
    result['build_sha256'] = hash_json(result)
    return result


def verify_build(spec):
    require(type(spec) is dict and spec.get('kind') == 'omni_dashboard_build', 'Dashboard build required')
    require(build(spec['source_contract'], spec['mapping']) == spec, 'Dashboard build changed; regenerate and review')
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--candidate-sha256')
    parser.add_argument('--model-id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source = load_json(args.source)
        result = build(source, load_json(args.mapping)) if args.mapping else template(source, args.candidate_sha256, args.model_id)
        # Reuse the private, exclusive writer; no tenant calls on this path.
        from omni_native import _private_file
        _private_file(args.output, result)
        print(json.dumps({'status': result.get('status', 'mapping_requires_review'), 'native_verified': False}))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RecursionError):
        print(json.dumps({'status': 'blocked', 'code': 'dashboard.invalid_or_unapproved_input'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
