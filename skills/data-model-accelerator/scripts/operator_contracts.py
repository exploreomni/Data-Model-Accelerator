#!/usr/bin/env python3
"""Discover examples and validate intake without creating or changing engagements.

Examples are synthetic requests, never approvals or observed source evidence.
The existing workflow validators remain authoritative; this helper only explains
their input shapes and leaves rejected preferences intact for correction.
"""
import argparse
import copy
import difflib
import json
from pathlib import Path
import sys

from ae_common import hash_json
import guided_workflow as guided

QUALIFICATION = ('Read-only operator guidance. Examples are synthetic; no workflow, source, host configuration, '
                 'cloud service or native system was changed or qualified.')
MODEL_GUIDANCE = ('Preserve the host-configured model and reasoning effort. Do not choose cheaper settings, '
                  'silently downgrade or infer observed settings from a role label. Record actual settings only '
                  'from attributable host telemetry. Model and effort are host settings, not intake answer keys.')
NAMES = ('intake', 'import-design', 'decision-responses', 'source-registration', 'design-coverage', 'design-evidence', 'design-assembly')
LIST_ANSWERS = {'deliverables', 'trusted_outputs', 'retained_behavior', 'corrected_behavior'}


def answer_fields():
    """Machine-readable discovery from the actual intake key/enum registries."""
    result = {}
    for key in sorted(guided.ANSWER_KEYS):
        result[key] = {'type': ('object' if key in {'naming_policy', 'metadata_policy', 'dbt_runtime'}
                                else 'array_of_strings' if key in LIST_ANSWERS else 'string'), 'nullable': True}
        if key in guided.ENUMS:
            result[key]['allowed_values'] = sorted(guided.ENUMS[key])
    result['deliverables']['allowed_items'] = sorted(guided.DELIVERABLES)
    result['naming_policy'].update(required_keys=['mode', 'domain', 'decision_reference'],
        allowed_modes=['preserve', 'type_domain', 'layer_domain'],
        preserve_example={'mode': 'preserve', 'domain': None, 'decision_reference': None})
    result['metadata_policy']['validator'] = 'metadata_options.validate_options'
    result['dbt_runtime']['validator'] = 'dbt_runtime.validate_selection'
    return result


def _design_example():
    def entity(identity, parents):
        return {'id': identity, 'name': identity, 'domain': 'commerce', 'layer': 'gold',
                'grain': 'One row per ' + identity, 'keys': [identity + '_id'],
                'columns': [{'name': identity + '_id', 'type': 'integer',
                             'description': 'Synthetic declared entity identifier'}],
                'depends_on': parents, 'asset_ids': ['report.orders'],
                'security': 'Unverified; requires the actual source access contract',
                'history': 'Unverified; requires the actual history policy',
                'disposition': 'undetermined', 'reuse': None,
                'source_paths': [], 'catalogue_pointers': [], 'mapping_status': 'inferred'}
    return {'schema_version': 1, 'id': 'example.commerce', 'revision': 1,
            'entities': [entity('customers', []), entity('orders', ['customers'])],
            'relationships': [{'from': 'orders', 'to': 'customers', 'kind': 'lineage',
                               'label': 'Synthetic dependency; not a validated foreign key'}],
            'assets': [{'id': 'report.orders', 'name': 'Synthetic order report', 'kind': 'report', 'mapping_status': 'inferred'}],
            'existing_models': [], 'decisions': [{'id': 'order.population',
                'question': 'Which supplied order population should be retained?',
                'options': [{'id': 'preserve', 'label': 'Preserve the reviewed source population'}],
                'recommendation': None, 'reviewer_role': 'Business reviewer', 'model_ids': ['orders'],
                'asset_ids': ['report.orders'], 'blocking_stages': ['design'],
                'rationale': 'Population changes affect totals.',
                'evidence_summary': 'Synthetic example only; actual definitions are not supplied.'}]}


def examples(name='all'):
    """Return fresh JSON-serializable contracts; never load an engagement."""
    if name not in ('all', *NAMES):
        raise ValueError('Unknown contract; choose all, ' + ', '.join(NAMES))
    design = _design_example()
    contracts = [
        {'id': 'intake', 'validator': 'guided_workflow._answers', 'fields': answer_fields(),
         'example': {'engagement_type': 'migration', 'priority_domain': 'commerce', 'framework': 'dbt',
                     'warehouse': 'bigquery', 'semantic_target': 'omni', 'migration_scope': 'model_semantic',
                     'input_handling': 'metadata_only', 'deliverables': ['documentation', 'diagrams', 'dictionary'],
                     'trusted_outputs': ['synthetic:report.orders'], 'retained_behavior': ['Retain reviewed order attribution'],
                     'corrected_behavior': [], 'execution_mode': 'candidate_only',
                     'naming_policy': {'mode': 'preserve', 'domain': None, 'decision_reference': None}},
         'command_argv': ['guided_workflow.py', 'start', '--repo', '<approved-source-directory>', '--run', '<separate-run-directory>', '--answers', '<answers.json>'],
         'guidance': ['Use the existing answer/--run path to resume; do not restart an engagement merely to correct input.',
                      'GCP alone leaves the warehouse unresolved; select BigQuery only when confirmed.',
                      'naming_policy is an object. Preserve mode allows null domain and decision_reference; renaming modes require both.',
                      MODEL_GUIDANCE]},
        {'id': 'import-design', 'validator': 'engagement_stages.validate_design', 'example': design,
         'command_argv': ['guided_workflow.py', 'import-design', '--run', '<existing-run-directory>', '--document', '<canonical-design.json>'],
         'guidance': ['Import the full canonical envelope, including entities, relationships, assets, decisions and existing_models.',
                      'Use bronze/silver/gold as the canonical tier; keep physical naming decisions separate.',
                      'Use only retained source-relative paths and catalogue pointers. Empty example evidence is unresolved, not proof of absence.',
                      'Keep the existing design ID and advance revision when importing a revision. This example does not authorize implementation.']},
        {'id': 'decision-responses', 'validator': 'engagement_stages.record_responses',
         'example': {'schema_version': 1, 'kind': 'decision_responses', 'intent': 'record_answers',
                     'engagement_id': 'example.engagement', 'design_id': design['id'], 'design_revision': design['revision'],
                     'design_sha256': hash_json(design), 'request_only': True,
                     'answers': [{'decision_id': 'order.population', 'answer': 'Synthetic example: preserve the reviewed source population',
                                  'option_id': 'preserve', 'rationale': 'Replace with the actual supplied response and rationale.'}]},
         'command_argv': ['guided_workflow.py', 'answer-decisions', '--run', '<existing-run-directory>', '--document', '<responses.json>'],
         'guidance': ['Copy engagement_id, design_id, design_revision and design_sha256 from the current saved design; never reuse example bindings.',
                      'Use answers, not decisions, for this envelope. Supply an actual option ID or null and the actual answer.',
                      'Responses are requests and do not confer approval; request_only must remain true.']},
        {'id': 'source-registration', 'validator': 'migration_review.extract_periscope request fields',
         'example': {'schema_version': 1},
         'command_argv': ['guided_workflow.py', 'extract-periscope', '--run', '<existing-run-directory>', '--document', '<periscope-request.json>'],
         'guidance': ['The example is only the supported Periscope extraction request; do not use it as a universal source registration payload.',
                      'Register the source root when starting the engagement with --repo. Preserve that source read-only and retain generated contracts outside it.',
                      'Select the actual adapter and inspect its capabilities before parsing. Parsing/detection is not native validation or source completeness.',
                      'Keep source_adapter_contract in specialist output; retain partial/unsupported findings and the complete supplied-file denominator.',
                      'Generic source occurrence registration uses record-coverage with actual reports, expected_files, requirements, targets and mappings; never fabricate reports or omit unmapped occurrences.'],
         'adapter_capabilities_argv': ['run_source_adapter.py', '--source', '<adapter>', '--capabilities'],
         'adapter_parse_argv': ['run_source_adapter.py', '<approved-source-directory>', '--source', '<adapter>', '--output', '<separate-retained-contract.json>'],
         'coverage_command_argv': ['guided_workflow.py', 'record-coverage', '--run', '<existing-run-directory>', '--document', '<actual-coverage-ledger.json>'],
         'coverage_required_keys': ['schema_version', 'expected_files', 'reports', 'requirements', 'targets', 'mappings'],
         'coverage_validator': 'mapping_coverage.register',
         'contract_validator': 'source_adapters.registry.validate'},
    ]
    from source_adapters.registry import SOURCES
    contracts[-1]['supported_adapter_names'] = list(SOURCES)
    contracts.extend([
        {'id': 'design-coverage', 'validator': 'design_coverage.record',
         'example': {'schema_version': 1, 'sources': [
             {'id': identity, 'namespace': identity, 'role': role, 'kind': kind,
              'status': 'missing', 'domain_ids': ['commerce'],
              'inventory': {'status': 'not_supplied', 'reference': 'synthetic://not-yet-provided', 'files': []}}
             for identity, role, kind in [('legacy', 'legacy_repository', 'repository'),
                                          ('catalogue', 'warehouse_catalogue', 'external_inventory'),
                                          ('existing', 'existing_models', 'external_inventory')]],
             'objects': [], 'consumers': [], 'assignments': []},
         'command_argv': ['guided_workflow.py', 'record-design-coverage', '--run', '<existing-run-directory>', '--document', '<source-inventory.json>'],
         'guidance': ['Register every supplied source with stable namespace, explicit root, captured hashes and parse status.',
                      'This missing-input example is intentionally incomplete. Replace it with actual parser output; do not mark unavailable inputs complete.',
                      'Record objects, unresolved references and consumers before assigning targets. Assignments cannot erase the source denominator.',
                      'Use the maintained design-reliability reference for row contracts, exclusions and partial-input behavior.']},
        {'id': 'design-evidence', 'validator': 'design_evidence.record',
         'example': {'schema_version': 1, 'kind': 'design_evidence', 'baselines': [],
                     'claims': [{'id': 'assumption.orders', 'model_ids': ['orders'], 'subject': 'grain',
                                 'basis': 'proposal', 'statement': 'Proposed order grain; source verification pending.', 'sources': []}]},
         'command_argv': ['guided_workflow.py', 'record-design-evidence', '--run', '<existing-run-directory>', '--document', '<design-provenance.json>'],
         'guidance': ['Observed metadata, repository declarations, user assertions and proposals are different evidence classes.',
                      'A reused model needs a separately captured existing-model snapshot and evidence for each comparison dimension.',
                      'Independent review and human approval use separate commands and current bindings.']},
        {'id': 'design-assembly', 'validator': 'design_builder.assemble',
         'example': {'schema_version': 1, 'kind': 'design_assembly', 'id': 'example.commerce', 'revision': 1,
                     'nodes': [{'id': 'orders', 'name': 'orders', 'domain': 'commerce', 'layer': 'gold',
                                'object_kind': 'model', 'columns': [{'name': 'order_id'}]}], 'edges': []},
         'command_argv': ['guided_workflow.py', 'assemble-design', '--run', '<existing-run-directory>', '--document', '<design-proposal.json>'],
         'guidance': ['Use the supported builder instead of a one-off script. Missing semantics stay unknown.',
                      'Declare model, source or interface explicitly. Lineage does not establish a relational join.',
                      'Export the same canonical revision with design_builder.py export, then package selected files with the existing finalizer.']},
    ])
    return {'schema_version': 1, 'kind': 'operator_contract_examples', 'qualification': QUALIFICATION,
            'model_and_effort_guidance': MODEL_GUIDANCE,
            'host_qualification': {'portable_skill': 'inspect_with_check_installation_preflight',
                                   'plugin_integration': 'not_tested', 'native_execution': 'not_tested'},
            'contracts': contracts if name == 'all' else [x for x in contracts if x['id'] == name]}


def validate_answers(value):
    """Explain invalid fields without mutating, dropping or applying preferences."""
    result = {'schema_version': 1, 'kind': 'operator_answer_validation', 'status': 'invalid',
              'valid': False, 'submitted_answers': None, 'normalized_answers': None,
              'errors': [], 'missing_answers': [], 'qualification': QUALIFICATION,
              'model_and_effort_guidance': MODEL_GUIDANCE}
    if type(value) is not dict or any(type(k) is not str for k in value):
        result['errors'].append({'path': '$', 'code': 'invalid_type', 'message': 'Answers must be a JSON object with string field names.'})
        return result
    try:
        guided._secrets(value)
        if len(guided._bytes(value)) > guided.MAX_JSON_BYTES:
            raise ValueError('Answers exceed the bounded JSON size.')
    except (ValueError, TypeError, RecursionError):
        result['errors'].append({'path': '$', 'code': 'unsafe_or_invalid_json',
                                 'message': 'Input contains credential-like data, unsupported JSON values or exceeds the size limit. Values are not echoed; keep credentials outside the workflow.'})
        return result
    result['submitted_answers'] = copy.deepcopy(value)
    normalized = {}
    for key in sorted(value):
        if key not in guided.ANSWER_KEYS:
            suggestions = difflib.get_close_matches(key, sorted(guided.ANSWER_KEYS), n=3, cutoff=0.55)
            guidance = MODEL_GUIDANCE if key in {'model', 'effort', 'reasoning_effort'} else 'Correct the field name explicitly; no preference was discarded or applied.'
            result['errors'].append({'path': key, 'code': 'unsupported_key', 'message': guidance,
                                     'suggested_keys': suggestions, 'supported_keys': sorted(guided.ANSWER_KEYS)})
            continue
        try:
            normalized.update(guided._answers({key: value[key]}))
        except (ValueError, TypeError, KeyError) as error:
            issue = {'path': key, 'code': 'unsupported_value_or_type', 'message': str(error),
                     'expected': answer_fields()[key]}
            if key == 'naming_policy' and type(value[key]) is str and value[key] in {'preserve', 'type_domain', 'layer_domain'}:
                issue['suggested_shape'] = {'mode': value[key], 'domain': None, 'decision_reference': None}
                issue['guidance'] = ('Keep the supplied naming preference in this supported object shape. '
                                     'Preserve mode permits null details; renaming requires an actual domain and reviewed decision_reference. Nothing was rewritten.')
            result['errors'].append(issue)
    if not result['errors']:
        # Whole-object validation is authoritative, including future cross-field rules.
        try:
            normalized = guided._answers(copy.deepcopy(value))
        except (ValueError, TypeError, KeyError) as error:
            result['errors'].append({'path': '$', 'code': 'invalid_answers', 'message': str(error)})
            return result
        result.update(status='valid', valid=True, normalized_answers=normalized,
                      missing_answers=guided._missing(normalized))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    example = sub.add_parser('examples', help='Print discoverable synthetic contract examples.')
    example.add_argument('name', nargs='?', choices=('all', *NAMES), default='all')
    validate = sub.add_parser('validate-answers', help='Validate only; never save or update an engagement.')
    validate.add_argument('--answers', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'examples':
            result = examples(args.name)
        else:
            # Existing bounded, nonsecret reader rejects links and credential files.
            value = guided._nonsecret_json(args.answers)[0]
            result = validate_answers(value)
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
        return 0 if args.command == 'examples' or result['valid'] else 1
    except (OSError, ValueError, TypeError, RecursionError):
        print('Operator input unavailable: use a bounded nonsecret JSON file in an approved local path. No input values were printed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
