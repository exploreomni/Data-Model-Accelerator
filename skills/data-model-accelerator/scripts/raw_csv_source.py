#!/usr/bin/env python3
"""Metadata-only reader for already bounded CSV bytes; never reads paths or executes input.

CSV lexical fields are text, not inferred warehouse types. Header names are
metadata; data values, value examples, formulas and exception text are never
returned. Existing callers own safe filesystem scanning and total byte bounds.
"""
import csv
import hashlib
import io


DEFAULT_MAX_ROWS = 1000000
DEFAULT_MAX_COLUMNS = 2048
DEFAULT_MAX_FIELD_CHARS = 131072


def inspect_csv(data, *, max_rows=DEFAULT_MAX_ROWS, max_columns=DEFAULT_MAX_COLUMNS,
                max_field_chars=DEFAULT_MAX_FIELD_CHARS):
    """Inspect comma-delimited UTF-8/UTF-8-BOM bytes with a required header.

    row_count is exact only after reaching EOF. Malformed/ragged records leave
    metadata_complete false even when their logical record count is known.
    No delimiter sniffing, NULL coercion, formula evaluation or type guessing.
    """
    if not isinstance(data, bytes):
        raise ValueError('CSV input must be already bounded bytes')
    if any(type(n) is not int or n <= 0 for n in (max_rows, max_columns, max_field_chars)):
        raise ValueError('CSV metadata limits must be positive integers')
    result = {
        'schema_version': 1, 'kind': 'raw_csv_metadata',
        'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
        'encoding': 'utf-8-sig', 'delimiter': ',', 'header_required': True,
        'columns': [], 'row_count': None, 'records_observed': 0,
        'metadata_complete': False, 'native_types_verified': False,
        'type_basis': 'CSV fields are lexical text; native database types and null semantics are unknown',
        'grain': 'unknown', 'source_platform': 'unknown',
        'limits': {'max_rows': max_rows, 'max_columns': max_columns,
                   'max_field_chars': max_field_chars},
        'gaps': [],
    }

    def gap(code, **counts):
        result['gaps'].append({'code': code, **counts})

    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        gap('unsupported_encoding')
        return result
    if '\0' in text:
        gap('nul_byte')
        return result
    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    # csv's process-level parser guard is not changed; callers may only impose
    # a stricter per-field bound. A lower runtime guard stays an explicit gap.
    try:
        header = next(reader, None)
        if header is None:
            gap('missing_header')
            return result
        if not header or any(not name.strip() for name in header):
            gap('blank_header')
            return result
        if len(header) > max_columns:
            gap('column_limit', observed_columns=len(header))
            return result
        if any(len(name) > max_field_chars for name in header):
            gap('field_size_limit')
            return result
        result['columns'] = [{'position': i + 1, 'name': name, 'data_type': 'text'}
                             for i, name in enumerate(header)]
        if len(set(header)) != len(header):
            gap('duplicate_headers')
        elif len({name.strip().casefold() for name in header}) != len(header):
            gap('ambiguous_normalized_headers')
        ragged, oversized = 0, 0
        for row in reader:
            if result['records_observed'] == max_rows:
                gap('row_limit', observed_records=max_rows)
                return result
            result['records_observed'] += 1
            ragged += len(row) != len(header)
            oversized += any(len(value) > max_field_chars for value in row)
        result['row_count'] = result['records_observed']
        if ragged:
            gap('ragged_rows', count=ragged)
        if oversized:
            gap('field_size_limit', count=oversized)
        result['metadata_complete'] = not result['gaps']
    except csv.Error:
        # Parser errors may contain input text; retain only a stable code.
        gap('csv_parse_error_or_runtime_field_limit')
    return result
