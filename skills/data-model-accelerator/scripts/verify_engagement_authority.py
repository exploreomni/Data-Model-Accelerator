"""Check typed decision records; never authenticate a person or authorize writes."""
from ae_common import hash_file, require
from freeze_benchmark import _bound_json, _fields, _sha, _text

PINS = ('source_revision', 'candidate_sha256', 'catalogue_sha256', 'baseline_sha256',
        'scope_contract_sha256', 'value_contract_sha256', 'native_source_bindings_sha256')


def verify(contract_path, context):
    """Context comes from recomputed engagement artifacts, never from this file.

    Human approval *recorded* is a typed claim for host review, not approval
    authenticated by this checker. Simulation decisions cannot become that claim.
    """
    contract, digest = _bound_json(contract_path)
    _fields(contract, ('schema_version', 'kind', 'purpose', 'decision_state', 'actor_id',
                      'review_reference', 'rule_ids', 'decision_ids') + PINS)
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['kind'] == 'engagement_authority', 'Unsupported engagement authority')
    for name in PINS:
        require(_sha(contract[name]) == _sha(context[name]), 'Authority pin mismatch: ' + name)
    require(contract['purpose'] in ('simulation', 'development_validation'), 'Unknown engagement purpose')
    require(contract['decision_state'] in ('proposed', 'simulation_authorized', 'human_approval_recorded'), 'Unknown decision state')
    _text(contract['actor_id'], 'decision actor')
    for name in ('rule_ids', 'decision_ids'):
        values = contract[name]
        require(type(values) is list, 'Authority ' + name + ' must be a list')
        for value in values:
            _text(value, name)
        require(len(set(values)) == len(values) and set(values) == set(context[name]), 'Authority decision denominator mismatch: ' + name)
    if contract['decision_state'] == 'proposed':
        require(contract['review_reference'] is None, 'Proposed definitions cannot claim an approval reference')
    else:
        _text(contract['review_reference'], 'review reference')
    if context['origin'] == 'synthetic' or context['execution_mode'] == 'fixture_replay':
        require(contract['purpose'] == 'simulation', 'Synthetic catalogue/fixture replay requires simulation purpose')
    if contract['purpose'] == 'simulation':
        require(context['stage'] == 'local', 'Simulation cannot establish target evidence')
        require(contract['decision_state'] in ('proposed', 'simulation_authorized'), 'Simulation cannot record human model approval')
    else:
        require(context['origin'] in ('provided_export', 'live_metadata'), 'Development validation requires real metadata provenance')
        require(contract['decision_state'] in ('proposed', 'human_approval_recorded'), 'Simulation authority cannot be used for development validation')
    require(hash_file(contract_path) == digest, 'Authority record changed during verification')
    return {'schema_version': 1, 'kind': 'engagement_authority_verification', 'passed': True,
            'contract_sha256': digest, 'purpose': contract['purpose'], 'decision_state': contract['decision_state'],
            'review_reference': contract['review_reference'], 'promotion_authorized': False,
            'human_approval_authenticated': False,
            'limitations': ['Actor identity and review references are supplied claims; the trusted host must verify actual human authority.',
                            'Development validation may test explicitly proposed definitions; it does not accept them for production.',
                            'This checker grants no execution, publication, retirement or deployment permission.']}
