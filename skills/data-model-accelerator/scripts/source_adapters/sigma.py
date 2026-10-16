"""Offline, bounded extraction of documented Sigma REST v2 response bodies.

Response files are not a complete workbook export. In particular, most list
entries omit their request's workbook/page/element context; filenames never
supply that missing identity. Formula text and SQL are preserved, not executed.
"""
import json
import re
from pathlib import PurePosixPath

from .base import Report, read_json
from .sql import parse_sql


CAPABILITY = {
    'formats': ['Sigma REST v2 workbook/page/element/column/query/dataset/grant JSON',
                'Sigma REST v2 workbook element lineage JSON', 'Unbound SQL evidence'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'Metadata snapshots are not complete logic exports; request scope and versions need external evidence.',
        'Sigma formulas and SQL are retained without formula evaluation or inferred SQL dialect.',
        'Workbook code representation is Beta and retained as opaque unsupported contents.',
        'Datasets are Deprecated; their metadata response does not supply dataset logic.',
        'Declared grants and lineage do not establish effective security or semantic parity.',
    ],
}

_KEYS = {
    'workbook': set('workbookId workbookUrlId name url path latestVersion ownerId createdBy updatedBy '
                    'createdAt updatedAt isArchived tags description taggedSourceUrlId documentVersion contents'.split()),
    'dataset': set('datasetId createdBy updatedBy createdAt updatedAt name description url owner '
                   'referenceCount path migrationToDataModel migrationStatus isArchived'.split()),
    'page': {'pageId', 'name', 'hidden'},
    'element': {'elementId', 'name', 'type', 'columns', 'vizualizationType', 'error'},
    'column': {'columnId', 'label', 'formula', 'type'},
    'query': {'elementId', 'name', 'sql', 'error'},
    'grant': set('grantId inodeId organizationId memberId teamId permission createdBy updatedBy '
                 'createdAt updatedAt inodeType'.split()),
}
_ID = {'workbook': 'workbookId', 'dataset': 'datasetId', 'page': 'pageId',
       'element': 'elementId', 'query': 'elementId', 'column': 'columnId', 'grant': 'grantId'}


def _string(value):
    return isinstance(value, str) and bool(value.strip())


class _Parser:
    def __init__(self, files):
        self.r = Report('sigma', files)
        self.seen = {}

    def gap(self, path, code, message, loc='$'):
        self.r.gap(path, 'sigma.' + code, message, loc)

    def opaque(self, path, loc, value):
        self.r.expression(path, loc, 'sigma_json', json.dumps(value, ensure_ascii=True),
                          interpretation='preserved_uninterpreted')

    def unknown(self, path, loc, value, keys):
        if set(value) - keys:
            self.gap(path, 'unknown_fields', 'Unrecognized fields are retained without interpretation.', loc)

    def kind(self, value):
        if not isinstance(value, dict):
            return None
        kinds = [kind for kind in ('workbook', 'dataset', 'page', 'column', 'grant') if _ID[kind] in value]
        if 'elementId' in value:
            # A query's optional fields can both be absent. Such a projection is
            # ambiguous with element metadata and cannot be guessed from a name.
            if 'type' in value and 'sql' not in value:
                kinds.append('element')
            elif 'sql' in value or ('error' in value and 'type' not in value):
                kinds.append('query')
        return kinds[0] if len(kinds) == 1 else None

    def resource(self, path, loc, value):
        kind = self.kind(value)
        if kind is None:
            self.opaque(path, loc, value)
            self.gap(path, 'unknown_resource', 'Response entry is not an unambiguous supported native resource.', loc)
            return None
        native_id = value[_ID[kind]]
        if not _string(native_id):
            self.opaque(path, loc, value)
            self.gap(path, 'invalid_identity', 'Native identity must be a non-empty string.', loc)
            return None
        self.unknown(path, loc, value, _KEYS[kind])
        name = value.get('label' if kind == 'column' else 'name', native_id)
        if not isinstance(name, str):
            self.gap(path, 'invalid_field', 'Resource display name must be a string when supplied.', loc)
            name = native_id
        oid = self.r.object(path, loc, kind, name, native_id=native_id, raw_metadata=value)
        identity = (kind, native_id)
        if identity in self.seen:
            self.gap(path, 'duplicate_identity', 'Repeated native identity is retained as separate evidence; versions and parent scope are not merged.', loc)
            old_path, old_loc = self.seen[identity]
            self.gap(old_path, 'duplicate_identity', 'Repeated native identity is retained as separate evidence; versions and parent scope are not merged.', old_loc)
        self.seen[identity] = (path, loc)
        if kind in ('page', 'element', 'column', 'query'):
            self.gap(path, 'request_context_missing', 'This response does not establish its request parent, version, tag, or saved-view scope; filename context is not inferred.', loc)
        if kind == 'workbook':
            self.gap(path, 'workbook_logic_incomplete', 'Workbook metadata alone omits definitions, controls, interactions and effective security.', loc)
            if 'contents' in value:
                self.gap(path, 'beta_contents_unsupported', 'Workbook code representation is Beta; contents are retained without interpretation and can omit unsupported vendor features.', loc + '.contents')
        elif kind == 'dataset':
            self.gap(path, 'dataset_deprecated', 'Datasets are Deprecated; this metadata endpoint does not expose dataset SQL, formulas or security behavior.', loc)
            migration = value.get('migrationToDataModel')
            if migration is not None:
                if isinstance(migration, dict) and _string(migration.get('dataModelId')):
                    self.unknown(path, loc + '.migrationToDataModel', migration,
                                 {'dataModelId', 'dataModelUrl', 'migratedAt', 'migratedBy'})
                    self.r.dependency(path, loc + '.migrationToDataModel.dataModelId', oid,
                                      migration['dataModelId'], kind='migration_to_data_model',
                                      resolution='unresolved', acceptance='not_verified')
                else:
                    self.gap(path, 'invalid_field', 'Migration metadata requires an explicit dataModelId.', loc + '.migrationToDataModel')
        elif kind == 'page':
            if 'hidden' in value and type(value['hidden']) is not bool:
                self.gap(path, 'invalid_field', 'Page hidden flag must be boolean; visibility is not an access-control claim.', loc + '.hidden')
        elif kind == 'element':
            if not _string(value.get('type')):
                self.gap(path, 'invalid_field', 'Element type must be a non-empty string.', loc + '.type')
            cols = value.get('columns')
            if cols is not None:
                if not isinstance(cols, list) or not all(_string(v) for v in cols):
                    self.gap(path, 'invalid_field', 'Element columns must be a list of native column ID strings.', loc + '.columns')
                else:
                    for i, column in enumerate(cols):
                        self.r.dependency(path, loc + '.columns[%d]' % i, oid, column,
                                          kind='declared_column', resolution='unresolved')
            self.gap(path, 'element_behavior_incomplete', 'Element metadata does not define filters, grouping, joins, controls, actions or presentation behavior.', loc)
        elif kind == 'column':
            formula = value.get('formula')
            if isinstance(formula, str):
                self.r.expression(path, loc + '.formula', 'sigma_formula', formula, oid,
                                  interpretation='preserved_original')
                self.gap(path, 'formula_unresolved', 'Formula evaluation, referenced columns, controls and user context require native evidence; no bracket-based lineage is inferred.', loc + '.formula')
            else:
                self.gap(path, 'formula_missing', 'Column formula is absent or is not a string.', loc + '.formula')
        elif kind == 'query':
            sql = value.get('sql')
            if _string(sql):
                # The documented query response does not identify the warehouse
                # dialect. Preserve its bytes rather than guessing from syntax.
                parse_sql(self.r, path, sql, None, oid, loc + '.sql')
                if re.search(r'\{\{|\{%|\bEXECUTE\s+IMMEDIATE\b|\bCALL\s+', sql, re.I):
                    self.gap(path, 'dynamic_sql', 'Dynamic or parameterized SQL is preserved; runtime expansion is unavailable.', loc + '.sql')
            else:
                self.gap(path, 'query_unavailable', 'The response omits SQL or supplies an invalid/empty SQL value.', loc)
        elif kind == 'grant':
            inode, permission = value.get('inodeId'), value.get('permission')
            if _string(inode):
                self.r.dependency(path, loc + '.inodeId', oid, inode, kind='grant_on', resolution='unresolved')
            else:
                self.gap(path, 'invalid_field', 'Grant requires a native inodeId.', loc)
            principals = [k for k in ('memberId', 'teamId') if value.get(k) is not None]
            if len(principals) != 1 or not all(_string(value[k]) for k in principals) or not _string(permission):
                self.gap(path, 'invalid_grant', 'Grant requires exactly one declared member/team principal and a permission string.', loc)
            self.gap(path, 'security_not_verified', 'Grant declarations do not establish inherited permissions, warehouse policies, row/column security or effective user access.', loc)
        if value.get('error'):
            self.gap(path, 'api_resource_error', 'The native response reports an error; retained metadata or SQL is not proof of successful execution.', loc + '.error')
        return kind

    def lineage(self, path, data):
        self.unknown(path, '$', data, {'dependencies', 'edges'})
        nodes, edges = data.get('dependencies'), data.get('edges')
        if not isinstance(nodes, dict) or not isinstance(edges, list):
            self.opaque(path, '$', data)
            self.gap(path, 'invalid_lineage', 'Expected a dependencies mapping and an edges list.')
            return
        owners = {}
        for native_key, node in sorted(nodes.items()):
            loc = '$.dependencies[' + json.dumps(native_key) + ']'
            if not isinstance(node, dict) or not _string(node.get('nodeId')) or node['nodeId'] != native_key:
                self.opaque(path, loc, node)
                self.gap(path, 'invalid_lineage_node', 'Lineage nodeId must equal its dependencies key.', loc)
                continue
            self.unknown(path, loc, node, {'name', 'nodeId', 'type', 'elementId'})
            owners[native_key] = self.r.object(path, loc, 'lineage_node',
                node.get('name') if isinstance(node.get('name'), str) else native_key,
                native_id=native_key, raw_metadata=node)
        for i, edge in enumerate(edges):
            loc = '$.edges[%d]' % i
            if not isinstance(edge, dict):
                self.opaque(path, loc, edge)
                self.gap(path, 'invalid_lineage_edge', 'Lineage edge must be an object.', loc)
                continue
            self.unknown(path, loc, edge, {'source', 'target', 'type'})
            source, target = edge.get('source'), edge.get('target')
            if not _string(source) or not _string(target) or source not in owners or target not in owners:
                self.opaque(path, loc, edge)
                self.gap(path, 'unbound_lineage_edge', 'Edge endpoints must identify nodes in this same supplied graph.', loc)
                continue
            # Sigma edges run upstream -> downstream. Canonical dependencies
            # run dependent -> prerequisite. Retain both native endpoint IDs.
            self.r.dependency(path, loc, owners[target], owners[source],
                              kind='native_lineage', resolution='declared', raw_metadata=edge,
                              native_source_id=source, native_target_id=target)
            if edge.get('type') not in ('source', 'lookup'):
                self.gap(path, 'unknown_lineage_type', 'Edge type is retained without interpreting its semantics.', loc)
        self.gap(path, 'lineage_scope_unverified', 'Graph relationships are declarations; request element, versions, physical paths, join logic and completeness remain unverified.')

    def document(self, path, data):
        if isinstance(data, dict) and ('dependencies' in data or 'edges' in data):
            self.lineage(path, data)
            return
        if isinstance(data, dict) and 'entries' in data:
            self.unknown(path, '$', data, {'entries', 'nextPage', 'hasMore', 'total'})
            entries = data['entries']
            if not isinstance(entries, list):
                self.opaque(path, '$', data)
                self.gap(path, 'invalid_entries', 'A list endpoint requires an entries array.')
                return
            if not entries:
                self.gap(path, 'empty_response', 'Empty entries do not establish that the requested source scope is empty or accessible.')
            if data.get('nextPage') or data.get('hasMore') is True:
                self.gap(path, 'pagination_incomplete', 'Response indicates another page; this adapter does not fetch or reconcile pagination chains.')
            if ('nextPage' not in data or (data['nextPage'] is not None and not isinstance(data['nextPage'], str))
                    or ('hasMore' in data and type(data['hasMore']) is not bool)):
                self.gap(path, 'pagination_metadata_invalid', 'Pagination terminal state is absent or malformed.')
            total = data.get('total')
            if total is not None and (type(total) not in (int, float) or total < 0 or total != len(entries)):
                self.gap(path, 'count_mismatch', 'Total is invalid or differs from this response count; coverage remains unverified.')
            kinds = {self.resource(path, '$.entries[%d]' % i, entry) for i, entry in enumerate(entries)}
            if len(kinds - {None}) > 1:
                self.gap(path, 'mixed_resource_collection', 'A collection contains different native resource kinds; endpoint provenance is unverified.')
            return
        if self.resource(path, '$', data) is None:
            self.r.cover(path, 'unsupported', 'Unknown Sigma response shape.')


def parse(files: dict[str, str]):
    parser = _Parser(files)
    for path, text in sorted(files.items()):
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == '.sql':
            parse_sql(parser.r, path, text, None, locator='$sql')
            parser.gap(path, 'unbound_sql', 'Standalone SQL lacks a native Sigma resource binding and execution context.')
            continue
        if suffix != '.json':
            parser.r.cover(path, 'unsupported', 'Only documented JSON response bodies and unbound SQL evidence are accepted.')
            parser.gap(path, 'data_export_not_logic', 'CSV, spreadsheets, PDF, images and other exports do not establish native Sigma logic.')
            continue
        try:
            data = read_json(text)
        except ValueError:
            parser.r.expression(path, '$raw', 'sigma_json', text, interpretation='preserved_uninterpreted')
            parser.r.cover(path, 'unsupported', 'Malformed or unsafe JSON.')
            parser.gap(path, 'invalid_json', 'JSON failed bounded, duplicate-key or syntax validation.')
            continue
        parser.r.cover(path)
        parser.document(path, data)
        parser.gap(path, 'snapshot_scope_unverified', 'Supplied response does not prove API principal, request filters, pagination chain, snapshot version or complete logic coverage.')
    return parser.r.finish()
