"""Bounded Tableau declarations, reusing the existing read-only TWB/TDS inventory.

XML is evidence, never executable input. Native execution, published dependencies,
relationship semantics and source completeness are intentionally not established.
"""
from pathlib import Path, PurePosixPath
import logging
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

import tableau_source as legacy
from .base import Report


CAPABILITY = {
    'formats': ['UTF-8 TWB workbook XML (26.1 synthetic fixture)',
                'UTF-8 TDS datasource XML (mirror/declaration evidence)'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'No Tableau, SQL, scripts, network acquisition or source code execution.',
        'Legacy Snowflake custom-SQL analysis is reused; other relations remain declarations.',
        'Published sources, relationships, blending, extracts and Prep require separate evidence.',
        'TDS mirrors do not establish workbook authority; no cross-version compatibility claim.',
        'XML parsing and the separate official-schema attempt are not native validation.',
    ],
}

# XML depth is tighter than the JSON contract because legacy native-node evidence
# alternates child arrays and dictionaries. Bound before any recursive helper.
MAX_XML_DEPTH = 16
MAX_XML_NODES = 5000
_LOD = re.compile(r'\{\s*(FIXED|INCLUDE|EXCLUDE)\b', re.I)
_TABLE_CALC = re.compile(r'\b(?:WINDOW_\w+|RUNNING_\w+|RANK\w*|LOOKUP|INDEX|FIRST|LAST|SIZE|PREVIOUS_VALUE|TOTAL)\s*\(', re.I)
_EXTERNAL = re.compile(r'\b(?:SCRIPT_\w+|MODEL_EXTENSION_\w+|RAWSQL_\w+)\s*\(', re.I)


def _nodes(root):
    """Stable, index-based XML locators retain repeated native declarations."""
    stack = [(root, '/' + root.tag + '[1]', 1)]
    count = 0
    while stack:
        node, loc, depth = stack.pop()
        count += 1
        if depth > MAX_XML_DEPTH or count > MAX_XML_NODES:
            raise ValueError('Tableau XML structure exceeds bounded limits')
        yield node, loc
        children, counts = [], {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            children.append((child, loc + '/' + child.tag + '[' + str(counts[child.tag]) + ']', depth + 1))
        stack.extend(reversed(children))


def _safe_xml(content, suffix):
    declaration = re.match(r'\ufeff?\s*<\?xml\s+[^?]*encoding\s*=\s*[\'"]([^\'"]+)', content, re.I)
    if declaration and declaration.group(1).lower() not in ('utf-8', 'utf8'):
        raise ValueError('Only UTF-8 XML declarations are supported')
    root = legacy._xml(content.encode('utf-8'))
    if root.tag != ('workbook' if suffix == '.twb' else 'datasource'):
        raise ValueError('Root element does not match the Tableau file type')
    list(_nodes(root))
    return root


def _normalize(r, inventory):
    """Translate the existing extractor's scoped identities into common evidence."""
    ids, records, filter_refs = {}, {}, []
    parameters = {p['id']: p for p in inventory['parameters']}
    for collection, kind in (('workbooks', 'workbook'), ('datasources', 'datasource'),
                             ('fields', 'field'), ('worksheets', 'worksheet'), ('dashboards', 'dashboard')):
        for item in inventory[collection]:
            path, identity = item['path'], item['id']
            details = {k: v for k, v in item.items() if k not in
                       ('id', 'path', 'name', 'native_id', 'fields', 'filters', 'datasource_filters', 'custom_sql',
                        'formula', 'table_calc', 'table_calculations', 'instances')}
            details['legacy_id'] = identity
            details['analysis_origin'] = 'tableau_source.inspect_repo'
            if identity in parameters:
                kind_for_item = 'parameter'
                details.update({k: parameters[identity].get(k) for k in
                                ('default', 'native_value', 'domain_type', 'members', 'range')})
            else:
                kind_for_item = kind
            # Field/datasource names are native scoped identifiers; only workbook
            # repository IDs and worksheet simple IDs can identify server content.
            native_id = item.get('native_id') if kind in ('workbook', 'worksheet') else item.get('name')
            oid = r.object(path, 'legacy:' + identity, kind_for_item,
                           item.get('caption') or item.get('name') or PurePosixPath(path).stem,
                           native_id=native_id, **details)
            ids[identity], records[identity] = oid, item
            if item.get('formula') is not None:
                formula = item['formula']
                markers = _LOD.findall(formula)
                r.expression(path, 'legacy:' + identity + '/calculation', 'tableau', formula, oid,
                             calculation_attributes=item.get('calculation_attributes'),
                             lod_markers=markers, evaluation='not_run')
                if markers:
                    r.gap(path, 'tableau.lod_unvalidated', 'LOD declaration retained; filter order and grain require native validation.', 'legacy:' + identity)
                if _TABLE_CALC.search(formula):
                    r.gap(path, 'tableau.table_calculation_unvalidated', 'Table calculation formula retained; addressing, partitioning and densification require native validation.', 'legacy:' + identity)
                if _EXTERNAL.search(formula):
                    r.gap(path, 'tableau.external_calculation', 'External calculation declaration is not executed or resolved.', 'legacy:' + identity)
            for index, filt in enumerate(item.get('filters', [])):
                loc = 'legacy:' + identity + '/filter[' + str(index) + ']'
                fid = r.object(path, loc, 'filter', filt.get('caption') or filt.get('column') or 'unnamed filter',
                               native_id=filt.get('column'), owner_id=oid, native=filt)
                if filt.get('field_id'):
                    filter_refs.append((path, loc, fid, filt['field_id']))
            for index, tc in enumerate(item.get('table_calculations', [])):
                r.object(path, 'legacy:' + identity + '/table-calculation[' + str(index) + ']',
                         'table_calculation', tc.get('column') or 'unnamed table calculation',
                         native_id=tc.get('column'), owner_id=oid, native=tc,
                         partitioning_status='inference_from_view_dimensions', evaluation='not_run')
    for path, loc, fid, target in filter_refs:
        r.dependency(path, loc, fid, ids.get(target, target), kind='filter_field',
                     resolution='declared' if target in ids else 'unresolved')
    for edge in inventory['edges']:
        # In the legacy graph edges point from input to consumer. Common contract
        # dependencies point from owner/consumer to referenced input.
        consumer = edge['to']
        if consumer in ids:
            item = records[consumer]
            r.dependency(item['path'], 'legacy:' + consumer, ids[consumer],
                         ids.get(edge['from'], edge['from']), kind=edge['kind'],
                         native_reference=edge.get('evidence'),
                         resolution='declared' if edge['from'] in ids else 'unresolved_physical_reference')
    for mirror in inventory['mirrors']:
        oid = r.object(mirror['path'], '/datasource[1]', 'datasource_mirror',
                       mirror['datasource_id'], authority='consistency_mirror_only',
                       matches_embedded=mirror['matches_embedded'])
        r.dependency(mirror['path'], '/datasource[1]', oid,
                     ids.get(mirror['datasource_id'], mirror['datasource_id']), kind='mirror_of')
    for gap in inventory['gaps']:
        paths = [gap['path']] if gap.get('path') in r.files else sorted({a['path'] for a in inventory['assets']})
        for path in paths:
            r.gap(path, 'tableau.' + gap['kind'], gap['message'], 'legacy:' + gap['id'] if gap.get('id') else '$')
    return ids


def _declarations(r, path, root):
    """Preserve omitted native structures without interpreting runtime semantics."""
    nodes = list(_nodes(root))
    parents = {child: node for node, _ in nodes for child in node}
    normalized_filters = set(root.findall('./datasources/datasource/filter') +
                             root.findall('./worksheets/worksheet/table/view/filter'))
    r.expression(path, '/' + root.tag + '[1]', 'tableau_xml', r.files[path],
                 evaluation='not_run', authority='original_supplied_document')
    if root.get('version') != '26.1':
        r.gap(path, 'tableau.unqualified_version', 'Version is absent or outside the 26.1 synthetic fixture; declarations only.', '/' + root.tag + '[1]')
    r.gap(path, 'tableau.declaration_subset', 'Only the documented declaration subset is normalized; other native XML remains in the source expression.')
    for node, loc in nodes:
        tag = node.tag.split('}')[-1]
        if tag == 'relation':
            kind = node.get('type')
            oid = r.object(path, loc, 'relation', node.get('name') or node.get('table') or kind or 'unnamed relation',
                           native_id=node.get('name'), native=legacy._node(node), relation_type=kind,
                           semantics='declaration_only')
            if kind == 'text':
                r.expression(path, loc + '/text()', 'sql', node.text or '', oid, dialect='unresolved', evaluation='not_run')
            elif kind == 'table' and node.get('table'):
                r.dependency(path, loc, oid, node.get('table'), kind='declared_table', resolution='unresolved')
            if kind not in ('text', 'table'):
                r.gap(path, 'tableau.relation_semantics_unresolved', 'Join, union or unknown relation is retained without translating physical/logical semantics.', loc)
        elif tag in ('object-graph', 'object-model', 'relationship', 'relationships'):
            r.object(path, loc, 'relationship_declaration', node.get('name') or node.get('id') or tag,
                     native_id=node.get('id'), native=legacy._node(node), semantics='unresolved')
            r.gap(path, 'tableau.relationships_unresolved', 'Logical relationships, cardinality and referential-integrity declarations require query-context validation; not converted into joins.', loc)
        elif tag == 'repository-location' and root.tag == 'datasource' and parents.get(node) is root:
            r.object(path, loc, 'datasource_identity', root.get('name') or 'unnamed datasource',
                     native_id=node.get('id'), native=legacy._node(node), identity_status='declared_not_authenticated')
        elif tag in ('publishedsource', 'datasource-url') or (tag == 'connection' and node.get('class') == 'sqlproxy') or (
                tag == 'repository-location' and parents.get(node) is not None and parents[node].tag == 'datasource'):
            target = node.get('id') or node.get('path') or node.get('name') or (node.text or '').strip() or 'unidentified published source'
            oid = r.object(path, loc, 'published_source_reference', target, native_id=node.get('id'), native=legacy._node(node))
            r.dependency(path, loc, oid, target, kind='published_source', resolution='unresolved')
            r.gap(path, 'tableau.published_source_unresolved', 'Published datasource reference requires a separately acquired authoritative definition and identity binding; filenames/names do not resolve it.', loc)
        elif tag in ('datasource-dependency', 'blend', 'blending', 'link', 'links', 'column-mapping'):
            r.object(path, loc, 'blending_declaration', tag, native=legacy._node(node))
            r.gap(path, 'tableau.blending_unresolved', 'Potential cross-datasource/blending declaration retained; primary/secondary aggregation behavior is unresolved.', loc)
        elif tag == 'worksheet':
            physical = [d.get('name') for d in node.findall('./table/view/datasources/datasource') if d.get('name') != 'Parameters']
            if len(set(physical)) > 1:
                r.gap(path, 'tableau.blending_unresolved', 'Worksheet references multiple non-parameter datasources; relationship/blending semantics require separate validation.', loc)
        elif tag == 'table-calc':
            r.object(path, loc, 'table_calculation_declaration', node.get('type') or 'table-calc',
                     native=legacy._node(node), evaluation='not_run')
            r.gap(path, 'tableau.table_calculation_unvalidated', 'Authored table-calc declaration preserved without asserting partitioning, ordering or densification parity.', loc)
        elif tag in ('extract', 'refresh', 'incremental-refresh', 'virtual-connection', 'data-policy',
                     'initial-sql', 'initialsql', 'script', 'extension', 'extensions'):
            r.object(path, loc, 'unsupported_declaration', tag, native=legacy._node(node))
            r.gap(path, 'tableau.unsupported_construct', 'Native ' + tag + ' requires separate evidence; it is not run or interpreted.', loc)
        # A TDS without a TWB is still useful declaration evidence, but cannot
        # silently become a workbook or a resolved published datasource.
        if root.tag == 'datasource' and tag == 'column' and parents.get(node) is root:
            oid = r.object(path, loc, 'datasource_field_declaration', node.get('caption') or node.get('name') or 'unnamed field',
                           native_id=node.get('name'), native=legacy._node(node), authority='tds_declaration_only')
            calc = node.find('calculation')
            if calc is not None and calc.get('formula') is not None:
                r.expression(path, loc + '/calculation[1]/@formula', 'tableau', calc.get('formula'), oid,
                             evaluation='not_run', lod_markers=_LOD.findall(calc.get('formula')))
        if tag == 'filter' and node not in normalized_filters:
            r.object(path, loc, 'filter_declaration', node.get('column') or 'unnamed filter',
                     native_id=node.get('column'), native=legacy._node(node), evaluation='not_run')
            r.gap(path, 'tableau.filter_unvalidated', 'Filter declaration retained without resolving its field, population or order of operations.', loc)


def parse(files):
    r = Report('tableau', files)
    safe = {}
    collisions = {}
    for path in sorted(files):
        key = unicodedata.normalize('NFC', path).casefold()
        collisions.setdefault(key, []).append(path)
    colliding = {p for paths in collisions.values() if len(paths) > 1 for p in paths}
    for path, text in sorted(files.items()):
        suffix = PurePosixPath(path).suffix.lower()
        if path in colliding or any(unicodedata.normalize('NFC', str(p)).casefold() in collisions
                                    for p in PurePosixPath(path).parents if str(p) != '.'):
            r.cover(path, 'unsupported', 'Ambiguous or colliding source path.')
            r.gap(path, 'tableau.path_collision', 'Case/Unicode collision or file-directory conflict prevents safe inventory.')
        elif suffix not in ('.twb', '.tds'):
            r.cover(path, 'unsupported', 'Only supplied UTF-8 TWB/TDS XML is accepted.')
            code = 'tableau.prep_unsupported' if suffix in ('.tfl', '.tflx') else 'tableau.package_or_extract_unsupported' if suffix in ('.twbx', '.tdsx', '.hyper', '.tde') else 'tableau.unsupported_format'
            r.gap(path, code, 'Requires a separate approved acquisition/inventory; no unpacking, data reading or execution occurs.')
        else:
            r.cover(path)
            try:
                safe[path] = _safe_xml(text, suffix)
            except legacy.CredentialContentError:
                r.gap(path, 'tableau.credential_content', 'Credential-bearing XML is excluded; provide a credential-free export.')
            except (ET.ParseError, ValueError, RecursionError, UnicodeError):
                r.gap(path, 'tableau.invalid_xml', 'Invalid, unsafe, oversized or unsupported XML; source contents are not echoed.')
    if safe:
        with tempfile.TemporaryDirectory(prefix='dma-tableau-') as directory:
            root = Path(directory)
            for path in safe:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(files[path], encoding='utf-8')
            try:
                # SQLGlot may otherwise log rejected SQL source text. Diagnostics
                # belong in the evidence result, never incidental process logs.
                logger = logging.getLogger('sqlglot')
                previous = logger.disabled
                try:
                    logger.disabled = True
                    inventory = legacy.inspect_repo(root)
                finally:
                    logger.disabled = previous
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError, ET.ParseError):
                inventory = None
                for path in safe:
                    r.gap(path, 'tableau.legacy_inventory_unavailable', 'Legacy inventory could not interpret this supplied structure; only bounded native declarations are retained.')
            if inventory is not None:
                _normalize(r, inventory)
        for path, tree in safe.items():
            _declarations(r, path, tree)
    return r.finish()
