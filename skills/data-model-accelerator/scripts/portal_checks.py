"""Bounded checks for the generated offline page, independent of target execution.

The normal render path uses only the standard library. JavaScript syntax and
stub-DOM execution are explicit developer checks and require Node only on request.
"""
import base64
import hashlib
from html.parser import HTMLParser
import json
import shutil
import subprocess

from ae_common import require


REQUIRED_SECTIONS = ('architecture', 'lineage', 'implementation-code', 'replacement-map')
SECTION_PARENTS = {'architecture': 'model', 'lineage': 'model',
                   'implementation-code': 'delivery', 'replacement-map': 'delivery'}
VOID_ELEMENTS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                 'param', 'source', 'track', 'wbr'}
SCRIPT_TYPES = {'', 'module', 'application/ecmascript', 'application/javascript',
                'application/x-ecmascript', 'application/x-javascript', 'text/ecmascript',
                'text/javascript', 'text/jscript', 'text/livescript', 'text/x-ecmascript',
                'text/x-javascript', *('text/javascript1.' + str(version) for version in range(6))}


class PageContract(HTMLParser):
    """Collect template ownership and scripts without interpreting their contents."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.nodes = {}
        self.navigation = []
        self.scripts = []
        self.script = None

    def handle_starttag(self, tag, attrs):
        require(len({key for key, _ in attrs}) == len(attrs), 'Page has duplicate HTML attributes')
        attrs = dict(attrs)
        node = {'tag': tag, 'attrs': attrs, 'parents': tuple(self.stack)}
        identifier = attrs.get('id')
        if identifier is not None:
            require(identifier and identifier not in self.nodes, 'Page IDs must be unique: ' + str(identifier))
            self.nodes[identifier] = node
        if 'data-nav' in attrs:
            self.navigation.append(node)
        if tag == 'script':
            require(self.script is None, 'Nested page script')
            self.script = {'attrs': attrs, 'source': ''}
            self.scripts.append(self.script)
        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, identifier))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        require(self.stack and self.stack[-1][0] == tag, 'Page has invalid element nesting at </' + tag + '>')
        self.stack.pop()
        if tag == 'script':
            self.script = None

    def handle_data(self, text):
        if self.script is not None:
            self.script['source'] += text


def parse_page(page):
    if isinstance(page, bytes):
        page = page.decode('utf-8')
    require(isinstance(page, str), 'Page must contain UTF-8 HTML')
    parsed = PageContract()
    parsed.feed(page)
    parsed.close()
    require(not parsed.stack and parsed.script is None, 'Page has unclosed elements')
    records = [script for script in parsed.scripts if script['attrs'].get('id') == 'delivery-data']
    require(len(records) == 1 and records[0]['attrs'].get('type') == 'application/json',
            'Page requires one separate delivery-data JSON block')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate delivery-data JSON key')
            result[key] = value
        return result

    def invalid(_):
        raise ValueError('Invalid delivery-data JSON number')

    try:
        data = json.loads(records[0]['source'], object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, TypeError) as error:
        raise ValueError('Page delivery-data must be unambiguous JSON: ' + str(error)) from error
    require(isinstance(data, dict), 'Page delivery-data must be an object')
    return parsed, data


def validate_page(page, *, expected_files=None, expected_data=None, require_current=True):
    """Check navigation and embedded inventory; never read source artifact paths.

    expected_files maps portable paths to already-selected or ZIP bytes. Omitting
    it still verifies the embedded bytes against their declared lengths/hashes.
    Legacy packages may lack the new page-mode metadata and sections; their
    context-bound embedded file inventory can still be checked independently.
    """
    parsed, data = parse_page(page)
    if expected_data is not None:
        require(data == expected_data, 'Rendered delivery-data differs from its selected projection')
    if require_current:
        require(data.get('page_mode') in {'status', 'package'}, 'Page mode must be status or package')
        require(isinstance(data.get('selected_categories'), list)
                and all(isinstance(value, str) for value in data['selected_categories'])
                and data['selected_categories'] == sorted(set(data['selected_categories'])),
                'Page selected categories must be a sorted unique list')
        for identifier in REQUIRED_SECTIONS:
            node = parsed.nodes.get(identifier, {})
            attrs = node.get('attrs', {})
            require(node.get('tag') == 'section' and 'review-section' in attrs.get('class', '').split()
                    and 'data-section' not in attrs, 'Page review section is missing or invalid: ' + identifier)
            parent = SECTION_PARENTS[identifier]
            require(node.get('parents', ())[-1:] == (('section', parent),)
                    and 'data-section' in parsed.nodes.get(parent, {}).get('attrs', {}),
                    'Page review section has an invalid parent route: ' + identifier)
            require(any(nav['attrs'].get('data-nav') == identifier for nav in parsed.navigation),
                    'Page review section has no navigation: ' + identifier)
    for nav in parsed.navigation:
        attrs = nav['attrs']
        target = attrs['data-nav']
        node = parsed.nodes.get(target, {})
        require(attrs.get('href') == '#' + target and
                ('data-section' in node.get('attrs', {}) or target in SECTION_PARENTS and node.get('tag') == 'section'),
                'Page navigation must target a review section: ' + str(target))
        require(any(tag == 'nav' for tag, _ in nav['parents']), 'Page navigation link must belong to nav')

    files = data.get('files')
    require(isinstance(files, list), 'Page embedded file inventory must be a list')
    identifiers, paths, decoded = set(), set(), {}
    for item in files:
        require(isinstance(item, dict), 'Page embedded file record must be an object')
        identifier, path = item.get('id'), item.get('path')
        require(isinstance(identifier, str) and identifier and identifier not in identifiers,
                'Page embedded file IDs must be unique')
        require(isinstance(path, str) and path and path.casefold() not in paths,
                'Page embedded file paths must be unique')
        identifiers.add(identifier)
        paths.add(path.casefold())
        try:
            body = base64.b64decode(item.get('base64', ''), validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Page embedded file has invalid base64: ' + path) from error
        require(type(item.get('size')) is int and item['size'] == len(body)
                and item.get('sha256') == hashlib.sha256(body).hexdigest(),
                'Page embedded file bytes differ: ' + path)
        decoded[path] = body
        if require_current:
            require(item.get('category') in data['selected_categories'],
                    'Page embedded file category is outside its selection: ' + path)
    if expected_files is not None:
        require(decoded == expected_files, 'Page embedded inventory differs from selected package files')
    if require_current:
        require(type(data.get('file_count')) is int and data['file_count'] == len(files),
                'Page file count differs from embedded inventory')
        projection = data.get('projection', {})
        require(isinstance(projection, dict)
                and type(projection.get('selected_artifact_count')) is int
                and projection['selected_artifact_count'] == len(files)
                and type(projection.get('excluded_artifact_count')) is int
                and projection['excluded_artifact_count'] >= 0, 'Page projection counts are inconsistent')
        if data['page_mode'] == 'status':
            require(not files and not data['selected_categories'], 'Status page cannot embed artifact payloads')
    return {'status': 'page_contract_verified', 'page_mode': data.get('page_mode', 'legacy'),
            'files': len(files), 'sections': len([node for node in parsed.nodes.values()
                                               if 'data-section' in node['attrs']]),
            'authority': 'Structure and embedded file integrity only; not execution or acceptance.'}


def check_javascript(page, *, prelude=None, assertions=''):
    """Explicit Node syntax checks plus optional caller-supplied stub-DOM smoke.

    The prelude/assertions are trusted developer test code, never artifact data.
    The separate application/json payload is not executed or syntax-checked as JS.
    """
    parsed, _ = parse_page(page)
    node = shutil.which('node')
    require(node is not None, 'Node is required only for the requested JavaScript self-check')
    scripts = []
    for script in parsed.scripts:
        attrs = script['attrs']
        kind = (attrs.get('type') or '').lower().strip()
        if kind not in SCRIPT_TYPES:
            continue
        require('src' not in attrs, 'Offline page cannot load external executable scripts')
        source = script['source']
        command = [node, '--check']
        if kind == 'module':
            command.append('--input-type=module')
        try:
            result = subprocess.run(command, input=source, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            raise ValueError('Page JavaScript syntax check timed out') from error
        require(result.returncode == 0, 'Page JavaScript syntax check failed: ' + result.stderr.strip())
        scripts.append(source)
    require(scripts, 'Page has no executable inline scripts')
    if prelude is not None:
        require(isinstance(prelude, str) and isinstance(assertions, str), 'Smoke harness must be developer text')
        try:
            result = subprocess.run([node], input='\n'.join([prelude, *scripts, assertions]),
                                    capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            raise ValueError('Page stub-DOM smoke check timed out') from error
        require(result.returncode == 0, 'Page stub-DOM smoke check failed: ' + result.stderr.strip())
    return {'status': 'javascript_checked', 'scripts': len(scripts), 'smoke': prelude is not None}
