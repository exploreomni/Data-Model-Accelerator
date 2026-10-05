"""Versioned disclosure contracts. Declarations never authenticate a reviewer/host.

These local gates minimize disclosure; they do not implement warehouse policies,
certify compliance or sandbox an agent. Protected source-to-agent processing
remains blocked until a separately qualified host integration exists.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re


SENSITIVITIES = ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
CATEGORIES = {'PII', 'PCI', 'PHI'}
DESTINATIONS = ('agent_input', 'metadata', 'ai_context', 'share')
TRANSFORMATIONS = {'source', 'copy', 'alias', 'derive', 'join', 'aggregate', 'hash', 'mask', 'tokenize', 'unknown'}
SHA = re.compile(r'[0-9a-f]{64}\Z')


def _text(value):
    return type(value) is str and 0 < len(value.strip()) <= 1024


def _enum(value, options):
    return type(value) is str and value in options


def _strings(value, allowed=None):
    return (type(value) is list and len(value) <= 10000 and all(_text(v) for v in value)
            and len(set(value)) == len(value) and (allowed is None or set(value) <= set(allowed)))


def _evidence(value):
    return (type(value) is list and len(value) <= 100 and all(type(v) is dict
            and set(v) == {'reference', 'sha256'} and _text(v['reference'])
            and type(v['sha256']) is str and SHA.fullmatch(v['sha256']) for v in value))


def new_classification(sensitivity='UNKNOWN'):
    """Create an unresolved record; this function cannot approve a classification."""
    if sensitivity not in SENSITIVITIES + ('UNKNOWN',):
        raise ValueError('Unsupported sensitivity')
    return {'schema_version': 1, 'kind': 'sensitive_data_classification',
            'sensitivity': sensitivity, 'categories': [], 'categories_known': False,
            'review_status': 'unresolved', 'review_reference': None, 'evidence': [],
            'lineage': {'status': 'unresolved', 'upstream_ids': [], 'transformation': 'unknown'},
            'handling': {destination: 'review' for destination in DESTINATIONS}}


def validate_classification(value):
    required = {'schema_version', 'kind', 'sensitivity', 'categories', 'categories_known',
                'review_status', 'review_reference', 'evidence', 'lineage', 'handling'}
    if type(value) is not dict or set(value) != required:
        return ['classification.fields']
    errors = []
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'sensitive_data_classification':
        errors.append('classification.version')
    if type(value['sensitivity']) is not str or value['sensitivity'] not in SENSITIVITIES + ('UNKNOWN',):
        errors.append('classification.sensitivity')
    if not _strings(value['categories'], CATEGORIES) or type(value['categories_known']) is not bool:
        errors.append('classification.categories')
    if not _enum(value['review_status'], ('unresolved', 'proposed', 'approved')) or not _evidence(value['evidence']):
        errors.append('classification.review')
    if value['review_reference'] is not None and not _text(value['review_reference']):
        errors.append('classification.review_reference')
    if value['review_status'] == 'approved' and (not _text(value['review_reference']) or not value['evidence']
            or value['categories_known'] is not True or value['sensitivity'] == 'UNKNOWN'):
        errors.append('classification.approval_requires_known_evidence')
    lineage = value['lineage']
    if (type(lineage) is not dict or set(lineage) != {'status', 'upstream_ids', 'transformation'}
            or not _enum(lineage['status'], ('complete', 'unresolved'))
            or not _strings(lineage['upstream_ids']) or not _enum(lineage['transformation'], TRANSFORMATIONS)):
        errors.append('classification.lineage')
    elif (lineage['status'] == 'complete' and (lineage['transformation'] == 'unknown'
            or (lineage['transformation'] != 'source' and not lineage['upstream_ids'])
            or (lineage['transformation'] == 'source' and lineage['upstream_ids']))):
        errors.append('classification.lineage_incomplete')
    handling = value['handling']
    if (type(handling) is not dict or set(handling) != set(DESTINATIONS)
            or any(not _enum(v, ('allow', 'deny', 'review')) for v in handling.values())):
        errors.append('classification.handling')
    return errors


def default_policy():
    """Unapproved deny-all policy; callers must supply actual reviewed selections."""
    return {'schema_version': 1, 'kind': 'disclosure_policy', 'policy_id': 'unreviewed',
            'review_status': 'proposed', 'review_reference': None, 'evidence': [],
            'destinations': {d: {'allowed_sensitivities': [], 'allowed_categories': []} for d in DESTINATIONS},
            'host_boundary': {'mode': 'unenforced', 'evidence_reference': None}}


def validate_disclosure_policy(value):
    if (type(value) is not dict or set(value) != {'schema_version', 'kind', 'policy_id',
            'review_status', 'review_reference', 'evidence', 'destinations', 'host_boundary'}):
        return ['policy.fields']
    errors = []
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'disclosure_policy':
        errors.append('policy.version')
    if not _text(value['policy_id']) or not _enum(value['review_status'], ('approved', 'proposed')) or not _evidence(value['evidence']):
        errors.append('policy.review')
    if value['review_reference'] is not None and not _text(value['review_reference']):
        errors.append('policy.review_reference')
    if value['review_status'] == 'approved' and (not _text(value['review_reference']) or not value['evidence']):
        errors.append('policy.approval_requires_evidence')
    destinations = value['destinations']
    if type(destinations) is not dict or set(destinations) != set(DESTINATIONS):
        errors.append('policy.destinations')
    else:
        for rule in destinations.values():
            if (type(rule) is not dict or set(rule) != {'allowed_sensitivities', 'allowed_categories'}
                    or not _strings(rule['allowed_sensitivities'], SENSITIVITIES)
                    or not _strings(rule['allowed_categories'], CATEGORIES)):
                errors.append('policy.destination_rule')
    boundary = value['host_boundary']
    if (type(boundary) is not dict or set(boundary) != {'mode', 'evidence_reference'}
            or not _enum(boundary['mode'], ('unenforced', 'presanitized_only', 'claimed_enforced'))
            or boundary['evidence_reference'] is not None and not _text(boundary['evidence_reference'])):
        errors.append('policy.host_boundary')
    elif boundary['mode'] != 'unenforced' and not _text(boundary['evidence_reference']):
        errors.append('policy.host_evidence_missing')
    return sorted(set(errors))


def evaluate_disclosure(classification, policy, destination, scan_report=None):
    """Return value-free reasons; never substitute an approval flag for authority.

    A caller still authenticates policy approvals and exact-file scan provenance.
    Agent input supports pre-sanitized low-sensitivity metadata only: declared host
    enforcement cannot authorize raw/protected inputs on this portable route.
    """
    reasons = validate_classification(classification)
    if destination == 'private_candidate':
        return {'status': 'blocked' if reasons else 'private_only', 'allowed': False,
                'reasons': reasons or ['private_candidate_no_disclosure_authority'],
                'host_enforcement_authenticated': False, 'authorization_authenticated': False}
    policy = default_policy() if policy is None else policy
    reasons += validate_disclosure_policy(policy)
    if destination not in DESTINATIONS:
        reasons.append('destination.unsupported')
    if reasons:
        return {'status': 'blocked', 'allowed': False, 'reasons': sorted(set(reasons)),
                'host_enforcement_authenticated': False, 'authorization_authenticated': False}
    if policy['review_status'] != 'approved':
        reasons.append('policy.unapproved')
    if classification['review_status'] != 'approved':
        reasons.append('classification.unapproved')
    if classification['sensitivity'] == 'UNKNOWN' or not classification['categories_known']:
        reasons.append('classification.unknown')
    if classification['lineage']['status'] != 'complete':
        reasons.append('lineage.unresolved')
    rule = policy['destinations'][destination]
    if classification['sensitivity'] not in rule['allowed_sensitivities']:
        reasons.append('destination.sensitivity_denied')
    if not set(classification['categories']) <= set(rule['allowed_categories']):
        reasons.append('destination.categories_denied')
    if classification['handling'][destination] != 'allow':
        reasons.append('destination.handling_not_allowed')
    if (type(scan_report) is not dict or scan_report.get('kind') != 'sensitive_data_scan'
            or type(scan_report.get('schema_version')) is not int or scan_report['schema_version'] != 1
            or scan_report.get('status') != 'clear' or type(scan_report.get('coverage')) is not dict
            or scan_report['coverage'].get('complete') is not True
            or not isinstance(scan_report.get('artifact_sha256'), str) or not SHA.fullmatch(scan_report['artifact_sha256'])
            or scan_report.get('findings') != []):
        reasons.append('scan.not_clear')
    if destination == 'agent_input':
        if (policy['host_boundary']['mode'] != 'presanitized_only'
                or classification['sensitivity'] not in ('PUBLIC', 'INTERNAL') or classification['categories']):
            reasons.append('host.protected_input_integration_unqualified')
    return {'status': 'allowed_by_declared_policy' if not reasons else 'blocked', 'allowed': not reasons,
            'reasons': sorted(set(reasons)), 'host_enforcement_authenticated': False,
            'authorization_authenticated': False}


def propagate_classification(upstreams, upstream_ids, transformation='derive'):
    """Conservative proposed union; masking/hashing/aggregation never downgrade.

    A missing/unknown input or unresolved dependency prevents a complete result.
    This helper makes no automatic declassification decision or human approval.
    """
    if type(upstreams) is not list or not _strings(upstream_ids) or len(upstreams) != len(upstream_ids):
        raise ValueError('Lineage requires one distinct identity per input classification')
    if not _enum(transformation, TRANSFORMATIONS - {'source'}):
        raise ValueError('Unsupported lineage transformation')
    if any(validate_classification(value) for value in upstreams):
        raise ValueError('Lineage contains an invalid classification')
    known = bool(upstreams) and all(v['sensitivity'] != 'UNKNOWN' and v['categories_known']
                                  and v['lineage']['status'] == 'complete' for v in upstreams)
    sensitivity = max((v['sensitivity'] for v in upstreams), key=SENSITIVITIES.index) if known else 'UNKNOWN'
    result = new_classification(sensitivity)
    result['categories'] = sorted({c for v in upstreams for c in v['categories']})
    result['categories_known'] = known
    result['review_status'] = 'proposed' if known else 'unresolved'
    result['lineage'] = {'status': 'complete' if known and transformation != 'unknown' else 'unresolved',
                         'upstream_ids': list(upstream_ids), 'transformation': transformation}
    # Even unanimously allowed input handling needs review for a new expression.
    for destination in DESTINATIONS:
        if any(v['handling'][destination] == 'deny' for v in upstreams):
            result['handling'][destination] = 'deny'
    return result


def validate_lineage_classifications(records):
    """Check dictionary-resolved edges; no declassification route is qualified.

    ``records`` maps column IDs to classifications. IDs are never echoed in
    errors. A complete derived record cannot ignore unknown external sources,
    reduce the union of categories or claim less sensitivity than an input.
    """
    if type(records) is not dict:
        return ['lineage.records']
    errors, incoming = [], {}
    for index, (identity, value) in enumerate(records.items()):
        if validate_classification(value):
            errors.append('lineage.invalid_record[' + str(index) + ']')
            continue
        lineage = value['lineage']
        incoming[identity] = [key for key in lineage['upstream_ids'] if key in records]
        if lineage['status'] != 'complete' or lineage['transformation'] == 'source':
            continue
        if any(key not in records for key in lineage['upstream_ids']):
            errors.append('lineage.unresolved_input[' + str(index) + ']')
            continue
        upstream = [records[key] for key in lineage['upstream_ids']]
        if any(validate_classification(item) for item in upstream):
            continue
        floor = propagate_classification(upstream, lineage['upstream_ids'], lineage['transformation'])
        if floor['sensitivity'] == 'UNKNOWN':
            errors.append('lineage.unknown_input[' + str(index) + ']')
        elif (value['sensitivity'] == 'UNKNOWN'
              or SENSITIVITIES.index(value['sensitivity']) < SENSITIVITIES.index(floor['sensitivity'])):
            errors.append('lineage.sensitivity_downgrade[' + str(index) + ']')
        if not set(floor['categories']) <= set(value['categories']):
            errors.append('lineage.category_downgrade[' + str(index) + ']')
        for destination in DESTINATIONS:
            if floor['handling'][destination] == 'deny' and value['handling'][destination] != 'deny':
                errors.append('lineage.handling_downgrade[' + str(index) + ']')
    # Kahn's algorithm avoids recursion limits for large inventories.
    pending = {key: set(edges) for key, edges in incoming.items()}
    resolved = [key for key, edges in pending.items() if not edges]
    dependents = {}
    for key, edges in pending.items():
        for source in edges:
            dependents.setdefault(source, set()).add(key)
    while resolved:
        key = resolved.pop()
        pending.pop(key, None)
        for target in dependents.get(key, ()):
            if target in pending:
                pending[target].discard(key)
                if not pending[target]:
                    resolved.append(target)
    if pending:
        errors.append('lineage.cycle_or_invalid_dependency')
    return sorted(set(errors))


def migrate_dictionary_privacy(dictionary):
    """Copy a valid v2 dictionary and add unresolved privacy v1 extensions.

    All original content is preserved. Existing legacy sensitivity is retained,
    but never interpreted as completed category, lineage or disclosure review.
    """
    from data_dictionary_v2 import validate_dictionary
    if validate_dictionary(dictionary):
        raise ValueError('A valid v2 dictionary is required')
    result = copy.deepcopy(dictionary)
    if 'privacy_schema_version' in result and (type(result['privacy_schema_version']) is not int or result['privacy_schema_version'] != 1):
        raise ValueError('Unsupported dictionary privacy extension')
    result['privacy_schema_version'] = 1
    for model in result['models'] + result.get('sources', []):
        for column in model['columns']:
            column.setdefault('privacy', new_classification(column['sensitivity']))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    migrate = sub.add_parser('migrate-dictionary')
    migrate.add_argument('--input', type=Path, required=True)
    migrate.add_argument('--output', type=Path, required=True)
    evaluate = sub.add_parser('evaluate')
    evaluate.add_argument('--classification', type=Path, required=True)
    evaluate.add_argument('--policy', type=Path, required=True)
    evaluate.add_argument('--input', type=Path, required=True)
    evaluate.add_argument('--destination', choices=DESTINATIONS + ('private_candidate',), required=True)
    args = parser.parse_args(argv)
    try:
        from ae_common import load_json, _json_bytes, _path
        if args.action == 'migrate-dictionary':
            result = migrate_dictionary_privacy(load_json(args.input))
            output = _path(args.output, must_exist=False)
            if output.exists():
                raise ValueError('Use a new private candidate output')
            # Migrated dictionaries retain original data: never echo their body.
            content = _json_bytes(result) + b'\n'
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(content)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
            report = {'status': 'private_candidate', 'privacy_schema_version': 1, 'approval_granted': False}
        else:
            from sensitive_data import scan_file
            report = evaluate_disclosure(load_json(args.classification), load_json(args.policy),
                                         args.destination, scan_file(args.input))
    except (ValueError, OSError, TypeError, RecursionError):
        report = {'status': 'blocked', 'allowed': False, 'reasons': ['privacy.invalid_or_unavailable_input']}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] in ('allowed_by_declared_policy', 'private_candidate', 'private_only') else 1


if __name__ == '__main__':
    raise SystemExit(main())
