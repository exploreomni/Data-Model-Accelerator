"""Bounded, offline literal provenance; never render templates or execute sources.

``scan_literals(root, paths, dialect)`` returns hash-only occurrences and findings.
Occurrence IDs bind path, file bytes and locator. Spans use zero-based Python
character offsets, end exclusive (not UTF-8 byte offsets). CSV spans identify the
raw cell; its context hash binds the complete row and column, preventing a label
from a different key from substantiating the candidate. SQL context hashes bind
the containing projection or predicate, not a source-wide substring.

``check_provenance(root, source_root, contract, paths, dialect)`` returns
``(findings, source_hashes)``. A provenance entry has ``occurrence_id`` and
``classification`` (technical, preserved, derived, proposed, unknown, redacted).
Optional ``source`` has exactly path, sha256, span, field, expression_sha256,
copied from an independently scanned source occurrence. Optional ``decision``
has reference and status=host_reported_reviewed. This only records a host
assertion, never authenticates or grants approval. ``derived`` requires
expression_sha256 and a matching model.expressions[field] contract. Unknown and
proposed values remain not_run, even in reviewed_candidate mode.
Decision-only evidence and derived expressions without matching source context
also remain not_run: an authored formula cannot establish its own provenance.

Supported SQL: SELECT/CTEs and CREATE TABLE/VIEW AS SELECT, with literal static
dbt ref/source calls. Unsupported syntax, macros and ambiguous scope remain
coverage findings. No claim of physical column resolution or SQL equivalence.
The optional SQLGlot dependency is required for SQL; CSV needs only stdlib.
Native Omni .view/.topic/model/relationships YAML additionally supports scalar
sql/on_sql expressions and typed measure-filter operators. YAML aliases,
templates, unknown filter operators and other YAML formats remain unsupported.
For SQL embedded in YAML, span also contains value_start/value_end offsets in
the decoded scalar; start/end identify that exact raw YAML scalar. Only hashes
and locations leave the scanner. This is not a complete Omni contract checker.
"""
import csv
import hashlib
import io
import logging
from pathlib import Path
import re
import stat
import threading

from ae_common import _path, hash_file, hash_json, require, safe_relative
from authoring_evidence import finding, validate_contract
from dbt_references import extract_references

MAX_BYTES = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 256
MAX_OCCURRENCES = 20000
MAX_NODES = 30000
CLASSIFICATIONS = {'technical', 'preserved', 'derived', 'proposed', 'unknown', 'redacted'}
REDACTED = re.compile(r'(?i)^(?:\[redacted\]|<redacted>|redacted|\*{3,}|TODO(?:\([^)]*\))?(?::.*)?)$')
LITERAL_TOKENS = {'STRING', 'NUMBER', 'TRUE', 'FALSE', 'NULL', 'UNKNOWN',
                  'NATIONAL_STRING', 'RAW_STRING', 'UNICODE_STRING', 'HEREDOC_STRING'}
GRANULARITIES = {'YEAR', 'QUARTER', 'MONTH', 'WEEK', 'DAY', 'HOUR', 'MINUTE', 'SECOND'}


class _Quiet(logging.Filter):
    def __init__(self):
        super().__init__(); self.thread = threading.get_ident()

    def filter(self, record):
        return record.thread != self.thread


def _read(root, relative):
    relative = safe_relative(relative)
    path = _path(root / relative)
    require(root in path.parents, 'Provenance path escapes declared root')
    require(stat.S_ISREG(path.stat().st_mode), 'Provenance input must be a regular file')
    require(path.stat().st_size <= MAX_BYTES, 'Provenance file bound exceeded')
    with path.open('rb') as stream:
        body = stream.read(MAX_BYTES + 1)
    require(len(body) <= MAX_BYTES, 'Provenance file bound exceeded')
    digest = hashlib.sha256(body).hexdigest()
    require(hash_file(path) == digest, 'Provenance input changed')
    return body.decode('utf-8-sig'), digest, len(body)


def _protected_offsets(text):
    # Omni scalar SQL uses this separate protection map for ${field} references.
    # dbt extraction is owned by the shared literal-reference reader below.
    protected, i = set(), 0
    while i < len(text):
        if text.startswith('--', i):
            end = text.find('\n', i); end = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2); end = len(text) if end < 0 else end + 2
        elif text[i] in "'\"`":
            quote, end = text[i], i + 1
            while end < len(text):
                if text[end] == quote:
                    if end + 1 < len(text) and text[end + 1] == quote:
                        end += 2; continue
                    end += 1; break
                if text[end] == '\\': end += 1
                end += 1
        else:
            i += 1; continue
        protected.update(range(i, end)); i = end
    return protected


def mask_static_dbt_sql(text):
    """Return (same-length SQL, calls, gap_codes); no evaluation or imports.

    Calls contain name, arguments, identifier and span. Only ref('model'),
    ref('package', 'model'), versioned refs and source('source', 'table') are
    accepted by the shared literal reader. Statements, dynamic calls and
    templates inside SQL strings/comments remain gaps.
    """
    calls, gaps, output = [], [], list(text)
    # A synthetic relation must not shadow an existing table, CTE or alias.
    # Include quoted/case-varied identifiers and conservatively reserve tokens
    # in comments/strings too; this never requires executing the template.
    reserved = {word.casefold() for word in re.findall(r'[A-Za-z_][A-Za-z_0-9$]*', text)}
    next_identifier = 0
    extracted = extract_references(text)
    for template in extracted['templates']:
        if template['kind'] == 'comment':
            start, end = template['span']['start'], template['span']['end']
            output[start:end] = ['\n' if c == '\n' else ' ' for c in text[start:end]]
    for call in extracted['references']:
        start, end = call['span']['start'], call['span']['end']
        while 'd' + str(next_identifier) in reserved:
            next_identifier += 1
        identifier = 'd' + str(next_identifier)
        reserved.add(identifier); next_identifier += 1
        output[start:end] = list(identifier + ' ' * (end - start - len(identifier)))
        calls.append({'name': call['kind'], 'arguments': call['arguments'], 'identifier': identifier,
                      'span': call['span'], 'key': call['key'], 'version': call['version']})
    gaps += ['sql_template_in_literal_or_comment' if item['reason'] == 'template_in_literal_or_comment'
             else 'sql_template_unsupported' for item in extracted['unresolved']]
    masked = ''.join(output)
    if any(marker in masked for marker in ('{{', '{%', '{#')):
        gaps.append('sql_template_unsupported')
    return masked, calls, sorted(set(gaps))


def _occurrence(path, digest, locator, span, kind, value, field, expression, *,
                reachable=True, technical=False, supported=True):
    return {'id': 'literal-' + hash_json([path, digest, locator]), 'path': path,
            'file_sha256': digest, 'locator': locator, 'span': span, 'kind': kind,
            'value_sha256': hash_json({'kind': kind, 'value': value}), 'field': field,
            'expression_sha256': expression, 'reachable': reachable,
            'technical': technical, 'supported': supported,
            'redacted': type(value) is str and REDACTED.fullmatch(value.strip()) is not None}


def _context(node, exp):
    current = node
    while current.parent is not None:
        parent = current.parent
        if isinstance(parent, exp.Alias):
            return parent.alias, hash_json(parent.this.sql(comments=False))
        if isinstance(parent, exp.Select) and current in parent.expressions:
            name = current.alias_or_name if isinstance(current, exp.Column) else None
            return name or None, hash_json(current.sql(comments=False))
        if isinstance(parent, (exp.Where, exp.Having, exp.Qualify, exp.Join)):
            expression = parent.args.get('on') if isinstance(parent, exp.Join) else parent.this
            columns = {column.name for column in expression.find_all(exp.Column)}
            return next(iter(columns)) if len(columns) == 1 else None, hash_json(expression.sql(comments=False))
        current = parent
    return None, None


def _live_nodes(tree, exp):
    """Conservative projection liveness for unambiguous SELECT/CTE scopes."""
    from sqlglot.optimizer.scope import traverse_scope, Scope
    scopes = list(traverse_scope(tree))
    require(scopes, 'SQL scope unavailable')
    live, visited = set(), set()
    def visit(scope, demand=None):
        key = (id(scope), None if demand is None else tuple(sorted(demand)))
        if key in visited: return
        visited.add(key)
        query = scope.expression
        require(isinstance(query, exp.Select), 'Set operations require separate evidence')
        projections = [p for p in query.expressions if demand is None or p.alias_or_name in demand
                       or isinstance(p, exp.Star)]
        active = list(projections)
        for name in ('where', 'having', 'qualify', 'joins', 'group', 'order', 'limit', 'offset'):
            value = query.args.get(name)
            active.extend(value if isinstance(value, list) else [value] if value is not None else [])
        sources = scope.selected_sources
        demands = {alias: set() for alias in sources}
        for expression in active:
            for child in expression.walk():
                # Nested query expressions get their own scope rather than
                # accidentally making every CTE declaration live.
                if child.find_ancestor(exp.Select) is not query: continue
                live.add(id(child))
                if isinstance(child, exp.Column):
                    if child.table:
                        require(child.table in sources, 'Correlated scope requires evidence')
                        demands[child.table].add(child.name)
                    elif len(sources) == 1:
                        demands[next(iter(sources))].add(child.name)
                    elif len(sources) > 1:
                        raise ValueError('Ambiguous unqualified scope')
                elif isinstance(child, exp.Star):
                    for alias in demands: demands[alias] = None
        for alias, (_, source) in sources.items():
            if isinstance(source, Scope): visit(source, demands[alias])
        for child in scope.subquery_scopes:
            visit(child)
    visit(scopes[-1])
    return live


def _sql(text, path, digest, dialect):
    findings, occurrences = [], []
    try:
        import sqlglot
        from sqlglot import exp
        require(type(dialect) is str and bool(dialect), 'SQL dialect required')
        selected = sqlglot.Dialect.get_or_raise(dialect)
    except ImportError:
        return [], [finding('sql_parser_unavailable', 'unsupported', path=path)]
    except (ValueError, TypeError):
        return [], [finding('sql_dialect_unsupported', 'unsupported', path=path)]
    masked, _, gaps = mask_static_dbt_sql(text)
    try:
        tokens = selected.tokenize(masked)
        require(len(tokens) <= MAX_NODES, 'SQL token bound exceeded')
    except Exception:
        return [], [finding('sql_tokenization_unsupported', 'unsupported', path=path)]
    # SQLGlot otherwise omits positions for boolean/null primary expressions.
    # Preserve token positions while retaining the selected dialect parser.
    primary = dict(selected.parser_class.PRIMARY_PARSERS)
    for key, original in list(primary.items()):
        if key.name in LITERAL_TOKENS:
            def positioned(parser, token, original=original):
                result = original(parser, token)
                if isinstance(result, (exp.Literal, exp.Boolean, exp.Null)):
                    result.update_positions(token)
                return result
            primary[key] = positioned
    parser_type = type('PositionedProvenanceParser', (selected.parser_class,), {'PRIMARY_PARSERS': primary})
    nodes, live, parsed = {}, set(), not gaps
    if parsed:
        logger, quiet = logging.getLogger('sqlglot'), _Quiet()
        logger.addFilter(quiet)
        try:
            trees = parser_type(dialect=selected, error_level=sqlglot.ErrorLevel.RAISE).parse(tokens, masked)
            require(any(tree is not None for tree in trees), 'SQL statement required')
            require(sum(1 for tree in trees if tree for _ in tree.walk()) <= MAX_NODES, 'SQL node bound exceeded')
            for tree in trees:
                if tree is None: continue
                require(isinstance(tree, exp.Select) or (isinstance(tree, exp.Create)
                        and str(tree.args.get('kind', '')).upper() in {'TABLE', 'VIEW'}
                        and isinstance(tree.expression, exp.Select)), 'Unsupported SQL statement')
                live.update(_live_nodes(tree, exp))
                for node in tree.walk():
                    if isinstance(node, (exp.Literal, exp.Boolean, exp.Null)) and 'start' in node.meta:
                        nodes[node.meta['start']] = (node, False)
                    # DATE_TRUNC normalizes the unit into a Var and loses its
                    # original literal positions. Match only its own first arg.
                    if isinstance(node, (exp.DateTrunc, exp.TimestampTrunc)) and 'start' in node.meta:
                        index = next((i for i, t in enumerate(tokens) if t.start == node.meta['start']), -1)
                        if index >= 0 and index + 3 < len(tokens):
                            a, b, c = tokens[index + 1:index + 4]
                            if a.token_type.name == 'L_PAREN' and b.token_type.name == 'STRING' and c.token_type.name == 'COMMA':
                                nodes[b.start] = (node, b.text.upper() in GRANULARITIES)
        except Exception:
            parsed = False; nodes = {}; live = set()
        finally:
            logger.removeFilter(quiet)
    findings.append(finding('sql_file_scanned' if parsed else 'sql_coverage_unsupported',
                            'passed' if parsed else 'unsupported', path=path))
    for token in tokens:
        if token.token_type.name not in LITERAL_TOKENS: continue
        node, granularity = nodes.get(token.start, (None, False))
        kind = 'string' if 'STRING' in token.token_type.name else 'number' if token.token_type.name == 'NUMBER' else token.token_type.name.lower()
        value = token.text
        if kind == 'null': value = None
        if kind in {'true', 'false'}: kind, value = 'boolean', kind == 'true'
        field, expression = _context(node, exp) if node is not None else (None, None)
        technical = granularity
        if isinstance(node, exp.Literal):
            technical = technical or (isinstance(node.parent, exp.Count) and node.parent.this is node
                                      and node.is_number and node.this == '1')
            if isinstance(node.parent, exp.Neg): value = '-' + value
            if isinstance(node.parent, exp.Cast):
                cast = node.parent.args.get('to')
                if cast is not None and cast.sql().upper() in {'DATE', 'TIME', 'TIMESTAMP', 'TIMESTAMPTZ'}:
                    kind = cast.sql().lower()
        supported = parsed and node is not None
        occurrences.append(_occurrence(path, digest, '$sql:' + str(token.start),
            {'start': token.start, 'end': token.end + 1}, kind, value, field, expression,
            reachable=id(node) in live if supported else None, technical=technical,
            supported=supported))
    return occurrences, findings


def _csv(text, path, digest):
    try:
        rows = list(csv.reader(io.StringIO(text, newline=''), strict=True))
        require(rows and rows[0] and len(set(rows[0])) == len(rows[0])
                and all(name.strip() for name in rows[0]), 'CSV headers required')
        require(all(len(row) == len(rows[0]) for row in rows), 'CSV row width differs')
        require(sum(map(len, rows)) <= MAX_OCCURRENCES + len(rows[0]), 'CSV cell bound exceeded')
        # Track raw cell spans including quotes and embedded newlines. csv.reader
        # supplies values; this scanner only supplies positions and must agree.
        spans, row, start, quoted, i = [], [], 0, False, 0
        while i < len(text):
            c = text[i]
            if c == '"':
                if quoted and i + 1 < len(text) and text[i + 1] == '"': i += 2; continue
                if i == start or quoted: quoted = not quoted
            if not quoted and c in ',\r\n':
                row.append({'start': start, 'end': i})
                if c != ',':
                    spans.append(row); row = []
                    if c == '\r' and i + 1 < len(text) and text[i + 1] == '\n': i += 1
                start = i + 1
            i += 1
        if start < len(text) or row:
            row.append({'start': start, 'end': len(text)}); spans.append(row)
        require([len(row) for row in rows] == [len(row) for row in spans], 'CSV spans unsupported')
        occurrences = []
        for row_index, values in enumerate(rows[1:], 1):
            for col_index, value in enumerate(values):
                field = rows[0][col_index]
                occurrences.append(_occurrence(path, digest, '$csv:%d:%d' % (row_index, col_index),
                    spans[row_index][col_index], 'string', value, field,
                    hash_json({'columns': rows[0], 'row': values, 'field': field})))
        return occurrences, [finding('csv_file_scanned', 'passed', path=path)]
    except (ValueError, csv.Error, OverflowError):
        return [], [finding('csv_coverage_unsupported', 'unsupported', path=path)]


def _omni_path(path):
    name = Path(path).name
    if name.endswith(('.yaml', '.yml')): name = name.rsplit('.', 1)[0]
    return name.endswith(('.view', '.topic')) or name in {'model', 'relationships'}


def _omni(text, path, digest, dialect):
    try:
        import yaml
        from yaml.nodes import MappingNode, ScalarNode, SequenceNode
    except ImportError:
        return [], [finding('omni_yaml_parser_unavailable', 'unsupported', path=path)]
    occurrences, findings = [], []
    try:
        tokens = list(yaml.scan(text))
        require(len(tokens) <= MAX_NODES and not any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
                                                   for t in tokens), 'YAML aliases or bounds unsupported')
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        require(len(docs) == 1 and docs[0] is not None, 'One YAML document required')
        count = [0]
        def plain(node, depth=0):
            count[0] += 1
            require(count[0] <= MAX_NODES and depth <= 64, 'YAML structure bound exceeded')
            if isinstance(node, ScalarNode):
                require(node.tag in {'tag:yaml.org,2002:' + name for name in ('str', 'int', 'float', 'bool', 'null', 'timestamp')}, 'Unsupported YAML tag')
                return {'tag': node.tag, 'value': node.value}
            if isinstance(node, SequenceNode): return [plain(v, depth + 1) for v in node.value]
            require(isinstance(node, MappingNode), 'Unsupported YAML node')
            result = {}
            for key, value in node.value:
                require(isinstance(key, ScalarNode) and key.tag == 'tag:yaml.org,2002:str' and key.value not in result,
                        'YAML mapping keys must be unique strings')
                result[key.value] = plain(value, depth + 1)
            return result
        plain(docs[0])  # Validate tags, keys, depth and aliases before interpreting.
        allowed = {'is', 'not', 'greater_than', 'greater_than_or_equal_to', 'less_than',
                   'less_than_or_equal_to', 'contains', 'not_contains', 'starts_with',
                   'not_starts_with', 'ends_with', 'not_ends_with'}
        def pointer(parts): return '$yaml:/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)
        def scalar_occurrence(node, parts, field, context, supported):
            tag = node.tag.rsplit(':', 1)[-1]
            kind = {'str': 'string', 'int': 'number', 'float': 'number', 'bool': 'boolean',
                    'null': 'null', 'timestamp': 'date'}[tag]
            value = None if kind == 'null' else node.value.lower() in {'true', 'yes', 'on'} if kind == 'boolean' else node.value
            occurrences.append(_occurrence(path, digest, pointer(parts),
                {'start': node.start_mark.index, 'end': node.end_mark.index}, kind, value, field,
                context, supported=supported))
        def filters(node, parts):
            if not isinstance(node, MappingNode):
                findings.append(finding('omni_filter_shape_unsupported', 'unsupported', path=path)); return
            for dimension, operators in node.value:
                field = dimension.value
                if not isinstance(operators, MappingNode):
                    findings.append(finding('omni_filter_operator_unsupported', 'unsupported', path=path)); continue
                context = hash_json({'path': parts + [field], 'filter': plain(operators)})
                for operator, values in operators.value:
                    valid = operator.value in allowed
                    leaves = values.value if isinstance(values, SequenceNode) else [values]
                    for index, leaf in enumerate(leaves):
                        if isinstance(leaf, ScalarNode):
                            scalar_occurrence(leaf, parts + [field, operator.value, index], field, context, valid)
                        else: valid = False
                    if not valid:
                        findings.append(finding('omni_filter_operator_unsupported', 'unsupported', path=path))
        def expression(node, parts):
            if not isinstance(node, ScalarNode) or node.tag != 'tag:yaml.org,2002:str':
                findings.append(finding('omni_sql_shape_unsupported', 'unsupported', path=path)); return
            original, masked = node.value, node.value
            protected = _protected_offsets(original)
            matches = list(re.finditer(r'\$\{([^}]*)\}', original))
            if any(m.start() in protected or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', m.group(1)) is None for m in matches):
                findings.append(finding('omni_sql_reference_unsupported', 'unsupported', path=path)); return
            for match in reversed(matches):
                value = match.group(1)
                masked = masked[:match.start()] + value + ' ' * (len(match.group()) - len(value)) + masked[match.end():]
            if '${' in masked:
                findings.append(finding('omni_sql_reference_unsupported', 'unsupported', path=path)); return
            prefix = 'SELECT '
            rows, checks = _sql(prefix + masked + ' AS __dma_provenance', path, digest, dialect)
            if any(c['status'] != 'passed' for c in checks):
                findings.append(finding('omni_sql_context_unsupported', 'unsupported', path=path))
            for row in rows:
                start, end = row['span']['start'] - len(prefix), row['span']['end'] - len(prefix)
                if not (0 <= start <= end <= len(original)): continue
                locator = pointer(parts) + '/sql:' + str(start)
                row.update(id='literal-' + hash_json([path, digest, locator]), locator=locator,
                    field=parts[-2] if len(parts) >= 2 else parts[-1],
                    expression_sha256=hash_json({'path': parts, 'expression': row['expression_sha256']}),
                    span={'start': node.start_mark.index, 'end': node.end_mark.index,
                          'value_start': start, 'value_end': end})
                occurrences.append(row)
        interpreted = [False]
        def walk(node, parts):
            if isinstance(node, MappingNode):
                for key, value in node.value:
                    if key.value == 'filters':
                        interpreted[0] = True; filters(value, parts + [key.value])
                    elif key.value in {'sql', 'on_sql'}:
                        interpreted[0] = True; expression(value, parts + [key.value])
                    else: walk(value, parts + [key.value])
            elif isinstance(node, SequenceNode):
                for index, value in enumerate(node.value): walk(value, parts + [str(index)])
        walk(docs[0], [])
        findings.insert(0, finding('omni_sql_filters_scanned' if interpreted[0] else 'omni_no_supported_literal_context',
                                  'passed' if interpreted[0] else 'unsupported', path=path))
        return occurrences, findings
    except (ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError):
        return [], [finding('omni_yaml_coverage_unsupported', 'unsupported', path=path)]


def scan_literals(root, paths, dialect):
    """Hash-only public inventory; findings never contain source/literal text."""
    root = _path(root)
    require(root.is_dir(), 'Provenance root must be a directory')
    require(type(paths) is list and len(paths) <= MAX_FILES and all(type(p) is str for p in paths)
            and len(set(paths)) == len(paths), 'Invalid provenance paths')
    files, occurrences, findings, total = {}, [], [], 0
    for path in paths:
        safe_relative(path)
        try:
            text, digest, size = _read(root, path)
            total += size
            require(total <= MAX_TOTAL, 'Provenance total bound exceeded')
            files[path] = digest
            suffix = Path(path).suffix.lower()
            if suffix == '.sql': current, checks = _sql(text, path, digest, dialect)
            elif suffix == '.csv': current, checks = _csv(text, path, digest)
            elif _omni_path(path): current, checks = _omni(text, path, digest, dialect)
            else: current, checks = [], [finding('provenance_format_unsupported', 'unsupported', path=path)]
            require(len(occurrences) + len(current) <= MAX_OCCURRENCES, 'Provenance occurrence bound exceeded')
            occurrences.extend(current); findings.extend(checks)
        except (ValueError, OSError, UnicodeError, RecursionError):
            findings.append(finding('provenance_file_unavailable_or_bound', 'unsupported', path=path))
    return {'schema_version': 1, 'files': files, 'occurrences': occurrences, 'findings': findings}


def _expression_hash(expression, dialect):
    import sqlglot
    masked, _, gaps = mask_static_dbt_sql(expression)
    require(not gaps, 'Expression contract unsupported')
    return hash_json(sqlglot.parse_one(masked, read=dialect).sql(comments=False))


def check_provenance(root, source_root, contract, paths, dialect):
    contract = validate_contract(contract)
    scanned = scan_literals(root, paths, dialect)
    findings, source_hashes = list(scanned['findings']), {}
    models = {model['path']: model for model in contract['models'] if model['path'] is not None}
    occurrences = {row['id']: row for row in scanned['occurrences']}
    entries, duplicates = {}, set()
    for entry in contract['provenance']:
        identifier = entry.get('occurrence_id')
        if type(identifier) is not str or identifier not in occurrences:
            findings.append(finding('provenance_occurrence_unknown', 'failed')); continue
        if identifier in entries: duplicates.add(identifier)
        entries[identifier] = entry
    source_cache, source_bytes = {}, 0
    for identifier, occurrence in occurrences.items():
        model = models.get(occurrence['path'])
        def add(code, status):
            findings.append(finding(code, status, path=occurrence['path'],
                                    model_id=model['id'] if model else None, field=identifier))
        entry = entries.get(identifier)
        if identifier in duplicates: add('provenance_occurrence_duplicate', 'failed'); continue
        if not occurrence['supported']: add('literal_context_unsupported', 'unsupported'); continue
        if not occurrence['reachable']: add('literal_unreachable', 'not_run'); continue
        if entry is not None and (set(entry) - {'occurrence_id', 'classification', 'source', 'decision', 'expression_sha256'}
                or type(entry.get('classification')) is not str or entry['classification'] not in CLASSIFICATIONS):
            add('provenance_entry_invalid', 'failed'); continue
        classification = entry.get('classification') if entry else None
        if classification == 'technical' and not occurrence['technical']:
            add('technical_classification_contradicted', 'failed'); continue
        if occurrence['redacted']:
            add('literal_redacted_or_placeholder', 'not_run'); continue
        if classification in {'proposed', 'unknown', 'redacted'}:
            decision = entry.get('decision')
            if decision is not None:
                if not (type(decision) is dict and set(decision) == {'reference', 'status'}
                        and type(decision['reference']) is str and 0 < len(decision['reference'].strip()) <= 8000
                        and decision['status'] == 'host_reported_reviewed'):
                    add('decision_reference_invalid', 'failed'); continue
                add('decision_reference_host_reported', 'not_run')
            else:
                add('literal_proposed_or_unknown', 'not_run')
            continue
        if occurrence['technical'] and classification in (None, 'technical'):
            add('technical_constant_context_verified', 'passed'); continue
        if entry is None:
            add('literal_provenance_missing', 'not_run'); continue
        try:
            source = entry.get('source')
            bound = None
            if source is not None:
                require(type(source) is dict and set(source) == {'path', 'sha256', 'span', 'field', 'expression_sha256'}, 'Invalid source occurrence')
                name = safe_relative(source['path'])
                if name not in source_cache:
                    require(len(source_cache) < MAX_FILES, 'Source evidence file bound exceeded')
                    source_bytes += _path(_path(source_root) / name).stat().st_size
                    require(source_bytes <= MAX_TOTAL, 'Source evidence total bound exceeded')
                    source_cache[name] = scan_literals(source_root, [name], dialect)
                capture = source_cache[name]
                require(capture['files'].get(name) == source['sha256'], 'Source changed or absent')
                source_hashes[name] = capture['files'][name]
                matches = [row for row in capture['occurrences'] if row['span'] == source['span']
                           and row['field'] == source['field'] and row['expression_sha256'] == source['expression_sha256']]
                require(len(matches) == 1, 'Source span/context mismatch')
                bound = matches[0]
                require(bound['supported'] and bound['reachable'] and not bound['redacted'], 'Source context is unsupported or redacted')
            decision = entry.get('decision')
            if decision is not None:
                require(type(decision) is dict and set(decision) == {'reference', 'status'}
                        and type(decision['reference']) is str and 0 < len(decision['reference'].strip()) <= 8000
                        and decision['status'] == 'host_reported_reviewed', 'Invalid decision assertion')
            if classification == 'preserved':
                require(bound is not None and bound['value_sha256'] == occurrence['value_sha256']
                        and bound['field'] is not None and bound['field'] == occurrence['field']
                        and bound['expression_sha256'] == occurrence['expression_sha256'], 'Preserved value/context differs')
                add('preserved_occurrence_context_verified', 'passed')
            elif classification == 'derived':
                require(model is not None and occurrence['field'] in model.get('expressions', {}), 'Derived expression is unbound')
                expected = _expression_hash(model['expressions'][occurrence['field']], dialect)
                require(expected == occurrence['expression_sha256'] == entry.get('expression_sha256'), 'Derived expression differs')
                # A matching author-supplied formula is conformance, not proof
                # that its new constants or business definition came from source.
                exact = bound is not None and bound['value_sha256'] == occurrence['value_sha256'] \
                    and bound['field'] is not None and bound['field'] == occurrence['field'] \
                    and bound['expression_sha256'] == occurrence['expression_sha256']
                add('derived_source_context_verified' if exact else 'derived_contract_requires_source_evidence',
                    'passed' if exact else 'not_run')
            elif decision is not None:
                add('decision_reference_host_reported', 'not_run')
            else:
                add('literal_evidence_missing', 'not_run')
        except (ValueError, OSError, TypeError, KeyError, ImportError, RecursionError):
            add('literal_evidence_contradicted_or_invalid', 'failed')
    # Recheck captured bytes; provenance cannot outlive an input that drifted
    # while this bounded check was running.
    for base, hashes, code in ((_path(root), scanned['files'], 'candidate_changed'),
                               (_path(source_root), source_hashes, 'source_evidence_changed')):
        for path, digest in hashes.items():
            try: require(hash_file(base / safe_relative(path)) == digest, 'Evidence changed')
            except (ValueError, OSError): findings.append(finding(code, 'failed', path=path))
    return findings, source_hashes
