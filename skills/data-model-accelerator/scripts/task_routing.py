"""Portable local assignment and review contracts. No dispatch or release authority.

Kept byte-identical in DMA and OAA so either installed skill works independently.
Host receipts are observations, not authenticated execution or a sandbox.
"""
import copy
import hashlib
import json
from pathlib import PurePosixPath
import re

SHA = re.compile(r'[a-f0-9]{64}')
ALIASES = {'omni_modeler': 'semantic_modeler', 'semantic_architect': 'semantic_modeler',
           'independent_qa': 'independent_reviewer'}
STAGE_ROLES = {
    'discovery': {'source_specialist', 'catalogue_specialist', 'artifact-translator', 'data-analyst'},
    'design': {'warehouse_architect', 'independent_reviewer', 'validation_analyst', 'data-analyst'},
    'implementation': {'analytics_engineer', 'app-engineer', 'bi-engineer'},
    'semantic': {'semantic_modeler', 'bi-engineer'},
    'validation': {'validation_analyst', 'independent_reviewer', 'qa-analyst'},
    'packaging': {'documentation_specialist', 'data-storyteller'},
    'migration_plan': {'migration_project_manager', 'backend-handoff'},
    'dashboard': {'dashboard-designer', 'bi-engineer', 'data-analyst', 'artifact-translator',
                  'branding', 'design-systems', 'data-storyteller', 'qa-analyst'},
    'app': {'app-designer', 'app-engineer', 'bi-engineer', 'motion-designer', 'branding',
            'design-systems', 'data-analyst', 'qa-analyst'},
}
FIELDS = {'schema_version', 'task_id', 'domain_id', 'stage', 'role', 'scope_ids', 'objective',
          'outputs', 'acceptance', 'input_bindings', 'dependencies', 'unknowns', 'authoring_mode'}
CHANGES = {'source', 'design', 'grain', 'keys', 'naming', 'sql', 'joins', 'filters', 'incremental',
           'security', 'semantic', 'metrics', 'dashboard', 'app', 'presentation', 'documentation', 'business_rules'}
DEFAULT_CHANGES = {'discovery': ['source'], 'design': ['design'], 'implementation': ['sql'],
                   'semantic': ['semantic'], 'validation': ['business_rules'], 'packaging': ['presentation'],
                   'migration_plan': ['documentation'], 'dashboard': ['dashboard'], 'app': ['app']}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def text(value):
    need(type(value) is str and bool(value.strip()) and len(value) <= 8192, 'Expected bounded nonempty text')


def strings(value, nonempty=False):
    need(type(value) is list and len(value) <= 512 and (value or not nonempty), 'Expected bounded list')
    for item in value:
        text(item)
    need(len(set(value)) == len(value), 'Duplicate list entry')


def pins(value, nonempty=False):
    need(type(value) is dict and len(value) <= 512 and (value or not nonempty), 'Expected bounded bindings')
    for key, pin in value.items():
        text(key)
        need(type(pin) is str and SHA.fullmatch(pin), 'Invalid content fingerprint')


def output_path(value):
    text(value)
    path = PurePosixPath(value)
    need(not path.is_absolute() and path.as_posix() == value and '..' not in path.parts
         and '\\' not in value and not any(p.startswith('.') for p in path.parts)
         and not any(ord(c) < 32 or ord(c) == 127 for c in value)
         and ':' not in value and value.casefold() not in {'project.json', 'task-operations.json', 'start_here.md'},
         'Output must be a canonical candidate path, not coordinator state')
    return value


def outputs_overlap(left, right):
    return any(a.casefold() == b.casefold() or a.casefold().startswith(b.casefold() + '/')
               or b.casefold().startswith(a.casefold() + '/') for a in left for b in right)


def validate_assignment(value):
    need(type(value) is dict and set(value) == FIELDS, 'Invalid assignment fields')
    need(type(value['schema_version']) is int and value['schema_version'] == 1, 'Unsupported assignment version')
    result = copy.deepcopy(value)
    for key in ('task_id', 'domain_id', 'stage', 'role', 'objective'):
        text(result[key])
    result['role'] = ALIASES.get(result['role'], result['role'])
    need(result['stage'] in STAGE_ROLES and result['role'] in STAGE_ROLES[result['stage']],
         'Specialist role is incompatible with assignment stage')
    for key in ('scope_ids', 'outputs', 'acceptance', 'unknowns'):
        strings(result[key], nonempty=key != 'unknowns')
    for path in result['outputs']:
        output_path(path)
    need(not any(a != b and outputs_overlap([a], [b])
                 for a in result['outputs'] for b in result['outputs']), 'Overlapping output paths')
    pins(result['input_bindings'], nonempty=True)
    pins(result['dependencies'])
    need(result['authoring_mode'] in {'provisional', 'reviewed_candidate'}, 'Invalid authoring qualification')
    need(len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) <= 65536,
         'Assignment exceeds 64 KiB; split the work into targeted tasks')
    # Unknown semantics are recorded, not a reason to prohibit provisional work.
    for key in ('scope_ids', 'outputs'):
        result[key] = sorted(result[key])
    return result


def bind_assignment(value, *, task_id, role, scope_ids=None, stage=None, bindings=None):
    result = validate_assignment(value)
    need(result['task_id'] == task_id, 'Assignment task differs from reserved task')
    need(result['role'] == ALIASES.get(role, role), 'Assignment role differs from reserved role')
    if scope_ids is not None:
        need(set(result['scope_ids']) == set(scope_ids), 'Assignment scope differs from task')
    if stage is not None:
        need(result['stage'] == stage, 'Assignment stage differs from task')
    if bindings is not None:
        need(result['input_bindings'] == bindings, 'Assignment inputs differ from current task')
    return result


def route_reviews(assignment, changes=None, dependency_state='known'):
    assignment = validate_assignment(assignment)
    changes = DEFAULT_CHANGES[assignment['stage']] if changes is None else changes
    strings(changes, nonempty=True)
    need(set(changes) <= CHANGES, 'Unknown change classification')
    need(dependency_state in {'known', 'unknown'}, 'Unknown dependency coverage')
    changes = set(changes)
    # A caller's change label cannot waive minimum checks for executable outputs.
    if any(PurePosixPath(p).suffix.lower() == '.sql' for p in assignment['outputs']):
        changes.add('sql')
    if assignment['stage'] in {'design', 'semantic', 'dashboard', 'app'}:
        changes.update(DEFAULT_CHANGES[assignment['stage']])
    disciplines = set()
    if changes & {'source', 'design', 'grain', 'keys', 'naming', 'business_rules'}:
        disciplines.add('model')
    if changes & {'sql', 'joins', 'filters', 'incremental', 'metrics', 'business_rules'}:
        disciplines.add('logic')
    if changes & {'semantic', 'joins', 'filters', 'metrics', 'business_rules', 'dashboard', 'app'}:
        disciplines.add('semantic')
    if changes & {'source', 'design', 'sql', 'joins', 'filters', 'incremental', 'security', 'semantic',
                  'metrics', 'business_rules', 'dashboard', 'app'}:
        disciplines.add('security')
    if changes & {'dashboard', 'app', 'presentation', 'documentation'}:
        disciplines.add('experience')
    if dependency_state == 'unknown':
        disciplines.update({'model', 'logic', 'security'})
    descriptions = {
        'model': 'Grain, keys, naming, lineage, requested coverage and independent source evidence',
        'logic': 'SQL validity, fanout, filters, history, incremental behavior and independent numerical expectations',
        'semantic': 'Bindings, measures, joins and affected consumer/report parity',
        'security': 'Effective access, tenant boundaries, sensitive fields and changed downstream exposure',
        'experience': 'Readable complete artifacts, navigation, rendering and interactions',
    }
    frontend = assignment['role'] in set().union(STAGE_ROLES['dashboard'], STAGE_ROLES['app'])
    reviewers = []
    for name in sorted(disciplines):
        role = 'qa-analyst' if frontend else ('validation_analyst' if name in {'logic', 'semantic'} else 'independent_reviewer')
        reviewers.append({'id': name, 'role': role, 'expectation': descriptions[name]})
    return {'schema_version': 1, 'assignment_sha256': fingerprint(assignment), 'changes': sorted(changes),
            'dependency_state': dependency_state, 'reviews': reviewers,
            'context_requests': [] if dependency_state == 'known' else
                ['Identify affected consumers and access dependencies before claiming complete validation'],
            'max_concurrent_specialists': 2, 'model_policy': 'preserve_configured',
            'qualification': 'Review disciplines may share one scoped independent worker; this plan does not dispatch agents.'}


def start_review(assignment, artifacts, changes=None, dependency_state='known', builder_reference=None):
    assignment = validate_assignment(assignment)
    pins(artifacts, nonempty=True)
    need(set(assignment['outputs']) <= set(artifacts), 'Review snapshot omits assigned outputs')
    for path in artifacts:
        output_path(path)
    if builder_reference is not None:
        text(builder_reference)
    return {'schema_version': 1, 'assignment': assignment, 'artifacts': copy.deepcopy(artifacts),
            'candidate_sha256': fingerprint({'assignment': assignment, 'artifacts': artifacts}),
            'plan': route_reviews(assignment, changes, dependency_state), 'builder_reference': builder_reference,
            'correction_count': 0, 'results': {}, 'previous_rounds': []}


def record_review(review, result):
    need(type(result) is dict and set(result) == {'review_id', 'candidate_sha256', 'verdict', 'findings',
         'reviewer_reference', 'execution_mode'}, 'Invalid review result fields')
    required = {r['id'] for r in review['plan']['reviews']}
    need(result['review_id'] in required, 'Review is not applicable to this assignment')
    need(result['candidate_sha256'] == review['candidate_sha256'], 'Review belongs to a stale candidate')
    need(result['verdict'] in {'pass', 'changes', 'unknown'}, 'Invalid review verdict')
    text(result['reviewer_reference'])
    need(result['execution_mode'] in {'specialist', 'inline'}, 'Invalid reviewer execution mode')
    need(type(result['findings']) is list and len(result['findings']) <= 512, 'Invalid findings')
    ids = set()
    for item in result['findings']:
        need(type(item) is dict and set(item) == {'id', 'severity', 'message', 'evidence', 'affected_ids', 'acceptance'},
             'Invalid finding fields')
        for key in ('id', 'message', 'acceptance'):
            text(item[key])
        strings(item['evidence'], nonempty=True); strings(item['affected_ids'], nonempty=True)
        need(item['severity'] in {'blocking', 'warning'}, 'Invalid finding severity')
        need(item['id'] not in ids, 'Duplicate finding in review')
        ids.add(item['id'])
    need(result['verdict'] != 'changes' or result['findings'], 'Changes need actionable findings')
    need(result['verdict'] != 'pass' or not any(f['severity'] == 'blocking' for f in result['findings']),
         'Blocking findings cannot pass')
    old = review['results'].get(result['review_id'])
    need(old is None or old == result, 'Review result is immutable; open a new revision')
    updated = copy.deepcopy(review)
    updated['results'][result['review_id']] = copy.deepcopy(result)
    return updated


def review_decision(review, artifacts):
    pins(artifacts, nonempty=True)
    if artifacts != review['artifacts']:
        return {'action': 'stale', 'reason': 'Candidate bytes changed; open a new review snapshot'}
    pending = sorted({r['id'] for r in review['plan']['reviews']} - set(review['results']))
    if pending:
        return {'action': 'wait', 'pending_reviews': pending, 'reason': 'Collect applicable reviews before correction'}
    results = list(review['results'].values())
    uncertain = [r['review_id'] for r in results if r['verdict'] == 'unknown' or r['execution_mode'] == 'inline'
                 or not review['builder_reference'] or r['reviewer_reference'] == review['builder_reference']]
    findings = {}
    for result in results:
        for item in result['findings']:
            # Consolidate equivalent findings without discarding conflicting acceptance requirements.
            key = fingerprint({k: item[k] for k in ('message', 'acceptance', 'affected_ids')})
            saved = findings.setdefault(key, {**copy.deepcopy(item), 'review_ids': [], 'finding_ids': []})
            saved['review_ids'].append(result['review_id']); saved['finding_ids'].append(item['id'])
            saved['evidence'] = sorted(set(saved['evidence']) | set(item['evidence']))
            if item['severity'] == 'blocking':
                saved['severity'] = 'blocking'
    changes = any(r['verdict'] == 'changes' for r in results)
    if changes:
        return {'action': 'correct' if review['correction_count'] < 1 else 'needs_human',
                'findings': list(findings.values()), 'unknown_reviews': uncertain,
                'reason': 'One consolidated correction' if review['correction_count'] < 1 else
                          'Correction allowance exhausted; resolve the listed findings or explicitly scope a follow-up'}
    if uncertain or review['plan']['context_requests']:
        return {'action': 'needs_human', 'unknown_reviews': uncertain,
                'context_requests': review['plan']['context_requests'],
                'reason': 'Independent review or dependency coverage remains unverified; provisional work may continue'}
    return {'action': 'reviews_complete', 'findings': list(findings.values()),
            'qualification': 'Host-reported review evidence only; no native validation, business acceptance or deployment authority'}


def revise_review(review, artifacts, builder_reference=None):
    decision = review_decision(review, review['artifacts'])
    need(decision['action'] == 'correct', 'Collect reviews and obtain a correction assignment first')
    need(artifacts != review['artifacts'], 'Unchanged candidate: reuse existing reviews')
    updated = start_review(review['assignment'], artifacts, review['plan']['changes'],
                           review['plan']['dependency_state'], builder_reference or review['builder_reference'])
    updated['correction_count'] = review['correction_count'] + 1
    updated['previous_rounds'] = [*copy.deepcopy(review['previous_rounds']),
        {k: copy.deepcopy(review[k]) for k in ('candidate_sha256', 'artifacts', 'results')}]
    return updated
