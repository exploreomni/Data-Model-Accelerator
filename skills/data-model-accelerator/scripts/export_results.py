"""Serialize already-fetched DB-API rows under a frozen benchmark contract.

This module does not execute SQL, obtain credentials, or write files. Successful
serialization validates the complete supplied population, not its provenance or
whether the caller fetched every row from the database.
"""
from collections.abc import Mapping, Set
from datetime import date, datetime
from decimal import Decimal
from itertools import islice
import math

from ae_common import require
from freeze_benchmark import validate_columns, validate_rows


MAX_ROWS = 100_000


def _ordered_iterator(value, label):
    require(not isinstance(value, (str, bytes, bytearray, Mapping, Set)),
            label + ' must be an ordered iterable')
    try:
        return iter(value)
    except TypeError as error:
        raise ValueError(label + ' must be an ordered iterable') from error


def _exact_width(value, width, label):
    # Read at most one excess item, even if a malformed row is an iterator.
    items = list(islice(_ordered_iterator(value, label), width + 1))
    require(len(items) == width, label + ' width must exactly match declared columns')
    return items


def _serialize_value(value, kind, name):
    if value is None:
        return None  # Nullability and nonnull keys are checked by validate_rows.
    if kind == 'decimal':
        if type(value) is Decimal:
            require(value.is_finite(), 'Nonfinite decimal in ' + name)
            return str(value)
        if type(value) is float:
            require(math.isfinite(value), 'Nonfinite decimal in ' + name)
            return str(value)
        if type(value) in (int, str):
            return str(value)
    elif kind == 'integer':
        if type(value) is int:
            return value
        if type(value) is Decimal:
            require(value.is_finite() and value == value.to_integral_value(),
                    'Expected a finite integral Decimal in ' + name)
            return int(value)
    elif kind == 'string':
        if type(value) is str:
            return value
        if type(value) is datetime:
            return value.isoformat(sep=' ')
        if type(value) is date:
            return value.isoformat()
    elif kind == 'boolean' and type(value) is bool:
        return value
    raise ValueError('Unsupported DB-API value type for ' + name + ' (' + kind + ')')


def serialize_rows(description, rows, columns, keys):
    """Return validated row dictionaries from positional DB-API result rows.

    ``description`` contains DB-API column descriptors; only each descriptor's
    first item (its exact column name) is used. Column order may differ from the
    contract, but missing, extra, duplicate or case-changed names are rejected.
    ``rows`` may be a generator. More than MAX_ROWS raises ValueError rather
    than truncating the population; full row widths and composite keys are
    checked, including an empty result's column/key contract.

    Decimal columns accept Decimal, finite float, int, or an already-serialized
    numeric string. Decimal/string precision is preserved; floats use Python's
    shortest round-trip representation, without quantizing or claiming to
    recover precision already lost by the driver. The existing benchmark
    validator enforces decimal-string syntax and bounds. Integer columns accept
    only int or finite integral Decimal, never bool, float or numeric strings.
    String columns also accept date/datetime with their native ISO formatting;
    datetime offsets and naive timestamps are preserved without conversion.
    Boolean columns require bool. Nulls follow the declared contract.
    """
    columns = validate_columns(columns)
    validate_rows([], columns, keys)  # Fail invalid keys before consuming rows.
    descriptors = _exact_width(description, len(columns), 'DB-API description')
    names = []
    for descriptor in descriptors:
        first = list(islice(_ordered_iterator(descriptor, 'Column descriptor'), 1))
        require(first and type(first[0]) is str, 'DB-API column name must be a string')
        names.append(first[0])
    require(len(set(names)) == len(names), 'Duplicate DB-API column names')
    require(set(names) == set(columns), 'DB-API column names must exactly match declared columns')

    serialized = []
    for index, row in enumerate(_ordered_iterator(rows, 'Rows')):
        require(index < MAX_ROWS, 'Row limit exceeded; population was not truncated')
        values = _exact_width(row, len(names), 'DB-API row')
        serialized.append({name: _serialize_value(value, columns[name]['type'], name)
                           for name, value in zip(names, values)})
    return validate_rows(serialized, columns, keys)
