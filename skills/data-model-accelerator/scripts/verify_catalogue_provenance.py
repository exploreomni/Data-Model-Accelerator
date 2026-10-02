"""Bind normalized catalogue fields to exact values in pinned JSON exports.

Consistency is not authenticity: a fabricated export and matching declarations
can agree. This checker neither contacts a warehouse nor grants approval.
"""
import argparse
from pathlib import Path
import re
import sys

from ae_common import hash_file, hash_json, require, safe_relative, write_json
from freeze_benchmark import _bound_json, _fields, _sha, _text

ORIGINS = {'synthetic_generator': 'synthetic', 'operator_export': 'provided_export',
           'live_connector': 'live_metadata'}
INDEX = re.compile(r'(?:0|[1-9][0-9]*)\Z')


def pointer(document, value):
    """Resolve RFC 6901 string syntax, with exact keys and bounded traversal."""
    require(type(value) is str and len(value) <= 4096, 'JSON pointer must be a bounded string')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value), 'Control character in JSON pointer')
    require(value == '' or value.startswith('/'), 'JSON pointer must be empty or start with /')
    require('*' not in value and '?' not in value, 'Wildcard JSON pointers are not supported')
    parts = value[1:].split('/') if value else []
    require(len(parts) <= 128, 'JSON pointer nesting limit exceeded')
    current = document
    for part in parts:
        require(re.search(r'~(?:[^01]|$)', part) is None, 'Invalid JSON pointer escape')
        key = part.replace('~1', '/').replace('~0', '~')
        if type(current) is dict:
            require(key in current, 'Missing JSON pointer key: ' + key)
            current = current[key]
        elif type(current) is list:
            require(INDEX.fullmatch(key) is not None, 'Invalid JSON pointer array index')
            require(len(key) <= 10 and int(key) < len(current), 'JSON pointer array index out of range')
            current = current[int(key)]
        else:
            raise ValueError('JSON pointer traverses a scalar')
    return current


def _targets(catalogue):
    require(type(catalogue) is dict and type(catalogue.get('schema_version')) is int
            and catalogue['schema_version'] == 1 and catalogue.get('kind') == 'warehouse_raw_catalogue',
            'Unsupported catalogue schema')
    objects = catalogue.get('objects')
    require(type(objects) is list and objects, 'Catalogue objects must be nonempty')
    targets = set()
    for index, obj in enumerate(objects):
        require(type(obj) is dict and type(obj.get('identity')) is dict, 'Catalogue object identity is required')
        base = '/objects/' + str(index)
        for name in ('catalog', 'schema', 'name'):
            _text(obj['identity'].get(name), 'object identity ' + name)
            targets.add(base + '/identity/' + name)
        _text(obj.get('object_type'), 'object_type')
        targets.add(base + '/object_type')
        columns = obj.get('columns')
        require(type(columns) is list and columns, 'Catalogue object columns must be nonempty')
        for column_index, column in enumerate(columns):
            require(type(column) is dict and type(column.get('path')) is list and column['path'],
                    'Column path must be a nonempty list')
            for component in column['path']:
                _text(component, 'column path component')
            _text(column.get('data_type'), 'column data_type')
            require('nullable' in column and (column['nullable'] is None or type(column['nullable']) is bool),
                    'Column nullable must be boolean or null')
            targets.update(base + '/columns/' + str(column_index) + '/' + name
                           for name in ('path', 'data_type', 'nullable'))
    return targets


def verify(contract_path, catalogue_path):
    """Return a content-consistency report; reject malformed or stale evidence."""
    contract_path, catalogue_path = Path(contract_path).absolute(), Path(catalogue_path).absolute()
    require(contract_path != catalogue_path, 'Contract and catalogue must be distinct')
    contract, contract_hash = _bound_json(contract_path)
    _fields(contract, ('schema_version', 'kind', 'catalogue_sha256', 'capture_method',
                      'provenance_reference', 'mappings'))
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['kind'] == 'catalogue_provenance', 'Unsupported catalogue provenance contract')
    method = contract['capture_method']
    require(type(method) is str and method in ORIGINS, 'Unknown catalogue capture method')
    reference = _text(contract['provenance_reference'], 'provenance_reference')
    require(len(reference) <= 4096, 'Provenance reference exceeds text limit')
    catalogue, catalogue_hash = _bound_json(catalogue_path, _sha(contract['catalogue_sha256']))
    required = _targets(catalogue)
    require(catalogue.get('origin') == ORIGINS[method], 'Capture method and catalogue origin differ')
    extractions = catalogue.get('extractions')
    require(type(extractions) is list and extractions, 'Catalogue extractions must be nonempty')
    indexed = {}
    for extraction in extractions:
        require(type(extraction) is dict, 'Invalid extraction record')
        extraction_id = _text(extraction.get('extraction_id'), 'extraction_id')
        require(extraction_id not in indexed, 'Duplicate extraction ID')
        indexed[extraction_id] = extraction
    mappings = contract['mappings']
    require(type(mappings) is list and mappings, 'Catalogue field mappings must be nonempty')
    seen, exports, errors = set(), {}, []
    for mapping in mappings:
        _fields(mapping, ('catalogue_pointer', 'extraction_id', 'export_pointer'))
        target = mapping['catalogue_pointer']
        require(type(target) is str and target in required, 'Unexpected catalogue mapping target')
        require(target not in seen, 'Duplicate catalogue mapping target')
        seen.add(target)
        extraction_id = _text(mapping['extraction_id'], 'mapping extraction_id')
        require(extraction_id in indexed, 'Mapping references unknown extraction')
        if extraction_id not in exports:
            extraction = indexed[extraction_id]
            path = catalogue_path.parent / safe_relative(extraction.get('artifact_path'))
            exported, digest = _bound_json(path, _sha(extraction.get('sha256')))
            require(type(exported) in (list, dict), 'Extraction JSON must be an object or array')
            exports[extraction_id] = (path, digest, exported)
        exported = exports[extraction_id][2]
        if hash_json(pointer(catalogue, target)) != hash_json(pointer(exported, mapping['export_pointer'])):
            errors.append('Normalized catalogue value differs from export: ' + target)
    require(seen == required, 'Catalogue mapping denominator incomplete: ' + ', '.join(sorted(required - seen)))
    for path, digest, _ in exports.values():
        require(hash_file(path) == digest, 'Export changed during provenance verification')
    require(hash_file(contract_path) == contract_hash and hash_file(catalogue_path) == catalogue_hash,
            'Catalogue provenance evidence changed during verification')
    return {'schema_version': 1, 'kind': 'catalogue_provenance_verification', 'passed': not errors,
            'catalogue_sha256': catalogue_hash, 'origin': catalogue['origin'], 'capture_method': method,
            'mapped_fields': len(seen), 'errors': errors,
            'limitations': ['Capture method and provenance reference are declarations, not authenticated identities or query execution.',
                            'Pinned field equality does not detect consistently fabricated exports or establish warehouse visibility.',
                            'Only identity, object type, column path/type/nullability are reconciled; freshness, bindings and other metadata require catalogue review.',
                            'Synthetic evidence cannot establish live warehouse, human approval or production acceptance.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract', 'catalogue', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.contract, args.catalogue)
        write_json(args.output, result)
        print('PASS' if result['passed'] else 'FAIL: ' + '; '.join(result['errors']))
        return 0 if result['passed'] else 1
    except (ValueError, OSError, TypeError, KeyError) as error:
        print('Catalogue provenance verification refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
