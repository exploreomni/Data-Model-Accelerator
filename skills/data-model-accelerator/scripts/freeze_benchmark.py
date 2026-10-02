"""Freeze analyst-supplied expected exports; no candidate code or SQL is executed.

Receipts and author/approval identities are self-attested. Hash consistency does
not authenticate independence, approval, source execution or business meaning.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys

from ae_common import hash_file, hash_json, load_json, require, safe_relative, write_json

SHA = re.compile(r'[0-9a-f]{64}\Z')
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
TYPES = {'string', 'integer', 'decimal', 'boolean'}


def _fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional), 'Missing or unknown object fields')


def _text(value, label):
    require(type(value) is str and value and value == value.strip() and
            not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid ' + label)
    return value


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, 'Invalid SHA-256')
    return value


def _decimal(value):
    require(type(value) is str and len(value) <= 128 and NUMBER.fullmatch(value) is not None, 'Expected a bounded decimal string')
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError('Invalid decimal string') from error
    require(number.is_finite() and -1000 <= number.adjusted() <= 1000, 'Decimal exponent is out of bounds')
    return number


def validate_columns(columns):
    """Return typed descriptors, filling numeric tolerance defaults with '0'."""
    require(type(columns) is dict and columns, 'columns must be a nonempty object')
    normalized = {}
    for name, descriptor in columns.items():
        _text(name, 'column name')
        _fields(descriptor, ('type', 'nullable'), ('abs_tolerance', 'rel_tolerance'))
        require(type(descriptor['type']) is str and descriptor['type'] in TYPES, 'Unsupported column type')
        require(type(descriptor['nullable']) is bool, 'nullable must be boolean')
        item = dict(descriptor)
        numeric = item['type'] in ('integer', 'decimal')
        for tolerance in ('abs_tolerance', 'rel_tolerance'):
            if numeric:
                item.setdefault(tolerance, '0')
                require(_decimal(item[tolerance]) >= 0, 'Tolerance must be nonnegative')
            else:
                require(tolerance not in item, 'Tolerance is allowed only on numeric columns')
        normalized[name] = item
    return normalized


def validate_rows(rows, columns, keys):
    """Validate exact row schemas/types and unique nonnull keys; return copied rows."""
    columns = validate_columns(columns)
    require(type(keys) is list and keys, 'keys must be a nonempty list')
    for key in keys:
        _text(key, 'key column')
    require(len(set(keys)) == len(keys) and set(keys) <= set(columns), 'Duplicate or unknown key columns')
    for key in keys:
        require(not columns[key]['nullable'], 'Key columns must declare nullable false')
        require(all(_decimal(columns[key].get(name, '0')) == 0 for name in ('abs_tolerance', 'rel_tolerance')), 'Key tolerances must be zero')
    require(type(rows) is list, 'rows must be a list')
    seen, copied = set(), []
    for row in rows:
        require(type(row) is dict and set(row) == set(columns), 'Row columns must exactly match declared columns')
        for name, value in row.items():
            definition = columns[name]
            if value is None:
                require(definition['nullable'] and name not in keys, 'Unexpected null in ' + name)
                continue
            kind = definition['type']
            if kind == 'decimal':
                _decimal(value)
            else:
                require(type(value) is {'string': str, 'integer': int, 'boolean': bool}[kind], 'Invalid value type for ' + name)
        key = tuple(_decimal(row[name]) if columns[name]['type'] == 'decimal' else row[name] for name in keys)
        require(key not in seen, 'Duplicate composite key')
        seen.add(key)
        copied.append(dict(row))
    return copied


def _bound_json(path, expected=None):
    before = hash_file(path)
    if expected is not None:
        require(before == _sha(expected), 'Source receipt hash changed: ' + str(path))
    content = load_json(path)
    require(hash_file(path) == before, 'Source file changed while being read')
    return content, before


def _export_path(value, base):
    value = _text(value, 'expected export path')
    path = Path(value)
    if not path.is_absolute():
        path = base / safe_relative(value)
    # Common read/hash helpers reject noncanonical paths and symlinks.
    return path.absolute()


def _contract(raw, base):
    _fields(raw, ('schema_version', 'analyst_id', 'source_revision', 'catalogue_sha256', 'cases'))
    require(type(raw['schema_version']) is int and raw['schema_version'] == 1, 'Unsupported contract schema_version')
    analyst = _text(raw['analyst_id'], 'analyst_id')
    revision = _text(raw['source_revision'], 'source_revision')
    catalogue = _sha(raw['catalogue_sha256'])
    require(type(raw['cases']) is list and raw['cases'], 'cases must be a nonempty list')
    cases, expected_rows, seen = [], {}, set()
    for case in raw['cases']:
        require(type(case) is dict and case.get('category') in ('compatibility', 'correctness'), 'Invalid case category')
        required = ('id', 'category', 'context', 'keys', 'columns', 'expected')
        _fields(case, required + (('decision',) if case['category'] == 'correctness' else ()))
        case_id = _text(case['id'], 'case id')
        require(case_id not in seen, 'Duplicate case id')
        seen.add(case_id)
        _fields(case['context'], ('timezone', 'watermark', 'principal'), ('currency', 'filters'))
        context = {key: _text(case['context'][key], 'context ' + key) for key in ('timezone', 'watermark', 'principal')}
        if 'currency' in case['context']:
            context['currency'] = _text(case['context']['currency'], 'context currency')
        if 'filters' in case['context']:
            filters = case['context']['filters']
            require(type(filters) is dict, 'context filters must be an object')
            for key, value in filters.items():
                _text(key, 'filter name')
                values = value if type(value) is list else [value]
                require(all(item is None or type(item) in (str, bool, int, float) for item in values), 'Filters require primitive values or primitive lists')
            hash_json(filters)  # Reject nonfinite values while preserving exact filter types.
            context['filters'] = filters
        columns = validate_columns(case['columns'])
        _fields(case['expected'], ('path', 'sha256', 'query_id'))
        receipt = case['expected']
        query_id = _text(receipt['query_id'], 'query_id')
        path = _export_path(receipt['path'], base)
        exported, digest = _bound_json(path, receipt['sha256'])
        _fields(exported, ('rows',))
        rows = validate_rows(exported['rows'], columns, case['keys'])
        normalized = {'id': case_id, 'category': case['category'], 'context': context,
                      'keys': list(case['keys']), 'columns': columns,
                      'expected': {'path': str(path), 'sha256': digest, 'query_id': query_id}}
        if case['category'] == 'correctness':
            _fields(case['decision'], ('id', 'approved_by', 'reason'))
            normalized['decision'] = {key: _text(value, 'decision ' + key) for key, value in case['decision'].items()}
        cases.append(normalized)
        expected_rows[case_id] = rows
    return {'schema_version': 1, 'analyst_id': analyst, 'source_revision': revision,
            'catalogue_sha256': catalogue, 'cases': cases}, expected_rows


def freeze(contract_path, output_path):
    """Create a new baseline file from a contract and its hashed expected exports."""
    contract_path = Path(contract_path).absolute()
    raw, digest = _bound_json(contract_path)
    contract, rows = _contract(raw, contract_path.parent)
    bundle = {'schema_version': 1, 'kind': 'frozen_benchmark_baseline',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'contract_receipt': {'path': str(contract_path), 'sha256': digest},
              'contract': contract, 'expected_rows': rows}
    bundle['baseline_sha256'] = hash_json(bundle)
    write_json(output_path, bundle)
    return bundle


def verify_baseline(path):
    """Verify self-digest, original contract/export bytes and every embedded row."""
    bundle = load_json(path)
    _fields(bundle, ('schema_version', 'kind', 'created_at', 'contract_receipt', 'contract', 'expected_rows', 'baseline_sha256'))
    require(type(bundle['schema_version']) is int and bundle['schema_version'] == 1 and
            bundle['kind'] == 'frozen_benchmark_baseline', 'Unsupported baseline schema/kind')
    require(_sha(bundle['baseline_sha256']) == hash_json({key: value for key, value in bundle.items() if key != 'baseline_sha256'}), 'Baseline digest changed')
    _text(bundle['created_at'], 'created_at')
    created = datetime.fromisoformat(bundle['created_at'].replace('Z', '+00:00'))
    require(created.tzinfo is not None and created.utcoffset() == timezone.utc.utcoffset(created), 'created_at must be UTC')
    _fields(bundle['contract_receipt'], ('path', 'sha256'))
    receipt = bundle['contract_receipt']
    original_path = Path(_text(receipt['path'], 'contract path'))
    require(original_path.is_absolute(), 'Original contract receipt path must be absolute')
    raw, _ = _bound_json(original_path, receipt['sha256'])
    contract, rows = _contract(raw, original_path.parent)
    require(hash_json(bundle['contract']) == hash_json(contract), 'Embedded contract differs from original receipt')
    require(hash_json(bundle['expected_rows']) == hash_json(rows), 'Embedded expected rows differ from source receipts')
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        if args.contract is not None or args.output is not None:
            parser.error('--verify cannot be combined with --contract or --output')
    elif args.contract is None or args.output is None:
        parser.error('use --contract and --output together, or --verify')
    try:
        bundle = verify_baseline(args.verify) if args.verify is not None else freeze(args.contract, args.output)
        print('Baseline verified' if args.verify is not None else 'Baseline frozen', bundle['baseline_sha256'])
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print('Baseline failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
