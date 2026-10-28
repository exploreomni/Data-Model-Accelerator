#!/usr/bin/env python3
"""Source-qualified privacy assessment for candidate gold and Omni outputs.

Legacy v1 registers retain explicit exclusion semantics. V2 classifications and
reviewed destination treatments are separate; imports start unresolved. Static
lineage and expression hashes never establish de-identification, active native
controls, disclosure authorization, or deployment approval.
"""
import argparse
import copy
import csv
import json
import hashlib
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


def _normalize_v1(register):
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
        row = {'column': _norm(entry['column']), 'table': entry['table'].strip() if entry.get('table') else None,
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
    return normalize({'schema_version': 2, 'entries': entries, 'treatments': [], 'source_reference': Path(path).name})


def from_dictionary(dictionary):
    """Entries for v2 dictionary columns classified as PII, PCI or PHI."""
    entries = []
    for model in dictionary.get('models', []) + dictionary.get('sources', []):
        for column in model.get('columns', []):
            categories = set((column.get('privacy') or {}).get('categories') or [])
            if categories & SENSITIVE_CATEGORIES and _text(column.get('name')):
                from privacy_contract import new_classification, validate_classification
                classification = copy.deepcopy(column['privacy'])
                if validate_classification(classification):
                    classification = new_classification()
                    classification['categories'] = sorted(categories & SENSITIVE_CATEGORIES)
                entries.append({'column': column['name'], 'table': model.get('name') or model.get('id'),
                                'attribute': ','.join(sorted(categories & SENSITIVE_CATEGORIES)), 'origin': 'classification',
                                'classification': classification})
    return normalize({'schema_version': 2, 'entries': entries, 'treatments': []})


def _merge_v1(*registers):
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


def _check_v1(register, outputs):
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
    try:
        import yaml
    except ImportError:
        return sql_identifiers(text)
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
    return ('Registered personal data treatment or lineage needs review (' + shown + more + '). Review the source-qualified treatment findings; '
            'hashing does not establish de-identification or native access controls. See references/sensitive-data.md.')


def normalize(register):
    """Preserve v1 exclusions; v2 source identities retain punctuation and case."""
    from privacy_contract import new_classification, validate_classification, validate_treatment
    _need(type(register) is dict, 'personal_data: register object required')
    if register.get('schema_version') == 1:
        return _normalize_v1(register)
    _need(type(register.get('schema_version')) is int and register['schema_version'] == 2
          and {'schema_version', 'entries', 'treatments'} <= set(register)
          and set(register) <= {'schema_version', 'entries', 'treatments', 'source_reference', 'legacy_exclusions'},
          'personal_data: schema_version 2 entries and treatments required')
    _need(type(register['entries']) is list and len(register['entries']) <= MAX_ENTRIES, 'personal_data.entries')
    entries = {}
    for entry in register['entries']:
        _need(type(entry) is dict and {'table', 'column', 'origin'} <= set(entry)
              and set(entry) <= {'table', 'column', 'origin', 'attribute', 'classification'}
              and _text(entry['column']) and (entry['table'] is None or _text(entry['table']))
              and entry['origin'] in ORIGINS and (entry.get('attribute') is None or _text(entry['attribute'])),
              'personal_data.entry: source identity and origin required')
        row = copy.deepcopy(entry)
        row['table'] = entry['table'].strip() if entry['table'] else None
        row['column'] = entry['column'].strip()
        row.setdefault('attribute', None)
        classification = row.setdefault('classification', new_classification())
        _need(not validate_classification(classification), 'personal_data.classification')
        key = (row['table'] or '', row['column'], row['origin'])
        _need(key not in entries or entries[key] == row, 'personal_data.conflicting_classification')
        entries[key] = row
    treatments = register['treatments']
    _need(type(treatments) is list and len(treatments) <= MAX_ENTRIES * 2, 'personal_data.treatments')
    normalized, seen = [], set()
    identities = {(e['table'], e['column']) for e in entries.values()}
    for treatment in treatments:
        row = copy.deepcopy(treatment)
        if type(row) is dict: row.setdefault('expression_sha256', None)
        _need(not validate_treatment(row), 'personal_data.treatment')
        identity = (row['source']['table'], row['source']['column'])
        _need(identity in identities, 'personal_data.treatment_source_missing')
        # Distinct expression decisions may coexist for one classified source.
        key = (*identity, row['destination'], row['expression_sha256'])
        _need(key not in seen, 'personal_data.duplicate_treatment')
        seen.add(key); normalized.append(row)
    result = {'schema_version': 2, 'entries': [entries[k] for k in sorted(entries)],
              'treatments': sorted(normalized, key=lambda r: json.dumps(r, sort_keys=True))}
    if register.get('source_reference') is not None:
        _need(_text(register['source_reference'], 4000), 'personal_data.source_reference')
        result['source_reference'] = register['source_reference']
    if 'legacy_exclusions' in register:
        result['legacy_exclusions'] = _normalize_v1(register['legacy_exclusions'])
    return result


def merge(*registers):
    """Imports add evidence; they cannot replace existing treatment decisions."""
    registers = [normalize(r) for r in registers]
    if all(r['schema_version'] == 1 for r in registers):
        return _merge_v1(*registers)
    result = {'schema_version': 2, 'entries': [], 'treatments': []}
    legacy = []
    for register in registers:
        if register['schema_version'] == 1:
            legacy.append(register)
            # Retain explicit exclusions separately, including legacy waivers.
            for row in register['entries']:
                result['entries'].append(dict(row))
        else:
            result['entries'] += register['entries']
            result['treatments'] += register['treatments']
            if register.get('legacy_exclusions'): legacy.append(register['legacy_exclusions'])
    if legacy: result['legacy_exclusions'] = _merge_v1(*legacy)
    return normalize(result)


def _source_matches(entry, source, legacy=False):
    column = bool(match({'entries': [entry]}, source['column'])) if legacy else source['column'] == entry['column']
    return column and (entry['table'] is None or entry['table'] == source['table'])


def _output(output):
    _need(type(output) is dict and all(_text(output.get(k), 4000) for k in ('scope', 'identifier', 'kind')),
          'personal_data.output')
    row = copy.deepcopy(output)
    row.setdefault('destination', 'omni' if row['kind'].startswith('omni') else 'gold')
    _need(row['destination'] in ('gold', 'omni'), 'personal_data.output_destination')
    row.setdefault('source_columns', [])
    row.setdefault('lineage_complete', False)
    _need(type(row['source_columns']) is list and len(row['source_columns']) <= 10000
          and type(row['lineage_complete']) is bool, 'personal_data.output_lineage')
    for source in row['source_columns']:
        _need(type(source) is dict and set(source) == {'table', 'column'} and _text(source['column'])
              and (source['table'] is None or _text(source['table'])), 'personal_data.source_column')
    if any(s['table'] is None for s in row['source_columns']): row['lineage_complete'] = False
    return row


def assess(register, outputs):
    """Value-free candidate impact; unresolved findings do not authorize release."""
    from privacy_contract import evaluate_treatment, new_classification, propagate_classification
    register = normalize(register)
    _need(type(outputs) is list and len(outputs) <= MAX_ENTRIES, 'personal_data.outputs')
    findings, impact = [], []
    legacy = register if register['schema_version'] == 1 else register.get('legacy_exclusions')
    for raw in outputs:
        output = _output(raw); matched = []
        def add(code, status, source=None):
            finding = {k: output[k] for k in ('scope', 'identifier', 'kind', 'destination')}
            finding.update(code=code, status=status, severity='blocking' if status == 'violation' else 'review')
            if source is not None: finding['source'] = source
            findings.append(finding)
        if not output['lineage_complete']: add('lineage.unresolved', 'unresolved')
        legacy_hits = []
        if legacy:
            if output['source_columns']:
                legacy_hits = [e for e in legacy['entries'] if any(_source_matches(e, s, True) for s in output['source_columns'])]
            elif not output['lineage_complete']:
                legacy_hits = match(legacy, output['identifier'], _index(legacy))
            if legacy_hits and not _exempt(legacy, output['identifier'], output['scope']):
                add('legacy.excluded_source_reaches_output', 'violation')
        if register['schema_version'] == 2:
            matched = [entry for entry in register['entries'] if any(_source_matches(entry, s) for s in output['source_columns'])]
            for entry in register['entries']:
                if any(entry['column'].casefold() == s['column'].casefold()
                       and entry['table'] and s['table'] and entry['table'].casefold() == s['table'].casefold()
                       and not _source_matches(entry, s) for s in output['source_columns']):
                    add('source.identifier_case_requires_binding', 'unresolved')
            for entry in matched:
                source = {'table': entry['table'], 'column': entry['column']}
                choices = [t for t in register['treatments'] if t['source'] == source and t['destination'] == output['destination']]
                exact = [t for t in choices if t['expression_sha256'] is not None and t['expression_sha256'] == output.get('expression_sha256')]
                choices = exact or [t for t in choices if t['expression_sha256'] is None]
                if not entry['table']: add('source.identity_unqualified', 'unresolved', source)
                elif len(choices) != 1: add('treatment.unresolved_or_changed', 'unresolved', source)
                else:
                    result = evaluate_treatment(choices[0], output)
                    if result['status'] != 'satisfied':
                        for code in result['reasons']: add(code, result['status'], source)
        classifications = [e['classification'] for e in matched]
        # One source can have several independent evidence origins. Preserve union.
        identities = [json.dumps([e['table'], e['column'], e['origin']]) for e in matched]
        derived = propagate_classification(classifications, identities, output.get('transformation') or 'unknown') if matched else new_classification()
        current = [f for f in findings if f['scope'] == output['scope'] and f['identifier'] == output['identifier']]
        impact.append({k: output[k] for k in ('scope', 'identifier', 'kind', 'destination', 'source_columns', 'lineage_complete')} |
                      {'status': 'violation' if any(f['status'] == 'violation' for f in current) else 'unresolved' if current else 'within_declared_treatment',
                       'sensitivity': derived['sensitivity'], 'categories': derived['categories'],
                       'classification_review_status': derived['review_status'], 'declassified': False,
                       'expression_sha256': output.get('expression_sha256'), 'transformation': output.get('transformation', 'unknown')})
    unique = {json.dumps(f, sort_keys=True): f for f in findings}
    findings = [unique[k] for k in sorted(unique)]
    return {'schema_version': 1, 'kind': 'personal_data_assessment',
            'status': 'violations' if any(f['status'] == 'violation' for f in findings) else 'unresolved' if findings else 'clear',
            'findings': findings, 'impact': impact, 'authorization_authenticated': False, 'native_controls_verified': False,
            'qualification': 'Static assessment of declared sources and treatments only. No automatic declassification, disclosure or deployment authority.'}


def check(register, outputs):
    """Compatibility: name-only v1 callers keep their original exclusion guard."""
    normalized = normalize(register)
    if normalized['schema_version'] == 1 and all('source_columns' not in o and 'lineage_complete' not in o for o in outputs):
        return [dict(f, code='legacy.excluded_identifier', status='violation', severity='blocking') for f in _check_v1(normalized, outputs)]
    return assess(normalized, outputs)['findings']


def _gap(scope, kind, destination, reason, identifier='<unresolved>'):
    return {'scope': scope, 'identifier': identifier, 'kind': kind, 'destination': destination,
            'source_columns': [], 'lineage_complete': False, 'lineage_reasons': [reason],
            'transformation': 'unknown', 'expression_sha256': None}


def sql_outputs(text, scope, kind='gold_code', dialect=None):
    """Bounded projection lineage in supplied SQL only; never resolve/read files.

    CTE aliases are traced locally. Physical stars, ambiguous unqualified columns,
    dynamic templates, correlated/set queries and unavailable parsers stay gaps.
    ref/source identities are their exact static argument paths (versioned refs
    carry @vN); they are not silently mapped to warehouse tables.
    """
    destination = 'omni' if kind.startswith('omni') else 'gold'
    gap = lambda reason: [_gap(scope, kind, destination, reason)]
    if type(text) is not str or len(text.encode()) > 2 * 1024 * 1024: return gap('sql.input_limit')
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.scope import build_scope, Scope
        from authoring_provenance import mask_static_dbt_sql
    except ImportError: return gap('sql.parser_unavailable')
    try:
        masked, calls, gaps = mask_static_dbt_sql(text)
        if gaps: return gap('sql.dynamic_template')
        trees = [t for t in sqlglot.parse(masked, read=dialect, error_message_context=0) if t is not None]
        if len(trees) != 1: return gap('sql.multiple_or_missing_statements')
        tree = trees[0]
        if isinstance(tree, exp.Create): tree = tree.expression
        if not isinstance(tree, exp.Select): return gap('sql.projection_unsupported')
        if sum(1 for _ in tree.walk()) > 25000: return gap('sql.structure_limit')
        root = build_scope(tree)
        if root is None: return gap('sql.scope_unsupported')
        call_map = {c['identifier']: '.'.join(c['arguments']) + (('@v' + str(c['version'])) if c['version'] is not None else '') for c in calls}
        def table_identity(table):
            if table.name in call_map: return call_map[table.name]
            return '.'.join(part.name if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*', part.name)
                            else part.sql(dialect=dialect) for part in table.parts)
        def transformation_of(projection):
            expression = projection.this if isinstance(projection, exp.Alias) else projection
            funcs = {n.sql_name().upper() for n in expression.walk() if isinstance(n, exp.Func)}
            return ('copy' if isinstance(expression, exp.Column) else 'aggregate' if any(isinstance(n, exp.AggFunc) for n in expression.walk())
                    else 'hash' if funcs & {'SHA', 'SHA1', 'SHA2', 'MD5', 'SHA256', 'SHA512'} else 'derive')
        def trace(current, projection, active=()):
            if len(active) > 40 or id(current) in active or current.outer_columns or not isinstance(current.expression, exp.Select):
                return [], False, ['sql.scope_unsupported']
            if projection.is_star or any(isinstance(n, exp.Star) and not isinstance(n.parent, exp.Count) for n in projection.walk()):
                return [], False, ['sql.star_unresolved']
            if any(isinstance(n, (exp.Subquery, exp.Select)) for n in projection.walk()):
                return [], False, ['sql.subquery_unresolved']
            sources, complete, reasons = [], True, []
            observed_transformations.add(transformation_of(projection))
            selected = current.selected_sources
            columns = list(projection.find_all(exp.Column))
            # COUNT(*) depends on row population even with no named projected column.
            if not columns and any(isinstance(n, exp.Star) for n in projection.walk()):
                return [], False, ['sql.row_population_unresolved']
            for column in columns:
                available = [selected[column.table][1]] if column.table in selected else [v[1] for v in selected.values()] if not column.table else []
                if len(available) != 1:
                    sources.append({'table': None, 'column': column.name}); complete = False; reasons.append('sql.column_ambiguous'); continue
                source = available[0]
                if isinstance(source, exp.Table):
                    sources.append({'table': table_identity(source), 'column': column.name})
                elif isinstance(source, Scope):
                    candidates = [p for p in source.expression.selects if p.alias_or_name == column.name]
                    if len(candidates) == 1:
                        refs, ok, gaps = trace(source, candidates[0], (*active, id(current)))
                        sources += refs; complete &= ok; reasons += gaps
                    else:
                        sources.append({'table': None, 'column': column.name}); complete = False; reasons.append('sql.cte_projection_unresolved')
                else: complete = False; reasons.append('sql.relation_unsupported')
            return sources, complete, reasons
        rows = []
        names = [p.alias_or_name for p in tree.selects]
        for number, projection in enumerate(tree.selects):
            identifier = projection.alias_or_name or '<unnamed-' + str(number + 1) + '>'
            observed_transformations = set()
            refs, complete, reasons = trace(root, projection)
            if not projection.alias_or_name or names.count(projection.alias_or_name) != 1: complete = False; reasons.append('sql.output_identity_unresolved')
            transformation = transformation_of(projection)
            underlying = observed_transformations - {'copy'}
            if transformation == 'copy' and underlying:
                transformation = next(iter(underlying)) if len(underlying) == 1 else 'derive'
            refs = [dict(table=t, column=c) for t, c in sorted({(r['table'], r['column']) for r in refs}, key=lambda x: (x[0] or '', x[1]))]
            # Bind all query predicates and template bindings as well as the projection.
            digest = hashlib.sha256(json.dumps([text, scope, identifier, dialect], ensure_ascii=True).encode()).hexdigest()
            rows.append({'scope': scope, 'identifier': identifier, 'kind': kind, 'destination': destination,
                         'source_columns': refs, 'lineage_complete': complete, 'lineage_reasons': sorted(set(reasons)),
                         'transformation': transformation, 'expression_sha256': digest})
        return rows or gap('sql.projection_missing')
    except Exception:
        return gap('sql.parse_or_lineage_unsupported')


def omni_outputs(text, scope):
    """Project local Omni fields; unresolved view references require caller lineage.

    This bounded helper never loads another view or treats a logical view name as
    a physical binding. Callers may replace incomplete sources with checked
    canonical producer lineage before assessment.
    """
    from omni_contract import _load
    try:
        obj = _load(text)
    except Exception:
        return [_gap(scope, 'omni_field', 'omni', 'omni.parser_or_document_unsupported')]
    if type(obj) is not dict: return [_gap(scope, 'omni_field', 'omni', 'omni.document_unsupported')]
    rows = []
    table = obj.get('table_name')
    physical = '.'.join(str(obj[k]) for k in ('catalog', 'schema', 'table_name') if obj.get(k)) if type(table) is str else None
    if 'sql' in obj or 'query' in obj:
        # A query view's physical origin needs the canonical multi-file producer.
        physical = None
    for category in ('dimensions', 'measures', 'filters', 'parameters'):
        fields = obj.get(category) or {}
        if type(fields) is not dict: return [_gap(scope, 'omni_field', 'omni', 'omni.fields_unsupported')]
        for name, definition in fields.items():
            if not _text(name) or type(definition) is not dict:
                rows.append(_gap(scope, 'omni_field', 'omni', 'omni.field_unsupported', str(name))); continue
            expression = definition.get('sql')
            row = _gap(scope, 'omni_field', 'omni', 'omni.canonical_lineage_required', name)
            if expression is None and physical and category == 'dimensions':
                row.update(source_columns=[{'table': physical, 'column': name}], lineage_complete=True, lineage_reasons=[], transformation='copy')
            elif type(expression) is str and '${' not in expression and physical:
                quoted = '"' + name.replace('"', '""') + '"'
                parsed = sql_outputs('SELECT ' + expression + ' AS ' + quoted + ' FROM ' + physical, scope, 'omni_field')
                if len(parsed) == 1: row = dict(parsed[0], identifier=name)
            else:
                row['source_columns'] = [{'table': None, 'column': match[1]} for match in re.findall(r'\$\{([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\}', str(expression or ''))]
            row['expression_sha256'] = hashlib.sha256(json.dumps([text, scope, name], ensure_ascii=True).encode()).hexdigest()
            rows.append(row)
    if not rows and any(k in obj for k in ('base_view', 'extends', 'query', 'sql')):
        rows.append(_gap(scope, 'omni_field', 'omni', 'omni.canonical_lineage_required'))
    return rows


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
    evaluation = sub.add_parser('assess', help='Report candidate treatment findings and downstream impact; never authorize release')
    evaluation.add_argument('--register', required=True)
    evaluation.add_argument('--outputs', required=True, help='JSON projection/lineage records; no raw values needed')
    evaluation.add_argument('--output', help='Optional new report path; report is also printed')
    args = parser.parse_args(argv)
    if args.command == 'assess':
        report = assess(json.loads(Path(args.register).read_text()), json.loads(Path(args.outputs).read_text()))
        if args.output:
            with open(args.output, 'x') as handle:
                handle.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps(report, sort_keys=True))
        return 1 if report['status'] == 'violations' else 0
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
