"""Offline Domo declarations: Platform DataSets, Beast Modes and ETL clipboard.

Native snapshots remain authoritative. No API requests or source evaluation.
"""
import json
from collections import defaultdict, deque

from .base import Report, read_json

CAPABILITY = {
    'formats': ['Platform v1 DataSet JSON detail/list',
                'Product v1 Beast Mode template/search JSON',
                'Magic ETL domo/dataflow-actions clipboard JSON'],
    'interpretation': 'bounded_static_extraction',
    'acquisition': 'supplied_exports',
    'limitations': [
        'Unversioned Magic ETL clipboard subset is evidenced by public native examples, not a vendor schema guarantee.',
        'Card definitions, SQL DataFlow envelopes and other Product API responses are unsupported.',
        'Native formulas and filter declarations are retained without execution or dialect substitution.',
        'Pagination, omitted definitions, runtime semantics and effective PDP/sharing access remain unverified.',
    ],
}

MAX_ACTIONS = 1000
MAX_EDGES = 4000
_DATASET = {'id', 'name', 'description', 'rows', 'columns', 'schema', 'owner',
            'createdAt', 'updatedAt', 'dataCurrentAt', 'pdpEnabled', 'policies'}
_BEAST = {'id', 'name', 'owner', 'locked', 'global', 'expression', 'checkSum',
          'links', 'legacyId', 'lastModified', 'created', 'aggregated', 'analytic',
          'nonAggregatedColumns', 'dataType', 'status', 'cacheWindow',
          'columnPositions', 'functions', 'functionTemplateDependencies',
          'archived', 'hidden', 'variable', 'activeLinks'}
_COMMON_ACTION = {'id', 'name', 'type', 'gui', 'dependsOn', 'removeByDefault', 'notes'}
_ACTION = {
    'LoadFromVault': {'dataSourceId', 'executeFlowWhenUpdated', 'onlyLoadNewVersions',
                      'columnSettings', 'visiblePartitionColumn', 'versionWindow'},
    'PublishToVault': {'dataSource', 'versionChainType', 'partitionIdColumns'},
    'ExpressionEvaluator': {'expressions'},
    'Filter': {'filterList'},
    'SelectValues': {'fields'},
    'MergeJoin': {'joinType', 'step1', 'step2', 'keys1', 'keys2',
                  'schemaModification1', 'schemaModification2', 'partitioningInputId'},
    'UnionAll': {'unionType', 'schemaSource', 'strict'},
    'Unique': {'countRows', 'partitionedAggregation', 'fields'},
    'WindowAction': {'partitionedAggregation', 'additions', 'orderRules', 'groupRules'},
}


def _identity(value):
    return str(value) if type(value) in (str, int) and str(value).strip() else None


def _unknown(report, path, value, allowed, loc):
    if set(value) - allowed:
        report.gap(path, 'domo.opaque_fields', 'Uninterpreted fields retained: ' +
                   ', '.join(sorted(set(value) - allowed)), loc)


def _objects(report, path, value, loc, code):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        report.gap(path, code, 'Expected an array of objects; original declaration retained.', loc)
        return []
    return value


def _object(report, path, loc, kind, value, **details):
    native_id = _identity(value.get('id'))
    if native_id is None:
        report.gap(path, 'domo.native_id_missing', 'Missing or invalid native identity; no identity inferred from a name.', loc)
    name = value.get('name')
    if not isinstance(name, str) or not name:
        report.gap(path, 'domo.name_missing', 'Missing or invalid object name.', loc)
        name = native_id or '(unnamed)'
    return report.object(path, loc, kind, name, native_id,
                         native_definition=value, **details)


def _dataset(report, path, value, loc, refs):
    owner = _object(report, path, loc, 'dataset', value, api_surface='platform_v1')
    refs[('dataset', _identity(value.get('id')))].append((owner, path, loc))
    _unknown(report, path, value, _DATASET, loc)
    schema = value.get('schema')
    if not isinstance(schema, dict):
        report.gap(path, 'domo.schema_missing', 'DataSet schema is absent or malformed.', loc + '.schema')
    else:
        _unknown(report, path, schema, {'columns'}, loc + '.schema')
        columns = _objects(report, path, schema.get('columns'), loc + '.schema.columns', 'domo.invalid_columns')
        if not columns:
            report.gap(path, 'domo.empty_schema', 'No column declarations were supplied.', loc + '.schema')
        names = set()
        for index, column in enumerate(columns):
            at = loc + '.schema.columns[%d]' % index
            name, data_type = column.get('name'), column.get('type')
            if not isinstance(name, str) or not name or not isinstance(data_type, str):
                report.gap(path, 'domo.invalid_column', 'Column requires a name and native type.', at)
                continue
            if name in names:
                report.gap(path, 'domo.duplicate_column', 'Repeated column name; no unique binding established.', at)
            names.add(name)
            report.object(path, at, 'column', name, parent_id=owner,
                          data_type=data_type, native_definition=column)
            if data_type not in {'STRING', 'DECIMAL', 'LONG', 'DOUBLE', 'DATE', 'DATETIME'}:
                report.gap(path, 'domo.unknown_data_type', 'Native type is outside the documented Platform subset.', at)
            _unknown(report, path, column, {'name', 'type'}, at)
    if type(value.get('pdpEnabled')) is not bool:
        report.gap(path, 'domo.pdp_state_missing', 'PDP enablement is absent or not boolean.', loc)
    policies = _objects(report, path, value.get('policies'), loc + '.policies', 'domo.policies_missing_or_invalid')
    if value.get('pdpEnabled') is True and not policies:
        report.gap(path, 'domo.enabled_pdp_without_policies', 'Enabled PDP has no supplied policy definitions.', loc)
    for index, policy in enumerate(policies):
        at = loc + '.policies[%d]' % index
        policy_id = _object(report, path, at, 'pdp_policy', policy,
                            parent_id=owner, effective_access='not_established')
        _unknown(report, path, policy, {'id', 'type', 'name', 'filters', 'users', 'groups'}, at)
        if not isinstance(policy.get('type'), str) or policy['type'] not in {'open', 'user', 'system'}:
            report.gap(path, 'domo.unknown_policy_type', 'PDP policy type requires native review.', at)
        for principal in ('users', 'groups'):
            if not isinstance(policy.get(principal), list) or any(_identity(v) is None for v in policy.get(principal, [])):
                report.gap(path, 'domo.invalid_policy_principals', 'PDP principal IDs are absent or malformed.', at)
        filters = _objects(report, path, policy.get('filters'), at + '.filters', 'domo.invalid_pdp_filters')
        for j, predicate in enumerate(filters):
            location = at + '.filters[%d]' % j
            report.expression(path, location, 'domo:pdp_filter', json.dumps(predicate, ensure_ascii=False),
                              policy_id, interpretation='native_declaration')
            _unknown(report, path, predicate, {'column', 'values', 'operator', 'not'}, location)
            if not isinstance(predicate.get('column'), str) or not isinstance(predicate.get('operator'), str) or not isinstance(predicate.get('values'), list) or ('not' in predicate and type(predicate['not']) is not bool):
                report.gap(path, 'domo.invalid_pdp_filter', 'Malformed PDP predicate retained without interpretation.', location)
    report.gap(path, 'domo.effective_access_unverified', 'PDP declarations do not establish sharing, group membership, bypass privileges or effective access.', loc)


def _beast(report, path, value, loc, refs, pending):
    owner = _object(report, path, loc, 'beast_mode', value, api_surface='product_v1')
    refs[('beast_mode', _identity(value.get('id')))].append((owner, path, loc))
    _unknown(report, path, value, _BEAST, loc)
    expression = value.get('expression')
    if isinstance(expression, str) and expression.strip():
        report.expression(path, loc + '.expression', 'domo:beast_mode', expression, owner,
                          interpretation='preserved_original', dialect='not_assumed')
    else:
        report.gap(path, 'domo.formula_missing', 'Beast Mode formula is absent or malformed; search metadata is not its definition.', loc)
    for index, link in enumerate(_objects(report, path, value.get('links'), loc + '.links', 'domo.invalid_links')):
        at = loc + '.links[%d]' % index
        resource = link.get('resource')
        if not isinstance(resource, dict) or _identity(resource.get('id')) is None:
            report.gap(path, 'domo.invalid_link', 'Resource identity is absent or malformed.', at)
            continue
        _unknown(report, path, link, {'resource', 'visible', 'active', 'valid'}, at)
        _unknown(report, path, resource, {'type', 'id'}, at + '.resource')
        resource_type = resource.get('type')
        kind = {'DATA_SOURCE': 'dataset', 'CARD': 'card'}.get(resource_type) if isinstance(resource_type, str) else None
        if kind is None:
            report.gap(path, 'domo.unknown_link_type', 'Resource type is outside this subset; full link retained.', at)
        pending.append((path, at, owner, kind or 'unknown', str(resource['id']),
                        'beast_mode_link', {'native_link': link}))
    if value.get('functionTemplateDependencies'):
        report.gap(path, 'domo.formula_dependencies_opaque', 'Nested Beast Mode dependency declarations retained without inferred bindings.', loc)
    report.gap(path, 'domo.formula_semantics_unverified', 'Aggregation, windows, filter context and native evaluation remain unverified.', loc)


def _magic(report, path, value, refs, pending):
    _unknown(report, path, value, {'contentType', 'data'}, '$')
    owner = report.object(path, '$', 'magic_etl_clipboard', path,
                          format_version='unversioned', native_definition=value)
    report.gap(path, 'domo.clipboard_scope_partial', 'Clipboard selection does not establish a complete DataFlow, flow ID, version or runtime settings.')
    actions = _objects(report, path, value.get('data'), '$.data', 'domo.invalid_actions')
    if len(actions) > MAX_ACTIONS:
        report.gap(path, 'domo.graph_limit', 'Action count exceeds the offline graph limit; raw clipboard retained.')
        return
    if not actions:
        report.gap(path, 'domo.empty_actions', 'No actions were supplied.')
    by_id, rows, edge_count = defaultdict(list), [], 0
    for index, action in enumerate(actions):
        at = '$.data[%d]' % index
        action_id = _object(report, path, at, 'etl_action', action, parent_id=owner)
        native_id, kind = _identity(action.get('id')), action.get('type')
        if native_id is not None:
            by_id[native_id].append(action_id)
        rows.append((action, at, action_id, native_id))
        if not isinstance(kind, str) or kind not in _ACTION:
            report.gap(path, 'domo.unknown_action', 'Unknown action type retained without behavioral interpretation.', at)
            continue
        _unknown(report, path, action, _COMMON_ACTION | _ACTION[kind], at)
        if kind in {'LoadFromVault', 'PublishToVault'}:
            data_source = action.get('dataSource')
            dataset = action.get('dataSourceId') if kind == 'LoadFromVault' else data_source.get('guid') if isinstance(data_source, dict) else None
            if _identity(dataset) is None:
                report.gap(path, 'domo.dataset_reference_missing', 'Action lacks a supported native DataSet reference.', at)
            else:
                pending.append((path, at, action_id, 'dataset', str(dataset),
                                'reads_from' if kind == 'LoadFromVault' else 'writes_to', {}))
        elif kind == 'ExpressionEvaluator':
            expressions = _objects(report, path, action.get('expressions'), at + '.expressions', 'domo.invalid_formulas')
            if not expressions:
                report.gap(path, 'domo.formula_missing', 'Formula action has no supplied expressions.', at)
            for j, expression in enumerate(expressions):
                loc = at + '.expressions[%d]' % j
                text = expression.get('expression')
                if not isinstance(text, str) or not text.strip() or not isinstance(expression.get('fieldName'), str):
                    report.gap(path, 'domo.invalid_formula', 'Formula requires expression text and fieldName.', loc)
                    continue
                report.expression(path, loc + '.expression', 'domo:magic_etl_formula', text, action_id,
                                  output_name=expression['fieldName'], interpretation='preserved_original')
                _unknown(report, path, expression, {'expression', 'fieldName', 'settings'}, loc)
                if expression.get('settings') is not None:
                    report.gap(path, 'domo.formula_settings_opaque', 'Formula settings retained without interpretation.', loc)
        else:
            # Native join/filter/window configuration is evidence, not SQL.
            fields = {k: action[k] for k in _ACTION[kind] if k in action}
            report.expression(path, at, 'domo:action_configuration',
                              json.dumps(fields, sort_keys=True, ensure_ascii=False), action_id,
                              action_type=kind, interpretation='native_declaration')
            report.gap(path, 'domo.action_semantics_unverified', 'Native action configuration retained; column lineage and runtime semantics are unverified.', at)
            if kind == 'Filter':
                _objects(report, path, action.get('filterList'), at + '.filterList', 'domo.invalid_filters')
    for native_id, ids in by_id.items():
        if len(ids) > 1:
            report.gap(path, 'domo.duplicate_action_id', 'Duplicate action ID; dependent edges cannot resolve uniquely.')
    adjacency, indegree = defaultdict(list), {key: 0 for key in by_id if len(by_id[key]) == 1}
    for action, at, action_id, native_id in rows:
        dependencies = action.get('dependsOn')
        if not isinstance(dependencies, list):
            report.gap(path, 'domo.invalid_action_dependencies', 'dependsOn must be a native action-ID array.', at)
            continue
        for index, dependency in enumerate(dependencies):
            edge_count += 1
            if edge_count > MAX_EDGES:
                report.gap(path, 'domo.graph_limit', 'Dependency count exceeds the offline graph limit; raw clipboard retained.')
                return
            key = _identity(dependency)
            loc = at + '.dependsOn[%d]' % index
            if key is None:
                report.gap(path, 'domo.invalid_action_dependency', 'Dependency ID is malformed; no binding inferred.', loc)
                continue
            matches = by_id.get(key, [])
            resolved = len(matches) == 1
            report.dependency(path, loc, action_id, matches[0] if resolved else 'action:' + key,
                              kind='depends_on', native_reference=key,
                              resolution='declared' if resolved else 'unresolved')
            if not resolved:
                report.gap(path, 'domo.action_dependency_unresolved', 'Action dependency is missing or duplicated in this clipboard selection.', loc)
            if resolved and native_id in indegree and key in indegree:
                adjacency[key].append(native_id)
                indegree[native_id] += 1
    queue = deque(k for k, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        key = queue.popleft()
        visited += 1
        for downstream in adjacency[key]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if visited != len(indegree):
        report.gap(path, 'domo.action_cycle', 'Declared action graph contains a cycle; execution order is not inferred.')


def parse(files):
    report, refs, pending = Report('domo', files), defaultdict(list), []
    for path in sorted(files):
        if not path.lower().endswith('.json'):
            report.cover(path, 'unsupported', 'Only the documented JSON subset is recognized.')
            report.gap(path, 'domo.unsupported_format', 'File is retained by hash without interpretation.')
            continue
        report.expression(path, '$', 'json', files[path], interpretation='preserved_original')
        try:
            value = read_json(files[path])
        except ValueError:
            report.cover(path, 'unsupported')
            report.gap(path, 'domo.invalid_json', 'Malformed, duplicate-key or over-limit JSON rejected; original text retained.')
            continue
        recognized = False
        if isinstance(value, dict) and value.get('contentType') == 'domo/dataflow-actions':
            _magic(report, path, value, refs, pending)
            recognized = True
        else:
            search = isinstance(value, dict) and {'results', 'totalHits', 'hasMore'} <= set(value)
            rows = value.get('results') if search else value if isinstance(value, list) else [value]
            if search:
                _unknown(report, path, value, {'results', 'totalHits', 'hasMore', 'degraded'}, '$')
                report.gap(path, 'domo.pagination_unverified', 'Search paging and totalHits are source declarations; inventory completeness is not established.')
                if type(value['hasMore']) is not bool or type(value['totalHits']) is not int or value['totalHits'] < 0:
                    report.gap(path, 'domo.invalid_pagination', 'Search paging fields have invalid types or values.')
                if value.get('hasMore') is True:
                    report.gap(path, 'domo.more_pages', 'Search reports additional results not present in this file.')
                if value.get('degraded') is True:
                    report.gap(path, 'domo.degraded_search', 'Source reports degraded search results.')
            if not isinstance(rows, list):
                report.gap(path, 'domo.invalid_collection', 'Expected a result array.')
                rows = []
            if not rows or value == {}:
                report.gap(path, 'domo.empty_export', 'No definitions supplied; absence of source objects cannot be concluded.')
            for index, row in enumerate(rows):
                loc = '$.results[%d]' % index if search else '$[%d]' % index if isinstance(value, list) else '$'
                if isinstance(row, dict) and 'schema' in row and not search:
                    _dataset(report, path, row, loc, refs)
                    recognized = True
                elif isinstance(row, dict) and 'legacyId' in row and ('links' in row or 'expression' in row):
                    _beast(report, path, row, loc, refs, pending)
                    recognized = True
                else:
                    report.gap(path, 'domo.unsupported_shape', 'Record does not match a supported DataSet, Beast Mode or clipboard definition.', loc)
            if isinstance(value, list):
                report.gap(path, 'domo.pagination_unverified', 'Array coverage does not establish completion of any API list or export.')
        report.cover(path, 'parsed' if recognized else 'unsupported')
    for (kind, native_id), matches in refs.items():
        if native_id is not None and len(matches) > 1:
            for _, path, loc in matches:
                report.gap(path, 'domo.duplicate_native_id', 'Multiple supplied definitions share this native ID; references remain unresolved.', loc)
    for path, loc, owner, kind, native_id, edge_kind, details in pending:
        matches = refs.get((kind, native_id), [])
        resolved = len(matches) == 1
        report.dependency(path, loc, owner, matches[0][0] if resolved else kind + ':' + native_id,
                          kind=edge_kind, native_reference=native_id,
                          resolution='declared' if resolved else 'unresolved', **details)
        if not resolved:
            report.gap(path, 'domo.reference_unresolved', 'Referenced native object is missing, ambiguous or outside the supported subset.', loc)
    return report.finish()
