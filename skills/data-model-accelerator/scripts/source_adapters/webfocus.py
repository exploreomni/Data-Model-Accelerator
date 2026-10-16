"""Bounded offline WebFOCUS declarations; never execute FEX or resolve includes.

This is deliberately a recognizer, not a WebFOCUS interpreter. Original source
and native expressions are authoritative; dependencies are unbound declarations.
"""
import re
from pathlib import PurePosixPath

from .base import Report

CAPABILITY = {
    'formats': ['UTF-8 .fex literal report subset', 'UTF-8 .mas declarations',
                'UTF-8 .acx declarations'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No Dialogue Manager evaluation, includes, remote requests or report execution.',
        'One command per physical FEX line; inline SUM/PRINT/BY/WHERE/COMPUTE clauses supported.',
        'Master/Access declarations require dollar terminators; unsupported syntax is retained with gaps.',
        'Expressions, application-path binding, effective access and native behavior remain unverified.',
    ],
}

# Global work budget keeps output within the shared contract's node bound even
# across hundreds of files. Raw source is retained if interpretation is bounded.
MAX_UNITS = 800
MAX_LINES = 20000
MAX_UNIT_CHARS = 32768
MAX_CLAUSES = 64
MAX_ATTRIBUTES = 32
MAX_FIELDS = 128
_NAME = r'[A-Za-z_][A-Za-z0-9_.$]*'
_REF = r'[A-Za-z_][A-Za-z0-9_.$/-]*'
_FORMAT = r'[A-Za-z][A-Za-z0-9.]*'
_ASSIGN = re.compile(r'(' + _NAME + r')(?:/(' + _FORMAT + r'))?\s*=\s*(.+);\s*$', re.I)
_TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z0-9_.$/]*|\S")


def _split(text, delimiter):
    """Offsets at unquoted delimiters; reject unmatched quotes, no evaluation."""
    start, index, quote, result = 0, 0, None, []
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == delimiter:
            result.append((start, index + 1, True))
            if len(result) > MAX_UNITS:
                raise ValueError('webfocus.structure_limit')
            start = index + 1
        index += 1
    if quote:
        raise ValueError('webfocus.unterminated_quote')
    if start < len(text):
        result.append((start, len(text), False))
    return result


def _literal(value):
    value = value.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1].replace(value[0] * 2, value[0])
    return value


def _dep(report, path, loc, owner, target, kind, **details):
    report.dependency(path, loc, owner, target, kind=kind,
                      native_reference=target, resolution='unresolved', **details)


def _formula(report, path, loc, text, owner, kind):
    match = _ASSIGN.fullmatch(text.strip())
    if match is None:
        report.gap(path, 'webfocus.unsupported_formula',
                   'Expected one name[/format] = expression; declaration on one physical line.', loc)
        return
    name, data_format, formula = match.groups()
    field = report.object(path, loc, 'virtual_field' if kind == 'DEFINE' else 'calculated_field',
                          name, name, parent_id=owner, native_format=data_format,
                          evaluation_stage='record' if kind == 'DEFINE' else 'report',
                          native_declaration=text)
    report.expression(path, loc + '.formula', 'webfocus:expression', formula, field,
                      interpretation='preserved_original', expression_kind=kind)
    report.gap(path, 'webfocus.expression_semantics_unverified',
               'Native expression, missing values, function calls and field bindings require native review.', loc)


def _clauses(text):
    """Split only report-clause keywords outside literals; formulas end at ;."""
    _split(text, '\x00')  # Validate quotes without rewriting source.
    tokens = list(_TOKEN.finditer(text))
    start, current, result = 0, None, []
    for token in tokens:
        keyword = token.group().upper()
        if keyword not in {'SUM', 'PRINT', 'BY', 'WHERE', 'COMPUTE'}:
            continue
        if current == 'WHERE':
            continue
        if current == 'COMPUTE' and not text[start:token.start()].rstrip().endswith(';'):
            continue
        if current is not None:
            result.append(text[start:token.start()])
            start = token.start()
        current = keyword
    if current is None:
        return [text]
    result.append(text[start:])
    return result


def _fex(report, path, text, budget):
    owner = report.object(path, '$', 'procedure', path, source_path=path)
    mode, active, seen_body = None, owner, False
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        report.gap(path, 'webfocus.structure_limit', 'Physical line count exceeds the offline limit.')
        return
    for number, original in enumerate(lines, 1):
        line, loc = original.strip(), 'line:%d' % number
        if not line or line.startswith('-*'):
            continue
        budget[0] -= 1
        if budget[0] < 0 or len(original) > MAX_UNIT_CHARS:
            report.gap(path, 'webfocus.structure_limit', 'Offline statement budget exceeded; remaining source retained.', loc)
            break
        report.expression(path, loc, 'webfocus:fex', original, active,
                          interpretation='preserved_original')
        if '&' in line:
            report.gap(path, 'webfocus.dynamic', 'Amper variables require Dialogue Manager and session evidence; no substitution performed.', loc)
            continue
        if line.startswith('-'):
            include = re.fullmatch(r'-INCLUDE\s+(' + _REF + r')\s*;?', line, re.I)
            if include:
                _dep(report, path, loc, owner, include[1], 'include')
            report.gap(path, 'webfocus.dialogue_manager', 'Dialogue Manager commands/includes are retained and never followed or executed.', loc)
            continue
        if re.match(r'(SET|ENGINE|SQL|FILEDEF|APP|USE|EX|EXEC)\b', line, re.I):
            report.gap(path, 'webfocus.session_or_execution', 'Session, SQL passthrough or execution command retained without effects.', loc)
            continue
        try:
            _split(line, '\x00')
        except ValueError:
            report.gap(path, 'webfocus.unterminated_quote', 'Malformed quoted text is retained without interpretation.', loc)
            continue
        header = re.fullmatch(r'(TABLE|DEFINE)\s+FILE\s+(' + _REF + r')', line, re.I)
        if header:
            if mode:
                report.gap(path, 'webfocus.missing_end', 'Previous report or DEFINE block lacks END.', loc)
            mode, table = header[1].upper(), header[2]
            active = report.object(path, loc, 'report_request' if mode == 'TABLE' else 'define_block',
                                   table, parent_id=owner, native_source=table)
            _dep(report, path, loc, active, table, 'master_file')
            seen_body = False
            continue
        if line.upper() == 'END':
            if mode is None:
                report.gap(path, 'webfocus.unmatched_end', 'END has no supported open block.', loc)
            elif not seen_body:
                report.gap(path, 'webfocus.empty_block', 'Block has no supported body declarations.', loc)
            mode, active = None, owner
            continue
        join = re.fullmatch(r'JOIN\s+(' + _NAME + r')\s+IN\s+(' + _REF +
                            r')\s+TO\s+(ALL\s+)?(' + _NAME + r')\s+IN\s+(' + _REF +
                            r')\s+AS\s+(' + _NAME + r')\s*;?', line, re.I)
        if join:
            left, left_table, all_flag, right, right_table, name = join.groups()
            obj = report.object(path, loc, 'join_declaration', name, name, parent_id=owner,
                                source_key=left, target_key=right,
                                all_declared=bool(all_flag), native_declaration=original)
            _dep(report, path, loc, obj, left_table, 'join_source')
            _dep(report, path, loc, obj, right_table, 'join_target')
            report.gap(path, 'webfocus.join_behavior_unverified', 'Join cardinality, persistence, optimization and effective session scope are unverified.', loc)
            continue
        if mode == 'DEFINE':
            _formula(report, path, loc + '.define', line, active, 'DEFINE')
            seen_body = True
            continue
        if mode == 'TABLE' and re.match(r'(?:AND\s+)?(?:SUM|PRINT|BY|WHERE|COMPUTE)\b', line, re.I):
            clauses = _clauses(line)
            if len(clauses) > MAX_CLAUSES:
                report.gap(path, 'webfocus.structure_limit', 'Inline clause count exceeds the offline limit.', loc)
                continue
            for index, clause in enumerate(clauses):
                budget[0] -= 1
                if budget[0] < 0:
                    report.gap(path, 'webfocus.structure_limit', 'Offline clause budget exceeded; remaining source retained.', loc)
                    break
                at = loc + '.clause[%d]' % index
                match = re.fullmatch(r'(?:AND\s+)?(SUM|PRINT|BY|WHERE|COMPUTE)\s+(.+)', clause.strip(), re.I)
                if not match:
                    report.gap(path, 'webfocus.invalid_clause', 'Malformed report clause retained.', at)
                    continue
                kind, body = match[1].upper(), match[2]
                report.expression(path, at, 'webfocus:fex', clause, active,
                                  interpretation='native_declaration', expression_kind=kind)
                seen_body = True
                if kind == 'COMPUTE':
                    _formula(report, path, at + '.compute', body, active, kind)
                elif kind == 'WHERE':
                    report.expression(path, at + '.predicate', 'webfocus:expression', body, active,
                                      interpretation='preserved_original', expression_kind='WHERE')
                    report.gap(path, 'webfocus.predicate_semantics_unverified', 'WHERE expression retained; native evaluation, stage and dependencies remain unverified.', at)
                else:
                    fields = body.split()
                    if fields and fields[-1].upper() == 'AND':
                        fields = fields[:-1]
                    reserved = {'AS', 'NOPRINT', 'AND', 'ACROSS', 'ON', 'IN', 'OVER', 'WITHIN', 'WHERE', 'COMPUTE'}
                    if len(fields) > MAX_FIELDS:
                        report.gap(path, 'webfocus.structure_limit', 'Field-list count exceeds the offline limit.', at)
                        continue
                    if not fields or any(not re.fullmatch(_NAME, field) or field.upper() in reserved for field in fields) or (kind == 'BY' and len(fields) != 1):
                        report.gap(path, 'webfocus.unsupported_projection', 'Only literal field lists and single-field BY clauses are extracted; modifiers remain opaque.', at)
                    else:
                        # Prefix operators and qualified names remain native strings.
                        report.expression(path, at + '.fields', 'webfocus:field_list', body, active,
                                          native_fields=fields, expression_kind=kind,
                                          interpretation='unbound_field_references')
            continue
        report.gap(path, 'webfocus.unsupported_command', 'Command, multiline continuation or report behavior lies outside the literal subset.', loc)
    if mode:
        report.gap(path, 'webfocus.missing_end', 'Open report or DEFINE block lacks a supported END.')


def _attributes(text):
    attrs = {}
    for start, end, terminated in _split(text, ','):
        part = text[start:end - 1 if terminated else end].strip()
        if not part:
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)', part, re.S)
        if not match:
            raise ValueError('webfocus.invalid_attribute')
        key, value = match[1].upper(), match[2].strip()
        if key in attrs:
            raise ValueError('webfocus.duplicate_attribute')
        attrs[key] = value
        if len(attrs) > MAX_ATTRIBUTES:
            raise ValueError('webfocus.structure_limit')
    return attrs


def _metadata(report, path, text, extension, budget):
    root = report.object(path, '$', 'master_file' if extension == '.mas' else 'access_file', path,
                         source_path=path)
    # Ignore whole-line $$ comments while keeping byte/character offsets stable.
    cleaned = ''.join((' ' * len(line.rstrip('\r\n')) + line[len(line.rstrip('\r\n')):])
                      if line.lstrip().startswith('$$') else line for line in text.splitlines(True))
    try:
        records = _split(cleaned, '$')
    except ValueError as exc:
        report.gap(path, str(exc), 'Malformed or over-limit metadata is retained without interpretation.')
        return
    segment, master, names = None, None, set()
    for start, end, terminated in records:
        body = cleaned[start:end - 1 if terminated else end].strip()
        if not body:
            continue
        loc = 'chars:%d-%d' % (start, end)
        budget[0] -= 1
        if budget[0] < 0 or end - start > MAX_UNIT_CHARS:
            report.gap(path, 'webfocus.structure_limit', 'Offline metadata budget exceeded; remaining source retained.', loc)
            break
        report.expression(path, loc, 'webfocus:' + extension[1:], text[start:end], root,
                          interpretation='preserved_original')
        if not terminated:
            report.gap(path, 'webfocus.unterminated_record', 'Metadata record lacks the required dollar terminator.', loc)
            continue
        if '&' in body:
            report.gap(path, 'webfocus.dynamic', 'Parameterized metadata is retained without variable substitution.', loc)
            continue
        try:
            attrs = _attributes(body)
        except ValueError as exc:
            report.gap(path, str(exc), 'Malformed or duplicate metadata attributes retained without interpretation.', loc)
            continue
        if extension == '.acx' and 'SEGNAME' in attrs:
            kind, key, allowed = 'access_segment', 'SEGNAME', {'SEGNAME', 'TABLENAME', 'CONNECTION', 'KEYS', 'WRITE', 'READ'}
            parent = root
        elif extension == '.mas' and 'FILENAME' in attrs:
            kind, key, allowed = 'synonym', 'FILENAME', {'FILENAME', 'SUFFIX', 'DATASET', 'ACCESS', 'REMARKS'}
            parent = root
        elif extension == '.mas' and ('SEGMENT' in attrs or 'SEGNAME' in attrs):
            kind, key = 'segment', 'SEGMENT' if 'SEGMENT' in attrs else 'SEGNAME'
            allowed = {key, 'SEGTYPE', 'PARENT', 'DESCRIPTION', 'REMARKS'}
            parent = master or root
        elif extension == '.mas' and ('FIELDNAME' in attrs or 'FIELD' in attrs):
            kind, key = 'column', 'FIELDNAME' if 'FIELDNAME' in attrs else 'FIELD'
            allowed = {key, 'ALIAS', 'USAGE', 'FORMAT', 'ACTUAL', 'MISSING', 'TITLE', 'DESCRIPTION', 'REMARKS'}
            parent = segment or master or root
        else:
            report.gap(path, 'webfocus.unsupported_metadata', 'Metadata record type is outside the declared subset.', loc)
            continue
        name = _literal(attrs[key])
        if not re.fullmatch(_REF if kind == 'synonym' else _NAME, name):
            report.gap(path, 'webfocus.invalid_name', 'Declaration name is outside the literal identifier subset.', loc)
            continue
        identity = (parent, kind, name.casefold())
        if identity in names:
            report.gap(path, 'webfocus.duplicate_declaration', 'Duplicate declaration name; unique binding is not established.', loc)
        names.add(identity)
        obj = report.object(path, loc, kind, name, name, parent_id=parent, native_attributes=attrs)
        unknown = set(attrs) - allowed
        if unknown:
            report.gap(path, 'webfocus.opaque_attributes', 'Uninterpreted attributes: ' + ', '.join(sorted(unknown)), loc)
        if kind == 'synonym':
            if master:
                report.gap(path, 'webfocus.multiple_master_headers', 'Multiple FILENAME declarations require review.', loc)
            master, segment = obj, None
            if 'SUFFIX' not in attrs:
                report.gap(path, 'webfocus.missing_suffix', 'Master declaration lacks SUFFIX.', loc)
            for attribute in ('DATASET', 'ACCESS'):
                if attribute in attrs:
                    _dep(report, path, loc, obj, _literal(attrs[attribute]), attribute.lower())
        elif kind == 'segment':
            segment = obj
            if not master or 'SEGTYPE' not in attrs:
                report.gap(path, 'webfocus.incomplete_segment', 'Segment requires a preceding master and SEGTYPE.', loc)
            if 'PARENT' in attrs:
                _dep(report, path, loc, obj, _literal(attrs['PARENT']), 'parent_segment')
        elif kind == 'column':
            if not segment or not ({'USAGE', 'FORMAT'} & set(attrs)):
                report.gap(path, 'webfocus.incomplete_field', 'Field requires a preceding segment and native usage/format.', loc)
        elif kind == 'access_segment':
            if 'TABLENAME' in attrs:
                _dep(report, path, loc, obj, _literal(attrs['TABLENAME']), 'physical_relation',
                     native_connection=_literal(attrs.get('CONNECTION', '')) or None)
            else:
                report.gap(path, 'webfocus.access_binding_missing', 'Access declaration lacks TABLENAME; adapter-specific bindings are unsupported.', loc)
    if extension == '.mas' and master is None:
        report.gap(path, 'webfocus.master_header_missing', 'No supported literal FILENAME declaration was supplied.')


def parse(files):
    report, budget = Report('webfocus', files), [MAX_UNITS]
    for path in sorted(files):
        extension = PurePosixPath(path).suffix.lower()
        if extension not in {'.fex', '.mas', '.acx'}:
            report.cover(path, 'unsupported', 'Only supplied FEX, Master and Access text files are recognized.')
            report.gap(path, 'webfocus.unsupported_format', 'File retained by hash; binary, XML, archives and other formats are not interpreted.')
            continue
        text = files[path]
        report.expression(path, '$source', 'webfocus:' + extension[1:], text,
                          interpretation='preserved_original')
        report.cover(path, 'parsed', 'Bounded declaration extraction only.')
        report.gap(path, 'webfocus.runtime_context_unverified',
                   'Application-path resolution, profiles/session settings, security and effective access are not established by source files.')
        if not text.strip():
            report.gap(path, 'webfocus.empty_source', 'Empty source does not establish absence of source behavior.')
        elif any(ord(char) < 32 and char not in '\r\n\t' for char in text):
            report.gap(path, 'webfocus.invalid_text', 'Control characters rejected; original source retained.')
        elif extension == '.fex':
            _fex(report, path, text, budget)
        else:
            _metadata(report, path, text, extension, budget)
    return report.finish()
