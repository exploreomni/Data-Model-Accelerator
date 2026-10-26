#!/usr/bin/env python3
"""Deterministic pre-review checks for authored dbt SQL. Read-only; nothing is compiled or executed.

Run these before an independent review so the reviewer can focus on logic and assumptions:

* column existence: every qualified reference ``alias.column`` resolves to an output column of the
  CTE or ``ref()``'d model the alias points to (candidate models first, then an optional read-only
  upstream project);
* key contracts: declared shared keys exist in every listed model and are built the declared way;
  the same key column built differently in two models is reported;
* foreign-key populations: a foreign key's target filters (WHERE / QUALIFY) must be acknowledged,
  so rows excluded from the target cannot silently become dangling keys;
* value domains: string literals compared to a column are checked against supplied distinct values.

The parser is a bounded, dialect-light reader of dbt model files. Jinja control flow is flattened,
macro arguments are read as SQL expressions, and anything it cannot resolve is counted as
unresolved coverage rather than passed. A clean report is not compilation, execution or data evidence.
"""
import argparse
import json
from pathlib import Path
import re
import sys

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 5000
ERROR_CODES = {'column.missing', 'key.missing', 'key.construction_mismatch', 'fk.model_missing',
               'fk.column_missing', 'literal.unknown_value'}
_KEYWORDS = set('''select from where as on and or not is in null true false join left right inner outer full cross using
group order by having limit qualify with union all distinct case when then else end cast safe_cast over partition rows
range between asc desc interval exists like if coalesce nullif struct array unnest window except replace'''.split())
_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'


def _need(ok, message):
    if not ok:
        raise ValueError(message)


# ---------------------------------------------------------------------------------------------- text
def _strip(text):
    """Remove comments and resolve dbt relations to placeholder tokens; keep literals."""
    text = re.sub(r'{#.*?#}', ' ', text, flags=re.S)
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r"--[^\n]*", ' ', text)
    text = re.sub(r"{{\s*ref\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?\s*\)\s*}}",
                  lambda m: ' __ref__' + (m.group(2) or m.group(1)) + ' ', text)
    text = re.sub(r"{{\s*source\([^)]*\)\s*}}", ' __source__ ', text)
    text = re.sub(r'{%-?\s*(?:config|set|endset|if|elif|else|endif|for|endfor|macro|endmacro)\b.*?-?%}', ' ', text, flags=re.S)
    text = re.sub(r'{{\s*config\(.*?\)\s*}}', ' ', text, flags=re.S)

    def macro(m):
        body = m.group(1)
        quoted = re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", body)
        args = [a or b for a, b in quoted]
        return ' (' + ', '.join(args) + ') ' if args else ' __macro__ '
    return re.sub(r'{{(.*?)}}', macro, text, flags=re.S)


def _blank_literals(text):
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)


def _split_top(text, sep=','):
    parts, depth, cur, quote = [], 0, [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote: quote = None
            continue
        if ch in "'\"`":
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(''.join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append(''.join(cur))
    return [p.strip() for p in parts if p.strip()]


def _matching(text, start):
    """Index after the parenthesis that closes text[start] == '('."""
    depth, quote = 0, None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote: quote = None
            continue
        if ch in "'\"`": quote = ch
        elif ch == '(': depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0: return i + 1
    return len(text)


def _ctes(text):
    """[(name, body)] for top-level CTEs plus ('__final__', final query)."""
    out = []
    m = re.search(r'\bwith\b', text, re.I)
    if not m:
        return [('__final__', text)]
    pos = m.end()
    while True:
        cm = re.compile(r'\s*,?\s*(' + _IDENT + r')\s+as\s*\(', re.I).match(text, pos)
        if not cm:
            break
        start = cm.end() - 1
        end = _matching(text, start)
        out.append((cm.group(1).lower(), text[start + 1:end - 1]))
        pos = end
    out.append(('__final__', text[pos:]))
    return out


def _depth_zero_keyword(text, word, start=0):
    depth, quote = 0, None
    pattern = re.compile(r'\b' + word + r'\b', re.I)
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote: quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and pattern.match(text, i) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == '_')):
            return i
        i += 1
    return -1


def _select_parts(query):
    """[(select_list, from_clause)] for each UNION branch of a query body."""
    branches, rest = [], query
    while True:
        s = _depth_zero_keyword(rest, 'select')
        if s < 0:
            break
        f = _depth_zero_keyword(rest, 'from', s)
        u = _depth_zero_keyword(rest, 'union', s)
        if f < 0 or (0 <= u < f):
            sel = rest[s + 6:u if u >= 0 else len(rest)]; frm = ''
        else:
            sel = rest[s + 6:f]
            frm = rest[f + 4:u if u >= 0 else len(rest)]
        branches.append((re.sub(r'^\s*distinct\b', '', sel, flags=re.I), frm))
        if u < 0:
            break
        rest = rest[u + 5:]
    return branches


def _relations(from_clause):
    """alias -> relation name for FROM/JOIN items at depth 0 (subqueries are opaque)."""
    rels = {}
    flat = []
    depth = 0
    for ch in from_clause:
        if ch == '(': depth += 1
        if depth == 0: flat.append(ch)
        else: flat.append(' ')
        if ch == ')': depth -= 1
    flat = ''.join(flat)
    for m in re.finditer(r'(?:^|\bfrom\b|\bjoin\b|,)\s*(' + _IDENT + r')(?:\s+(?:as\s+)?(' + _IDENT + r'))?', ' ' + flat, re.I):
        name = m.group(1)
        if name.lower() in _KEYWORDS:
            continue
        alias = m.group(2) if m.group(2) and m.group(2).lower() not in _KEYWORDS else name
        rels[alias.lower()] = name.lower()
    return rels


def _item_name(item):
    a = re.search(r'\bas\s+(' + _IDENT + r')\s*$', item, re.I)
    if a:
        return a.group(1).lower(), item[:a.start()].strip()
    b = re.fullmatch(r'(?:(' + _IDENT + r')\.)?(' + _IDENT + r')', item.strip())
    if b:
        return b.group(2).lower(), item.strip()
    star = re.fullmatch(r'(?:(' + _IDENT + r')\.)?\*', item.strip())
    if star:
        return '*', (star.group(1) or '').lower()
    return None, item


# --------------------------------------------------------------------------------------- the project
class Project:
    def __init__(self, roots):
        self.files = {}
        self.order = []
        for priority, root in enumerate(roots):
            root = Path(root)
            _need(root.is_dir(), 'Model root is not a directory: ' + str(root))
            paths = sorted(p for p in root.rglob('*.sql') if p.is_file() and not p.is_symlink())
            _need(len(paths) <= MAX_FILES, 'Too many model files; narrow the root')
            for p in paths:
                name = p.stem.lower()
                if name in self.files:
                    continue  # earlier roots (the candidate) win over later ones (upstream)
                _need(p.stat().st_size <= MAX_FILE_BYTES, 'Model file too large: ' + str(p))
                self.files[name] = {'path': str(p), 'root': priority, 'raw': p.read_text(encoding='utf-8', errors='replace')}
                self.order.append(name)
        self._parsed = {}
        self._outputs = {}

    def parsed(self, model):
        if model not in self._parsed:
            text = _strip(self.files[model]['raw'])
            ctes = []
            for name, body in _ctes(text):
                branches = _select_parts(body)
                ctes.append({'name': name, 'body': body, 'branches': branches})
            self._parsed[model] = ctes
        return self._parsed[model]

    def outputs(self, model, stack=()):
        """Output columns of a model, or None when they cannot be resolved."""
        model = model.lower()
        if model not in self.files:
            return None
        if model in self._outputs:
            return self._outputs[model]
        if model in stack:
            return None
        ctes = self.parsed(model)
        result = self._cte_columns(model, ctes, '__final__', stack + (model,))
        self._outputs[model] = result
        return result

    def _cte_columns(self, model, ctes, cte_name, stack, seen=()):
        by = {c['name']: c for c in ctes}
        cte = by.get(cte_name)
        if cte is None or not cte['branches'] or cte_name in seen:
            return None
        sel, frm = cte['branches'][0]
        rels = _relations(frm)
        cols = []
        for item in _split_top(sel):
            name, ref = _item_name(item)
            if name is None:
                return None
            if name == '*':
                targets = ([rels[ref]] if ref in rels else []) if ref else list(dict.fromkeys(rels.values()))
                if not targets:
                    return None  # star over a subquery, macro or unknown alias: unresolved, never empty
                for t in targets:
                    expanded = self.relation_columns(model, ctes, t, stack, seen + (cte_name,))
                    if expanded is None:
                        return None
                    cols.extend(c for c in expanded if c not in cols)
            else:
                cols.append(name)
        return cols

    def relation_columns(self, model, ctes, relation, stack, seen=()):
        relation = relation.lower()
        if relation.startswith('__ref__'):
            return self.outputs(relation[7:], stack)
        if relation == '__source__':
            return None
        names = {c['name'] for c in ctes}
        if relation in names:
            return self._cte_columns(model, ctes, relation, stack, seen)
        return None

    def defining_expression(self, model, column, cte_name='__final__', seen=()):
        """Expression that defines an output column, following SELECT * through local CTEs."""
        ctes = self.parsed(model)
        by = {c['name']: c for c in ctes}
        cte = by.get(cte_name)
        if cte is None or not cte['branches'] or cte_name in seen:
            return None
        sel, frm = cte['branches'][0]
        rels = _relations(frm)
        for item in _split_top(sel):
            name, expr = _item_name(item)
            if name == column.lower():
                return expr
            if name == '*':
                targets = [rels[expr]] if expr in rels else [] if expr else list(dict.fromkeys(rels.values()))
                for t in targets:
                    if t in by:
                        found = self.defining_expression(model, column, t, seen + (cte_name,))
                        if found is not None:
                            return found
        return None

    def filters(self, model):
        """WHERE / QUALIFY predicates anywhere in the model (normalised whitespace)."""
        out = []
        text = _strip(self.files[model]['raw'])
        for m in re.finditer(r'\b(where|qualify)\b', text, re.I):
            end = len(text)
            for stop in (r'\bgroup\s+by\b', r'\border\s+by\b', r'\bqualify\b', r'\bunion\b', r'\bwindow\b', r'\)\s*,\s*' + _IDENT + r'\s+as\s*\(', r'\)\s*select\b'):
                s = re.search(stop, text[m.end():], re.I)
                if s:
                    end = min(end, m.end() + s.start())
            depth, cut = 0, end
            for i in range(m.end(), end):
                if text[i] == '(':
                    depth += 1
                elif text[i] == ')':
                    if depth == 0:
                        cut = i; break
                    depth -= 1
            out.append(m.group(1).upper() + ' ' + ' '.join(text[m.end():cut].split()))
        return out


# ------------------------------------------------------------------------------------------ checks
def check_columns(project, models):
    findings, stats = [], {'qualified_references': 0, 'verified': 0, 'unresolved_relations': 0}
    for model in models:
        ctes = project.parsed(model)
        for cte in ctes:
            for sel, frm in cte['branches'] or [('', '')]:
                rels = _relations(frm)
                body = _blank_literals(cte['body'] if cte['name'] != '__final__' else sel + ' from ' + frm)
                for m in re.finditer(r'(?<![\w.])(' + _IDENT + r')\.(' + _IDENT + r')\b(?!\s*\()', body):
                    alias, col = m.group(1).lower(), m.group(2).lower()
                    if alias not in rels:
                        continue
                    stats['qualified_references'] += 1
                    columns = project.relation_columns(model, ctes, rels[alias], (model,))
                    if columns is None:
                        stats['unresolved_relations'] += 1
                        continue
                    if col in columns:
                        stats['verified'] += 1
                    else:
                        findings.append({'code': 'column.missing', 'severity': 'error', 'model': model, 'cte': cte['name'],
                                         'reference': alias + '.' + col, 'relation': rels[alias].replace('__ref__', 'ref:')})
    unique = {json.dumps(f, sort_keys=True): f for f in findings}
    return list(unique.values()), stats


def _norm_expr(expr):
    """Construction shape: columns become x and literals ?, so only how a key is built is compared."""
    expr = re.sub(r"'(?:[^'\\]|\\.)*'", "'?'", (expr or '').lower())
    expr = re.sub(r'\b' + _IDENT + r'\.(' + _IDENT + r')\b', r'\1', expr)
    expr = re.sub(r'\b(' + _IDENT + r')\b(?!\s*\()',
                  lambda m: m.group(1) if m.group(1) in _KEYWORDS or m.group(1) in ('string', 'int64', 'date', 'timestamp') else 'x', expr)
    return ' '.join(expr.split())


def check_keys(project, contract):
    findings = []
    for key in contract.get('keys', []):
        _need(isinstance(key, dict) and isinstance(key.get('column'), str) and isinstance(key.get('models'), list),
              'keys[] needs column and models')
        pattern = re.compile(key['pattern'], re.I | re.S) if key.get('pattern') else None
        for model in key['models']:
            model = model.lower()
            cols = project.outputs(model)
            if cols is None or key['column'].lower() not in cols:
                findings.append({'code': 'key.missing', 'severity': 'error', 'key': key.get('id', key['column']),
                                 'model': model, 'column': key['column']})
                continue
            expr = project.defining_expression(model, key['column'])
            if pattern and expr is not None and not pattern.search(expr):
                findings.append({'code': 'key.construction_mismatch', 'severity': 'error', 'key': key.get('id', key['column']),
                                 'model': model, 'column': key['column'], 'expected_pattern': key['pattern']})
    return findings


def check_divergent_keys(project, models, suffixes=('_natural_key', '_key', '_fk')):
    """Same key column built in differently shaped ways in different models (input names may differ)."""
    seen = {}
    for model in models:
        for col in project.outputs(model) or []:
            if not col.endswith(suffixes):
                continue
            expr = project.defining_expression(model, col)
            if expr is None or re.fullmatch(r'(?:' + _IDENT + r'\.)?' + _IDENT, expr.strip()):
                continue  # pass-through or rename of an upstream column
            seen.setdefault(col, {}).setdefault(_norm_expr(expr), []).append(model)
    return [{'code': 'key.divergent_definition', 'severity': 'warning', 'column': col,
             'definitions': [{'models': sorted(ms), 'expression': e[:300]} for e, ms in sorted(defs.items())]}
            for col, defs in sorted(seen.items()) if len(defs) > 1]


def check_foreign_keys(project, contract):
    findings = []
    for fk in contract.get('foreign_keys', []):
        _need(isinstance(fk, dict) and all(isinstance(fk.get(k), str) for k in ('model', 'column', 'target_model', 'target_column')),
              'foreign_keys[] needs model, column, target_model and target_column')
        model, target = fk['model'].lower(), fk['target_model'].lower()
        for m, c in ((model, fk['column']), (target, fk['target_column'])):
            cols = project.outputs(m)
            if m not in project.files:
                findings.append({'code': 'fk.model_missing', 'severity': 'error', 'model': m}); continue
            if cols is not None and c.lower() not in cols:
                findings.append({'code': 'fk.column_missing', 'severity': 'error', 'model': m, 'column': c})
        if target not in project.files:
            continue
        chain, filters, queue = set(), [], [target]
        for depth in range(int(fk.get('depth', 3))):
            nxt = []
            for m in queue:
                if m in chain or m not in project.files:
                    continue
                chain.add(m)
                filters += [m + ': ' + f for f in project.filters(m)]
                nxt += re.findall(r'__ref__(' + _IDENT + r')', _strip(project.files[m]['raw']))
            queue = [n.lower() for n in nxt]
        if filters and not fk.get('population_resolution'):
            findings.append({'code': 'fk.population_unconfirmed', 'severity': 'warning', 'model': model,
                             'column': fk['column'], 'target_model': target, 'target_filters': filters[:20],
                             'action': 'Confirm every row the key can hold survives these filters, or resolve keys through the '
                                       'target itself; record the answer as population_resolution.'})
    return findings


def check_literals(project, models, contract):
    known = {k.lower(): set(v) for k, v in (contract.get('known_values') or {}).items()}
    findings, occurrences = [], 0
    for model in models:
        text = _strip(project.files[model]['raw'])
        for m in re.finditer(r'(?:(' + _IDENT + r')\.)?(' + _IDENT + r')\s*(=|!=|<>|\bnot\s+in\b|\bin\b)\s*(\(\s*\'[^)]*\)|\'(?:[^\'\\]|\\.)*\')', text, re.I):
            col = m.group(2).lower()
            if col in _KEYWORDS:
                continue
            values = re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(4))
            for value in values:
                occurrences += 1
                if col in known and value not in known[col]:
                    findings.append({'code': 'literal.unknown_value', 'severity': 'error', 'model': model, 'column': col,
                                     'value_length': len(value), 'value_preview': value[:40]})
                elif col not in known:
                    findings.append({'code': 'literal.unverified', 'severity': 'info', 'model': model, 'column': col,
                                     'value_preview': value[:40]})
    unique = {json.dumps(f, sort_keys=True): f for f in findings}
    return list(unique.values()), occurrences


def run(model_roots, contract=None, scope=None):
    """model_roots: candidate root first, then read-only upstream roots. scope: model names to check (default: first root)."""
    contract = contract or {}
    _need(isinstance(contract, dict) and contract.get('schema_version', SCHEMA_VERSION) == SCHEMA_VERSION, 'Unsupported contract')
    project = Project(model_roots)
    models = [m.lower() for m in scope] if scope else [m for m in project.order if project.files[m]['root'] == 0]
    col_findings, stats = check_columns(project, models)
    lit_findings, literal_count = check_literals(project, models, contract)
    findings = (col_findings + check_keys(project, contract) + check_divergent_keys(project, models)
                + check_foreign_keys(project, contract) + lit_findings)
    unresolved_outputs = sorted(m for m in models if project.outputs(m) is None)
    errors = [f for f in findings if f['severity'] == 'error']
    warnings = [f for f in findings if f['severity'] == 'warning']
    return {'schema_version': SCHEMA_VERSION, 'kind': 'sql_contract_check',
            'status': 'failed' if errors else 'warnings' if warnings else 'passed',
            'models_checked': len(models), 'models_with_unresolved_outputs': unresolved_outputs,
            'coverage': dict(stats, literal_occurrences=literal_count),
            'counts': {s: sum(f['severity'] == s for f in findings) for s in ('error', 'warning', 'info')},
            'findings': findings,
            'qualification': 'Static, bounded parse of dbt SQL only. Unqualified references, subqueries, dynamic Jinja and '
                             'unresolved relations are coverage gaps, not passes. No compilation, execution or data check.'}


def summary_line(report):
    c = report['counts']
    return ('sql contracts: %s · %d models · %d errors · %d warnings · %d/%d qualified references verified'
            % (report['status'], report['models_checked'], c['error'], c['warning'],
               report['coverage']['verified'], report['coverage']['qualified_references']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--models', required=True, help='Candidate models root (checked)')
    parser.add_argument('--upstream', action='append', default=[], help='Read-only upstream models root(s) for resolution')
    parser.add_argument('--contract', help='JSON with keys, foreign_keys and known_values')
    parser.add_argument('--output', help='Write the full report here (new file); the console gets one summary line')
    args = parser.parse_args(argv)
    contract = json.loads(Path(args.contract).read_text()) if args.contract else None
    report = run([args.models] + args.upstream, contract)
    if args.output:
        out = Path(args.output)
        _need(not out.exists(), 'Output exists; choose a new path')
        out.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
        print(summary_line(report))
    else:
        print(json.dumps(report, indent=1, sort_keys=True))
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
