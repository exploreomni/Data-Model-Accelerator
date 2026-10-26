#!/usr/bin/env python3
"""Personal-data exclusion: registered personal columns never reach gold or Omni.

The register is recorded once as the engagement answer `personal_data`. It holds
columns listed by the user (for example a personal-data inventory CSV) and
columns the accelerator classified as PII/PCI/PHI. Delivery and the Omni handoff
refuse any gold model column, gold implementation identifier or Omni field that
matches an entry. Hashed keys to a dimension use different names and pass.
Matching is name based: it cannot follow a rename it never sees, and it does not
replace warehouse access controls or a privacy review.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
import re
import sys

ORIGINS = {'prompt', 'classification', 'scanner'}
SENSITIVE_CATEGORIES = {'PII', 'PCI', 'PHI'}
# A one-word entry matches only that exact name, unless it is an unambiguous
# identifier word; then it also matches names ending in _<word>.
STRONG_WORDS = {'email', 'phone', 'mobile', 'iban', 'ssn', 'passport', 'surname', 'firstname', 'lastname',
                'dob', 'birthdate', 'postcode', 'zipcode', 'msisdn', 'pan'}
MAX_ENTRIES = 100000
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
SQL_NOISE = re.compile(r"--[^\n]*|/\*.*?\*/|\{#.*?#\}|'(?:''|[^'])*'", re.S)


def _need(ok, message):
    if not ok: raise ValueError(message)


def _norm(name):
    return re.sub(r'[^a-z0-9]+', '_', str(name).strip().lower()).strip('_')


def _text(value, limit=500):
    return type(value) is str and 0 < len(value.strip()) <= limit


def normalize(register):
    """Validate and canonicalise a register; duplicates collapse to one entry."""
    _need(type(register) is dict and register.get('schema_version') == 1
          and set(register) <= {'schema_version', 'entries', 'not_personal_data', 'source_reference'},
          'personal_data: schema_version 1 object with entries required')
    entries = register.get('entries', [])
    _need(type(entries) is list and len(entries) <= MAX_ENTRIES, 'personal_data.entries')
    seen = {}
    for entry in entries:
        _need(type(entry) is dict and set(entry) <= {'column', 'table', 'attribute', 'origin'}
              and _text(entry.get('column')) and entry.get('origin') in ORIGINS
              and all(entry.get(k) is None or _text(entry[k]) for k in ('table', 'attribute')),
              'personal_data.entry: column and origin (prompt, classification, scanner) required')
        row = {'column': _norm(entry['column']), 'table': _norm(entry['table']) if entry.get('table') else None,
               'attribute': entry.get('attribute'), 'origin': entry['origin']}
        _need(bool(row['column']), 'personal_data.entry.column')
        seen[(row['column'], row['table'], row['origin'])] = row
    exemptions = register.get('not_personal_data', [])
    _need(type(exemptions) is list and len(exemptions) <= 10000, 'personal_data.not_personal_data')
    for item in exemptions:
        # A recorded false positive only: the field is not personal data. It is
        # never a way to keep real personal data in the output.
        _need(type(item) is dict and set(item) == {'identifier', 'scope', 'reason', 'reference'}
              and all(_text(item[k], 4000) for k in item), 'personal_data.not_personal_data entry')
    result = {'schema_version': 1, 'entries': [seen[k] for k in sorted(seen, key=lambda k: (k[0], k[1] or '', k[2]))],
              'not_personal_data': sorted(copy.deepcopy(exemptions), key=lambda i: (i['scope'], i['identifier']))}
    if register.get('source_reference') is not None:
        _need(_text(register['source_reference'], 4000), 'personal_data.source_reference')
        result['source_reference'] = register['source_reference']
    return result


def from_csv(path, *, column_field='column_name', table_field='table_name', attribute_field='attribute',
             attributes=None, origin='prompt'):
    """Build register entries from a personal-data inventory CSV.

    attributes optionally restricts rows to the listed attribute values (for
    example CONTACT_EMAIL, NAME_FIRST) when the inventory is broader than the
    personal data the engagement must exclude.
    """
    wanted = None if not attributes else {a.strip().upper() for a in attributes}
    entries = []
    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        _need(reader.fieldnames and column_field in reader.fieldnames, 'personal_data.csv: missing column ' + column_field)
        for row in reader:
            attribute = (row.get(attribute_field) or '').strip() or None
            if wanted is not None and (attribute or '').upper() not in wanted: continue
            if not (row.get(column_field) or '').strip(): continue
            entries.append({'column': row[column_field], 'table': (row.get(table_field) or '').strip() or None,
                            'attribute': attribute, 'origin': origin})
    return normalize({'schema_version': 1, 'entries': entries, 'source_reference': Path(path).name})


def from_dictionary(dictionary):
    """Entries for v2 dictionary columns classified as PII, PCI or PHI."""
    entries = []
    for model in dictionary.get('models', []) + dictionary.get('sources', []):
        for column in model.get('columns', []):
            categories = set((column.get('privacy') or {}).get('categories') or [])
            if categories & SENSITIVE_CATEGORIES and _text(column.get('name')):
                entries.append({'column': column['name'], 'table': model.get('name') or model.get('id'),
                                'attribute': ','.join(sorted(categories & SENSITIVE_CATEGORIES)), 'origin': 'classification'})
    return normalize({'schema_version': 1, 'entries': entries})


def merge(*registers):
    combined = {'schema_version': 1, 'entries': [], 'not_personal_data': []}
    for register in registers:
        register = normalize(register)
        combined['entries'] += register['entries']
        combined['not_personal_data'] += register['not_personal_data']
    unique = {json.dumps(i, sort_keys=True): i for i in combined['not_personal_data']}
    combined['not_personal_data'] = list(unique.values())
    return normalize(combined)


def _index(register):
    exact, suffix = {}, {}
    for entry in register['entries']:
        exact.setdefault(entry['column'], []).append(entry)
        if '_' in entry['column'] or entry['column'] in STRONG_WORDS:
            suffix.setdefault(entry['column'], []).append(entry)
    return exact, suffix


def match(register, identifier, index=None):
    """Register entries an output identifier would expose."""
    exact, suffix = index or _index(register)
    name = _norm(identifier)
    found = list(exact.get(name, []))
    parts = name.split('_')
    for i in range(1, len(parts)):
        found += suffix.get('_'.join(parts[i:]), [])
    return found


def _exempt(register, identifier, scope):
    return any(_norm(i['identifier']) == _norm(identifier) and i['scope'] in (scope, '*') for i in register['not_personal_data'])


def check(register, outputs):
    """outputs: [{scope, identifier, kind}] -> blocking findings (no values)."""
    register = normalize(register)
    index = _index(register); findings = {}
    for output in outputs:
        hits = match(register, output['identifier'], index)
        if hits and not _exempt(register, output['identifier'], output['scope']):
            key = (output['scope'], _norm(output['identifier']))
            findings[key] = {'scope': output['scope'], 'identifier': output['identifier'], 'kind': output['kind'],
                             'matched': sorted({h['column'] for h in hits}),
                             'origins': sorted({h['origin'] for h in hits})}
    return [findings[k] for k in sorted(findings)]


# Keywords and template functions are code, not output columns, even when a
# source happens to have a column with the same name (for example `from`).
KEYWORDS = set('''select from where as on and or not is in null true false join left right inner outer full cross
using group order by having limit qualify with union all distinct case when then else end cast safe_cast over partition
rows range between asc desc interval date timestamp datetime time current_date current_timestamp exists like ilike if
coalesce nullif count sum min max avg extract struct array unnest window to at zone ref source config var this is_incremental
macro endmacro set endset for endfor endif elif do return true false none'''.split())


def sql_identifiers(text):
    """Identifiers in SQL/Jinja/YAML code, ignoring comments, literals and keywords."""
    return {name for name in IDENTIFIER.findall(SQL_NOISE.sub(' ', text)) if name.lower() not in KEYWORDS}


def omni_identifiers(text):
    """Field names and referenced columns in an Omni view/topic; prose is skipped."""
    import yaml
    try:
        obj = yaml.safe_load(text)
    except yaml.YAMLError:
        return sql_identifiers(text)
    found = set()
    def walk(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                if key in ('dimensions', 'measures', 'filters', 'parameters') and isinstance(k, str): found.add(k)
                if k in ('description', 'label', 'ai_context', 'group_label', 'synonyms', 'sample_queries'): continue
                walk(v, k)
        elif isinstance(value, list):
            for v in value: walk(v, key)
        elif isinstance(value, str) and key in ('sql', 'on_sql', 'table_name', 'primary_key', 'always_where_sql'):
            found.update(sql_identifiers(re.sub(r'\$\{\w+\.(\w+)\}', r' \1 ', value)))
    walk(obj)
    return found


def message(findings, limit=12):
    shown = ', '.join(f['scope'] + ': ' + f['identifier'] for f in findings[:limit])
    more = '' if len(findings) <= limit else ' and ' + str(len(findings) - limit) + ' more'
    return ('Registered personal data reaches the output (' + shown + more + '). Remove these columns from gold models '
            'and Omni, or replace them with hashed keys to a dimension. Record not_personal_data only for false positives. '
            'See references/sensitive-data.md#personal-data-exclusion.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    imp = sub.add_parser('import-csv', help='Build a register from a personal-data inventory CSV')
    imp.add_argument('--csv', required=True); imp.add_argument('--output', required=True)
    imp.add_argument('--column-field', default='column_name'); imp.add_argument('--table-field', default='table_name')
    imp.add_argument('--attribute-field', default='attribute'); imp.add_argument('--attribute', action='append')
    dic = sub.add_parser('from-dictionary', help='Add PII/PCI/PHI-classified dictionary columns')
    dic.add_argument('--dictionary', required=True); dic.add_argument('--output', required=True)
    dic.add_argument('--merge', help='Existing register to merge into')
    args = parser.parse_args(argv)
    if args.command == 'import-csv':
        register = from_csv(args.csv, column_field=args.column_field, table_field=args.table_field,
                            attribute_field=args.attribute_field, attributes=args.attribute)
    else:
        register = from_dictionary(json.loads(Path(args.dictionary).read_text()))
        if args.merge: register = merge(json.loads(Path(args.merge).read_text()), register)
    output = Path(args.output)
    _need(not output.exists(), 'Output exists; choose a new path')
    output.write_text(json.dumps(register, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'entries': len(register['entries']), 'output': str(output)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
