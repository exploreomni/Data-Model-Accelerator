#!/usr/bin/env python3
"""Bounded, read-only SQL contract evidence; never compile or execute templates.

SQLGlot reads one SELECT/CTE (or CREATE AS SELECT) in the supplied dialect.
Only literal dbt ref/source calls are masked by the existing shared reader.
Unknown relations, stars, templates and syntax stay visible coverage gaps.
"""
import argparse
import copy
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import re
import sys

from authoring_provenance import mask_static_dbt_sql, _Quiet

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
    from sqlglot.optimizer.scope import build_scope, Scope
except ImportError:
    sqlglot = exp = None

SCHEMA_VERSION = 1
VERSION = 'sql-contracts-v2'
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 5000
MAX_NODES = 25000
MAX_DEPTH = 40


def _need(ok, message):
    if not ok: raise ValueError(message)


def validate_contract(value):
    """Validate local declarative rules; the contract supplies no execution code."""
    _need(type(value) is dict and set(value) <= {'schema_version', 'keys', 'foreign_keys', 'known_values'}
          and type(value.get('schema_version', 1)) is int and value.get('schema_version', 1) == 1, 'Unsupported SQL contract')
    for category in ('keys', 'foreign_keys'):
        _need(type(value.get(category, [])) is list and len(value.get(category, [])) <= 2000, category + ' must be a bounded list')
    for key in value.get('keys', []):
        _need(type(key) is dict and set(key) <= {'id', 'column', 'models', 'pattern'}
              and type(key.get('column')) is str and key['column'].strip()
              and type(key.get('models')) is list and key['models']
              and all(type(m) is str and m.strip() for m in key['models']), 'keys[] needs column and models')
        for name in ('id', 'pattern'):
            _need(name not in key or type(key[name]) is str and 0 < len(key[name]) <= 1000, 'Invalid key ' + name)
        if key.get('pattern'):
            try: re.compile(key['pattern'])
            except re.error: raise ValueError('Invalid key pattern') from None
    for fk in value.get('foreign_keys', []):
        _need(type(fk) is dict and set(fk) <= {'model', 'column', 'target_model', 'target_column', 'depth', 'population_resolution'}
              and all(type(fk.get(k)) is str and fk[k].strip() for k in ('model', 'column', 'target_model', 'target_column')),
              'foreign_keys[] needs model, column, target_model and target_column')
        _need(type(fk.get('depth', 3)) is int and 1 <= fk.get('depth', 3) <= MAX_DEPTH, 'Invalid foreign key depth')
        _need(fk.get('population_resolution') is None or type(fk['population_resolution']) is str and bool(fk['population_resolution'].strip()),
              'Invalid population resolution')
    known = value.get('known_values', {})
    _need(type(known) is dict and len(known) <= 2000, 'known_values must be an object')
    for key, vals in known.items():
        _need(type(key) is str and key.strip() and type(vals) is list and len(vals) <= 20000
              and all(type(v) is str for v in vals), 'known_values entries need an identifier and string values')
    return copy.deepcopy(value)


def _safe_pattern(pattern):
    """Literal/anchor/alternation grammar only: no repetition or lookaround."""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == '\\':
            index += 1
            if index >= len(pattern) or pattern[index] not in r'\()[]{}.*+?^$|': return False
        elif char in '()[]{}*+?': return False
        index += 1
    return True


class Project:
    def __init__(self, roots, dialect=None, candidate_paths=None, upstream_paths=None):
        _need(type(roots) in (list, tuple) and roots, 'At least one model root is required')
        self.roots = [Path(root).resolve(strict=True) for root in roots]
        self.dialect = dialect
        self.dialect_supported = True
        self.files, self.order, self._parsed, self._outputs, self.read_evidence = {}, [], {}, {}, {}
        self.gaps = []
        for root in self.roots: _need(root.is_dir(), 'Model root is not a directory')
        if dialect is not None:
            _need(type(dialect) is str and dialect.strip(), 'Invalid SQL dialect')
            if sqlglot is not None:
                try: sqlglot.Dialect.get_or_raise(dialect)
                except ValueError: self.dialect_supported = False
        _need(upstream_paths is None or type(upstream_paths) in (list, dict), 'Invalid upstream paths')
        if type(upstream_paths) is list: _need(len(roots) <= 2 or not upstream_paths, 'Multiple upstream roots need a root-to-paths mapping')
        for index, root in enumerate(self.roots):
            selected = candidate_paths if index == 0 else (upstream_paths.get(str(root), []) if type(upstream_paths) is dict else upstream_paths)
            if selected is None:
                paths = []
                for path in root.rglob('*.sql'):
                    if path.is_file() and not path.is_symlink():
                        _need(len(paths) + len(self.order) < MAX_FILES, 'Too many model files; narrow the registered scope')
                        paths.append(path.relative_to(root).as_posix())
                paths.sort()
            else:
                _need(type(selected) is list and all(type(p) is str for p in selected), 'Registered SQL paths must be a list')
                paths = sorted(set(selected))
            _need(len(paths) + len(self.order) <= MAX_FILES, 'Too many model files; narrow the registered scope')
            for relative in paths:
                part = PurePosixPath(relative)
                _need(not part.is_absolute() and '..' not in part.parts and str(part) == relative and part.suffix.lower() == '.sql', 'Invalid registered SQL path')
                path = root / relative
                _need(not any(p.is_symlink() for p in (path, *path.parents) if p == root or root in p.parents), 'SQL inputs cannot use symlinks')
                _need(path.is_file() and root in path.resolve().parents, 'Registered SQL file missing or outside root')
                name = part.stem
                if name in self.files:
                    _need(self.files[name]['root'] != index, 'Duplicate model identity in one root')
                    continue  # Candidate definitions explicitly take precedence.
                self.files[name] = {'path': path, 'relative': relative, 'root': index}
                self.order.append(name)

    def gap(self, code, model, **details):
        item = {'code': code, 'severity': 'info', 'model': model, **details}
        if item not in self.gaps: self.gaps.append(item)

    def model(self, name):
        if name in self.files: return name
        matches = [m for m in self.files if m.casefold() == name.casefold()]
        return matches[0] if len(matches) == 1 else None

    def identifier(self, name):
        if sqlglot is None or not self.dialect_supported: return name
        # Quoted contract names are parsed as identifiers; a bare name follows
        # the dialect's native folding. Never strip punctuation from names.
        try:
            tree = sqlglot.parse_one('SELECT ' + name, read=self.dialect)
            node = tree.expressions[0]
            if not isinstance(node, exp.Column) or node.table: return name
            return normalize_identifiers(node, dialect=self.dialect).name
        except Exception: return name

    def parsed(self, model):
        if model in self._parsed: return self._parsed[model]
        info = self.files.get(model)
        if info is None:
            self.gap('sql.model_unresolved', model); return None
        _need(info['path'].stat().st_size <= MAX_FILE_BYTES, 'Model file too large')
        with info['path'].open('rb') as stream: body = stream.read(MAX_FILE_BYTES + 1)
        _need(len(body) <= MAX_FILE_BYTES, 'Model file too large')
        self.read_evidence.setdefault(info['root'], {})[info['relative']] = hashlib.sha256(body).hexdigest()
        self._parsed[model] = None
        if sqlglot is None:
            self.gap('sql.parser_unavailable', model); return None
        if not self.dialect_supported:
            self.gap('sql.dialect_unsupported', model); return None
        if self.dialect is None: self.gap('sql.dialect_unspecified', model)
        try:
            text = body.decode('utf-8-sig')
            masked, calls, gaps = mask_static_dbt_sql(text)
            if gaps:
                self.gap('sql.template_unsupported', model); return None
            if len(sqlglot.Dialect.get_or_raise(self.dialect).tokenize(masked)) > MAX_NODES:
                self.gap('sql.structure_limit', model); return None
            logger, quiet = logging.getLogger('sqlglot'), _Quiet()
            logger.addFilter(quiet)
            try:
                trees = [t for t in sqlglot.parse(masked, read=self.dialect, error_message_context=0) if t is not None]
            finally: logger.removeFilter(quiet)
            if len(trees) != 1:
                self.gap('sql.statement_unsupported', model); return None
            tree = trees[0]
            if isinstance(tree, exp.Create): tree = tree.expression
            if not isinstance(tree, exp.Select) or sum(1 for _ in tree.walk()) > MAX_NODES:
                self.gap('sql.query_unsupported', model); return None
            tree = normalize_identifiers(tree, dialect=self.dialect)
            root = build_scope(tree)
            if root is None:
                self.gap('sql.scope_unsupported', model); return None
            call_map = {self.identifier(c['identifier']): c for c in calls}
            self._parsed[model] = {'tree': tree, 'root': root, 'calls': call_map, 'scopes': list(root.traverse())}
            return self._parsed[model]
        except (ValueError, UnicodeError, RecursionError, sqlglot.errors.SqlglotError):
            self.gap('sql.parse_unsupported', model); return None

    def relation(self, model, source):
        """Return (registered model or None, exact logical source identity)."""
        parsed = self.parsed(model)
        call = parsed['calls'].get(source.name) if parsed and isinstance(source, exp.Table) else None
        if call:
            identity = '.'.join(call['arguments']) + ('@v' + str(call['version']) if call['version'] is not None else '')
            # Package/version-qualified refs have no registered package/version
            # mapping in this API. Do not silently select a same-named model.
            target = self.model(call['arguments'][0]) if call['name'] == 'ref' and len(call['arguments']) == 1 and call['version'] is None else None
            return target, ('ref:' if call['name'] == 'ref' else 'source:') + identity
        return None, 'table:' + source.sql(dialect=self.dialect, comments=False) if isinstance(source, exp.Table) else 'unresolved'

    def source_outputs(self, model, source, stack):
        if isinstance(source, Scope): return self.scope_outputs(model, source, stack)
        target, _ = self.relation(model, source)
        if target: return self.output_info(target, stack)
        return {}, False

    def scope_outputs(self, model, scope, stack=()):
        identity = (model, id(scope))
        if identity in stack or len(stack) >= MAX_DEPTH or not isinstance(scope.expression, exp.Select) or scope.outer_columns or scope.is_correlated_subquery:
            self.gap('sql.scope_unsupported', model); return {}, False
        stack = (*stack, identity)
        result, complete = {}, True
        try: selected = scope.selected_sources
        except Exception:
            self.gap('sql.scope_unsupported', model); return {}, False
        for item in scope.expression.expressions:
            if item.is_star:
                if any(v for k, v in (item.this if isinstance(item, exp.Column) else item).args.items() if k != 'this'):
                    self.gap('sql.star_modifier_unsupported', model); complete = False; continue
                qualifier = item.table if isinstance(item, exp.Column) else ''
                targets = [selected[qualifier][1]] if qualifier in selected else list(v[1] for v in selected.values()) if not qualifier else []
                if not targets: complete = False
                for source in targets:
                    columns, known = self.source_outputs(model, source, stack); complete &= known
                    for name, definition in columns.items():
                        if name in result: complete = False; self.gap('sql.output_ambiguous', model, column=name)
                        result[name] = definition
                if not complete: self.gap('sql.star_unresolved', model)
            else:
                name = item.alias_or_name
                if not name or name in result:
                    complete = False; self.gap('sql.output_ambiguous', model, column=name or '<unnamed>')
                else: result[name] = (model, scope, item.this if isinstance(item, exp.Alias) else item)
        return result, complete

    def output_info(self, model, stack=()):
        parsed = self.parsed(model)
        if parsed is None: return {}, False
        # Cache only top-level requests; a recursive cycle must remain unknown.
        if not stack and model in self._outputs: return self._outputs[model]
        result = self.scope_outputs(model, parsed['root'], stack)
        if not stack: self._outputs[model] = result
        return result

    def outputs(self, model):
        found = self.model(model)
        if not found: return None
        columns, complete = self.output_info(found)
        return list(columns) if complete else None

    def defining_expression(self, model, column):
        columns, _ = self.output_info(model)
        definition = columns.get(self.identifier(column))
        return definition[2].sql(dialect=self.dialect, comments=False) if definition else None

    def resolve_column(self, model, scope, column):
        """Resolve one relation; unknown/ambiguous sources never prove absence."""
        try: selected = scope.selected_sources
        except Exception: return None, {}, False
        if column.table:
            if column.table not in selected: return None, {}, False
            source = selected[column.table][1]
            columns, complete = self.source_outputs(model, source, ())
            return source, columns, complete
        if len(selected) == 1:
            source = next(iter(selected.values()))[1]
            columns, complete = self.source_outputs(model, source, ())
            return source, columns, complete
        matches, unknown = [], False
        for _, source in selected.values():
            columns, complete = self.source_outputs(model, source, ())
            unknown |= not complete
            if column.name in columns: matches.append((source, columns, complete))
        return matches[0] if len(matches) == 1 and not unknown else (None, {}, False)

    def binding(self, model, scope, column, seen=()):
        """Logical domain identity through direct projections and local CTEs."""
        token = (model, id(scope), column.sql())
        if token in seen or len(seen) >= MAX_DEPTH: return None
        source, columns, complete = self.resolve_column(model, scope, column)
        if source is None: return None
        if isinstance(source, Scope):
            if not complete: return None
            definition = columns.get(column.name)
            if not definition: return None
            origin, inner, expression = definition
            if isinstance(expression, exp.Column): return self.binding(origin, inner, expression, (*seen, token))
            # A transformed CTE output has a distinct domain; do not borrow its
            # underlying raw source's known values.
            return 'expression:' + model + ':' + hashlib.sha256(inner.expression.sql().encode()).hexdigest() + '.' + column.name
        target, identity = self.relation(model, source)
        if target:
            if not complete or column.name not in columns: return None
            return 'ref:' + target + '.' + column.name
        return identity + '.' + column.name

    def filters(self, model):
        parsed = self.parsed(model)
        if parsed is None: return []
        return [node.sql(dialect=self.dialect, comments=False) for node in parsed['tree'].walk()
                if isinstance(node, (exp.Where, exp.Qualify))]

    def refs(self, model):
        parsed = self.parsed(model)
        if parsed is None: return []
        return [self.model(c['arguments'][0]) for c in parsed['calls'].values()
                if c['name'] == 'ref' and len(c['arguments']) == 1 and c['version'] is None]


def check_columns(project, models):
    findings, stats = [], {'qualified_references': 0, 'verified': 0, 'unresolved_relations': 0}
    for model in models:
        parsed = project.parsed(model)
        if not parsed: continue
        for scope in parsed['scopes']:
            if not isinstance(scope.expression, exp.Select) or scope.is_correlated_subquery:
                project.gap('sql.scope_unsupported', model); continue
            for column in scope.columns:
                if column.is_star: continue
                source, columns, complete = project.resolve_column(model, scope, column)
                if column.table: stats['qualified_references'] += 1
                if source is None or not complete and column.name not in columns:
                    stats['unresolved_relations'] += 1
                    project.gap('column.unresolved', model, reference=column.sql(dialect=project.dialect)); continue
                if column.name in columns:
                    if column.table: stats['verified'] += 1
                elif complete:
                    findings.append({'code': 'column.missing', 'severity': 'error', 'model': model,
                                     'reference': column.sql(dialect=project.dialect)})
    return findings, stats


def check_keys(project, contract):
    findings = []
    for key in contract.get('keys', []):
        supported = not key.get('pattern') or _safe_pattern(key['pattern'])
        pattern = re.compile(key['pattern'], re.I | re.S) if key.get('pattern') and supported else None
        for name in key['models']:
            model = project.model(name)
            if model is None:
                project.gap('key.model_unresolved', name, column=key['column']); continue
            if not supported: project.gap('key.pattern_unsupported', model, column=key['column'])
            cols, complete = project.output_info(model)
            column = project.identifier(key['column'])
            if column not in cols:
                if complete:
                    findings.append({'code': 'key.missing', 'severity': 'error', 'key': key.get('id', key['column']), 'model': model, 'column': key['column']})
                else: project.gap('key.output_unresolved', model, column=key['column'])
                continue
            expression = project.defining_expression(model, key['column'])
            if pattern and expression is not None and not pattern.search(expression):
                findings.append({'code': 'key.construction_mismatch', 'severity': 'error', 'key': key.get('id', key['column']), 'model': model, 'column': key['column'], 'expected_pattern_sha256': hashlib.sha256(key['pattern'].encode()).hexdigest()})
    return findings


def check_divergent_keys(project, models, suffixes=('_natural_key', '_key', '_fk')):
    seen = {}
    for model in models:
        cols, _ = project.output_info(model)
        for col, (_, _, expression) in cols.items():
            if not col.lower().endswith(suffixes) or isinstance(expression, exp.Column): continue
            # SQLGlot canonical formatting preserves exact inputs, qualifiers,
            # quoted identifiers and literals. It is not a SQL equivalence proof.
            canonical = expression.sql(dialect=project.dialect, comments=False)
            seen.setdefault(col, {}).setdefault(canonical, []).append(model)
    return [{'code': 'key.divergent_definition', 'severity': 'warning', 'column': col,
             'definitions': [{'models': sorted(ms), 'expression_sha256': hashlib.sha256(expression.encode()).hexdigest()} for expression, ms in sorted(defs.items())]}
            for col, defs in sorted(seen.items()) if len(defs) > 1]


def check_foreign_keys(project, contract):
    findings = []
    for fk in contract.get('foreign_keys', []):
        model, target = project.model(fk['model']), project.model(fk['target_model'])
        for name, resolved, column in ((fk['model'], model, fk['column']), (fk['target_model'], target, fk['target_column'])):
            if resolved is None:
                project.gap('fk.model_unresolved', name); continue
            cols, complete = project.output_info(resolved)
            if project.identifier(column) not in cols:
                if complete: findings.append({'code': 'fk.column_missing', 'severity': 'error', 'model': resolved, 'column': column})
                else: project.gap('fk.output_unresolved', resolved, column=column)
        if not target: continue
        chain, filters, queue = set(), [], [target]
        for _ in range(fk.get('depth', 3)):
            nxt = []
            for name in queue:
                if name in chain: continue
                chain.add(name)
                filters += [{'model': name, 'clause': value.split(' ', 1)[0],
                             'expression_sha256': hashlib.sha256(value.encode()).hexdigest()} for value in project.filters(name)]
                refs = project.refs(name)
                if None in refs: project.gap('fk.population_unresolved', name)
                nxt.extend(ref for ref in refs if ref is not None and ref not in chain)
            queue = nxt
        if queue: project.gap('fk.population_depth_limit', target)
        if filters and not fk.get('population_resolution'):
            findings.append({'code': 'fk.population_unconfirmed', 'severity': 'warning', 'model': model or fk['model'],
                             'column': fk['column'], 'target_model': target, 'target_filters': filters[:20],
                             'action': 'Review target population and record population_resolution; no referential integrity is proven.'})
    return findings


def check_literals(project, models, contract):
    known = contract.get('known_values', {})
    occurrences = []
    for model in models:
        parsed = project.parsed(model)
        if not parsed: continue
        for scope in parsed['scopes']:
            for node in scope.expression.walk(prune=lambda n: n is not scope.expression and isinstance(n, exp.Query)):
                column, values = None, []
                if isinstance(node, (exp.EQ, exp.NEQ)):
                    if isinstance(node.this, exp.Column) and isinstance(node.expression, exp.Literal): column, values = node.this, [node.expression]
                    elif isinstance(node.expression, exp.Column) and isinstance(node.this, exp.Literal): column, values = node.expression, [node.this]
                elif isinstance(node, exp.In) and isinstance(node.this, exp.Column) and not node.args.get('query'):
                    column, values = node.this, node.expressions
                if column is not None:
                    for literal in values:
                        if isinstance(literal, exp.Literal) and literal.is_string:
                            occurrences.append((model, column.name, project.binding(model, scope, column), literal.this))
    identities, model_identities = {}, {}
    for model, column, identity, _ in occurrences:
        identities.setdefault(column, set()).add(identity)
        model_identities.setdefault((model, column), set()).add(identity)
    findings = []
    for model, column, identity, value in occurrences:
        prefixes = [model]
        if identity:
            prefix = identity.rsplit('.', 1)[0]
            prefixes += [prefix, prefix.split(':', 1)[-1]]
        selected = None
        if identity:
            for prefix in prefixes:
                matches = [key for key in known if '.' in key and key.rsplit('.', 1)[0] == prefix
                           and project.identifier(key.rsplit('.', 1)[1]) == column]
                if matches and prefix == model and len(model_identities[(model, column)]) != 1:
                    project.gap('literal.domain_ambiguous', model, column=column); continue
                if len(matches) == 1:
                    selected = matches[0]; break
                if len(matches) > 1:
                    project.gap('literal.domain_ambiguous', model, column=column); break
        legacy = [key for key in known if '.' not in key and project.identifier(key) == column]
        if selected is None and legacy:
            if len(legacy) == 1 and None not in identities[column] and len(identities[column]) == 1:
                selected = legacy[0]
            else: project.gap('literal.domain_ambiguous', model, column=column)
        detail = {'model': model, 'column': column, 'value_length': len(value),
                  'value_sha256': hashlib.sha256(value.encode()).hexdigest()}
        if selected is not None and value not in known[selected]:
            findings.append({'code': 'literal.unknown_value', 'severity': 'error', **detail, 'domain': selected})
        elif selected is None:
            findings.append({'code': 'literal.unverified', 'severity': 'info', **detail})
            project.gap('literal.domain_unresolved', model, column=column)
    return findings, len(occurrences)


def run(model_roots, contract=None, scope=None, dialect=None, candidate_paths=None, upstream_paths=None):
    """Read selected SQL and registered dependencies, candidate root first.

    Path lists are exact relative files; [] means none, None uses bounded CLI
    discovery. A list of upstream_paths supports one upstream root; multiple
    roots use {absolute_root: [relative_paths]}. Empty scope never means all.
    Evidence maps contain only files actually read, with SHA256 of those bytes.
    """
    contract = validate_contract({} if contract is None else contract)
    project = Project(model_roots, dialect, candidate_paths, upstream_paths)
    _need(scope is None or type(scope) is list and all(type(m) is str for m in scope), 'Invalid model scope')
    models = [m for m in project.order if project.files[m]['root'] == 0] if scope is None else []
    for name in scope or []:
        model = project.model(name)
        if model and model not in models: models.append(model)
        elif not model: project.gap('sql.model_unresolved', name)
    if not models:
        project.gap('sql.scope_empty', '<scope>')
        findings, stats, literal_count = [], {'qualified_references': 0, 'verified': 0, 'unresolved_relations': 0}, 0
    else:
        col_findings, stats = check_columns(project, models)
        lit_findings, literal_count = check_literals(project, models, contract)
        findings = col_findings + check_keys(project, contract) + check_divergent_keys(project, models) + check_foreign_keys(project, contract) + lit_findings
    unresolved_outputs = sorted(m for m in models if project.outputs(m) is None)
    findings += project.gaps
    findings = list({json.dumps(f, sort_keys=True): f for f in findings}.values())
    errors = any(f['severity'] == 'error' for f in findings)
    warnings = any(f['severity'] == 'warning' for f in findings)
    status = ('failed' if errors else 'not_run' if not models else 'unsupported' if sqlglot is None or not project.dialect_supported else
              'partial' if project.gaps or unresolved_outputs else 'warnings' if warnings else 'passed')
    return {'schema_version': SCHEMA_VERSION, 'kind': 'sql_contract_check', 'version': VERSION, 'dialect': dialect,
            'status': status, 'models_checked': len(models), 'models_with_unresolved_outputs': unresolved_outputs,
            'coverage': dict(stats, literal_occurrences=literal_count, gaps=len(project.gaps)),
            'counts': {s: sum(f['severity'] == s for f in findings) for s in ('error', 'warning', 'info')},
            'findings': findings, 'candidate_evidence': project.read_evidence.get(0, {}),
            'source_evidence': project.read_evidence.get(1, {}),
            'root_evidence': {str(index): evidence for index, evidence in project.read_evidence.items() if index > 1},
            'qualification': 'Static SQL evidence only. Unknown schemas, dynamic templates, unsupported syntax and unresolved domains are gaps. No compilation, execution, data validation or SQL equivalence is proven.'}


def summary_line(report):
    c = report['counts']
    return ('sql contracts: %s · %d models · %d errors · %d warnings · %d/%d qualified references verified'
            % (report['status'], report['models_checked'], c['error'], c['warning'],
               report['coverage']['verified'], report['coverage']['qualified_references']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', required=True, help='Candidate models root (checked)')
    parser.add_argument('--upstream', action='append', default=[], help='Read-only upstream models roots')
    parser.add_argument('--dialect', help='SQLGlot dialect, such as snowflake or bigquery')
    parser.add_argument('--contract', help='JSON with keys, foreign_keys and known_values')
    parser.add_argument('--output', help='Write a new report file')
    args = parser.parse_args(argv)
    contract = json.loads(Path(args.contract).read_text()) if args.contract else None
    report = run([args.models] + args.upstream, contract, dialect=args.dialect)
    if args.output:
        with open(args.output, 'x') as stream: stream.write(json.dumps(report, indent=1, sort_keys=True) + '\n')
        print(summary_line(report))
    else: print(json.dumps(report, indent=1, sort_keys=True))
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__': sys.exit(main())
