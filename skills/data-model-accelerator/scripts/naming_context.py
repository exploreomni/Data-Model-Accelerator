"""Small, pinned naming instructions for a specialist's exact dependency scope."""
import copy
from ae_common import hash_json, require


def packet_contract(state, selected):
    from naming_governance import access, records
    from engagement_stages import closure
    if not state.get('workflow', {}).get('naming_governance'):
        return None
    graph = {e['id']: e['depends_on'] for e in (state['workflow'].get('design') or {}).get('entities', [])}
    require(type(selected) is list and selected and set(selected) <= set(graph), 'Naming packet needs known entity IDs')
    scope = closure(graph, selected)
    value = {'schema_version': 1, 'kind': 'naming_context', 'entity_ids': scope,
             'policy': access(state), 'resources': records(state, scope),
             'qualification': 'Use these selected names; request changes from the coordinator. This contract grants no execution or rename authority.'}
    value['sha256'] = hash_json(value)
    return value


def validate_packet(request):
    body = request.get('naming_contract')
    pin = request.get('bindings', {}).get('naming_contract')
    if body is None:
        require(pin is None, 'Naming pin requires its contract')
        return None
    require(type(body) is dict and set(body) == {'schema_version', 'kind', 'entity_ids', 'policy', 'resources', 'qualification', 'sha256'},
            'Invalid naming context fields')
    require(body['schema_version'] == 1 and body['kind'] == 'naming_context', 'Unsupported naming context')
    require(type(body['entity_ids']) is list and body['entity_ids'] and len(body['entity_ids']) <= 20000,
            'Invalid naming context scope')
    require(type(body['resources']) is list and all(isinstance(r, dict) and r.get('entity_id') in body['entity_ids'] for r in body['resources']),
            'Naming resources must stay inside the scoped packet')
    require(pin == body['sha256'] == hash_json({k: v for k, v in body.items() if k != 'sha256'}), 'Naming contract pin mismatch')
    return copy.deepcopy(body)
