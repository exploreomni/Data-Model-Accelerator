"""Modeling-standard lints for a domain review: table classification, duplicated grains, placement,
level-mixing fallbacks, topic reach of gold tables and semantic description language.

The lints read review page data (``domain_review_page`` page data, before or after ``normalise``):
``models``, ``topics``, ``decisions``, ``files`` and ``meta``. They are static and heuristic. A finding
is a prompt for a recorded decision, not proof of a defect; a passing report is not proof of a
correct model. Standard library only, plus the optional YAML parser for semantic files.

A finding is resolved by a recorded decision (status answered or assumed) whose area names the lint
and whose models include every table the finding names:

==========================  ==========================  =====
lint                        resolving decision area      gate
==========================  ==========================  =====
period_keyed_dimension      Classification               no
same_grain_overlap          Same grain                   yes
placement                   Placement                    no
level_mixing_fallback       (decision ID in SQL comment) yes
gold_without_topic          Topic exemption              yes
description_language        (none: fix the text)         yes
==========================  ==========================  =====

Gate lints fail promotion of a review draft (``domain_review_page.promote``).
"""
import argparse
import itertools
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from omni_contract import _load as load_omni_yaml, yaml
from omni_inventory import is_omni_file
from omni_query_views import _identity

LINTS = {
    'period_keyed_dimension': {'label': 'Dimensions keyed by a date or period', 'area': 'classification', 'gate': False},
    'same_grain_overlap': {'label': 'Gold tables at one grain repeating columns', 'area': 'same grain', 'gate': True},
    'placement': {'label': 'Logic placed in the other layer', 'area': 'placement', 'gate': False},
    'level_mixing_fallback': {'label': 'Fallbacks mixing hierarchy levels', 'area': None, 'gate': True},
    'gold_without_topic': {'label': 'Gold tables not reached by a topic', 'area': 'topic exemption', 'gate': True},
    'description_language': {'label': 'Semantic description language', 'area': None, 'gate': True},
}
RESOLVING_STATUSES = ('answered', 'assumed')

PERIOD_WORDS = ('date', 'day', 'week', 'month', 'quarter', 'year', 'period', 'snapshot', 'dt', 'ts')
HISTORY_WORDS = ('valid_from', 'valid_to', 'effective_from', 'effective_to', 'row_valid_from')
GRAIN_PERIOD = re.compile(r'\bper\s+(?:calendar\s+|fiscal\s+)?(?:day|date|week|month|quarter|year|period|snapshot)\b', re.I)
CALENDAR_GRAIN = re.compile(r'(?:one row per |one record per )?(?:calendar|fiscal) (?:date|day|week|month|quarter|year|period)', re.I)

LEVEL_TOKEN = re.compile(r'(?:^|_)(?:lvl|level|l|description|desc|code|name|tier)_?(\d+)(?:_|$)', re.I)
DESCRIPTIVE_TOKEN = re.compile(r'(?:^|_)(?:description|desc|code|name|label|category|segment|group|section|division)(?:_|$)', re.I)
FALLBACK_FUNCTIONS = {'COALESCE', 'IFNULL', 'NVL'}
SQL_IDENTIFIER = r'(?:[a-zA-Z_][\w$]*|"(?:""|[^"])*"|`(?:``|[^`])*`|\[(?:\]\]|[^\]])+\])'
SQL_COLUMN = re.compile(rf'(?:{SQL_IDENTIFIER}\s*\.\s*)*(?P<name>{SQL_IDENTIFIER})\Z')
SQL_MORE_ON_LINE = re.compile(r'[^\S\n]*\S')
SQL_TOKEN = re.compile(
    r'(?P<comment>--[^\n]*|/\*.*?(?:\*/|\Z))'
    r'|(?P<literal>\$(?P<tag>[A-Za-z_]\w*|)\$.*?\$(?P=tag)\$'
    r"|'(?:''|\\.|[^'\\])*(?:'|\Z)|\{\{.*?\}\}|\{%.*?%\}|\{\#.*?\#\})"
    rf'|(?P<identifier>{SQL_IDENTIFIER})|(?P<space>\s+)|.', re.S)
FALLBACK_DESCRIPTION = re.compile(r'\b(?:fallbacks?|coalesce|ifnull|nvl|mix(?:ed|ing)? (?:hierarchy )?levels)\b', re.I)

RATIO_SQL = re.compile(r'\bSAFE_DIVIDE\s*\(|\bDIV0(?:NULL)?\s*\(|/\s*NULLIF\s*\(', re.I)
DISTINCT_SQL = re.compile(r'\bCOUNT\s*\(\s*DISTINCT\b', re.I)
WINDOW_SQL = re.compile(r'\b(?:RANK|DENSE_RANK|ROW_NUMBER|NTILE|PERCENT_RANK)\s*\(', re.I)
WHEN_SQL = re.compile(r'\bWHEN\b', re.I)

DESCRIPTION_KEYS = ('description', 'label', 'group_label', 'ai_context', 'sample_queries', 'synonyms', 'view_label')
DEFAULT_PATTERNS = (
    ('legacy BI tool', r'\blook(?:er|ml)\b'),
    ('legacy reference', r'\blegacy\b'),
    ('migration note', r'\bmigrat(?:e|ed|es|ing|ion|ions)\b'),
    ('provisional status', r'\bprovisional\b'),
    ('dashboard or tile number', r'\b(?:dashboards?|tiles?|looks?|explores?)\s*#?\s*\d+\b'),
    ('ticket ID', r'\b(?!ISO-)[A-Z][A-Z0-9]{1,9}-\d{1,6}\b'),
)


# ---------------------------------------------------------------- helpers

def _columns(model):
    """(name, key) pairs from page-model ``cols`` rows or review ``columns`` objects."""
    out = []
    for col in model.get('cols') or model.get('columns') or []:
        if isinstance(col, (list, tuple)):
            out.append((str(col[0]), str(col[2] if len(col) > 2 else '') or ''))
        elif isinstance(col, dict):
            out.append((str(col.get('name')), str(col.get('key') or '')))
    return out


def _is_key(key):
    return key.upper() in ('PK', 'FK', 'PRIMARY', 'FOREIGN', 'UK', 'UNIQUE')


def _primary(model):
    return [name for name, key in _columns(model) if key.upper() in ('PK', 'PRIMARY')]


def _tokens(name):
    return [t for t in re.split(r'[^a-z0-9]+', name.lower()) if t]


def _gold(page, *, own_domain_only=True):
    domain = (page.get('meta') or {}).get('domain')
    return [m for m in page.get('models') or [] if m.get('layer') == 'gold'
            and (not own_domain_only or not domain or m.get('domain') in (None, '', domain))]


def _resolved(page, lint, model_ids):
    area = LINTS[lint]['area']
    if area is None:
        return None
    for decision in page.get('decisions') or []:
        if str(decision.get('status')).lower() not in RESOLVING_STATUSES:
            continue
        if str(decision.get('area') or '').strip().lower() != area:
            continue
        if set(model_ids) <= set(decision.get('models') or decision.get('model_ids') or []):
            return decision.get('id')
    return None


def _finding(page, lint, message, models=(), path=None, line=None):
    row = {'lint': lint, 'message': message, 'models': list(models)}
    if path:
        row['path'] = path
    if line:
        row['line'] = line
    row['resolved_by'] = _resolved(page, lint, models) if models else None
    return row


def _sql_files(page):
    return [f for f in page.get('files') or [] if f.get('path', '').endswith('.sql')]


def _model_sql(page):
    """Map each model to its packaged code, with a unique stem fallback for older pages."""
    files = {row['path']: row for row in _sql_files(page)}
    by_stem = {}
    for path in files:
        by_stem.setdefault(PurePosixPath(path).stem, []).append(path)
    mapped = {}
    for model in page.get('models') or []:
        paths = [model['code']] if model.get('code') else by_stem.get(model['id'], [])
        if len(paths) == 1 and paths[0] in files:
            mapped[model['id']] = files[paths[0]]
    return mapped


def _strip_comments(sql):
    return re.sub(r'--[^\n]*', '', re.sub(r'/\*.*?\*/', '', sql, flags=re.S))


def _semantic_files(page):
    rows = []
    target = (page.get('meta') or {}).get('semantic_target') or {}
    for row in page.get('files') or []:
        path = PurePosixPath(row.get('path') or '')
        kind, _ = _identity(path)
        if kind not in ('view', 'topic', 'model', 'relationships'):
            continue
        if path.suffix in ('.yaml', '.yml') and path.stem == kind:
            # model.yml and relationships.yaml are also ordinary framework filenames.
            folders = {part.lower() for part in path.parts[:-1]}
            if kind not in ('model', 'relationships'):
                continue
            if not folders.intersection({'omni', '03_omni', 'semantic'}):
                warehouse = row.get('kind') in ('dbt', 'warehouse') or folders.intersection(
                    {'dbt', 'coalesce', 'native_sql', '02_dbt', '02_warehouse', '02_implementation', '04_code_generation'})
                if warehouse or (target.get('platform') != 'omni' and not is_omni_file(str(path), row.get('content'))):
                    continue
        rows.append(row)
    return rows


def _load(row):
    """Return the bounded Omni document or a reason the language gate is unverified."""
    if yaml is None:
        return None, 'PyYAML is unavailable. Install the pinned YAML dependency and rerun the check.'
    kind, _ = _identity(row['path'])
    if not isinstance(row.get('content'), str):
        return None, 'The packaged file has no text content.'
    try:
        doc = load_omni_yaml(row['content'])
    except (ValueError, yaml.YAMLError, TypeError, OverflowError, RecursionError):
        return None, 'The bounded Omni YAML parser could not read this file. Check its syntax and supported constructs.'
    expected = list if kind == 'relationships' else dict
    if not isinstance(doc, expected):
        return None, 'Expected a YAML sequence of relationships.' if kind == 'relationships' else 'Expected a YAML mapping.'
    return doc, None


# ---------------------------------------------------------------- lints

def period_keyed_dimensions(page):
    """Flag entity-by-period dimensions while retaining calendar and history dimensions."""
    out = []
    for model in _gold(page):
        model_id = model.get('id') or ''
        name = re.split(r'__|\.', model_id.lower())[-1]
        if not (name.startswith('dim_') or name.endswith('_dim') or model.get('type') == 'dimension') or 'historical' in name:
            continue
        entity = name.removeprefix('dim_').removesuffix('_dim')
        grain = (model.get('grain') or '').strip().rstrip('.')
        if (re.fullmatch(r'(?:(?:calendar|fiscal)_)?(?:calendar|date|day|week|month|quarter|year)', entity)
                or CALENDAR_GRAIN.fullmatch(grain)):
            continue
        reasons = []
        for name in _primary(model):
            if any(h in name.lower() for h in HISTORY_WORDS):
                continue
            hits = [t for t in _tokens(name) if t in PERIOD_WORDS]
            if hits:
                reasons.append(f'primary key {name}')
        if GRAIN_PERIOD.search(model.get('grain') or '') or GRAIN_PERIOD.search(model.get('desc') or model.get('description') or ''):
            reasons.append('grain per period')
        if reasons:
            out.append(_finding(page, 'period_keyed_dimension',
                                f'{model_id}: {", ".join(reasons)}. A table at entity x period grain is a periodic snapshot '
                                '(a fact, factless when it holds no measures). Keep attribute history in a type 2 '
                                'dimension or a mini-dimension, or record a Classification decision.', [model_id]))
    return out


def same_grain_overlaps(page, *, min_shared=3, min_share=0.5):
    """Gold tables at one grain that repeat each other's non-key columns."""
    gold = _gold(page)

    def signature(model):
        grain = ' '.join(_tokens(model.get('grain') or ''))
        if grain in ('unknown', 'unspecified', 'tbd', 'not provided', 'not specified', 'unassessed',
                     'one row per id', 'one row per record', 'one row per entity'):
            grain = ''
        keys = frozenset(name.lower() for name in _primary(model))
        # Technical keys and timestamps occur on unrelated entities throughout a warehouse.
        generic = {'id', 'pk', 'key', 'sk', 'uuid', 'row', 'record', 'surrogate', 'business', *PERIOD_WORDS}
        entity_key = any(set(_tokens(key)) - generic for key in keys)
        return grain, keys if entity_key else frozenset()

    out = []
    signatures = {model['id']: signature(model) for model in gold}
    for a, b in itertools.combinations(gold, 2):
        (ga, ka), (gb, kb) = signatures[a['id']], signatures[b['id']]
        same_grain = ga == gb if ga and gb else bool(ka and ka == kb)
        if not same_grain:
            continue
        cols_a = {n for n, k in _columns(a) if not _is_key(k)}
        cols_b = {n for n, k in _columns(b) if not _is_key(k)}
        shared = cols_a & cols_b
        smaller = min(len(cols_a), len(cols_b)) or 1
        if len(shared) >= min_shared and len(shared) / smaller >= min_share:
            out.append(_finding(page, 'same_grain_overlap',
                                f'{a["id"]} and {b["id"]} share a grain and {len(shared)} non-key columns '
                                f'({len(shared) * 100 // smaller}% of the smaller table). Keep one, merge them, or record '
                                'a Same grain decision naming both.', [a['id'], b['id']]))
    return out


@dataclass
class _FallbackCall:
    name: str
    line: int
    arg_start: int
    args: list = field(default_factory=list)
    comments: list = field(default_factory=list)


def _calls(sql):
    """Read executable fallback calls and attach each SQL comment to at most one call."""
    calls, stack, active = [], [], []
    previous_name = trailing = None
    preceding = []
    line, code_on_line = 1, False
    for token in SQL_TOKEN.finditer(sql):
        value = token.group()
        start_line = line
        line += value.count('\n')
        if preceding and preceding[-1][0] < start_line - 1:
            preceding.clear()
        if token.lastgroup == 'space':
            if line != start_line:
                code_on_line = False
            continue
        if token.lastgroup == 'comment':
            comment = value[2:-2] if value.endswith('*/') and value.startswith('/*') else value[2:]
            if active:
                active[-1].comments.append(comment)
            elif trailing and trailing[1] == start_line:
                # A trailing comment belongs to the previous expression, never the next line.
                between = sql[trailing[2]:token.start()].strip()
                if between.endswith(',') and value.startswith('/*') and SQL_MORE_ON_LINE.match(sql, token.end()):
                    preceding.append((line, False, comment))
                elif ',' not in between.rstrip(',;') and ';' not in between.rstrip(',;'):
                    trailing[0].comments.append(comment)
            else:
                # A comment after other SQL can introduce a call on this line only.
                preceding.append((line, not code_on_line, comment))
            if line != start_line:
                code_on_line = False
            continue
        code_on_line = True
        if value == '(':
            call = None
            if previous_name:
                name, name_line = previous_name
                call = _FallbackCall(name, name_line, token.end())
                call.comments.extend(text for end_line, standalone, text in preceding
                                     if end_line == name_line or (standalone and end_line == name_line - 1))
                preceding.clear()
                active.append(call)
            stack.append(call)
        elif value in (',', ')') and stack:
            call = stack[-1]
            if call is not None:
                call.args.append(sql[call.arg_start:token.start()].strip())
                call.arg_start = token.end()
            if value == ')':
                stack.pop()
                if call is not None:
                    calls.append(call)
                    active.pop()
                    trailing = (call, line, token.end())
        elif value == ';':
            preceding.clear()
        name = value.upper() if token.lastgroup == 'identifier' else ''
        previous_name = (name, start_line) if name in FALLBACK_FUNCTIONS else None
    return calls


def _level(arg):
    """Hierarchy level of a column argument (``None`` when unleveled), or ``False`` when not a descriptive column."""
    if '/*' in arg or '--' in arg:
        arg = ''.join(' ' if t.lastgroup == 'comment' else t.group() for t in SQL_TOKEN.finditer(arg))
    ident = SQL_COLUMN.fullmatch(arg.strip())
    if not ident:
        return False
    name = ident['name'].strip('`"[]').split('.')[-1]
    level = LEVEL_TOKEN.search(name)
    if level:
        return int(level.group(1))
    return None if DESCRIPTIVE_TOKEN.search(name) else False


def _fallback_decisions(page, models):
    decisions = {}
    for decision in page.get('decisions') or []:
        if decision.get('status') not in RESOLVING_STATUSES:
            continue
        scoped = set(decision.get('models') or decision.get('model_ids') or [])
        if scoped and (not models or not set(models) <= scoped):
            continue
        answer = ' '.join(str(decision.get(key) or '') for key in ('assumed', 'answer', 'assumed_option', 'detail')).strip()
        area = str(decision.get('area') or '').strip().lower()
        question = decision.get('q') or decision.get('question') or ''
        if not answer or not (area == 'hierarchy fallback'
                              or (area == 'definition' and FALLBACK_DESCRIPTION.search(f'{question} {answer}'))):
            continue
        key = decision.get('id')
        if isinstance(key, str) and key.strip():
            decisions[key] = re.compile(r'(?<![\w./-])' + re.escape(key) + r'(?![\w/-]|\.\w)')
    return decisions


def level_mixing_fallbacks(page):
    """COALESCE/IFNULL/NVL over columns of different hierarchy levels, with scoped decision evidence."""
    out = []
    models_by_path = {}
    for model_id, row in _model_sql(page).items():
        models_by_path.setdefault(row['path'], []).append(model_id)
    for row in _sql_files(page):
        path = row['path']
        model_ids = models_by_path.get(path, [])
        decisions = _fallback_decisions(page, model_ids)
        for call in _calls(row.get('content') or ''):
            levels = {level for level in map(_level, call.args) if level is not False}
            if len(levels) < 2:
                continue
            finding = _finding(page, 'level_mixing_fallback',
                               f'{call.name}({", ".join(call.args)}) mixes hierarchy levels. Cite a recorded hierarchy '
                               'fallback decision in a SQL comment beside the expression or remove the fallback.',
                               models=model_ids, path=path, line=call.line)
            finding['resolved_by'] = next((key for key, pattern in decisions.items()
                                           if any(pattern.search(c) for c in call.comments)), None)
            out.append(finding)
    return out


def placement(page):
    """Query-time aggregations stored in gold, and fixed reporting rules computed in the semantic layer."""
    out = []
    gold_ids = {m['id'] for m in _gold(page, own_domain_only=False)}
    for model_id, row in _model_sql(page).items():
        if model_id not in gold_ids:
            continue
        sql = _strip_comments(row.get('content') or '')
        kinds = [label for label, pattern in (('ratio', RATIO_SQL), ('distinct count', DISTINCT_SQL)) if pattern.search(sql)]
        if kinds:
            out.append(_finding(page, 'placement',
                                f'{model_id} stores a {" and ".join(kinds)}. Ratios, distinct counts and other query-time '
                                'aggregations belong in the semantic layer unless a Placement decision records why not.',
                                [model_id], path=row['path']))
    if not _omni_review_in_scope(page):
        return out
    view_models = {}
    for topic in page.get('topics') or []:
        for node in topic.get('nodes') or []:
            if node.get('view_id') and node.get('model_ids'):
                view_models.setdefault(node['view_id'], set()).update(node['model_ids'])
    for row in _semantic_files(page):
        kind, view_id = _identity(row['path'])
        if kind != 'view':
            continue
        doc, error = _load(row)
        if error or not isinstance(doc.get('dimensions'), dict):
            continue
        for name, field in doc['dimensions'].items():
            sql = str((field or {}).get('sql') or '') if isinstance(field, dict) else ''
            rule = 'window function' if WINDOW_SQL.search(sql) else ('grouping' if len(WHEN_SQL.findall(sql)) >= 3 else None)
            if rule:
                models = sorted(view_models.get(view_id) or [])
                out.append(_finding(page, 'placement',
                                    f'{view_id}.{name} computes a fixed {rule} at query time. Fixed reporting rules (flags, '
                                    'rankings, groupings) belong in the warehouse unless a Placement decision records why not.',
                                    models, path=row['path']))
    return out


def _omni_review_in_scope(page):
    meta = page.get('meta') or {}
    stages = meta.get('requested_stages')
    if meta.get('migration_scope') == 'model_only' or (stages is not None and 'semantic' not in stages):
        return False
    platform = (meta.get('semantic_target') or {}).get('platform')
    if platform:
        return platform == 'omni'
    if meta.get('migration_scope') in ('model_semantic', 'full_dashboard'):
        return True
    # Older drafts did not store intake scope. Use the packaged semantic evidence.
    return bool(page.get('topics') or _semantic_files(page))


def gold_without_topic(page):
    """Own-domain gold tables that no topic reaches through an explicit binding."""
    if not _omni_review_in_scope(page):
        return []
    reached = {m for t in page.get('topics') or [] for n in t.get('nodes') or []
               if n.get('binding_status') == 'complete' for m in n.get('model_ids') or []}
    return [_finding(page, 'gold_without_topic',
                     f'{m["id"]} is not reached by any topic. Add it to a topic or record a Topic exemption decision '
                     'naming it, with the reason.', [m['id']])
            for m in _gold(page) if m['id'] not in reached]


def description_language(page, *, extra_terms=()):
    """Business-facing text in semantic files must not carry migration or legacy references."""
    patterns = [(label, re.compile(p, re.I if label != 'ticket ID' else 0)) for label, p in DEFAULT_PATTERNS]
    patterns += [('legacy system name', re.compile(r'\b' + re.escape(t) + r'\b', re.I)) for t in extra_terms if t]
    out = []

    def walk(node, trail):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, trail + [str(key)])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                yield from walk(value, trail + [str(i)])
        elif isinstance(node, str) and any(k in DESCRIPTION_KEYS for k in trail):
            yield '.'.join(trail), node

    for row in _semantic_files(page):
        doc, error = _load(row)
        if error:
            finding = _finding(page, 'description_language',
                               f'{row["path"]}: semantic description language unverified. {error}', path=row['path'])
            finding['assessment'] = 'unverified'
            out.append(finding)
            continue
        for where, text in walk(doc, []):
            for label, pattern in patterns:
                match = pattern.search(text)
                if match:
                    out.append(_finding(page, 'description_language',
                                        f'{PurePosixPath(row["path"]).name} {where}: {label} "{match.group(0)}". '
                                        'Descriptions are business-facing; keep migration notes in the design documents.',
                                        path=row['path']))
    return out


# ---------------------------------------------------------------- report

def lint_page(page, *, extra_terms=()):
    """All lints over page data. Returns ``{'status', 'findings', 'summary'}``; status fails on an unresolved gate lint.

    Legacy system names come from ``extra_terms`` and the page's ``meta.legacy_terms``.
    """
    extra_terms = list(extra_terms) + list((page.get('meta') or {}).get('legacy_terms') or [])
    omni_in_scope = _omni_review_in_scope(page)
    findings = (period_keyed_dimensions(page) + same_grain_overlaps(page) + placement(page)
                + level_mixing_fallbacks(page) + gold_without_topic(page))
    if omni_in_scope:
        findings.extend(description_language(page, extra_terms=extra_terms))
    for row in findings:
        row['gate'] = LINTS[row['lint']]['gate']
    open_gate = [f for f in findings if f['gate'] and not f['resolved_by']]
    summary = {lint: {'label': spec['label'], 'gate': spec['gate'],
                      'applicable': omni_in_scope or lint not in ('gold_without_topic', 'description_language'),
                      'open': sum(f['lint'] == lint and not f['resolved_by'] for f in findings),
                      'resolved': sum(f['lint'] == lint and bool(f['resolved_by']) for f in findings)}
               for lint, spec in LINTS.items()}
    return {'status': 'fail' if open_gate else 'pass', 'findings': findings, 'summary': summary}


def static_rows(report):
    """Rows for the review page's static observations: one per lint, counting unresolved findings."""
    rows = []
    for lint, spec in LINTS.items():
        if not report['summary'][lint]['applicable']:
            rows.append({'label': spec['label'], 'count': 0, 'of': 'Omni is outside this review scope', 'items': []})
            continue
        items = [f['message'] for f in report['findings'] if f['lint'] == lint and not f['resolved_by']]
        resolved = report['summary'][lint]['resolved']
        rows.append({'label': spec['label'], 'count': len(items),
                     'of': ('gate: blocks promotion' if spec['gate'] else 'advisory')
                           + (f'; {resolved} resolved by recorded decisions' if resolved else ''),
                     'items': items})
    return rows


def require_gate(report):
    open_gate = [f for f in report['findings'] if f['gate'] and not f['resolved_by']]
    if open_gate:
        raise ValueError('Modeling gate failed: ' + '; '.join(f['message'] for f in open_gate[:5])
                         + (f' (and {len(open_gate) - 5} more)' if len(open_gate) > 5 else ''))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('page', help='Page data JSON or a rendered START_HERE.html')
    parser.add_argument('--legacy-term', action='append', default=[], help='Legacy system name to ban in descriptions')
    parser.add_argument('--output', help='Write the JSON report here')
    args = parser.parse_args(argv)
    text = Path(args.page).read_text(encoding='utf-8')
    if args.page.endswith('.html'):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from domain_review_page import page_data
        page = page_data(text)
    else:
        page = json.loads(text)
    report = lint_page(page, extra_terms=args.legacy_term)
    body = json.dumps(report, indent=1)
    if args.output:
        Path(args.output).write_text(body + '\n', encoding='utf-8')
    for lint, row in report['summary'].items():
        if not row['applicable']:
            print(f"{row['label']}: outside this review scope")
            continue
        print(f"{row['label']}: {row['open']} open, {row['resolved']} resolved{' (gate)' if row['gate'] else ''}")
    for finding in report['findings']:
        if finding.get('assessment') == 'unverified':
            print(finding['message'])
    print('status:', report['status'])
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
