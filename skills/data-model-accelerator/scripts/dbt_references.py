"""Bounded dbt reference declarations, without Jinja/dbt imports or evaluation.

Only whole ``{{ ref(...) }}`` / ``{{ source(...) }}`` expressions with literal
arguments are interpreted. Other templates stay explicit unresolved evidence.
Keys describe authored logical references, not resolved native/physical IDs.
Spans are zero-based character offsets, end exclusive. SQL comments/strings,
Jinja comments and raw blocks cannot introduce references. Native manifests
remain the preferred evidence for a compatible, exact authored-file binding.
"""
import ast
import re
from urllib.parse import quote

MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_EXPRESSION_CHARS = 8192
MAX_TEMPLATES = 10000


def _span(start, end):
    return {'start': start, 'end': end}


def _quoted_end(text, start, sql=False):
    delimiter = text[start]
    close = ']' if delimiter == '[' else delimiter
    index = start + 1
    while index < len(text):
        if text[index] == '\\':
            index += 2
        elif text[index] == close:
            if sql and index + 1 < len(text) and text[index + 1] == close:
                index += 2
            else:
                return index + 1
        else:
            index += 1
    return len(text)


def _template_end(text, start, close):
    index = start + 2
    while index < len(text):
        if text.startswith(close, index):
            return index + 2
        if text[index] in "'\"":
            index = _quoted_end(text, index)
        else:
            index += 1
    return None


def scan_templates(text):
    """Return lexical template spans; protected SQL is never parsed as Jinja.

    ``protected`` spans intentionally retain a diagnostic: actual dbt may
    evaluate templates inside SQL comments/strings, which this reader does not.
    This is source inventory, not a substitute for native dependency discovery.
    """
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
        raise ValueError('dbt_reference_text_bound')
    result, index, scope = [], 0, []
    while index < len(text):
        if len(result) >= MAX_TEMPLATES:
            result.append({'kind': 'unsupported', 'reason': 'template_count_bound',
                           'span': _span(index, len(text))})
            break
        start, end = index, None
        if text.startswith('--', index) or text[index] == '#':
            end = text.find('\n', index)
            end = len(text) if end < 0 else end
        elif text.startswith('/*', index):
            depth, end = 1, index + 2
            while depth and end < len(text):
                if text.startswith('/*', end):
                    depth += 1; end += 2
                elif text.startswith('*/', end):
                    depth -= 1; end += 2
                else:
                    end += 1
        elif text[index] in "'\"`[":
            end = _quoted_end(text, index, sql=True)
        elif text[index] == '$':
            delimiter = re.match(r'\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$', text[index:index + 256])
            if delimiter:
                stop = text.find(delimiter[0], index + len(delimiter[0]))
                end = len(text) if stop < 0 else stop + len(delimiter[0])
        if end is not None:
            if any(marker in text[index:end] for marker in ('{{', '{%', '{#')):
                result.append({'kind': 'protected', 'reason': 'template_in_literal_or_comment',
                               'span': _span(index, end)})
            index = end
            continue
        opener = text[index:index + 2]
        if opener not in ('{{', '{%', '{#'):
            index += 1
            continue
        close = {'{{': '}}', '{%': '%}', '{#': '#}'}[opener]
        if opener == '{#':
            stop = text.find(close, index + 2)
            end = None if stop < 0 else stop + 2
        else:
            end = _template_end(text, index, close)
        if end is None:
            result.append({'kind': 'unsupported', 'reason': 'unterminated_template',
                           'span': _span(index, len(text))})
            break
        content = text[index + 2:end - 2]
        # Jinja trim controls surround, rather than form part of, expressions.
        if content[:1] in ('-', '+'): content = content[1:]
        if content[-1:] in ('-', '+'): content = content[:-1]
        content = content.strip()
        kind = {'{{': 'expression', '{%': 'statement', '{#': 'comment'}[opener]
        command = content.split(None, 1)[0] if content else ''
        if kind == 'statement' and command == 'raw':
            # Raw content can contain unmatched quotes/braces; only endraw is
            # meaningful here. It stays unsupported SQL rather than evaluated.
            raw_end = re.search(r'{%[-+]?\s*endraw\s*[-+]?%}', text[end:])
            end = end + raw_end.end() if raw_end else len(text)
            result.append({'kind': 'raw', 'reason': 'raw_block_uninterpreted',
                           'span': _span(index, end)})
            index = end
            continue
        if kind == 'statement' and command.startswith('end') and scope:
            if scope[-1] == command[3:]: scope.pop()
        result.append({'kind': kind, 'content': content, 'span': _span(start, end),
                       'context': list(scope)})
        if kind == 'statement' and command in ('if', 'for', 'macro', 'call', 'block', 'filter'):
            scope.append(command)
        index = end
    return result


def _key_part(value):
    # Preserve simple established keys, escaping separators inside literal names
    # so package/model boundaries and version suffixes cannot collide.
    return quote(str(value), safe='_-').replace('.', '%2E')


def parse_literal_call(expression):
    """Return a canonical literal-call record, or raise ValueError, never eval.

    Supports positional source/table and model/package names, plus literal
    ``version=`` or ``v=`` strings/numbers for refs. Unknown kwargs, duplicate
    version aliases, concatenation, expansion and variables are unresolved.
    """
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ValueError('reference_expression_bound')
    # ast is only a safe syntax reader. Reject Python-only lexical constructs
    # that could otherwise be mistaken for valid literal Jinja.
    index = 0
    while index < len(expression):
        if expression[index] in "'\"":
            index = _quoted_end(expression, index)
        elif expression[index] in '#\\':
            raise ValueError('template_expression_unresolved')
        else:
            index += 1
    try:
        call = ast.parse(expression, mode='eval').body
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError('template_expression_unresolved') from None
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id in ('ref', 'source')):
        raise ValueError('template_expression_unresolved')
    kind = call.func.id
    args = [arg.value for arg in call.args if isinstance(arg, ast.Constant) and type(arg.value) is str]
    if (len(args) != len(call.args) or any(not arg or len(arg) > 200 for arg in args)
            or len(args) not in ((1, 2) if kind == 'ref' else (2,))):
        raise ValueError('dynamic_or_invalid_reference_arguments')
    # Python accepts adjacent string literals unlike the supported Jinja subset.
    # Do not collapse authored expressions such as ref('a' 'b') into a new name.
    for arg in call.args:
        literal = ast.get_source_segment(expression, arg)
        if not literal or literal[0] not in "'\"" or _quoted_end(literal, 0) != len(literal):
            raise ValueError('dynamic_or_invalid_reference_arguments')
    version = None
    if call.keywords:
        if kind != 'ref' or len(call.keywords) != 1 or call.keywords[0].arg not in ('v', 'version'):
            raise ValueError('dynamic_or_invalid_reference_version')
        value = call.keywords[0].value
        if not isinstance(value, ast.Constant) or type(value.value) not in (str, int, float):
            raise ValueError('dynamic_or_invalid_reference_version')
        version = value.value
        if not str(version) or len(str(version)) > 200 or str(version) in ('inf', '-inf', 'nan'):
            raise ValueError('dynamic_or_invalid_reference_version')
        literal = ast.get_source_segment(expression, value)
        if type(version) is str:
            if not literal or literal[0] not in "'\"" or _quoted_end(literal, 0) != len(literal):
                raise ValueError('dynamic_or_invalid_reference_version')
        elif not literal or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', literal):
            raise ValueError('dynamic_or_invalid_reference_version')
    key = kind + ':' + '.'.join(_key_part(arg) for arg in args)
    if version is not None: key += '@version=' + _key_part(version)
    return {'kind': kind, 'name': args[-1], 'arguments': args, 'key': key,
            'package': args[0] if kind == 'ref' and len(args) == 2 else None,
            'source_name': args[0] if kind == 'source' else None, 'version': version}


def extract_references(text):
    """Return literal references, unresolved templates and lexical spans.

    A literal declaration does not resolve latest-version selection, local or
    package ownership, macro overrides, physical schemas or effective runtime
    dependencies. Statements and scoped expressions are intentionally unresolved.
    """
    templates, references, unresolved = scan_templates(text), [], []
    for template in templates:
        kind, span = template['kind'], template['span']
        if kind == 'comment': continue
        reason = template.get('reason')
        if kind == 'expression' and not template['context']:
            try:
                call = parse_literal_call(template['content'])
                references.append(dict(call, span=span, template_span=span))
                continue
            except ValueError as error:
                reason = str(error)
        unresolved.append({'reason': reason or ('template_control_flow_unresolved'
                           if template.get('context') else 'template_statement_unresolved'), 'span': span})
    return {'references': references, 'unresolved': unresolved, 'templates': templates,
            'interpretation': 'bounded_literal_declarations', 'execution_performed': False}
