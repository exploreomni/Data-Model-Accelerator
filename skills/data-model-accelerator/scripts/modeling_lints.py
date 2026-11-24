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
from pathlib import Path, PurePosixPath

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

LINTS = {
    'period_keyed_dimension': {'label': 'Dimensions keyed by a date or period', 'area': 'classification', 'gate': False},
    'same_grain_overlap': {'label': 'Gold tables at one grain repeating columns', 'area': 'same grain', 'gate': True},
    'placement': {'label': 'Logic placed in the other layer', 'area': 'placement', 'gate': False},
    'level_mixing_fallback': {'label': 'Fallbacks mixing hierarchy levels', 'area': None, 'gate': True},
    'gold_without_topic': {'label': 'Gold tables not reached by a topic', 'area': 'topic exemption', 'gate': True},
    'description_language': {'label': 'Semantic descriptions with migration language', 'area': None, 'gate': True},
}
RESOLVING_STATUSES = ('answered', 'assumed')

PERIOD_WORDS = ('date', 'day', 'week', 'month', 'quarter', 'year', 'period', 'snapshot', 'dt', 'ts')
HISTORY_WORDS = ('valid_from', 'valid_to', 'effective_from', 'effective_to', 'row_valid_from')
GRAIN_PERIOD = re.compile(r'\bper\s+(?:calendar\s+|fiscal\s+)?(?:day|date|week|month|quarter|year|period|snapshot)\b', re.I)

LEVEL_TOKEN = re.compile(r'(?:^|_)(?:lvl|level|l|description|desc|code|name|tier)_?(\d)(?:_|$)', re.I)
DESCRIPTIVE_TOKEN = re.compile(r'(?:^|_)(?:description|desc|code|name|label|category|segment|group|section|division)(?:_|$)', re.I)
DECISION_ID = re.compile(r'\b(?:D|DEC)-\d+\b')

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
    """Model id -> SQL text, by packaged file stem."""
    by_stem = {PurePosixPath(f['path']).stem: f for f in _sql_files(page)}
    return {m['id']: by_stem[m['id']] for m in page.get('models') or [] if m.get('id') in by_stem}


def _strip_comments(sql):
    return re.sub(r'--[^\n]*', '', re.sub(r'/\*.*?\*/', '', sql, flags=re.S))


def _semantic_files(page):
    return [f for f in page.get('files') or [] if f.get('path', '').endswith(('.view', '.topic'))
            or '/03_omni/' in '/' + f.get('path', '') and f.get('path', '').endswith(('.yaml', '.yml'))]


def _load(text):
    if yaml is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - YAML errors are reported by the static checks
        return None


# ---------------------------------------------------------------- lints

def period_keyed_dimensions(page):
    """A ``_dim`` whose key or stated grain includes a date or period is a periodic snapshot, not a dimension."""
    out = []
    for model in _gold(page):
        model_id = model.get('id') or ''
        if not (model_id.endswith('_dim') or model.get('type') == 'dimension') or 'historical' in model_id:
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
        grain = re.sub(r'\s+', ' ', (model.get('grain') or '').strip().lower().rstrip('.'))
        return grain or None, tuple(sorted(_primary(model)))

    out = []
    for a, b in itertools.combinations(gold, 2):
        (ga, ka), (gb, kb) = signature(a), signature(b)
        if not ((ga and ga == gb) or (ka and ka == kb)):
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


def _calls(sql, name):
    """Top-level argument lists of every ``name(...)`` call, with the line of the call."""
    out = []
    for match in re.finditer(r'\b' + name + r'\s*\(', sql, re.I):
        depth, start, args, current = 1, match.end(), [], ''
        for ch in sql[start:]:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    args.append(current)
                    break
            if ch == ',' and depth == 1:
                args.append(current); current = ''
            else:
                current += ch
        out.append((sql.count('\n', 0, match.start()) + 1, [a.strip() for a in args]))
    return out


def _level(arg):
    """Hierarchy level of a column argument (``None`` when unleveled), or ``False`` when not a descriptive column."""
    ident = re.fullmatch(r'[A-Za-z_][\w.`"]*', arg.strip())
    if not ident:
        return False
    name = arg.strip().strip('`"').split('.')[-1].strip('`"')
    level = LEVEL_TOKEN.search(name)
    if level:
        return int(level.group(1))
    return None if DESCRIPTIVE_TOKEN.search(name) else False


def level_mixing_fallbacks(page):
    """COALESCE/IFNULL/NVL over columns of different hierarchy levels, without a decision ID beside it."""
    out = []
    decision_ids = {str(d.get('id')) for d in page.get('decisions') or []}
    for row in _sql_files(page):
        raw = row.get('content') or ''
        lines = raw.split('\n')
        clean = '\n'.join(line.split('--')[0] for line in lines)
        for func in ('COALESCE', 'IFNULL', 'NVL'):
            for line, args in _calls(clean, func):
                levels = [_level(a) for a in args]
                described = [lv for lv in levels if lv is not False]
                leveled = {lv for lv in described if lv is not None}
                if len(described) < 2 or not leveled or (len(leveled) == 1 and None not in described):
                    continue
                nearby = ' '.join(lines[max(0, line - 2):line + 1])
                cited = [d for d in DECISION_ID.findall(nearby) if d in decision_ids]
                finding = _finding(page, 'level_mixing_fallback',
                                   f'{func}({", ".join(args)}) mixes hierarchy levels. Reproduce or decline it through a '
                                   'decision and cite the decision ID in a SQL comment beside it; never copy it silently.',
                                   path=row['path'], line=line)
                finding['resolved_by'] = cited[0] if cited else None
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
    view_models = {}
    for topic in page.get('topics') or []:
        for node in topic.get('nodes') or []:
            if node.get('view_id') and node.get('model_ids'):
                view_models.setdefault(node['view_id'], set()).update(node['model_ids'])
    for row in _semantic_files(page):
        if not row['path'].endswith('.view'):
            continue
        doc = _load(row.get('content') or '')
        if not isinstance(doc, dict):
            continue
        view_id = PurePosixPath(row['path']).stem
        for name, field in (doc.get('dimensions') or {}).items():
            sql = str((field or {}).get('sql') or '') if isinstance(field, dict) else ''
            rule = 'window function' if WINDOW_SQL.search(sql) else ('grouping' if len(WHEN_SQL.findall(sql)) >= 3 else None)
            if rule:
                models = sorted(view_models.get(view_id) or [])
                out.append(_finding(page, 'placement',
                                    f'{view_id}.{name} computes a fixed {rule} at query time. Fixed reporting rules (flags, '
                                    'rankings, groupings) belong in the warehouse unless a Placement decision records why not.',
                                    models, path=row['path']))
    return out


def gold_without_topic(page):
    """Own-domain gold tables that no topic reaches through an explicit binding."""
    reached = {m for t in page.get('topics') or [] for n in t.get('nodes') or [] for m in n.get('model_ids') or []}
    reached |= {m for t in page.get('topics') or [] for m in t.get('base_model_ids') or []}
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
        doc = _load(row.get('content') or '')
        for where, text in walk(doc, []) if doc is not None else []:
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
    findings = (period_keyed_dimensions(page) + same_grain_overlaps(page) + placement(page)
                + level_mixing_fallbacks(page) + gold_without_topic(page) + description_language(page, extra_terms=extra_terms))
    for row in findings:
        row['gate'] = LINTS[row['lint']]['gate']
    open_gate = [f for f in findings if f['gate'] and not f['resolved_by']]
    summary = {lint: {'label': spec['label'], 'gate': spec['gate'],
                      'open': sum(f['lint'] == lint and not f['resolved_by'] for f in findings),
                      'resolved': sum(f['lint'] == lint and bool(f['resolved_by']) for f in findings)}
               for lint, spec in LINTS.items()}
    return {'status': 'fail' if open_gate else 'pass', 'findings': findings, 'summary': summary}


def static_rows(report):
    """Rows for the review page's static observations: one per lint, counting unresolved findings."""
    rows = []
    for lint, spec in LINTS.items():
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
        print(f"{row['label']}: {row['open']} open, {row['resolved']} resolved{' (gate)' if row['gate'] else ''}")
    print('status:', report['status'])
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
