"""Versioned metadata definitions; structural validity never grants write authority.

The validator is dependency-free. Its JSON Schema companion is intentionally
permissive about extension fields so migration can preserve customer content.
Free-text classification/lineage is never parsed into governance assertions.
"""
import copy
import hashlib
import json
import math
import re


VERSION = 2
SENSITIVITIES = {'UNKNOWN', 'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'}
KEY_ROLES = {'UNKNOWN', 'NONE', 'PRIMARY_KEY', 'SURROGATE_PRIMARY_KEY',
             'FOREIGN_KEY', 'SURROGATE_FOREIGN_KEY', 'CROSSWALK_ID', 'GRAIN_COMPONENT'}
MODEL_ROLES = {'UNKNOWN', 'STAGING', 'INTERMEDIATE', 'DIMENSION', 'FACT',
               'BRIDGE', 'AGGREGATE', 'SNAPSHOT'}
REVIEW_STATUSES = {'proposed', 'approved', 'unresolved'}
ORIGINS = {'source_metadata', 'reviewer', 'inferred', 'generated'}
COLUMN_TEXT_FIELDS = ('name', 'description', 'data_type', 'nullability',
                      'key_role', 'source', 'transformation', 'units',
                      'classification', 'validation')
SHA = re.compile(r'[0-9a-f]{64}\Z')


def _text(value):
    return type(value) is str and bool(value.strip())


def _enum(value, choices):
    return type(value) is str and value in choices


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _json_bytes(value):
    """Reject non-JSON Python values rather than coercing them during migration."""
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError('Dictionary must contain only finite JSON values and string object keys')
    check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _strings(value, nonempty=False):
    return (type(value) is list and (bool(value) or not nonempty)
            and all(_text(item) for item in value) and len(value) == len(set(value)))


def _evidence_errors(value, path):
    errors = []
    if type(value) is not list:
        return [path + ': expected evidence array']
    seen = set()
    for index, item in enumerate(value):
        here = path + '/' + str(index)
        if (type(item) is not dict or set(item) != {'reference', 'sha256'}
                or not _text(item.get('reference')) or not _sha(item.get('sha256'))):
            errors.append(here + ': evidence requires exact reference and sha256 fields')
            continue
        key = (item['reference'], item['sha256'])
        if key in seen:
            errors.append(here + ': duplicate evidence reference/hash')
        seen.add(key)
    return errors


def _provenance_errors(value, status, path):
    if type(value) is not dict:
        return [path + ': provenance object is required']
    errors = []
    if not _enum(value.get('origin'), ORIGINS):
        errors.append(path + '/origin: unsupported origin')
    errors.extend(_evidence_errors(value.get('evidence'), path + '/evidence'))
    reference = value.get('review_reference')
    if 'review_reference' not in value or reference is not None and not _text(reference):
        errors.append(path + '/review_reference: expected null or a nonempty review reference')
    if status == 'approved' and (not _text(reference) or not value.get('evidence')):
        errors.append(path + ': approved definitions require evidence and a supplied review reference')
    return errors


def _source_errors(value, path):
    if type(value) is not list:
        return [path + ': expected exact source-reference array']
    errors, seen = [], set()
    for index, item in enumerate(value):
        here = path + '/' + str(index)
        if (type(item) is not dict or set(item) != {'object_id', 'column_path', 'catalogue_sha256'}
                or not _text(item.get('object_id'))
                or type(item.get('column_path')) is not list or not item['column_path']
                or not all(_text(part) for part in item['column_path'])
                or not _sha(item.get('catalogue_sha256'))):
            errors.append(here + ': require object_id, exact column_path components and catalogue_sha256')
            continue
        key = (item['object_id'], tuple(item['column_path']), item['catalogue_sha256'])
        if key in seen:
            errors.append(here + ': duplicate source reference')
        seen.add(key)
    return errors


def _roles_valid(value):
    return (_strings(value, nonempty=True) and all(role in KEY_ROLES for role in value)
            and (not {'NONE', 'UNKNOWN'} & set(value) or len(value) == 1))


def validate_dictionary(value):
    """Return v2 structural/semantic errors without mutating or authenticating input.

    UNKNOWN and unresolved records are valid documentation. Deployment eligibility,
    approved scope, actual catalogue bindings and independent acceptance remain
    separate gates. Version 1 callers must keep their historical checker or migrate.
    """
    try:
        _json_bytes(value)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return ['$: expected finite JSON data without cycles or unsupported Python types']
    if type(value) is not dict:
        return ['$: expected a data dictionary object']
    errors = []
    if type(value.get('schema_version')) is not int or value['schema_version'] != VERSION:
        errors.append('$/schema_version: metadata deployment requires data_dictionary v2; migrate a copy of v1')
    if value.get('kind') != 'data_dictionary':
        errors.append('$/kind: expected data_dictionary')
    if ('model_inventory_sha256' not in value or value['model_inventory_sha256'] is not None
            and not _sha(value['model_inventory_sha256'])):
        errors.append('$/model_inventory_sha256: expected null or a SHA-256 inventory binding')
    models = value.get('models')
    if type(models) is not list or not models:
        return errors + ['$/models: nonempty model inventory is required']
    sources = value.get('sources', [])
    if type(sources) is not list:
        errors.append('$/sources: expected a separate source inventory')
        sources = []
    if (sources or 'source_inventory_sha256' in value) and not _sha(value.get('source_inventory_sha256')):
        errors.append('$/source_inventory_sha256: source inventory requires a SHA-256 binding')
    model_ids, column_ids = set(), set()
    records = [('$/models/' + str(i), m, 'model_id') for i, m in enumerate(models)]
    records += [('$/sources/' + str(i), s, 'source_id') for i, s in enumerate(sources)]
    for path, model, identity_key in records:
        if type(model) is not dict:
            errors.append(path + ': expected model object')
            continue
        for key in (identity_key, 'description', 'grain'):
            if not _text(model.get(key)):
                errors.append(path + '/' + key + ': nonempty text is required')
        if identity_key == 'source_id' and 'model_id' in model:
            errors.append(path + ': source records must not masquerade as model records')
        if _text(model.get(identity_key)):
            if model[identity_key] in model_ids:
                errors.append(path + '/' + identity_key + ': duplicate ' + ('model' if identity_key == 'model_id' else 'resource') + ' identity')
            model_ids.add(model[identity_key])
        if not _strings(model.get('source_systems')):
            errors.append(path + '/source_systems: expected distinct explicit source-system IDs')
        if not _enum(model.get('model_role'), MODEL_ROLES):
            errors.append(path + '/model_role: unsupported model role; use UNKNOWN when unresolved')
        if 'owner' not in model or model['owner'] is not None and not _text(model['owner']):
            errors.append(path + '/owner: expected null or an explicitly supplied owner reference')
        if not _enum(model.get('review_status'), REVIEW_STATUSES):
            errors.append(path + '/review_status: unsupported review status')
        errors.extend(_provenance_errors(model.get('provenance'), model.get('review_status'), path + '/provenance'))
        columns = model.get('columns')
        if type(columns) is not list or not columns:
            errors.append(path + '/columns: nonempty column inventory is required')
            continue
        names = set()
        for number, column in enumerate(columns):
            here = path + '/columns/' + str(number)
            if type(column) is not dict:
                errors.append(here + ': expected column object')
                continue
            for key in COLUMN_TEXT_FIELDS + ('column_id',):
                if not _text(column.get(key)):
                    errors.append(here + '/' + key + ': nonempty text is required')
            if _text(column.get('name')):
                if column['name'] in names:
                    errors.append(here + '/name: duplicate exact column name')
                names.add(column['name'])
            if _text(column.get('column_id')):
                if column['column_id'] in column_ids:
                    errors.append(here + '/column_id: duplicate column identity')
                column_ids.add(column['column_id'])
            if not _enum(column.get('review_status'), REVIEW_STATUSES):
                errors.append(here + '/review_status: unsupported review status')
            errors.extend(_provenance_errors(column.get('provenance'), column.get('review_status'), here + '/provenance'))
            sensitivity = column.get('sensitivity')
            if not _enum(sensitivity, SENSITIVITIES):
                errors.append(here + '/sensitivity: unsupported sensitivity; use UNKNOWN when unresolved')
            status = column.get('sensitivity_review_status')
            if not _enum(status, REVIEW_STATUSES):
                errors.append(here + '/sensitivity_review_status: unsupported review status')
            evidence = column.get('sensitivity_evidence')
            errors.extend(_evidence_errors(evidence, here + '/sensitivity_evidence'))
            review = column.get('sensitivity_review_reference')
            if ('sensitivity_review_reference' not in column
                    or review is not None and not _text(review)):
                errors.append(here + '/sensitivity_review_reference: expected null or supplied review reference')
            if sensitivity == 'UNKNOWN' and status != 'unresolved':
                errors.append(here + ': UNKNOWN sensitivity must remain unresolved')
            if _enum(sensitivity, SENSITIVITIES - {'UNKNOWN'}) and (not evidence or status == 'unresolved'):
                errors.append(here + ': stated sensitivity requires evidence and a proposed or approved status')
            if status == 'approved' and not _text(review):
                errors.append(here + ': approved sensitivity requires a supplied review reference')
            roles = column.get('key_roles')
            if not _roles_valid(roles):
                errors.append(here + '/key_roles: distinct supported roles required; NONE/UNKNOWN must stand alone')
            elif roles == ['NONE'] and column.get('review_status') != 'approved':
                errors.append(here + '/key_roles: NONE means reviewed absence and requires an approved definition')
            errors.extend(_source_errors(column.get('source_refs'), here + '/source_refs'))
    return errors


def migrate_dictionary(value):
    """Return a new dictionary from canonical v1 or the explicit rental v1 shape.

    No original fields are discarded: the complete input is retained under
    migration.original. Unknowns and conversion decisions are reported by path.
    A valid v2 input is copied unchanged; migrating does not approve anything.
    """
    try:
        original_bytes = _json_bytes(value)
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise ValueError('Migration requires finite JSON data') from error
    if type(value) is not dict or type(value.get('schema_version')) is not int:
        raise ValueError('Migration requires an explicit integer schema_version')
    if value['schema_version'] == VERSION:
        errors = validate_dictionary(value)
        if errors:
            raise ValueError('Invalid v2 dictionary: ' + '; '.join(errors))
        return copy.deepcopy(value)
    if value['schema_version'] != 1:
        raise ValueError('Only canonical v1 and rental v1 dictionaries can be migrated')
    models = value.get('models')
    if type(models) is not list or not models or not all(type(model) is dict for model in models):
        raise ValueError('Version-1 migration requires a nonempty model inventory')
    canonical = value.get('kind') == 'data_dictionary' and all('model_id' in model for model in models)
    rental = 'kind' not in value and all('id' in model and 'dbt_id' in model and 'model_id' not in model for model in models)
    if not canonical and not rental:
        raise ValueError('Unsupported v1 dictionary shape; expected canonical model_id or rental id/dbt_id')
    if canonical and not _sha(value.get('model_inventory_sha256')):
        raise ValueError('Canonical v1 requires the original model_inventory_sha256 binding')
    result = copy.deepcopy(value)
    source_hash = hashlib.sha256(original_bytes).hexdigest()
    shape = 'canonical_v1' if canonical else 'rental_v1'
    unresolved = []

    def unknown(path, reason):
        unresolved.append({'path': path, 'reason': reason})

    def provenance(path):
        return {'origin': 'generated', 'evidence': [{'reference': shape + ':' + path, 'sha256': source_hash}],
                'review_reference': None}

    def reviews(record, path):
        status = record.get('review_status')
        if (not _enum(status, REVIEW_STATUSES)
                or _provenance_errors(record.get('provenance'), status, path)):
            record['review_status'] = 'unresolved'
            record['provenance'] = provenance(path)
            unknown(path + '/review_status', 'New metadata contract needs review; migration is not approval.')

    result.update(schema_version=VERSION, kind='data_dictionary')
    result.setdefault('model_inventory_sha256', None)
    if result['model_inventory_sha256'] is None:
        unknown('$/model_inventory_sha256', 'Bind the migrated copy to an independently established model inventory.')
    for index, model in enumerate(result['models']):
        path = '$/models/' + str(index)
        identifier = model.get('model_id') if canonical else model.get('id')
        if not _text(identifier) or not _text(model.get('grain')):
            raise ValueError(path + ': legacy model identity and grain are required')
        if rental:
            if not _text(model.get('dbt_id')):
                raise ValueError(path + ': rental dbt_id is required')
            model['model_id'] = identifier
            if not _text(model.get('description')):
                model['description'] = 'UNKNOWN: Model description was not supplied in the rental v1 dictionary.'
                unknown(path + '/description', 'No model-level business description was supplied.')
        elif not _text(model.get('description')):
            raise ValueError(path + ': canonical v1 model description is required')
        if not _strings(model.get('source_systems')):
            model['source_systems'] = []
            unknown(path + '/source_systems', 'Source-system IDs were not supplied in a structured form.')
        if not _enum(model.get('model_role'), MODEL_ROLES):
            model['model_role'] = 'UNKNOWN'
            unknown(path + '/model_role', 'Model role is not inferred from its name or layer.')
        if 'owner' not in model or model['owner'] is not None and not _text(model['owner']):
            model['owner'] = None
            unknown(path + '/owner', 'No explicit owner reference was supplied.')
        reviews(model, path)
        if type(model.get('columns')) is not list or not model['columns']:
            raise ValueError(path + '/columns: legacy column inventory is required')
        for number, column in enumerate(model['columns']):
            here = path + '/columns/' + str(number)
            if type(column) is not dict or not _text(column.get('name')):
                raise ValueError(here + ': legacy column name is required')
            if rental:
                if not _text(column.get('type')) or type(column.get('nullable')) is not bool:
                    raise ValueError(here + ': rental type and boolean nullable are required')
                for key, mapped in (('data_type', column['type']),
                                    ('nullability', 'Declared nullable' if column['nullable'] else 'Declared not nullable')):
                    if key in column and column[key] != mapped:
                        raise ValueError(here + '/' + key + ': conflicting rental/canonical fields require explicit review')
                    column[key] = mapped
                if not _text(column.get('source')) and _text(column.get('lineage')):
                    column['source'] = column['lineage']
                for key in COLUMN_TEXT_FIELDS:
                    if not _text(column.get(key)):
                        column[key] = 'UNKNOWN: Not supplied in the rental v1 dictionary.'
                        unknown(here + '/' + key, 'Legacy field has no explicit canonical definition.')
            elif not all(_text(column.get(key)) for key in COLUMN_TEXT_FIELDS):
                raise ValueError(here + ': canonical v1 requires all existing column text fields')
            if not _text(column.get('column_id')):
                column['column_id'] = 'column:' + json.dumps([identifier, column['name']], separators=(',', ':'), ensure_ascii=True)
            reviews(column, here)
            sensitivity = column.get('sensitivity')
            sensitivity_status = column.get('sensitivity_review_status')
            sensitivity_evidence = column.get('sensitivity_evidence')
            sensitivity_review = column.get('sensitivity_review_reference')
            known = (_enum(sensitivity, SENSITIVITIES - {'UNKNOWN'})
                     and _enum(sensitivity_status, {'proposed', 'approved'})
                     and bool(sensitivity_evidence) and not _evidence_errors(sensitivity_evidence, here)
                     and (sensitivity_review is None or _text(sensitivity_review))
                     and (sensitivity_status != 'approved' or _text(sensitivity_review)))
            if not known:
                column.update(sensitivity='UNKNOWN', sensitivity_evidence=[],
                              sensitivity_review_status='unresolved', sensitivity_review_reference=None)
                unknown(here + '/sensitivity', 'Classification prose/names are not an evidenced sensitivity assessment.')
            else:
                column.setdefault('sensitivity_review_reference', None)
            if not _roles_valid(column.get('key_roles')) or column['key_roles'] == ['NONE'] and column['review_status'] != 'approved':
                column['key_roles'] = ['UNKNOWN']
                unknown(here + '/key_roles', 'Readable key-role text is preserved; normalized roles need explicit review.')
            if _source_errors(column.get('source_refs'), here):
                column['source_refs'] = []
                unknown(here + '/source_refs', 'Free-text lineage is retained but not parsed into exact catalogue bindings.')
    result['migration'] = {'source_schema_version': 1, 'source_shape': shape,
                           'source_document_sha256': source_hash,
                           'hash_contract': 'SHA-256 of sorted compact ASCII JSON; source_file_sha256, when present, binds original bytes.',
                           'original': copy.deepcopy(value), 'unresolved': unresolved}
    errors = validate_dictionary(result)
    if errors:
        raise ValueError('Migrated dictionary is invalid: ' + '; '.join(errors))
    return result
