"""Optional naming candidates, never a second compiled-name resolver.

Input relation components are exact resolved names, not SQL expressions. Existing
objects and explicit aliases win. Only new Snowflake table/view names can receive
the reviewed TYPE_DOMAIN_STEM convention. Consumers must carry the returned map
into their bindings and reconcile it against compiled and observed identities.

Snowflake identifier rules: https://docs.snowflake.com/en/sql-reference/identifiers-syntax
Quoted names preserve case and have a 255-character limit. Generated components
use a conservative ASCII subset and uppercase; all supplied namespace components
remain exact. No macros, projects, files, sessions, or warehouses are changed.
"""
import copy
import re

from ae_common import hash_json, require
from data_dictionary_v2 import MODEL_ROLES
from metadata_options import validate_naming
from metadata_platforms import capabilities


DEFAULT_POLICY = {'mode': 'preserve', 'domain': None, 'decision_reference': None}
TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')
STEM = re.compile(r'[A-Za-z0-9][A-Za-z0-9_]*\Z')
RESOURCE_FIELDS = {'resource_id', 'relation', 'is_new', 'explicit_alias', 'model_role', 'stem'}


def _text(value, label, maximum=4000):
    require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and not any(t in value for t in ('{{', '{%', '{#')), 'Invalid ' + label)
    return value


def _relation(value, warehouse):
    require(type(value) is dict and set(value) == {'namespace', 'name', 'kind'}, 'Exact relation components required')
    require(type(value['namespace']) is list
            and len(value['namespace']) == capabilities(warehouse)['namespace_components'], 'Exact supplied namespace required')
    require(value['kind'] in ('table', 'view', 'ephemeral', 'external', 'late_binding_view'), 'Unsupported relation kind')
    for part in value['namespace'] + [value['name']]:
        _text(part, 'identifier', 255 if warehouse == 'snowflake' else 16000)
    return copy.deepcopy(value)


def _key(value):
    # Relation kind does not create a second namespace for a conflicting name.
    return tuple(value['namespace'] + [value['name']])


def _type_map(value):
    fields = {'schema_version', 'kind', 'review_status', 'decision_reference', 'prefixes'}
    require(type(value) is dict and set(value) == fields, 'An explicit reviewed naming type map is required')
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'metadata_naming_type_map', 'Unsupported naming type map')
    require(value['review_status'] == 'approved', 'Naming type map requires supplied review status')
    _text(value['decision_reference'], 'type-map review decision')
    prefixes = value['prefixes']
    require(type(prefixes) is dict and prefixes and set(prefixes) <= MODEL_ROLES - {'UNKNOWN'},
            'Type map requires known explicit model roles; UNKNOWN cannot receive a prefix')
    for prefix in prefixes.values():
        _text(prefix, 'type prefix', 255)
        require(TOKEN.fullmatch(prefix), 'Unsupported type prefix identifier')
    return prefixes


def preview_naming(warehouse, resources, policy=None, *, type_map=None, occupied_relations=()):
    """Return a deterministic, non-executable preview with explicit blockers.

    Each resource supplies resource_id, relation, is_new, explicit_alias,
    model_role and stem (nullable when preserving). Missing review decisions or
    malformed inputs raise ValueError. Valid unsupported renaming requests,
    unknown roles, long proposed names and collisions produce blocked previews.
    No selected platform receives renames by default. occupied_relations is an
    externally inventoried collision scope, not a live catalogue query.
    """
    capabilities(warehouse)
    policy = validate_naming(copy.deepcopy(DEFAULT_POLICY if policy is None else policy))
    require(type(resources) is list and 0 < len(resources) <= 5000, 'Nonempty bounded resource list required')
    require(type(occupied_relations) in (list, tuple) and len(occupied_relations) <= 5000, 'Invalid occupied relation scope')
    occupied = [_relation(row, warehouse) for row in occupied_relations]
    occupied_keys = {_key(row) for row in occupied}
    require(len(occupied_keys) == len(occupied), 'Duplicate occupied relation')
    ids, rows = set(), []
    for row in resources:
        require(type(row) is dict and set(row) == RESOURCE_FIELDS, 'Invalid naming resource fields')
        rid = _text(row['resource_id'], 'resource ID')
        require(rid not in ids, 'Duplicate naming resource ID')
        ids.add(rid)
        require(type(row['is_new']) is bool and type(row['explicit_alias']) is bool, 'Naming scope flags must be booleans')
        require(row['model_role'] in MODEL_ROLES, 'Unknown model role; use UNKNOWN explicitly')
        require(row['stem'] is None or type(row['stem']) is str, 'Supplied resource stem must be text or null')
        rows.append(dict(copy.deepcopy(row), relation=_relation(row['relation'], warehouse)))

    renamable = [r for r in rows if r['is_new'] and not r['explicit_alias'] and policy['mode'] != 'preserve']
    blockers, prefixes = [], _type_map(type_map) if type_map is not None else {}
    if renamable:
        if warehouse != 'snowflake':
            blockers.append('Renaming is not implemented for ' + warehouse + '; preserve exact existing bindings.')
        elif policy['mode'] != 'type_domain':
            blockers.append('Only Snowflake type_domain naming has a candidate preview; layer_domain requires qualification.')
        else:
            prefixes = _type_map(type_map)
            require(TOKEN.fullmatch(policy['domain']), 'Unsupported naming domain identifier')

    mappings = []
    for row in sorted(rows, key=lambda r: r['resource_id']):
        before = row['relation']
        after = copy.deepcopy(before)
        reason = ('existing_resource' if not row['is_new'] else 'explicit_alias' if row['explicit_alias']
                  else 'preserve_policy' if policy['mode'] == 'preserve' else 'unsupported_naming_route')
        if row['is_new'] and not row['explicit_alias'] and warehouse == 'snowflake' and policy['mode'] == 'type_domain':
            reason = 'reviewed_type_domain_candidate'
            if before['kind'] not in ('table', 'view'):
                blockers.append(row['resource_id'] + ': only new table/view model naming is supported')
            elif row['model_role'] not in prefixes:
                blockers.append(row['resource_id'] + ': model role is UNKNOWN or absent from the reviewed type map')
            elif type(row['stem']) is not str or not STEM.fullmatch(row['stem']):
                blockers.append(row['resource_id'] + ': supply a supported literal resource stem; do not infer it from an old name')
            else:
                proposed = '_'.join((prefixes[row['model_role']], policy['domain'], row['stem'])).upper()
                if len(proposed) > 255:
                    blockers.append(row['resource_id'] + ': proposed Snowflake name exceeds 255 characters; no truncation is allowed')
                else:
                    after['name'] = proposed
        mappings.append({'resource_id': row['resource_id'], 'before': before, 'proposed': after,
                         'changed': before != after, 'reason': reason, 'quoting': 'exact_components'})

    proposed_keys = {}
    for row, item in zip(sorted(rows, key=lambda r: r['resource_id']), mappings):
        key = _key(item['proposed'])
        if key in proposed_keys:
            blockers.append(item['resource_id'] + ': proposed name collides with ' + proposed_keys[key])
        proposed_keys[key] = item['resource_id']
        if row['is_new'] and key in occupied_keys:
            blockers.append(item['resource_id'] + ': proposed name collides with the supplied occupied relation inventory')
    result = {'schema_version': 1, 'kind': 'metadata_naming_preview', 'warehouse': warehouse,
              'status': 'blocked' if blockers else 'review_required' if any(m['changed'] for m in mappings) else 'preserved',
              'policy': policy, 'type_map_sha256': hash_json(type_map) if type_map is not None else None,
              'type_map_decision_reference': type_map['decision_reference'] if type_map is not None else None,
              'normalization': 'uppercase_generated_name_only', 'collision_scope': 'supplied_inventory_only',
              'scope_sha256': hash_json(sorted(rows, key=lambda r: r['resource_id'])),
              'occupied_sha256': hash_json(sorted(occupied, key=lambda r: _key(r))),
              'mapping': mappings, 'blockers': sorted(set(blockers)),
              'native_qualified': False, 'execution_authorized': False,
              'requirements': ['Use this reviewed mapping for code, dictionary, diagrams, native metadata and semantic bindings.',
                               'Reconcile every proposed identity against the compiled manifest and independently observed relations.',
                               'Keep custom schema/alias macros and existing explicit aliases unchanged.',
                               'Qualify exact quoted-identifier resolution and the per-environment namespace before applying the mapping.'],
              'assurance': 'Candidate preview only. Supplied review status and hashes do not authenticate approval, live uniqueness or deployment.'}
    result['preview_sha256'] = hash_json(result)
    return result
