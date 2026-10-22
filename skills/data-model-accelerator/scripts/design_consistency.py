"""Bounded, additive diagnostics for the existing schema-v1 entity design.

No SQL is evaluated or parsed. Only explicit column bindings are checked. A
consistent design means its supplied structures agree; it says nothing about
warehouse execution, data accuracy, business acceptance or authorization.
"""
import copy
import hashlib
import json
from collections import Counter

from ae_common import _json_bytes, hash_json, require

MAX_ITEMS = 20000
MAX_BYTES = 20 * 1024 * 1024
DICTIONARY_FIELDS = ('model_id', 'model_name', 'layer', 'domain', 'grain',
                     'column_name', 'data_type', 'key', 'description')
MODEL_FIELDS = ('id', 'name', 'layer', 'domain', 'grain', 'asset_ids', 'depends_on',
                'mapping_status', 'disposition', 'object_kind', 'keys', 'security', 'history')
COLUMN_FIELDS = ('name', 'type', 'key', 'nullable', 'description')
RELATIONSHIP_FIELDS = ('from', 'to', 'kind', 'predicate', 'cardinality', 'role', 'status',
                       'from_columns', 'to_columns', 'from_column', 'to_column')
QUALIFICATION = ('Structural diagnostics only. Unknown physical and business validation remain unknown. '
                 'Findings do not prohibit provisional artifacts or grant authoring or deployment authority.')
_UNKNOWN = {'unknown', 'unresolved', 'not supplied', 'not available'}
_PLACEHOLDERS = {'tbd', 'todo', 'placeholder', '?', '...', '<column>', '<column_name>',
                 '<name>', '<type>', '<data_type>', 'your_column', 'your_column_name'}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key')
        result[key] = value
    return result


def _load(value):
    if type(value) in (bytes, str):
        raw = value.encode('utf-8') if type(value) is str else value
        if len(raw) > MAX_BYTES:
            raise ValueError('Design consistency input exceeds byte limit')
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError) as error:
            raise ValueError('Design consistency input must be JSON: ' + str(error)) from error
        serialization = 'provided_json_bytes'
    else:
        raw = _json_bytes(value)
        serialization = 'canonical_json_bytes'
    if type(value) is not dict:
        raise ValueError('Design consistency input must be an object')
    if len(raw) > MAX_BYTES:
        raise ValueError('Design consistency input exceeds byte limit')
    # Apply bounds before inspecting any collection. Reject non-JSON numbers,
    # object keys and values using the same canonical encoder as the workflow.
    _json_bytes(value)
    for name in ('entities', 'models', 'relationships', 'assets', 'decisions', 'existing_models'):
        rows = value.get(name, [])
        if type(rows) is list and len(rows) > MAX_ITEMS:
            raise ValueError('Design consistency collection exceeds item limit')
    for collection in ('entities', 'models'):
        for row in _objects(value.get(collection)):
            if type(row.get('columns')) is list and len(row['columns']) > MAX_ITEMS:
                raise ValueError('Design consistency per-model column inventory exceeds item limit')
    return copy.deepcopy(value), hashlib.sha256(raw).hexdigest(), serialization


def _binding(design):
    return {'id': design.get('id'), 'revision': design.get('revision'),
            'sha256': hash_json({key: value for key, value in design.items() if key != 'sha256'})}


def _report(design, input_sha256, serialization, kind='design_consistency'):
    return {'schema_version': 1, 'kind': kind, 'status': 'consistent',
            'design_binding': _binding(design), 'input_sha256': input_sha256,
            'input_serialization': serialization, 'findings': [], 'unknowns': [],
            'authority': {'authoring': False, 'deployment': False}, 'qualification': QUALIFICATION}


def _finding(report, code, path, message, *, unknown=False, scope='structural', **context):
    row = {'code': code, 'scope': scope, 'status': 'unknown' if unknown else 'fail',
           'path': path, 'message': message, **context}
    report['unknowns' if unknown else 'findings'].append(row)
    if not unknown:
        report['status'] = 'findings'


def _objects(value):
    return [row for row in value if type(row) is dict] if type(value) is list else []


def _text(value):
    return type(value) is str and bool(value.strip())


def _unknown(value):
    return value is None or (type(value) is str and value.strip().casefold() in _UNKNOWN)


def _quoted(value):
    return (type(value) is str and len(value.strip()) > 1
            and (value.strip()[0], value.strip()[-1]) in {('"', '"'), ('`', '`'), ('[', ']')})


def _inventory_placeholder(value):
    if not _text(value) or _quoted(value):
        return False
    normalized = value.strip().casefold()
    return normalized in {'*', '(all columns)', 'all columns'} or normalized.startswith('same columns as ')


def _incomplete_columns(entity):
    columns = _objects(entity.get('columns'))
    return not columns or any(_inventory_placeholder(column.get('name')) for column in columns)


def _placeholder(value, identifier=False):
    if not _text(value):
        return True
    value = value.strip()
    # Quoting and spaces can be deliberate warehouse identifiers. Do not impose
    # a generic identifier regex or dialect-specific case folding.
    if identifier and _quoted(value):
        return False
    return value.casefold() in _PLACEHOLDERS


def _duplicates(report, rows, field, code, path, *, scope=None):
    seen = {}
    for index, row in enumerate(rows):
        name = row.get(field)
        if not _text(name):
            _finding(report, 'invalid_' + field, path + '/' + str(index), 'Identity must be nonempty text.')
            continue
        identity = hash_json([row.get(scope), name]) if scope else name
        if identity in seen:
            _finding(report, code, path + '/' + str(index), 'Duplicate identity in the declared scope.',
                     first_index=seen[identity], identity=name)
        else:
            seen[identity] = index


def _bindings(edge):
    """Return explicit binding pairs only; a SQL predicate remains opaque text."""
    source = edge
    if not any(key in source for key in ('from_columns', 'to_columns', 'from_column', 'to_column')):
        source = edge.get('predicate')
        if type(source) is not dict or not any(key in source for key in ('from_columns', 'to_columns', 'from_column', 'to_column')):
            return None
    left = source.get('from_columns', [source['from_column']] if 'from_column' in source else None)
    right = source.get('to_columns', [source['to_column']] if 'to_column' in source else None)
    return left, right


def assess_design(design):
    """Return JSON diagnostics bound to design bytes and its workflow content hash.

    A mapping uses canonical JSON serialization; str/bytes retain the exact input
    byte hash as well. The optional retained ``sha256`` is excluded only from the
    workflow design hash and is checked against it. No input is modified.
    """
    design, sha, serialization = _load(design)
    report = _report(design, sha, serialization)
    if design.get('schema_version') != 1:
        _finding(report, 'unsupported_design_schema', '/schema_version', 'Expected existing design schema version 1.')
    if 'sha256' in design and design['sha256'] != report['design_binding']['sha256']:
        _finding(report, 'design_hash_mismatch', '/sha256', 'Retained design hash does not match current design content.')
    for collection in ('entities', 'relationships', 'assets', 'decisions', 'existing_models'):
        if type(design.get(collection)) is not list or any(type(row) is not dict for row in design.get(collection, []) or []):
            _finding(report, 'invalid_collection', '/' + collection, 'Expected a bounded object collection.')
    entities = _objects(design.get('entities'))
    existing = _objects(design.get('existing_models'))
    _duplicates(report, entities, 'id', 'duplicate_entity_id', '/entities')
    # Refinement tier is the only target namespace in canonical v1. Domain is an
    # organizational label; it must not hide two models with the same target name.
    _duplicates(report, entities, 'name', 'duplicate_model_name', '/entities', scope='layer')
    _duplicates(report, existing, 'id', 'duplicate_existing_model_id', '/existing_models')
    _duplicates(report, existing, 'name', 'duplicate_existing_model_name', '/existing_models')
    for collection in ('assets', 'decisions'):
        _duplicates(report, _objects(design.get(collection)), 'id', 'duplicate_' + collection[:-1] + '_id', '/' + collection)
    index = {row['id']: row for row in entities if _text(row.get('id'))}
    for position, entity in enumerate(entities):
        path = '/entities/' + str(position)
        if entity.get('layer') not in ('bronze', 'silver', 'gold'):
            _finding(report, 'invalid_model_layer', path + '/layer', 'Model layer must use a canonical refinement tier.')
        if _placeholder(entity.get('name'), identifier=True):
            _finding(report, 'placeholder_model_name', path + '/name', 'Model name is missing or a placeholder.')
        columns = _objects(entity.get('columns'))
        if type(entity.get('columns')) is not list or len(columns) != len(entity.get('columns', [])):
            _finding(report, 'invalid_columns', path + '/columns', 'Expected column objects.')
        if not columns:
            _finding(report, 'columns_unknown', path + '/columns', 'No column inventory was supplied.', unknown=True)
        _duplicates(report, columns, 'name', 'duplicate_column_name', path + '/columns')
        names = {row['name'] for row in columns if _text(row.get('name'))}
        for number, column in enumerate(columns):
            location = path + '/columns/' + str(number)
            if _inventory_placeholder(column.get('name')):
                _finding(report, 'column_inventory_unknown', location + '/name', 'Column inventory marker is not an enumerated warehouse column.', unknown=True)
            elif _placeholder(column.get('name'), identifier=True):
                _finding(report, 'placeholder_column_name', location + '/name', 'Column name is missing or a placeholder.')
            if _unknown(column.get('type')):
                _finding(report, 'column_type_unknown', location + '/type', 'Column type remains explicitly unknown.', unknown=True)
            elif _placeholder(column.get('type')):
                _finding(report, 'placeholder_column_type', location + '/type', 'Column type is missing or a placeholder.')
        keys = entity.get('keys', [])
        if type(keys) is not list or any(not _text(key) for key in keys):
            _finding(report, 'invalid_key_list', path + '/keys', 'Keys must be a list of declared column names.')
        else:
            for key in keys:
                if key not in names:
                    if _incomplete_columns(entity):
                        _finding(report, 'key_binding_unknown', path + '/keys', 'Incomplete column inventory cannot establish the declared key binding.', unknown=True, column_name=key)
                    else:
                        _finding(report, 'key_column_missing', path + '/keys', 'Declared key is absent from the column inventory.', column_name=key)
        dependencies = entity.get('depends_on', [])
        if type(dependencies) is not list or any(not _text(dependency) for dependency in dependencies):
            _finding(report, 'invalid_dependency_list', path + '/depends_on', 'Dependencies must be declared entity IDs.')
        else:
            for dependency in dependencies:
                if dependency not in index:
                    _finding(report, 'unknown_dependency', path + '/depends_on', 'Dependency references an absent entity.', entity_id=dependency)
    for number, edge in enumerate(_objects(design.get('relationships'))):
        path = '/relationships/' + str(number)
        endpoints = [index.get(edge.get(side)) if type(edge.get(side)) is str else None for side in ('from', 'to')]
        for side, endpoint in zip(('from', 'to'), endpoints):
            if endpoint is None:
                _finding(report, 'unknown_relationship_endpoint', path + '/' + side, 'Relationship endpoint is not a declared entity.')
        bindings = _bindings(edge)
        if bindings is None:
            if edge.get('kind') == 'relationship':
                _finding(report, 'relationship_columns_unknown', path, 'No machine-readable relationship column binding; predicates were not parsed.', unknown=True)
            continue
        if any(type(values) is not list or not values or any(not _text(value) for value in values) for values in bindings):
            _finding(report, 'invalid_relationship_binding', path, 'Explicit relationship bindings require two nonempty column-name lists.')
            continue
        if len(bindings[0]) != len(bindings[1]) or any(len(set(values)) != len(values) for values in bindings):
            _finding(report, 'relationship_binding_arity', path, 'Relationship bindings must have equal arity without repeated columns.')
        for side, endpoint, names in zip(('from', 'to'), endpoints, bindings):
            if endpoint is None:
                continue
            available = {column['name'] for column in _objects(endpoint.get('columns')) if _text(column.get('name'))}
            for name in names:
                if name not in available:
                    if _incomplete_columns(endpoint):
                        _finding(report, 'relationship_columns_unknown', path + '/' + side, 'Incomplete column inventory cannot establish the relationship binding.', unknown=True, column_name=name)
                    else:
                        _finding(report, 'relationship_column_missing', path + '/' + side, 'Bound relationship column is absent from its entity.', column_name=name)
        # Check only cardinalities that explicitly identify a unique side, and
        # only supplied primary keys. This does not establish actual uniqueness.
        cardinality = edge.get('cardinality')
        unique_sides = {'many_to_one': (1,), 'one_to_many': (0,), 'one_to_one': (0, 1)}.get(cardinality, ()) if type(cardinality) is str else ()
        for side in unique_sides:
            endpoint = endpoints[side]
            keys = endpoint.get('keys') if endpoint else None
            if type(keys) is list and keys and all(_text(key) for key in keys) and set(bindings[side]) != set(keys):
                _finding(report, 'relationship_key_mismatch', path, 'Binding differs from the declared key; alternate-key uniqueness needs evidence.', unknown=True, scope='physical', side=('from', 'to')[side])
    _finding(report, 'physical_validation_unknown', '', 'No target catalogue, constraints, native build or data execution was verified.', unknown=True, scope='physical')
    _finding(report, 'business_validation_unknown', '', 'No business definition, owner approval or acceptance was verified.', unknown=True, scope='business')
    return report


def project_review(design):
    """Derive presentation inventory and dictionary cells without reauthoring names.

    This is a partial review payload, not a complete delivery contract. The host
    supplies source/context bindings, artifacts and other presentation content.
    """
    design, _, _ = _load(design)
    raw_assets = design.get('assets', [])
    assets = _objects(raw_assets)
    require(type(raw_assets) is list and len(assets) == len(raw_assets),
            'Projected assets must be a bounded object collection')
    models = []
    for entity in _objects(design.get('entities')):
        model = {key: copy.deepcopy(entity[key]) for key in MODEL_FIELDS if key in entity}
        model['columns'] = [{key: copy.deepcopy(column[key]) for key in COLUMN_FIELDS if key in column}
                            for column in _objects(entity.get('columns'))]
        models.append(model)
    rows = []
    for model in models:
        for column in model['columns'] or [{}]:
            values = (model.get('id'), model.get('name'), model.get('layer'), model.get('domain'), model.get('grain'),
                      column.get('name'), column.get('type'), column.get('key'),
                      column.get('description', 'Column definitions not supplied.' if not column else ''))
            rows.append(['' if value is None else str(value) for value in values])
    return {'design_binding': _binding(design), 'models': models,
            'relationships': copy.deepcopy(_objects(design.get('relationships'))),
            'assets': copy.deepcopy(assets),
            'dictionary_fields': list(DICTIONARY_FIELDS), 'dictionary_rows': rows}


def _relationship_signature(edge):
    # Labels and evidence prose can be added to the review. Structural claims,
    # including a newly asserted binding or predicate, must match the design.
    return hash_json({key: edge[key] for key in RELATIONSHIP_FIELDS if key in edge})


def compare_review(design, review):
    """Compare actual review content, even when its declared design hash matches.

    Model and column ordering and additive presentation fields are irrelevant.
    Missing canonical facts, extra model/column identities and changed joins
    remain findings; absent source-native knowledge is not synthesized.
    """
    report = assess_design(design)
    design, _, _ = _load(design)
    review, _, _ = _load(review)
    report['kind'] = 'review_design_consistency'
    report['review_sha256'] = hash_json(review)
    expected = project_review(design)
    if 'design_binding' in review and review['design_binding'] != expected['design_binding']:
        _finding(report, 'review_binding_mismatch', '/design_binding', 'Review binding differs from actual design content.')
    actual_models = _objects(review.get('models'))
    expected_models = {row['id']: row for row in expected['models'] if _text(row.get('id'))}
    actual_ids = [row.get('id') for row in actual_models if _text(row.get('id'))]
    for identifier, count in Counter(actual_ids).items():
        if count > 1:
            _finding(report, 'review_model_duplicate', '/models', 'Review repeats a model identity.', model_id=identifier)
    for identifier in sorted(expected_models.keys() - set(actual_ids)):
        _finding(report, 'review_model_missing', '/models', 'Canonical model is absent from the review.', model_id=identifier)
    for identifier in sorted(set(actual_ids) - expected_models.keys()):
        _finding(report, 'review_model_extra', '/models', 'Review contains a model absent from the design.', model_id=identifier)
    for number, model in enumerate(actual_models):
        path = '/models/' + str(number)
        if not _text(model.get('id')):
            _finding(report, 'review_model_identity_invalid', path, 'Review model ID must be nonempty text.')
            continue
        canonical = expected_models.get(model['id'])
        if canonical is None:
            continue
        for field in ('name', 'layer', 'grain', 'domain', 'depends_on'):
            if field in ('domain', 'depends_on') and field not in model:
                _finding(report, 'review_optional_mapping_unknown', path + '/' + field,
                         'Legacy review omitted an optional mapping; use the canonical projection for a complete view.',
                         unknown=True, model_id=model['id'], field=field)
                continue
            if field in canonical and model.get(field) != canonical[field]:
                _finding(report, 'review_model_mismatch', path + '/' + field, 'Review model field differs from the canonical design.', model_id=model['id'], field=field)
        columns = _objects(model.get('columns'))
        names = [column.get('name') for column in columns if _text(column.get('name'))]
        if len(names) != len(set(names)):
            _finding(report, 'review_column_duplicate', path + '/columns', 'Review repeats a column identity.', model_id=model['id'])
        target = {column['name']: column for column in canonical['columns'] if _text(column.get('name'))}
        differs = (len(columns) != len(names) or set(names) != set(target))
        for column in columns:
            reference = target.get(column.get('name')) if type(column.get('name')) is str else None
            if reference and any(column.get(key) != value for key, value in reference.items()):
                differs = True
        if differs:
            _finding(report, 'review_columns_mismatch', path + '/columns', 'Review columns differ from canonical names or supplied definitions.', model_id=model['id'])
    actual_edges = _objects(review.get('relationships'))
    if Counter(map(_relationship_signature, actual_edges)) != Counter(map(_relationship_signature, expected['relationships'])):
        _finding(report, 'review_relationships_mismatch', '/relationships', 'Review relationships differ from canonical structural claims.')
    return report


def reconcile_proposals(proposals):
    """Combine bounded schema-v1 domain proposals without resolving disagreements.

    Records are keyed by stable IDs (relationships by endpoints, kind and role).
    Shared records must agree. Explicit unknowns survive a competing assertion;
    new knowledge requires a separately reviewed design revision. A conflict
    returns ``design: None`` and diagnostics; input proposals are never changed.
    """
    if type(proposals) is not list or not proposals or len(proposals) > 100:
        raise ValueError('Provide between one and 100 bounded design proposals')
    loaded = [_load(proposal)[0] for proposal in proposals]
    merged = copy.deepcopy(loaded[0])
    report = {'schema_version': 1, 'kind': 'design_proposal_reconciliation', 'status': 'reconciled',
              'proposal_sha256': [hash_json(proposal) for proposal in loaded], 'design': None,
              'findings': [], 'unknowns': [], 'authority': {'authoring': False, 'deployment': False},
              'qualification': QUALIFICATION}
    # A malformed proposal must not disappear while records are merged. Missing
    # cross-domain references can resolve in the combined design, so assess those
    # only after merging. No input's retained hash mismatch is discarded.
    for number, proposal in enumerate(loaded):
        for finding in assess_design(proposal)['findings']:
            if finding['code'].startswith(('invalid_', 'duplicate_')) or finding['code'] in {'design_hash_mismatch', 'unsupported_design_schema'}:
                report['findings'].append({**finding, 'proposal_index': number})

    def merge_value(left, right, path):
        if left == right:
            return copy.deepcopy(left)
        if _unknown(left) or _unknown(right):
            _finding(report, 'proposal_unknown_preserved', path, 'Explicit unknown retained; no proposal is treated as authority to resolve it.', unknown=True)
            return copy.deepcopy(left if _unknown(left) else right)
        if type(left) is dict and type(right) is dict:
            result = copy.deepcopy(left)
            for key, value in right.items():
                result[key] = merge_value(result[key], value, path + '/' + key) if key in result else copy.deepcopy(value)
            return result
        if path.endswith('/columns') and type(left) is list and type(right) is list:
            left_names = [column.get('name') for column in left if type(column) is dict]
            right_names = [column.get('name') for column in right if type(column) is dict]
            if (len(left_names) == len(left) and len(right_names) == len(right)
                    and all(_text(name) for name in left_names + right_names)
                    and len(set(left_names)) == len(left_names)
                    and len(set(right_names)) == len(right_names) and set(left_names) == set(right_names)):
                by_name = {column['name']: column for column in right}
                return [merge_value(column, by_name[column['name']], path + '/' + str(number))
                        for number, column in enumerate(left)]
        _finding(report, 'proposal_conflict', path, 'Proposals supply contradictory values; no automatic winner was selected.')
        return copy.deepcopy(left)

    collections = ('entities', 'relationships', 'assets', 'decisions', 'existing_models')
    for proposal in loaded[1:]:
        for key in ('schema_version', 'id', 'revision'):
            if merged.get(key) != proposal.get(key):
                _finding(report, 'proposal_conflict', '/' + key, 'Proposals must identify the same design revision.')
        for collection in collections:
            rows = _objects(merged.get(collection))
            def identity(row):
                fields = ('from', 'to', 'kind', 'role') if collection == 'relationships' else ('id',)
                return hash_json([row.get(field) for field in fields])
            index = {identity(row): position for position, row in enumerate(rows)}
            for row in _objects(proposal.get(collection)):
                key = identity(row)
                if key in index:
                    position = index[key]
                    rows[position] = merge_value(rows[position], row, '/' + collection + '/' + str(position))
                else:
                    index[key] = len(rows)
                    rows.append(copy.deepcopy(row))
            merged[collection] = rows
    merged.pop('sha256', None)
    assessment = assess_design(merged)
    report['findings'].extend(assessment['findings'])
    report['unknowns'].extend(assessment['unknowns'])
    if report['findings']:
        report['status'] = 'conflicts'
    else:
        report.update(design=merged, design_binding=_binding(merged))
    return report
