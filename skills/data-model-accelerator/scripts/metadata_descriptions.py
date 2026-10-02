"""One deterministic description projection for dbt, native SQL and handoffs."""
import re

PLACEHOLDER = re.compile(r'^(?:todo|tbd|none|null|no description|unknown(?:\b.*)?)[.!]?$', re.I)


def meaningful_description(record):
    return bool(record['description'].strip()) and not PLACEHOLDER.fullmatch(record['description'].strip())


def relation_description(record):
    return record['description'].rstrip() + '\n\nGrain: ' + record['grain'].strip()


def column_description(record):
    value = record['description'].rstrip()
    units = record['units'].strip()
    if units.lower() not in {'identifier', 'none', 'n/a', 'not applicable', 'unitless', 'unknown'} and not units.upper().startswith('UNKNOWN:'):
        value += '\n\nUnits: ' + units
    return value
