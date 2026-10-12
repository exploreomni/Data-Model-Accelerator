"""Declared development complexity, never duration, execution or approval authority.

The host owns the reviewed scope and authenticates human decisions. This module
checks their supplied bindings and applies an explainable conservative rubric.
It reads no files, contacts no provider, and executes no project code.
"""
import copy
import hashlib
import json
import re


VERSION = 'development-effort-v1'
CATEGORIES = ('easy', 'somewhat_easy', 'difficult', 'very_difficult')
LABELS = dict(zip(CATEGORIES, ('Easy', 'Somewhat easy', 'Difficult', 'Very difficult')))
FACTORS = ('transformation', 'data_behavior', 'dependencies', 'platform',
           'validation', 'security', 'operations')
STAGES = ('implementation', 'semantic', 'validation', 'packaging', 'deployment', 'cutover')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
REQUEST_KEYS = {'schema_version', 'kind', 'bindings', 'review', 'scope', 'evidence', 'packages'}
BINDINGS = {'design_revision', 'design_material_sha256', 'scope_sha256', 'route_sha256'}


class EffortError(ValueError):
    """Invalid or ambiguous assessment contract."""


def need(condition, code):
    if not condition:
        raise EffortError(code)


def digest(value):
    try:
        body = json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError):
        raise EffortError('effort.invalid_json') from None
    need(len(body) <= 4 * 1024 * 1024, 'effort.input_limit')
    return hashlib.sha256(body).hexdigest()


def _keys(value, required, optional=()):
    need(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
         'effort.unsupported_fields')


def _text(value):
    need(type(value) is str and bool(value.strip()) and len(value) <= 4000,
         'effort.invalid_text')


def _identity(value):
    need(type(value) is str and ID.fullmatch(value) is not None, 'effort.invalid_id')


def _sha(value):
    need(type(value) is str and SHA.fullmatch(value) is not None, 'effort.invalid_hash')


def _ids(value, *, maximum=1000):
    need(type(value) is list and len(value) <= maximum, 'effort.invalid_ids')
    for item in value:
        _identity(item)
    need(len(value) == len(set(value)), 'effort.duplicate_id')
    return set(value)


def _texts(value):
    need(type(value) is list and len(value) <= 100, 'effort.invalid_notes')
    for item in value:
        _text(item)


def _validate(request):
    digest(request)
    _keys(request, REQUEST_KEYS)
    need(type(request['schema_version']) is int and request['schema_version'] == 1 and
         request['kind'] == 'development_effort_request', 'effort.request_version')
    bindings = request['bindings']
    _keys(bindings, BINDINGS)
    _identity(bindings['design_revision'])
    for key in BINDINGS - {'design_revision'}:
        _sha(bindings[key])
    scope = request['scope']
    _keys(scope, {'stages', 'excluded_stages'})
    included, excluded = _ids(scope['stages']), _ids(scope['excluded_stages'])
    need(included and not included & excluded and included | excluded == set(STAGES),
         'effort.scope_stages')
    need('cutover' not in included or 'deployment' in included, 'effort.cutover_requires_deployment_scope')
    need(bindings['scope_sha256'] == digest(scope), 'effort.scope_binding')
    review = request['review']
    _keys(review, {'status', 'reference'})
    need(review['status'] in ('reviewed', 'pending'), 'effort.review_status')
    if review['status'] == 'reviewed':
        _text(review['reference'])
    else:
        need(review['reference'] is None, 'effort.pending_review_reference')
    need(type(request['evidence']) is list and len(request['evidence']) <= 5000,
         'effort.evidence_limit')
    evidence = {}
    for record in request['evidence']:
        _keys(record, {'id', 'sha256'})
        _identity(record['id']); _sha(record['sha256'])
        need(record['id'] not in evidence, 'effort.duplicate_evidence')
        evidence[record['id']] = record['sha256']
    need(type(request['packages']) is list and 0 < len(request['packages']) <= 500,
         'effort.package_limit')
    packages = {}
    for package in request['packages']:
        _keys(package, {'id', 'stage', 'depends_on', 'material_inputs', 'factors',
                        'blockers', 'assumptions'}, {'model_ids'})
        _identity(package['id'])
        need(package['id'] not in packages, 'effort.duplicate_package')
        need(type(package['stage']) is str and package['stage'] in included,
             'effort.package_outside_scope')
        _ids(package['depends_on'])
        if 'model_ids' in package:
            need(bool(_ids(package['model_ids'])), 'effort.empty_model_ids')
        inputs = package['material_inputs']
        need(type(inputs) is dict and 0 < len(inputs) <= 1000, 'effort.material_inputs')
        for key, value in inputs.items():
            _identity(key); _sha(value)
        _keys(package['factors'], set(FACTORS))
        for factor in package['factors'].values():
            _keys(factor, {'level', 'rationale', 'evidence_ids'})
            need(type(factor['level']) is str and
                 factor['level'] in CATEGORIES + ('unknown', 'not_applicable'), 'effort.factor_level')
            _text(factor['rationale'])
            need(_ids(factor['evidence_ids']) <= set(evidence), 'effort.unknown_evidence_id')
        _texts(package['blockers']); _texts(package['assumptions'])
        packages[package['id']] = package
    need({p['stage'] for p in packages.values()} == included, 'effort.scope_package_coverage')
    for package in packages.values():
        need(set(package['depends_on']) <= set(packages), 'effort.unknown_dependency')
    remaining = {key: set(value['depends_on']) for key, value in packages.items()}
    order = []
    while remaining:
        ready = sorted(key for key, values in remaining.items() if not values)
        need(bool(ready), 'effort.dependency_cycle')
        order.extend(ready)
        for key in ready:
            del remaining[key]
        for values in remaining.values():
            values.difference_update(ready)
    return packages, evidence, order


def _maximum(values):
    return max(values, key=CATEGORIES.index) if values else None


def _readiness(values):
    order = ('ready', 'review_pending', 'blocked', 'needs_discovery')
    return max(values, key=order.index)


def _package_signature(package, evidence):
    used = {ref for factor in package['factors'].values() for ref in factor['evidence_ids']}
    return digest({'package': package, 'evidence': {key: evidence[key] for key in sorted(used)}})


def assess_effort(request):
    """Assess supplied evidence-backed factors; no semantic or human authentication.

    Unknown factors and missing evidence prevent a definitive classification.
    External blockers affect readiness without erasing known difficulty.
    Review pending or explicit assumptions produce provisional ratings. Harder
    prerequisite work propagates to dependent packages; package counts never
    average away shared difficulty.
    """
    packages, evidence, order = _validate(request)
    result = {}
    for identity in order:
        package = packages[identity]
        reasons = list(package['blockers'])
        discovery = []
        levels, drivers = [], []
        for name in FACTORS:
            factor = package['factors'][name]
            if factor['level'] == 'unknown':
                discovery.append('Unresolved factor: ' + name)
            if not factor['evidence_ids']:
                discovery.append('Missing evidence: ' + name)
            if factor['level'] in CATEGORIES:
                levels.append(factor['level'])
                drivers.append({'factor': name, **copy.deepcopy(factor)})
        if not levels:
            discovery.append('No assessed development work is declared.')
        dependencies = [result[key] for key in package['depends_on']]
        discovery.extend('Unassessed prerequisite: ' + row['id'] for row in dependencies if row['category'] is None)
        reasons.extend(discovery)
        reasons.extend('Blocked prerequisite: ' + row['id'] for row in dependencies if row['readiness'] == 'blocked')
        own_category = _maximum(levels)
        category = _maximum(levels + [row['category'] for row in dependencies if row['category']])
        inherited = sorted(row['id'] for row in dependencies if row['category'] and
                           own_category and CATEGORIES.index(row['category']) > CATEGORIES.index(own_category))
        if discovery:
            status, confidence, category = 'blocked', 'low', None
        elif request['review']['status'] != 'reviewed' or package['assumptions'] or any(
                row['status'] == 'provisional' for row in dependencies):
            status, confidence = 'provisional', 'medium'
            if request['review']['status'] != 'reviewed':
                reasons.append('Design review is pending.')
            reasons.extend('Assumption: ' + note for note in package['assumptions'])
            reasons.extend('Provisional prerequisite: ' + row['id'] for row in dependencies
                           if row['status'] == 'provisional')
        else:
            status, confidence = 'assessed', 'high'
        readiness = _readiness(['needs_discovery' if discovery else 'blocked' if package['blockers']
                                else 'review_pending' if request['review']['status'] != 'reviewed' else 'ready']
                               + [row['readiness'] for row in dependencies])
        reasons.extend('Difficulty includes prerequisite: ' + key for key in inherited)
        result[identity] = {'id': identity, 'stage': package['stage'],
            'model_ids': list(package.get('model_ids', [])), 'depends_on': sorted(package['depends_on']),
            'status': status, 'readiness': readiness, 'category': category, 'label': LABELS.get(category),
            'confidence': confidence, 'reasons': reasons, 'drivers': drivers,
            'assumptions': list(package['assumptions']),
            'input_sha256': _package_signature(package, evidence)}
    rows = [result[key] for key in sorted(result)]
    status = 'blocked' if any(row['status'] == 'blocked' for row in rows) else (
        'provisional' if any(row['status'] == 'provisional' for row in rows) else 'assessed')
    category = None if status == 'blocked' else _maximum([row['category'] for row in rows])
    report = {'schema_version': 1, 'kind': 'development_effort_assessment', 'rubric_version': VERSION,
        'bindings': copy.deepcopy(request['bindings']), 'scope': copy.deepcopy(request['scope']),
        'review': copy.deepcopy(request['review']), 'request': copy.deepcopy(request),
        'request_sha256': digest(request), 'packages': rows,
        'overall': {'status': status, 'readiness': _readiness([row['readiness'] for row in rows]),
                    'category': category, 'label': LABELS.get(category),
                    'confidence': {'blocked': 'low', 'provisional': 'medium', 'assessed': 'high'}[status],
                    'package_count': len(rows),
                    'drivers': [row['id'] for row in rows if category and row['category'] == category],
                    'blockers': [row['id'] for row in rows if row['readiness'] in ('blocked', 'needs_discovery')],
                    'rationale': 'Highest material package difficulty, including shared prerequisites; '
                                 'unresolved work prevents a complete overall classification.'},
        'qualification': 'Confidence describes completeness of supplied factors, reviewed design bindings and '
                         'evidence references. It is not a calibrated prediction or authentication of evidence. '
                         'Development difficulty does not estimate duration, staffing, price or productivity.',
        'human_approval_authenticated': False, 'execution_authorized': False, 'deployment_authorized': False}
    report['assessment_sha256'] = digest(report)
    return report


def refresh_effort(previous, request):
    """Mark a prior assessment stale; never silently reassess changed material.

    Current bindings describe the inspected request. Preserved package ratings
    retain their original assessment binding. Stale/new packages have no current
    category until a fresh assess_effort call is made after review of factors.
    """
    need(type(previous) is dict and type(previous.get('request')) is dict, 'effort.previous_assessment')
    expected = assess_effort(previous['request'])
    need(previous == expected, 'effort.previous_assessment_changed')
    packages, evidence, order = _validate(request)
    old_packages = {row['id']: row for row in previous['packages']}
    changes = {}
    for identity in order:
        reasons = []
        if identity not in old_packages:
            reasons.append('Package added.')
        elif _package_signature(packages[identity], evidence) != old_packages[identity]['input_sha256']:
            reasons.append('Material inputs, factors, evidence or package scope changed.')
        changes[identity] = reasons
    material_mapped = any(changes.values()) or bool(set(old_packages) - set(packages))
    global_reasons = []
    for field in ('scope_sha256', 'route_sha256'):
        if previous['bindings'][field] != request['bindings'][field]:
            global_reasons.append('Binding changed: ' + field)
    if previous['bindings']['design_material_sha256'] != request['bindings']['design_material_sha256'] and not material_mapped:
        global_reasons.append('Design material changed without mapped package impact.')
    material_stale = {identity: bool(changes[identity] or global_reasons) for identity in packages}
    if request['review']['status'] != 'reviewed':
        global_reasons.append('Current design review is pending.')
    for identity in order:
        material_stale[identity] = material_stale[identity] or any(material_stale[key] for key in packages[identity]['depends_on'])
        changes[identity].extend(global_reasons)
        changes[identity].extend('Stale prerequisite: ' + key for key in packages[identity]['depends_on'] if changes[key])
    rows = []
    for identity in sorted(packages):
        old = old_packages.get(identity)
        reasons = changes[identity]
        readiness = 'needs_discovery' if material_stale[identity] else _readiness([
            old['readiness'], 'review_pending' if request['review']['status'] != 'reviewed' else 'ready'])
        rows.append({'id': identity, 'status': 'stale' if reasons else 'current',
                     'readiness': readiness,
                     'category': None if reasons else old['category'],
                     'confidence': 'low' if reasons else old['confidence'],
                     'assessment_status': None if reasons else old['status'],
                     'reasons': reasons, 'origin_bindings': copy.deepcopy(previous['bindings']) if old else None})
    removed = sorted(set(old_packages) - set(packages))
    stale = bool(removed or any(changes.values()))
    return {'schema_version': 1, 'kind': 'development_effort_refresh', 'rubric_version': VERSION,
            'status': 'stale' if stale else 'current', 'bindings': copy.deepcopy(request['bindings']),
            'review': copy.deepcopy(request['review']), 'packages': rows, 'removed_packages': removed,
            'previous_assessment_sha256': previous['assessment_sha256'],
            'current_request_sha256': digest(request), 'requires_reassessment': stale,
            'overall': {'status': 'stale', 'category': None, 'confidence': 'low',
                        'readiness': 'needs_discovery' if removed else _readiness([row['readiness'] for row in rows])}
                       if stale else copy.deepcopy(previous['overall']),
            'qualification': 'Freshness checks preserve original provenance. They do not reapprove a design, '
                             'authenticate evidence or authorize execution.'}
