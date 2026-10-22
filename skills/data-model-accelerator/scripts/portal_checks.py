"""Bounded checks for the generated offline page, independent of target execution.

The normal render path uses only the standard library. JavaScript syntax and
stub-DOM execution are explicit developer checks and require Node only on request.
"""
import base64
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
import math
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ae_common import require


REQUIRED_SECTIONS = ('architecture', 'lineage', 'implementation-code', 'replacement-map')
SECTION_PARENTS = {'architecture': 'model', 'lineage': 'model',
                   'implementation-code': 'delivery', 'replacement-map': 'delivery',
                   'table-dictionary': 'model', 'review-feedback': None}
VOID_ELEMENTS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                 'param', 'source', 'track', 'wbr'}
SCRIPT_TYPES = {'', 'module', 'application/ecmascript', 'application/javascript',
                'application/x-ecmascript', 'application/x-javascript', 'text/ecmascript',
                'text/javascript', 'text/jscript', 'text/livescript', 'text/x-ecmascript',
                'text/x-javascript', *('text/javascript1.' + str(version) for version in range(6))}
DIAGRAM_QUALIFICATION = 'Model identity and table bounds only; not visual rendering, relationship correctness or acceptance.'
UNVERIFIED_DIAGRAM_QUALIFICATION = 'No diagram_model_ids scope was declared. File integrity does not establish model coverage.'
_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


def model_inventory(models, relationships=None, *, references=False):
    """Validate the warehouse graph before layout; never silently drop a layer."""
    require(isinstance(models, list) and len(models) <= 20000, 'Diagram models must be a bounded list')
    identifiers = []
    for model in models:
        require(isinstance(model, dict), 'Diagram model must be an object')
        require(references or not model.get('reference_only'), 'Reference-only endpoints cannot be canonical models')
        identifier = model.get('id')
        require(isinstance(identifier, str) and identifier.strip() == identifier and identifier
                and not any(ord(char) < 32 or ord(char) == 127 for char in identifier),
                'Diagram model ID must be nonempty text without surrounding whitespace or control characters')
        identifiers.append(identifier)
        require(isinstance(model.get('layer'), str) and (model['layer'] in {'bronze', 'silver', 'gold'} or references and model.get('reference_only') is True and model['layer'] == 'reference'),
                'Diagram model layer must be bronze, silver or gold')
        columns = model.get('columns', [])
        require(isinstance(columns, list) and all(isinstance(column, dict)
                and isinstance(column.get('name'), str) and column['name'] for column in columns),
                'Diagram model columns must have nonempty text names')
    require(len(identifiers) == len(set(identifiers)), 'Diagram model IDs must be unique')
    if relationships is not None:
        require(isinstance(relationships, list) and len(relationships) <= 20000,
                'Diagram relationships must be a bounded list')
        known = set(identifiers)
        for edge in relationships:
            require(isinstance(edge, dict) and isinstance(edge.get('from'), str) and isinstance(edge.get('to'), str)
                    and edge['from'] in known and edge['to'] in known,
                    'Diagram relationship references an absent model')
            require(isinstance(edge.get('kind'), str) and edge['kind'] in {'lineage', 'relationship'},
                    'Diagram relationship kind must be lineage or relationship')
    return identifiers


def erd_inventory(review):
    """Add explicitly supplied proposal occurrences without changing the canonical model.

    Unknown IDs require explicit reference_endpoints. Known IDs must come from this
    review inventory; a proposal cannot supply private model definitions indirectly.
    """
    models = review.get('models', [])
    known = set(model_inventory(models, review.get('relationships', [])))
    proposals = review.get('domain_proposals', [])
    require(isinstance(proposals, list) and len(proposals) <= 20000, 'Domain proposals must be a bounded list')
    nodes = [dict(model, proposal_domains=[]) for model in models]
    by_id = {node['id']: node for node in nodes}
    edges = [dict(edge, occurrence_id='canonical:' + str(i+1), record_origin='canonical', record_position=i+1)
             for i, edge in enumerate(review.get('relationships', []))]
    proposal_ids = set()
    association_count = 0
    for proposal in proposals:
        require(isinstance(proposal, dict) and set(proposal) <= {'id', 'domain', 'model_ids', 'relationships', 'reference_endpoints'},
                'Unsupported domain proposal fields')
        require(isinstance(proposal.get('id'), str) and proposal['id'].strip() and proposal['id'] not in proposal_ids,
                'Domain proposal IDs must be unique nonempty text')
        proposal_ids.add(proposal['id'])
        require(isinstance(proposal.get('domain'), str) and proposal['domain'].strip(), 'Domain proposal needs a domain')
        model_ids = _diagram_ids(proposal.get('model_ids'))
        association_count += len(model_ids)
        require(association_count <= 20000, 'Proposal associations exceed review limit; partition explicitly')
        require(set(model_ids) <= known, 'Domain proposal model_ids must be included canonical models')
        for identifier in model_ids:
            by_id[identifier]['proposal_domains'].append(proposal['domain'])
        endpoints = proposal.get('reference_endpoints', [])
        require(isinstance(endpoints, list) and len(endpoints) <= 20000, 'Reference endpoints must be a bounded list')
        external = set()
        for endpoint in endpoints:
            require(isinstance(endpoint, dict) and set(endpoint) <= {'id', 'name'}, 'Reference endpoints accept only id and name')
            identifier = endpoint.get('id')
            _diagram_ids([identifier])
            require(identifier not in known and identifier not in external, 'Reference endpoint duplicates a known model or endpoint')
            require('name' not in endpoint or isinstance(endpoint['name'], str) and endpoint['name'].strip(), 'Reference name must be text')
            external.add(identifier)
            if identifier in by_id:
                require(by_id[identifier]['name'] == endpoint.get('name', identifier), 'Conflicting reference endpoint names')
            else:
                node = {'id': identifier, 'name': endpoint.get('name', identifier), 'layer': 'reference',
                        'object_kind': 'reference', 'reference_only': True,
                        'grain': 'Definition absent from included model inventory'}
                require(len(nodes) < 20000, 'Combined ERD inventory exceeds review limit; partition explicitly')
                nodes.append(node); by_id[identifier] = node
        relationships = proposal.get('relationships', [])
        require(isinstance(relationships, list) and len(edges) + len(relationships) <= 20000,
                'Combined proposal relationships must be a bounded list')
        for i, edge in enumerate(relationships):
            require(isinstance(edge, dict) and isinstance(edge.get('from'), str) and isinstance(edge.get('to'), str), 'Invalid proposal relationship')
            require(edge['from'] in known | external and edge['to'] in known | external,
                    'Proposal relationship needs explicit reference_endpoints for missing models')
            require(edge.get('kind') in {'lineage', 'relationship'}, 'Proposal relationship kind must distinguish joins and dependencies')
            edges.append(dict(edge, occurrence_id='proposal:' + proposal['id'] + ':' + str(i+1), record_origin='domain_proposal',
                              proposal_id=proposal['id'], proposal_domain=proposal['domain'], record_position=i+1))
        require(external <= {edge[end] for edge in relationships for end in ('from', 'to')}, 'Reference endpoints must be used explicitly')
    require(len(nodes) <= 20000 and len(edges) <= 20000, 'Combined ERD inventory exceeds review limit; partition explicitly')
    groups = {}
    for edge in edges:
        key = json.dumps([edge['from'], edge['to'], edge['kind'], edge.get('role') or edge.get('label') or ''], sort_keys=True)
        groups.setdefault(key, []).append(edge)
    def signature(edge):
        return json.dumps([edge.get('predicate') or '', edge.get('cardinality') or '', edge.get('notation') or '',
                           edge.get('from_columns') or [], edge.get('to_columns') or [],
                           edge.get('status') or edge.get('implementation_status') or ''], sort_keys=True)
    for group in groups.values():
        signatures = Counter(signature(edge) for edge in group)
        for edge in group:
            edge['conflicting_definitions'] = len(signatures) > 1
            edge['duplicate_occurrences'] = signatures[signature(edge)]
    return nodes, edges


def _diagram_ids(value):
    require(isinstance(value, list) and value and all(isinstance(identifier, str) and identifier
            and identifier.strip() == identifier and not any(ord(char) < 32 or ord(char) == 127 for char in identifier)
            for identifier in value) and len(value) == len(set(value)),
            'Diagram scope model IDs must be a nonempty unique list')
    return value


def _numbers(text):
    require(isinstance(text, str) and re.fullmatch(r'\s*' + _NUMBER + r'(?:[ ,]+' + _NUMBER + r')*\s*', text),
            'Diagram geometry requires finite numeric coordinates')
    values = [float(value) for value in re.findall(_NUMBER, text)]
    require(all(math.isfinite(value) for value in values), 'Diagram geometry requires finite numeric coordinates')
    return values


def _matrix_product(left, right):
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def _svg_transform(text):
    result, cursor = (1, 0, 0, 1, 0, 0), 0
    for match in re.finditer(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)', text):
        require(not text[cursor:match.start()].strip(' ,\t\r\n'), 'Diagram transform is unsupported')
        name, values = match.group(1), _numbers(match.group(2))
        if name == 'matrix' and len(values) == 6:
            matrix = tuple(values)
        elif name == 'translate' and len(values) in {1, 2}:
            matrix = (1, 0, 0, 1, values[0], values[1] if len(values) == 2 else 0)
        elif name == 'scale' and len(values) in {1, 2}:
            matrix = (values[0], 0, 0, values[-1], 0, 0)
        elif name == 'rotate' and len(values) in {1, 3}:
            angle = math.radians(values[0]); cosine, sine = math.cos(angle), math.sin(angle)
            matrix = (cosine, sine, -sine, cosine, 0, 0)
            if len(values) == 3:
                x, y = values[1:]
                matrix = _matrix_product(_matrix_product((1, 0, 0, 1, x, y), matrix), (1, 0, 0, 1, -x, -y))
        elif name in {'skewX', 'skewY'} and len(values) == 1:
            tangent = math.tan(math.radians(values[0]))
            matrix = (1, 0, tangent, 1, 0, 0) if name == 'skewX' else (1, tangent, 0, 1, 0, 0)
        else:
            raise ValueError('Diagram transform is unsupported')
        result = _matrix_product(result, matrix); cursor = match.end()
    require(not text[cursor:].strip(' ,\t\r\n') and all(math.isfinite(value) for value in result),
            'Diagram transform is unsupported or nonfinite')
    return result


def _svg_suppressed(node, parents):
    """Reject obvious nondrawing contexts without claiming computed pixel visibility."""
    nondrawing = {'defs', 'marker', 'clippath', 'mask', 'pattern', 'lineargradient',
                  'radialgradient', 'symbol', 'title', 'desc', 'metadata'}
    while node is not None:
        if node.tag.split('}')[-1].lower() in nondrawing:
            return True
        if node.get('display', '').strip().lower() == 'none' or node.get('visibility', '').strip().lower() in {'hidden', 'collapse'}:
            return True
        opacity = node.get('opacity', '').strip()
        if re.fullmatch(_NUMBER + r'%?', opacity) and float(opacity.rstrip('%')) <= 0:
            return True
        node = parents.get(node)
    return False


def _svg_has_label(block, parents):
    for label in block.iter():
        if label.tag.split('}')[-1] != 'text':
            continue
        for node in label.iter():
            if (node.text or '').strip() and not _svg_suppressed(node, parents):
                return True
            # A tail belongs to its parent, so a hidden tspan need not hide it.
            if node is not label and (node.tail or '').strip() and not _svg_suppressed(parents[node], parents):
                return True
    return False


def svg_model_coverage(content, model_ids):
    """Count exact table groups and check their rectangular geometry, not pixels."""
    _diagram_ids(model_ids)
    from delivery_portal import _validate_svg
    _validate_svg(content)  # Preserve the existing inert-artifact gate unchanged.
    root = ET.fromstring(content)
    def number(value):
        values = _numbers(value)
        return values[0] if len(values) == 1 else None
    if 'viewBox' in root.attrib:
        bounds = _numbers(root.attrib['viewBox'])
        require(len(bounds) == 4, 'Diagram viewBox must contain four coordinates')
        left, top, width, height = bounds
    else:
        left, top = 0, 0
        width, height = number(root.get('width', '0')), number(root.get('height', '0'))
    require(width is not None and height is not None and width > 0 and height > 0,
            'Diagram bounds must have positive width and height')
    parents = {child: parent for parent in root.iter() for child in parent}
    blocks = [node for node in root.iter() if node.tag.split('}')[-1] == 'g' and 'data-model-id' in node.attrib]
    actual = [node.attrib['data-model-id'] for node in blocks]
    require(len(actual) == len(set(actual)), 'Diagram table groups contain duplicate model IDs')
    require(set(actual) == set(model_ids), 'Diagram table groups differ from the declared model IDs')
    for block in blocks:
        require(not _svg_suppressed(block, parents), 'Diagram model table group has a nondrawing or hidden context')
        ancestor = parents.get(block)
        while ancestor is not None:
            require(ancestor not in blocks, 'Diagram model table groups cannot be nested')
            ancestor = parents.get(ancestor)
        require(_svg_has_label(block, parents),
                'Diagram model table group must contain a nonempty text label outside hidden contexts')
        rectangles = [node for node in block.iter() if node.tag.split('}')[-1] == 'rect']
        require(rectangles, 'Diagram model table group must contain a table rectangle')
        for rectangle in rectangles:
            require(not _svg_suppressed(rectangle, parents), 'Diagram table rectangle has a nondrawing or hidden context')
            x, y = number(rectangle.get('x', '0')), number(rectangle.get('y', '0'))
            w, h = number(rectangle.get('width', '0')), number(rectangle.get('height', '0'))
            require(None not in (x, y, w, h) and w > 0 and h > 0, 'Diagram table rectangle must have positive numeric dimensions')
            chain, ancestor = [], rectangle
            while ancestor is not None:
                chain.append(ancestor); ancestor = parents.get(ancestor)
            matrix = (1, 0, 0, 1, 0, 0)
            for ancestor in reversed(chain):
                matrix = _matrix_product(matrix, _svg_transform(ancestor.get('transform', '')))
            a, b, c, d, e, f = matrix
            points = [(a*px+c*py+e, b*px+d*py+f) for px, py in ((x, y), (x+w, y), (x, y+h), (x+w, y+h))]
            require(abs(a*d-b*c) > 1e-12, 'Diagram table rectangle transform collapses its dimensions')
            require(all(math.isfinite(px) and math.isfinite(py) and left-1e-6 <= px <= left+width+1e-6
                        and top-1e-6 <= py <= top+height+1e-6 for px, py in points),
                    'Diagram table rectangle is outside the SVG bounds')
    return {'model_count': len(actual), 'model_ids': sorted(actual)}


def diagram_coverage(data, decoded_files=None):
    """Derive claims solely from included models and selected SVG bytes."""
    models = data.get('review', {}).get('models', [])
    identifiers = model_inventory(models)
    graph_nodes, _ = erd_inventory(data.get('review', {}))
    reference_ids = [node['id'] for node in graph_nodes if node.get('reference_only')]
    pages = data.get('diagrams', [])
    require(isinstance(pages, list), 'Diagram pages must be a list')
    seen = []
    for page in pages:
        require(isinstance(page, dict), 'Diagram page must be an object')
        scope = _diagram_ids(page.get('model_ids'))
        try:
            content = base64.b64decode(page.get('base64', ''), validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Diagram page has invalid base64') from error
        require(len(content) <= 20*1024*1024, 'Diagram page exceeds its byte limit')
        svg_model_coverage(content, scope)
        seen.extend(scope)
    if pages:
        if data.get('diagram_view_mode') == 'pipelines':
            require(set(seen) == set(identifiers + reference_ids), 'Pipeline views must cover every included model and reference')
            targets = [page.get('target_model_id') for page in pages if page.get('kind') == 'gold_pipeline']
            expected = {model['id'] for model in models if model['layer'] == 'gold'
                        and model.get('object_kind', 'model') not in {'interface', 'source', 'reference'}
                        and not model.get('reference_only')}
            require(len(targets) == len(set(targets)) and set(targets) == expected
                    and all(page.get('target_model_id') in page['model_ids'] for page in pages if page.get('kind') == 'gold_pipeline'),
                    'Each concrete gold output requires exactly one primary pipeline')
        else:
            require(len(seen) == len(set(seen)) and set(seen) == set(identifiers + reference_ids),
                    'Diagram pages must cover every included model exactly once')
    elif identifiers and (data.get('page_mode') == 'status' or 'diagrams' in data.get('selected_categories', [])):
        raise ValueError('Diagram pages are missing for the included model inventory')
    generated = {'status': 'verified' if pages else 'not_included', 'model_count': len(set(seen)) - (len(reference_ids) if pages else 0), 'page_count': len(pages)}
    if reference_ids and pages:
        generated['reference_count'] = len(reference_ids)
    registered = []
    for file in data.get('files', []):
        if not file.get('path', '').lower().endswith('.svg'):
            continue
        record = {'artifact_id': file['id'], 'sha256': file['sha256']}
        if 'diagram_model_ids' in file:
            scope = _diagram_ids(file['diagram_model_ids'])
            content = decoded_files[file['path']] if decoded_files is not None else base64.b64decode(file['base64'], validate=True)
            measured = svg_model_coverage(content, scope)
            record.update(status='verified_declared_scope', model_ids=measured['model_ids'],
                          model_count=measured['model_count'], qualification=DIAGRAM_QUALIFICATION)
        else:
            record.update(status='unverified', qualification=UNVERIFIED_DIAGRAM_QUALIFICATION)
        registered.append(record)
    return {'generated': generated, 'registered': registered}


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
        required_sections = REQUIRED_SECTIONS + (('table-dictionary',) if data.get('diagram_contract_version') == 1 else ())
        if data.get('package_layout_version') in (1, 2):
            required_sections += ('review-feedback',)
        for identifier in required_sections:
            node = parsed.nodes.get(identifier, {})
            attrs = node.get('attrs', {})
            parent = SECTION_PARENTS[identifier]
            require(node.get('tag') == 'section' and 'review-section' in attrs.get('class', '').split()
                    and ('data-section' in attrs) == (parent is None), 'Page review section is missing or invalid: ' + identifier)
            require((parent is None and not any(tag == 'section' for tag, _ in node.get('parents', ())))
                    or (parent is not None and node.get('parents', ())[-1:] == (('section', parent),)
                    and 'data-section' in parsed.nodes.get(parent, {}).get('attrs', {})),
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
    if 'diagram_contract_version' in data:
        require(type(data['diagram_contract_version']) is int and data['diagram_contract_version'] == 1,
                'Unsupported diagram coverage contract version')
        coverage = diagram_coverage(data, decoded)
        require(data.get('diagram_coverage') == coverage, 'Page diagram coverage differs from its included SVGs and models')
    else:
        coverage = {'status': 'unverified_legacy',
                    'qualification': 'This frozen page has no diagram coverage contract; integrity does not establish coverage.'}
    if 'package_layout_version' in data:
        from delivery_portal import validate_generated_deliverables
        require(data.get('page_mode') == 'package', 'Portable deliverable payloads require a package page')
        validate_generated_deliverables(data)
    return {'status': 'page_contract_verified', 'page_mode': data.get('page_mode', 'legacy'),
            'files': len(files), 'sections': len([node for node in parsed.nodes.values()
                                               if 'data-section' in node['attrs']]),
            'diagram_coverage': coverage,
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
