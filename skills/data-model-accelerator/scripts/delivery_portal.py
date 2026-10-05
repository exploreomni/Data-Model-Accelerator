#!/usr/bin/env python3
"""Offline, evidence-labelled review and allowlisted portable delivery. No execution.

Rendering is not a verifier: business/target acceptance stays with existing gates.
Python 3.9+, standard library; source artifacts never change.
"""
import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import sys
import tempfile
import textwrap
from urllib.parse import unquote, urlsplit
import zipfile

from ae_common import load_json, require, _json_bytes
from plan_specialists import is_secret

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'guided-delivery'
CATEGORIES = {'documentation', 'diagrams', 'dictionary', 'implementation', 'validation', 'sample_data', 'technical_audit'}
AUDIENCES = {'reviewer', 'engineer', 'audit'}
FOLDERS = {'documentation': '01_Model', 'diagrams': '01_Model', 'dictionary': '01_Model',
           'implementation': '02_Implementation', 'validation': '03_Validation',
           'sample_data': '04_Sample_Data', 'technical_audit': 'Technical_Audit'}
SUFFIXES = {'.md', '.txt', '.sql', '.yml', '.yaml', '.json', '.csv', '.tsv', '.svg', '.mmd', '.py', '.toml', '.lock'}
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_ARTIFACTS = 5000
MAX_REVIEW_ITEMS = 20000
LAYERS = ('bronze', 'silver', 'gold')
DEPLOYMENT_ACTIONS = ('publish_pr', 'deploy_development', 'promote')
QUALITY_SCOPES = {'code_conventions':'static', 'project_validity':'framework',
                  'warehouse_validation':'warehouse', 'data_accuracy':'independent_data'}
QUALITY_COUNTS = ('checked', 'failed', 'skipped', 'unsupported', 'pending', 'unknown', 'not_applicable')
QUALITY_FIELDS = ('id', 'status', 'scope', 'unit', *QUALITY_COUNTS, 'total', 'summary', 'next_action', 'gaps')
QUALITY_STATUSES = {'pass', 'fail', 'pending', 'unknown', 'skipped', 'unsupported', 'not_applicable'}


def _native_omni_artifact(path):
    """Native model text only; no general extensionless-file exception."""
    return path.suffix.lower() in {'.view', '.topic'} or path.name in {'model', 'relationships'}


def _check_disclosure_bytes(content, filename):
    from sensitive_data import scan_bytes
    report = scan_bytes(content, filename)
    require(report['status'] == 'clear',
            'Disclosure scan blocked this output; inspect value-free scan findings in the approved environment.')
    return {'status': report['status'], 'artifact_sha256': report['artifact_sha256'],
            'assurance': 'Bounded content scan only; classification and destination approval remain required.'}


def _check_share_policy(state, review, selected, data, audience):
    """New scoped engagements require classified, audience-bound disclosure.

    Legacy candidates retain scan-only assurance; they acquire no acceptance or
    deployment authority. Policy JSON is supplied review evidence, not a signature.
    """
    if not state.get('answers', {}).get('migration_scope'):
        return 'legacy_candidate_no_disclosure_approval'
    from privacy_contract import evaluate_disclosure
    from sensitive_data import scan_bytes
    contract = review.get('disclosure', {})
    require(isinstance(contract, dict) and contract.get('audience') == audience,
            'A reviewed disclosure contract for this audience is required')
    classifications = contract.get('artifacts', {})
    require(isinstance(classifications, dict), 'Artifact classifications required')
    for artifact in selected:
        report = scan_bytes(artifact['content'], artifact['path'])
        decision = evaluate_disclosure(classifications.get(artifact['id']), contract.get('policy'), 'share', report)
        require(decision['allowed'], 'Artifact disclosure policy is unresolved or denied')
    projected = _json_bytes(data)
    decision = evaluate_disclosure(contract.get('presentation'), contract.get('policy'), 'share',
                                   scan_bytes(projected, 'review.json'))
    require(decision['allowed'], 'Review presentation disclosure policy is unresolved or denied')
    return 'allowed_by_declared_policy_not_authenticated_approval'


def _markdown_destination(value):
    """Read an angle-wrapped or balanced Markdown destination, excluding a title."""
    value = value.lstrip()
    if value.startswith('<'):
        match = re.match(r'<((?:\\.|[^>])*)>', value)
        return match.group(1) if match else None
    depth, result, index = 0, [], 0
    while index < len(value):
        char = value[index]
        if char == '\\' and index + 1 < len(value):
            result.extend((char, value[index + 1])); index += 2; continue
        if char == '(':
            depth += 1
        elif char == ')':
            if not depth:
                break
            depth -= 1
        elif char.isspace() and not depth:
            break
        result.append(char); index += 1
    return ''.join(result) if depth == 0 else None


def _markdown_links(content):
    """Extract portable inline/reference links, ignoring fenced and inline code."""
    source = content.decode('utf-8')
    lines, fence = [], None
    for line in source.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            lines.append(''); continue
        lines.append('' if fence or line.startswith(('    ', '\t')) else line)
    source = re.sub(r'<!--.*?-->', '', '\n'.join(lines), flags=re.S)
    source = re.sub(r'(`+).*?\1', '', source, flags=re.S)
    references, destinations = {}, []
    normalize = lambda label: ' '.join(label.split()).casefold()
    definition = re.compile(r'^ {0,3}\[([^\]\n]+)\]:\s*(.*)$', re.M)
    for match in definition.finditer(source):
        if match.group(1).startswith('^'):
            continue  # Footnote bodies are prose, not file destinations.
        destination = _markdown_destination(match.group(2))
        require(destination is not None, 'Malformed Markdown reference destination: ' + match.group(1))
        references[normalize(match.group(1))] = destination
    source = definition.sub('', source)
    pattern = re.compile(r'(?<!\\)!?\[((?:\\.|[^\]\\\n])*)\]')
    for match in pattern.finditer(source):
        if match.group(1).startswith('^'):
            continue
        tail = source[match.end():]
        if tail.startswith('('):
            destination = _markdown_destination(tail[1:])
            require(destination is not None, 'Malformed Markdown link destination')
            destinations.append(destination)
        elif tail.startswith('['):
            label = re.match(r'\[([^\]\n]*)\]', tail)
            if label:
                key = normalize(label.group(1) or match.group(1))
                require(key in references, 'Unresolved Markdown reference label: ' + key)
                destinations.append(references[key])
        elif normalize(match.group(1)) in references:
            destinations.append(references[normalize(match.group(1))])
    # Raw HTML links in Markdown obey the same file boundary.
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            destinations.extend(value for name, value in attrs if name.lower() in {'href', 'src'} and value is not None)
    Links().feed(source)
    return destinations


def _internal_link(destination, source):
    destination = html.unescape(re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', destination))
    decoded = unquote(destination)
    require(not any(ord(char) < 32 or ord(char) == 127 for char in decoded),
            'Unsafe Markdown link in ' + source + ': control character')
    require('\\' not in decoded, 'Unsafe Markdown link in ' + source + ': backslash path')
    parsed = urlsplit(destination)
    if parsed.scheme:
        require(parsed.scheme.lower() in {'http', 'https', 'mailto', 'tel'},
                'Unsafe Markdown link in ' + source + ': scheme ' + parsed.scheme)
        return None
    path = unquote(parsed.path)
    require(not parsed.netloc and not path.startswith('/') and ':' not in path,
            'Unsafe Markdown link in ' + source + ': absolute or network path')
    if not path:
        return None  # Same-document fragments are intentionally not heading validation.
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
    require(resolved != '..' and not resolved.startswith('../'),
            'Unsafe Markdown link in ' + source + ': escapes package root')
    return resolved


def _validate_markdown_links(selected):
    """Validate actual relocated destinations and retain links as export dependencies."""
    by_destination = {record['destination']: record for record in selected}
    by_source = {record.get('path'): record for record in selected}
    for record in selected:
        if PurePosixPath(record['destination']).suffix.lower() != '.md':
            continue
        dependencies = set(record.get('requires', []))
        for link in _markdown_links(record['content']):
            resolved = _internal_link(link, record['destination'])
            if resolved is None:
                continue
            target = by_destination.get(resolved)
            suggestion = ''
            if target is None:
                try:
                    source_relative = _internal_link(link, record.get('path', record['destination']))
                except ValueError:
                    source_relative = None
                moved = by_source.get(source_relative)
                if moved:
                    suggestion = '; after category relocation use ' + posixpath.relpath(moved['destination'], posixpath.dirname(record['destination']))
            require(target is not None,
                    'Unresolved Markdown file link in ' + record['destination'] + ': ' + link +
                    ' (resolves to ' + resolved + '); include the linked artifact or correct its portable path' + suggestion)
            if target['id'] != record['id']:
                dependencies.add(target['id'])
        record['requires'] = sorted(dependencies)


def _path(value, root=None):
    raw = Path(value).expanduser()
    require('..' not in raw.parts, 'Parent traversal is not allowed')
    path = raw.absolute()
    require(not any(p.is_symlink() for p in (path,) + tuple(path.parents)), 'Symlink paths are not allowed')
    if root is not None:
        require(path != root and root in path.parents, 'Artifact must be inside the selected root')
    return path


def _relative(value):
    require(isinstance(value, str) and value and '\\' not in value and ':' not in value,
            'Use a portable relative artifact path')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Invalid path character')
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.as_posix() == value and '..' not in p.parts and '.' not in p.parts,
            'Artifact path must be canonical and relative')
    require(all(not part.endswith((' ', '.')) for part in p.parts), 'Nonportable artifact path')
    require(not any(re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part, re.I) for part in p.parts),
            'Reserved filename')
    return p


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def source_fingerprint(state):
    source = state.get('inputs', {}).get('source', {})
    return source.get('fingerprint') or source.get('sha256') or state.get('readiness', {}).get('platform', {}).get('fingerprint')


def context_fingerprint(state):
    return _sha(_json_bytes(state.get('inputs', {})))


def _quality_data(record):
    """Validate lane-local claims; never derive data correctness from lint."""
    require(isinstance(record, dict), 'Quality check must be an object')
    result = {key:record.get(key) for key in QUALITY_FIELDS}
    require(isinstance(result['id'], str) and result['id'] in QUALITY_SCOPES, 'Unknown quality lane')
    require(isinstance(result['status'], str) and result['status'] in QUALITY_STATUSES, 'Unknown quality status')
    require(result['scope'] in (QUALITY_SCOPES[result['id']], 'unknown'), 'Quality scope differs from its lane')
    for key in ('unit', 'summary', 'next_action'):
        require(isinstance(result[key], str) and bool(result[key].strip()) and len(result[key]) <= 10000,
                'Quality check requires bounded ' + key)
    gaps = result['gaps']
    require(isinstance(gaps, list) and len(gaps) <= 100
            and all(isinstance(g, str) and g.strip() and len(g) <= 10000 for g in gaps), 'Invalid quality gaps')
    for key in QUALITY_COUNTS:
        require(type(result[key]) is int and result[key] >= 0, 'Quality coverage must use nonnegative integer counts: ' + key)
    require(result['failed'] <= result['checked'], 'Quality failures exceed checked coverage')
    total = result['total']
    require(total is None or (type(total) is int and total >= 0), 'Quality total must be an integer or null for unknown scope')
    covered = result['checked'] + sum(result[key] for key in ('skipped', 'unsupported', 'pending', 'unknown', 'not_applicable'))
    require(total is None or covered == total, 'Quality coverage does not reconcile to total')
    status = result['status']
    require(result['failed'] == 0 or status == 'fail', 'Known quality failures must remain failed')
    if status == 'pass':
        require(total is not None and total > 0 and result['checked'] == total and result['failed'] == 0
                and not gaps and result['scope'] != 'unknown', 'Quality pass requires complete positive coverage with no failures or gaps')
    elif status == 'fail':
        require(result['failed'] > 0, 'Quality failure requires failed checks')
    elif status in ('skipped', 'unsupported'):
        require(result[status] > 0, 'Quality status requires matching coverage: ' + status)
    elif status == 'not_applicable':
        require(result['checked'] == 0 and total is not None and result['not_applicable'] == total,
                'Not-applicable quality coverage must contain no executed checks')
    if status != 'pass':
        require(bool(gaps), 'Non-passing quality checks require an actionable gap')
    return copy_quality(result)


def copy_quality(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _validate_quality_checks(state, review):
    checks = review.get('quality_checks', [])
    require(isinstance(checks, list) and len(checks) <= len(QUALITY_SCOPES), 'Quality review accepts at most four independent lanes')
    seen = set()
    for record in checks:
        item = _quality_data(record)
        require(item['id'] not in seen, 'Duplicate quality lane');seen.add(item['id'])
        require(record.get('context_sha256') == context_fingerprint(state), 'Quality evidence context is stale')
        require(isinstance(record.get('evidence_artifact_id'), str) and record['evidence_artifact_id'], 'Quality evidence artifact ID is required')
        require(isinstance(record.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', record['sha256']), 'Invalid quality evidence hash')
        artifact = [a for a in review.get('artifacts', []) if a.get('id') == record.get('evidence_artifact_id')]
        require(len(artifact) == 1 and artifact[0].get('category') == 'validation', 'Quality evidence must reference one registered validation artifact')
        require(artifact[0].get('sha256') == record['sha256'], 'Quality evidence hash differs from its registered artifact')


def _quality_omitted(identifier):
    result = {'id':identifier, 'status':'unknown', 'scope':'unknown', 'unit':'items', 'total':None,
              'summary':'Quality evidence is not included in this page.',
              'next_action':'Include the registered validation evidence to inspect this check.',
              'gaps':['No selected evidence bytes are available.'], 'evidence_state':'not_included'}
    result.update({key:0 for key in QUALITY_COUNTS})
    return result


def _validate_metadata_reference(review):
    """The review pins bytes; the plan, rather than a second summary, owns claims."""
    if 'metadata' not in review:
        return
    ref = review['metadata']
    require(isinstance(ref, dict) and set(ref) == {'plan_artifact_id', 'sha256'},
            'Metadata review requires only plan_artifact_id and sha256')
    require(isinstance(ref['plan_artifact_id'], str) and ref['plan_artifact_id'], 'Metadata artifact ID is required')
    require(isinstance(ref['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']), 'Invalid metadata artifact hash')
    matches = [a for a in review.get('artifacts', []) if a.get('id') == ref['plan_artifact_id']]
    require(len(matches) == 1 and matches[0].get('category') in {'documentation', 'validation', 'technical_audit'},
            'Metadata plan must reference one registered documentation, validation or audit artifact')
    require(matches[0].get('sha256') == ref['sha256'], 'Metadata hash differs from its registered artifact')
    require(str(matches[0].get('path', '')).lower().endswith('.json'), 'Metadata plan must be a JSON artifact')


def _metadata_omitted(ref):
    return {'plan_artifact_id': ref['plan_artifact_id'], 'sha256': ref['sha256'],
            'evidence_state': 'not_included', 'status': 'unknown',
            'summary': 'Metadata plan evidence is not included in this page.',
            'next_action': 'Include the registered metadata plan to inspect its scope, changes and blockers.'}


def _select_metadata_evidence(data, selected):
    """Regenerate a bounded display from selected canonical plan bytes only.

    This does not authenticate a collector, execute SQL, or establish release
    authority. Full dictionaries, SQL, target identities and receipts stay out
    of the display projection. A selected JSON artifact remains downloadable.
    """
    ref = data.get('review', {}).get('metadata')
    if ref is None:
        return
    require(isinstance(ref, dict) and isinstance(ref.get('plan_artifact_id'), str) and ref['plan_artifact_id']
            and isinstance(ref.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']),
            'Invalid metadata evidence reference')
    matches = [a for a in selected if a.get('id') == ref.get('plan_artifact_id')]
    require(len(matches) <= 1, 'Duplicate selected metadata artifact ID')
    if not matches:
        data['review']['metadata'] = _metadata_omitted(ref)
        return
    artifact = matches[0]
    require(_sha(artifact['content']) == ref['sha256'] == artifact['sha256'], 'Metadata evidence changed')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate metadata JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Non-finite metadata JSON value: ' + value)
    try:
        plan = json.loads(artifact['content'].decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
    except (UnicodeError, ValueError) as error:
        raise ValueError('Metadata evidence must be valid unambiguous UTF-8 JSON') from error
    require(isinstance(plan, dict) and plan.get('kind') == 'warehouse_metadata_plan', 'Unsupported metadata plan format')
    from plan_warehouse_metadata import verify_plan
    try:
        verify_plan(plan)  # Pure canonical rebuild, not native execution or live collection.
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Malformed metadata plan structure') from error
    contract, before = plan['contract'], plan['before']
    target = contract['configuration']
    require(all(target.get(key) == data['engagement']['target'].get(key) for key in ('framework', 'warehouse')),
            'Metadata plan target differs from selected target')
    resources = contract['resources']
    require(all(len(plan[key]) <= MAX_REVIEW_ITEMS for key in ('operations', 'blockers', 'governance_requests'))
            and len(resources) <= MAX_REVIEW_ITEMS and sum(len(r['columns']) for r in resources) <= MAX_REVIEW_ITEMS,
            'Metadata presentation scope exceeds review limit')
    required = [r for r in resources if r['disposition'] == 'required']
    columns = [(r, c) for r in resources for c in r['columns']]
    counts = dict(plan['counts'])
    counts.update(columns_selected=len(columns), columns_required=sum(len(r['columns']) for r in required),
                  model_resources=sum(r['resource_type'] == 'model' for r in resources),
                  source_resources=sum(r['resource_type'] == 'source' for r in resources),
                  observed_resources=len(before['resources']),
                  observed_columns=sum(len(r['columns']) for r in before['resources']),
                  unknown_sensitivity_columns=sum(c['sensitivity'] == 'UNKNOWN' for _, c in columns))
    data['review']['metadata'] = {
        'plan_artifact_id': ref['plan_artifact_id'], 'sha256': ref['sha256'], 'evidence_state': 'selected',
        'status': plan['status'], 'target': {key: target[key] for key in ('framework', 'warehouse', 'environment')},
        'plan_sha256': plan['plan_sha256'], 'contract_sha256': plan['contract_sha256'],
        'before_sha256': plan['before_sha256'], 'candidate_sha256': target['candidate_sha256'],
        'counts': counts, 'qualification': plan['qualification'] + ' Automatic live metadata dispatch is blocked pending authenticated drift collection; use a reviewed operator/CI handoff.',
        'sequence': list(plan['phases']),
        'scope': [{key: r[key] for key in ('id', 'resource_type', 'layer', 'relation', 'disposition', 'reason', 'source_write_decision')}
                  | {'columns': len(r['columns'])} for r in resources],
        'changes': [{key: op[key] for key in ('id', 'resource_id', 'column_id', 'kind', 'phase', 'relation', 'column', 'before', 'after')}
                    | {'tag_name': op['tag']['name'] if op['tag'] else None} for op in plan['operations']],
        'unknowns': [{'resource_id': r['id'], 'column': c['name'], 'reason': 'Sensitivity is UNKNOWN.'}
                     for r, c in columns if c['sensitivity'] == 'UNKNOWN'],
        'blockers': list(plan['blockers']), 'privilege_requirements': list(plan['privilege_requirements']),
        'governance_requests': copy_quality(plan['governance_requests']),
        'observation': {'origin': before['collection']['origin'], 'observed_at': before['observed_at'],
                        'reported_complete': before['collection']['complete'],
                        'qualification': 'Reported baseline only; this page does not authenticate collection or prove readback.'},
    }


def _select_quality_evidence(data, selected):
    """Bind public quality claims to exact selected JSON; omit other payloads.

    Producers add review.quality_checks and register sanitized validation JSON:
    {schema_version:1,kind:quality_evidence,context_sha256,target,checks:[...]}. Each
    checks item contains QUALITY_FIELDS only (extra technical metadata is ignored
    by this projection). Evidence may cover one or several lanes. The file hash,
    context, selected target and all public counts/status/gaps must agree.
    """
    checks = data.get('review', {}).get('quality_checks', [])
    by_id = {item['id']:item for item in selected}
    projected, loaded = [], {}
    for record in checks:
        artifact = by_id.get(record.get('evidence_artifact_id'))
        if artifact is None:
            projected.append(_quality_omitted(record['id']));continue
        require(record.get('context_sha256') == data['engagement']['context_sha256'], 'Quality summary context is stale')
        require(artifact['sha256'] == record.get('sha256'), 'Quality evidence changed: ' + artifact['id'])
        if artifact['id'] not in loaded:
            try:
                evidence = json.loads(artifact['content'].decode('utf-8'))
            except (ValueError, UnicodeError) as error:
                raise ValueError('Quality evidence must be valid UTF-8 JSON: ' + artifact['id']) from error
            require(isinstance(evidence, dict) and evidence.get('schema_version') == 1
                    and evidence.get('kind') == 'quality_evidence', 'Unsupported quality evidence format')
            require(evidence.get('context_sha256') == data['engagement']['context_sha256'], 'Quality evidence file context is stale')
            target = evidence.get('target', {})
            require(isinstance(target, dict) and all(target.get(key) == data['engagement']['target'].get(key)
                    for key in ('framework', 'warehouse')), 'Quality evidence target differs from selected target')
            rows = evidence.get('checks')
            require(isinstance(rows, list) and len(rows) <= len(QUALITY_SCOPES), 'Invalid quality evidence check collection')
            indexed = {}
            for row in rows:
                item = _quality_data(row)
                require(item['id'] not in indexed, 'Duplicate quality evidence lane')
                indexed[item['id']] = item
            loaded[artifact['id']] = indexed
        expected = _quality_data(record)
        require(loaded[artifact['id']].get(record['id']) == expected, 'Quality summary differs from its evidence: ' + record['id'])
        expected.update({key:record[key] for key in ('context_sha256', 'evidence_artifact_id', 'sha256')})
        expected['evidence_state'] = 'selected'
        projected.append(expected)
    if checks:
        data['review']['quality_checks'] = projected


def validate_review(state, review):
    require(isinstance(review, dict) and review.get('schema_version') == 1, 'Review schema_version must be 1')
    require(bool(source_fingerprint(state)), 'Engagement has no source fingerprint; run assessment first')
    require(review.get('source_fingerprint') == source_fingerprint(state), 'Review is stale: source fingerprint differs')
    require(review.get('context_sha256') == context_fingerprint(state), 'Review is stale: input, catalogue, target or runtime context differs')
    answers = state.get('answers', {})
    target = review.get('target', {})
    require(all(target.get(k) == answers.get(k) and target.get(k) for k in ('framework', 'warehouse')),
            'Review target differs from the engagement selection')
    for name in ('models', 'relationships', 'changes', 'decisions', 'validation', 'artifacts'):
        values = review.get(name, [])
        require(isinstance(values, list) and len(values) <= MAX_REVIEW_ITEMS and all(isinstance(x, dict) for x in values),
                'Invalid or oversized review collection: ' + name)
    models = review.get('models', [])
    ids = [m.get('id') for m in models]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), 'Model IDs must be unique')
    for model in models:
        require(model.get('layer') in LAYERS, 'Model layer must be bronze, silver or gold')
        require(isinstance(model.get('columns', []), list) and all(isinstance(c, dict) and c.get('name') for c in model.get('columns', [])),
                'Model columns must have names')
    for edge in review.get('relationships', []):
        require(edge.get('from') in ids and edge.get('to') in ids, 'Relationship references an absent model')
        require(edge.get('kind') in ('lineage', 'relationship'), 'Relationship kind must distinguish lineage from joins')
    for name in ('changes', 'decisions', 'validation'):
        keys = [v.get('id') for v in review.get(name, [])]
        require(all(isinstance(k, str) and k for k in keys) and len(set(keys)) == len(keys), name + ' IDs must be unique')
    for result in review.get('validation', []):
        require(result.get('status') in ('pass', 'fail', 'pending', 'skipped', 'not_applicable'), 'Unknown reported validation status')
        require(result.get('scope') in ('static', 'local', 'warehouse', 'semantic', 'business', 'operational'), 'Unknown validation scope')
        # This surface cannot authenticate a human or an external execution receipt.
        require(result.get('scope') != 'business' or result.get('status') != 'pass',
                'Human approval belongs in the authority record, not a pass badge')
    _validate_quality_checks(state, review)
    _validate_metadata_reference(review)
    return review


def select_artifacts(review, root, audience, include):
    require(audience in AUDIENCES, 'Unknown audience')
    include = set(include)
    require(include <= CATEGORIES, 'Unknown deliverable selection')
    require(audience != 'reviewer' or not include & {'implementation', 'sample_data', 'technical_audit'},
            'Reviewer packages cannot contain implementation, raw data or audit payloads')
    require(audience == 'audit' or 'technical_audit' not in include, 'Technical audit must be a separate package')
    require(audience != 'audit' or include <= {'technical_audit'}, 'Audit exports must be separate from working deliverables')
    root = _path(root)
    require(root.is_dir(), 'Artifact root must be a directory')
    artifacts = review.get('artifacts', [])
    require(len(artifacts) <= MAX_ARTIFACTS, 'Artifact count limit exceeded; split by domain')
    by_id, selected, total, destinations = {}, [], 0, set()
    for record in artifacts:
        aid = record.get('id')
        require(isinstance(aid, str) and aid and aid not in by_id, 'Artifact IDs must be unique')
        require(record.get('category') in CATEGORIES, 'Unknown artifact category')
        require(isinstance(record.get('audiences'), list) and set(record['audiences']) <= AUDIENCES, 'Explicit artifact audiences required')
        require(isinstance(record.get('requires', []), list), 'Artifact dependencies must be a list')
        by_id[aid] = record
    for record in artifacts:
        if record['category'] not in include or audience not in record['audiences']:
            continue
        relative = _relative(record.get('path'))
        native_omni = _native_omni_artifact(relative)
        require(relative.suffix.lower() in SUFFIXES or native_omni,
                'Unsupported artifact type; nested archives and active documents are excluded')
        require(not native_omni or record['category'] == 'implementation',
                'Native Omni files must be explicitly registered as implementation artifacts')
        require(audience != 'reviewer' or relative.suffix.lower() not in {'.sql', '.py', '.yaml', '.yml', '.toml', '.lock'},
                'Implementation file types cannot be relabeled as reviewer documentation')
        require(not any(is_secret(Path(part)) for part in relative.parts), 'Credentials/configuration file cannot be exported')
        source = _path(root / str(relative), root)
        require(source.exists() and stat.S_ISREG(source.stat().st_mode), 'Artifact must be a regular file')
        require(source.stat().st_size <= MAX_ARTIFACT_BYTES, 'Artifact too large; partition explicitly')
        with source.open('rb') as stream:
            content = stream.read(MAX_ARTIFACT_BYTES + 1)
        require(len(content) <= MAX_ARTIFACT_BYTES, 'Artifact grew beyond the size limit')
        require(_sha(content) == record.get('sha256'), 'Artifact changed: ' + record['id'])
        require(not content.startswith(b'PK'), 'Nested archives cannot be disguised as text artifacts')
        if native_omni:
            require('\x00' not in content.decode('utf-8'), 'Native Omni artifacts must be UTF-8 model text')
        _check_disclosure_bytes(content, str(relative))
        if relative.suffix.lower() == '.svg':
            _validate_svg(content)
        total += len(content)
        require(total <= MAX_PACKAGE_BYTES, 'Package size limit exceeded; split by domain')
        dest = FOLDERS[record['category']] + '/' + str(relative)
        require(dest.casefold() not in destinations, 'Portable output filename collision')
        destinations.add(dest.casefold())
        selected.append(dict(record, destination=dest, content=content))
    selected_ids = {a['id'] for a in selected}
    for record in selected:
        require(set(record.get('requires', [])) <= selected_ids,
                'Missing selected dependencies for ' + record['id'] + '; include required artifacts or supply a reviewed external-dependency guide')
    _validate_markdown_links(selected)
    return selected


def _validate_svg(content):
    # Only generated inert diagrams; no scripts, foreign HTML, events, links or remote resources.
    import xml.etree.ElementTree as ET
    decoded=content.decode('utf-8')
    require('\x00' not in decoded, 'SVG must use UTF-8 text without null bytes')
    require(b'<!DOCTYPE' not in content.upper() and b'<!ENTITY' not in content.upper(), 'SVG declarations are not allowed')
    require(b'<?' not in content, 'SVG processing instructions are not allowed')
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise ValueError('Malformed SVG XML: ' + str(exc)) from exc
    safe = {'svg', 'g', 'rect', 'path', 'line', 'polyline', 'polygon', 'circle', 'ellipse', 'text', 'tspan', 'title', 'desc', 'defs', 'marker'}
    require(root.tag.split('}')[-1] == 'svg', 'Expected an SVG diagram')
    for node in root.iter():
        require(node.tag.split('}')[-1] in safe, 'Active or unsupported SVG element')
        for key, value in node.attrib.items():
            require(not key.startswith('{'), 'Namespaced SVG attributes are not allowed')
            key = key.split('}')[-1].lower()
            require(not key.startswith('on') and key not in {'href', 'src', 'style', 'base'}, 'Active SVG attribute')
            require('url(' not in value.lower() or re.fullmatch(r'url\(#[A-Za-z0-9_-]+\)', value), 'External SVG reference')
            if key in {'fill', 'stroke', 'marker-end', 'marker-start', 'marker-mid', 'filter', 'clip-path', 'mask'}:
                require(re.fullmatch(r'(?:#[0-9A-Fa-f]{3,8}|[A-Za-z]+|url\(#[A-Za-z0-9_-]+\))', value) is not None,
                        'Unsupported SVG paint or resource reference')


def _edge_description(edge):
    """Keep declared semantics visible; never infer implementation or enforcement."""
    values = [str(edge.get('label') or edge['kind'])]
    for key, label in (('role', 'Role'), ('predicate', 'Predicate'), ('cardinality', 'Cardinality')):
        if edge.get(key):
            values.append(label + ': ' + str(edge[key]))
    status = edge.get('status', edge.get('implementation_status'))
    if edge['kind'] == 'relationship':
        values.append('Implementation: ' + (str(status) + ' (declared)' if status else 'not specified'))
    return ' · '.join(values)


def _diagram_layout(models, relationships):
    """Orthogonal routes stay in reserved gutters, never through another table."""
    grouped = {layer: [m for m in models if m['layer'] == layer] for layer in LAYERS}
    active_layers = [layer for layer in LAYERS if grouped[layer]]
    layer_index = {m['id']: active_layers.index(m['layer']) for m in models}
    incidents = {m['id']: [] for m in models}
    lanes = {index: [] for index in range(len(active_layers))}
    skips = []
    for index, edge in enumerate(relationships):
        a, b = layer_index[edge['from']], layer_index[edge['to']]
        incidents[edge['from']].append((index, 'from'))
        incidents[edge['to']].append((index, 'to'))
        if abs(a - b) == 1:
            lanes[min(a, b)].append(index)
        elif a == b:
            lanes[a].append(index)
        else:
            lanes[a].append(index); lanes[b].append(index); skips.append(index)
    card_width = 360
    card_height = max(138, 48 + 16 * max((len(v) for v in incidents.values()), default=0))
    gutter_widths = [max(156, 42 + len(lanes[i]) * 14) for i in range(len(active_layers))]
    column_x = [34]
    for i in range(len(active_layers) - 1):
        column_x.append(column_x[-1] + card_width + gutter_widths[i])
    top = 106 + len(skips) * 18
    positions = {m['id']: (column_x[i], top + j * (card_height + 48))
                 for i, layer in enumerate(active_layers) for j, m in enumerate(grouped[layer])}
    def port(identifier, index, end):
        items = incidents[identifier]
        return positions[identifier][1] + 24 + (items.index((index, end)) + .5) * (card_height - 48) / len(items)
    def lane(layer, index):
        return column_x[layer] + card_width + 24 + lanes[layer].index(index) * 14
    routes = []
    for index, edge in enumerate(relationships):
        a, b = layer_index[edge['from']], layer_index[edge['to']]
        x1, _ = positions[edge['from']]; x2, _ = positions[edge['to']]
        y1, y2 = port(edge['from'], index, 'from'), port(edge['to'], index, 'to')
        if abs(a - b) == 1:
            x1 += card_width if a < b else 0
            x2 += card_width if b < a else 0
            middle = lane(min(a, b), index)
            points = [(x1, y1), (middle, y1), (middle, y2), (x2, y2)]
        elif a == b:
            x1 += card_width; x2 += card_width
            middle = lane(a, index)
            points = [(x1, y1), (middle, y1), (middle, y2), (x2, y2)]
        else:
            x1 += card_width; x2 += card_width
            upper = 68 + skips.index(index) * 18
            points = [(x1, y1), (lane(a, index), y1), (lane(a, index), upper),
                      (lane(b, index), upper), (lane(b, index), y2), (x2, y2)]
        routes.append({'points': points, 'label': 'E' + str(index + 1), 'edge': edge})
    return {'positions': positions, 'routes': routes, 'card_width': card_width, 'card_height': card_height,
            'width': max(1080, column_x[-1] + card_width + gutter_widths[-1] + 34),
            'bottom': top + max(len(grouped[layer]) for layer in LAYERS) * (card_height + 48),
            'column_x': column_x, 'layers': active_layers}


def model_svg(models, relationships):
    """Connected table blocks plus a visible, complete relationship label ledger."""
    if not models:
        return ''
    layout = _diagram_layout(models, relationships)
    positions, width = layout['positions'], layout['width']
    card_width, card_height = layout['card_width'], layout['card_height']
    ledger, cursor = [], layout['bottom'] + 30
    for index, edge in enumerate(relationships):
        lines = [f"E{index + 1} · {edge['from']} → {edge['to']}"]
        lines.extend(textwrap.wrap(_edge_description(edge), width=120, break_long_words=True) or [''])
        ledger.append((cursor, lines, edge)); cursor += 22 * len(lines) + 20
    height = cursor + 28
    e = lambda value: html.escape(str(value), quote=True)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
             '<title>Layered model — table blocks and declared connections</title>',
             '<desc>Edges use reserved gutters. Edge IDs refer to the visible predicate, cardinality and role ledger below. Declared implementation is not constraint enforcement.</desc>',
             f'<rect width="{width}" height="{height}" fill="#f4f7fb"/>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#53697f"/></marker></defs>']
    for i, layer in enumerate(layout['layers']):
        count = sum(m['layer'] == layer for m in models)
        parts.append(f'<text x="{layout["column_x"][i]}" y="30" font-family="sans-serif" font-size="20" font-weight="700" fill="#172d43">{layer.title()} · {count} objects</text>')
    parts.append('<text x="34" y="51" font-family="sans-serif" font-size="11" fill="#53697f">Teal: lineage. Violet: authored join (declared). Dashed amber: proposed join. Dotted grey: other/unspecified. No enforced constraints implied.</text>')
    for route in layout['routes']:
        edge, points = route['edge'], route['points']
        status = edge.get('status', edge.get('implementation_status'))
        color = '#0c827e' if edge['kind'] == 'lineage' else '#7658a7' if status == 'authored' else '#9b641c' if status == 'proposed' else '#53697f'
        dash = '' if edge['kind'] == 'lineage' or status == 'authored' else ' stroke-dasharray="7 4"' if status == 'proposed' else ' stroke-dasharray="2 4"'
        path = 'M ' + ' L '.join(f'{x:g} {y:g}' for x, y in points)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#arrow)"><title>{e(route["label"] + ": " + _edge_description(edge))}</title></path>')
        x, y = points[0]; goes_right = points[1][0] > x
        parts.append(f'<text x="{x + (5 if goes_right else -5):g}" y="{y - 5:g}" text-anchor="{"start" if goes_right else "end"}" font-family="sans-serif" font-size="9" fill="{color}">{route["label"]}</text>')
    for model in models:
        x, y = positions[model['id']]
        name, grain = str(model.get('name', model['id'])), str(model.get('grain', 'Grain unresolved'))
        parts.append(f'<g><title>{e(name)} — {e(grain)}</title><rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="10" fill="white" stroke="#9aabba"/>')
        parts.append(f'<text x="{x+14}" y="{y+25}" font-family="sans-serif" font-size="15" font-weight="700" fill="#18324a">{e(name[:38] + ("…" if len(name) > 38 else ""))}</text>')
        parts.append(f'<text x="{x+14}" y="{y+44}" font-family="sans-serif" font-size="11" fill="#53697f">{e(grain[:48] + ("…" if len(grain) > 48 else ""))}</text>')
        columns = sorted(model.get('columns', []), key=lambda c: not bool(c.get('key')))
        for j, column in enumerate(columns[:4]):
            label = ((str(column.get('key')) + ' ') if column.get('key') else '') + column['name'] + ' · ' + str(column.get('type', 'unknown'))
            parts.append(f'<text x="{x+14}" y="{y+64+j*16}" font-family="monospace" font-size="11" fill="#18324a">{e(label[:49])}</text>')
        if len(columns) > 4:
            parts.append(f'<text x="{x+14}" y="{y+130}" font-family="sans-serif" font-size="10" fill="#53697f">+ {len(columns)-4} columns in dictionary</text>')
        parts.append('</g>')
    for y, lines, edge in ledger:
        for index, line in enumerate(lines):
            parts.append(f'<text x="34" y="{y+index*22}" font-family="sans-serif" font-size="12" font-weight="{"700" if index == 0 else "400"}" fill="#18324a">{e(line)}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def diagram_views(models, relationships, maximum=36):
    """Partition by domain/node and edge density, retaining cross-view accounting."""
    if not models:
        return []
    groups = []
    if len(models) <= maximum and len(relationships) <= maximum:
        groups = [('All layers', models)]
    else:
        domains = sorted({str(m.get('domain') or 'Unassigned domain') for m in models})
        for domain in domains:
            scoped = [m for m in models if str(m.get('domain') or 'Unassigned domain') == domain]
            chunks, current = [], []
            for model in scoped:
                ids = {m['id'] for m in current + [model]}
                edge_count = sum(r['from'] in ids and r['to'] in ids for r in relationships)
                if current and (len(current) >= maximum or edge_count > maximum):
                    chunks.append(current); current = []
                current.append(model)
            if current:
                chunks.append(current)
            groups.extend((domain + ' · view ' + str(index + 1), scope) for index, scope in enumerate(chunks))
    result = []
    for label, scope in groups:
        ids = {m['id'] for m in scope}
        edges = [r for r in relationships if r['from'] in ids and r['to'] in ids]
        external = [r for r in relationships if (r['from'] in ids) != (r['to'] in ids)]
        result.append({'label': label, 'model_ids': sorted(ids), 'internal_connections': len(edges), 'cross_view_connections': len(external),
                       'base64': base64.b64encode(model_svg(scope, edges).encode()).decode()})
    return result


def _summary(state):
    answers=state.get('answers', {})
    readiness=state.get('readiness', {})
    platform=readiness.get('platform', {})
    # Explicit projection: never embed absolute roots, full state, answers JSON or receipts.
    delivery = state.get('delivery', {})
    from delivery_assurance import pending_summary
    return {'engagement_id':state.get('engagement_id','Unassigned'), 'revision':state.get('revision',0),
            'delivery_assurance': pending_summary(answers.get('migration_scope')),
            'context_sha256':context_fingerprint(state),
            'delivery':{key:delivery[key] for key in ('status','artifact_count','assurance','audience','deliverables','qualification') if key in delivery},
            'status':state.get('status','discovery'), 'source_fingerprint':source_fingerprint(state),
            'target':{k:answers.get(k) for k in ('framework','warehouse','semantic_target')},
            'engagement_type':answers.get('engagement_type',answers.get('mode','unresolved')),
            'domain':answers.get('domain',answers.get('priority_domain','Not selected')),
            'next_actions':state.get('next_actions',[]), 'readiness':{'interview_complete':readiness.get('interview_complete',False),
            'generation_ready':readiness.get('generation_ready',False), 'questions':readiness.get('questions',[]),
            'missing_answers':readiness.get('missing_answers',[]), 'platform':{k:platform.get(k) for k in ('coverage','findings','capabilities','detected_sources')}}}


def _deployment_presentation(state, audience):
    """Curated display only. Never pass through runner configuration or authority."""
    raw = state.get('deployment_review')
    if not raw or audience == 'audit':
        return None
    require(isinstance(raw, dict) and raw.get('schema_version') == 1, 'Unknown deployment review format')
    audiences = raw.get('audiences', ['engineer'])
    require(isinstance(audiences, list) and set(audiences) <= AUDIENCES, 'Invalid deployment review audiences')
    if audience not in audiences:
        return None
    def fields(value, names):
        require(isinstance(value, dict), 'Deployment review records must be objects')
        result = {}
        for name in names:
            if name in value:
                require(isinstance(value[name], str), 'Deployment display field must be text: ' + name)
                result[name] = value[name]
        return result
    def digest(value, name):
        require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'Invalid deployment ' + name)
        return value
    def strings(value):
        require(isinstance(value, list) and len(value) <= 200 and all(isinstance(x, str) for x in value),
                'Deployment display lists require at most 200 text items')
        return list(value)
    answers = state.get('answers', {})
    target = fields(raw.get('target', {}), ('framework', 'warehouse', 'semantic_target', 'environment'))
    retained = {key:answers[key] for key in ('framework', 'warehouse', 'semantic_target') if answers.get(key)}
    target_matches = all(target.get(key) == value for key, value in retained.items())
    target.update(retained)
    handoff = fields(raw.get('handoff', {}), ('context_sha256', 'manifest_sha256'))
    for key, value in handoff.items():
        digest(value, key)
    current = (state.get('status') == 'handoff_prepared' and state.get('delivery', {}).get('status') == 'prepared'
               and target_matches and handoff.get('context_sha256') == context_fingerprint(state)
               and bool(handoff.get('manifest_sha256')) and raw.get('current', True) is True
               and raw.get('status') not in ('stale', 'invalid', 'invalidated', 'blocked'))
    public = fields(raw, ('status', 'next_action'))
    result = {'schema_version':1, 'status':public.get('status', 'not_prepared') if current else 'stale',
              'current':current, 'target':target, 'handoff':handoff, 'choices':[], 'receipts':[],
              'assurance':'Reported presentation only; this page does not authenticate approvals or execution.',
              'next_action':public.get('next_action') or 'Ask the agent to prepare a concrete deployment plan.'}
    if not current:
        result['next_action'] = 'Refresh the current handoff, retained target and deployment review before requesting an action.'
    choices = raw.get('choices', [])
    require(isinstance(choices, list) and len(choices) <= len(DEPLOYMENT_ACTIONS), 'Invalid deployment choices')
    seen = set()
    for choice in choices:
        item = fields(choice, ('id', 'label', 'reason'))
        require(item.get('id') in DEPLOYMENT_ACTIONS and item['id'] not in seen, 'Unknown or duplicate deployment action')
        seen.add(item['id']);item['available'] = current and choice.get('available') is True
        if not current:
            item['reason'] = result['next_action']
        result['choices'].append(item)
    if raw.get('plan'):
        plan = fields(raw['plan'], ('id', 'sha256', 'action', 'target_label', 'summary', 'evidence_artifact_id', 'evidence_sha256'))
        require(plan.get('action') in DEPLOYMENT_ACTIONS and bool(plan.get('id')), 'Deployment plan requires an ID and supported action')
        for key in ('sha256', 'evidence_sha256'):
            digest(plan.get(key), 'plan ' + key)
        require(bool(plan.get('evidence_artifact_id')), 'Deployment plan requires its sanitized evidence artifact')
        rows = raw['plan'].get('files', [])
        require(isinstance(rows, list) and len(rows) <= MAX_ARTIFACTS, 'Deployment plan file limit exceeded')
        plan['files'] = []
        for row in rows:
            item = fields(row, ('path', 'sha256', 'version', 'operation'))
            _relative(item.get('path'));digest(item.get('sha256'), 'file sha256')
            plan['files'].append(item)
        for key in ('impacts', 'steps', 'recovery', 'prerequisites'):
            plan[key] = strings(raw['plan'].get(key, []))
        result['plan'] = plan
        if current and not public.get('next_action'):
            result['next_action'] = 'Review the proposed impact and recovery, then save a request for the selected action.'
    receipts = raw.get('receipts', [])
    require(isinstance(receipts, list) and len(receipts) <= 200, 'Deployment receipt limit exceeded')
    for receipt in receipts:
        item = fields(receipt, ('id', 'action', 'status', 'scope', 'summary', 'evidence_artifact_id', 'sha256'))
        require(item.get('action') in DEPLOYMENT_ACTIONS, 'Unknown deployment receipt action')
        require(bool(item.get('evidence_artifact_id')), 'Deployment receipt requires its sanitized evidence artifact')
        digest(item.get('sha256'), 'receipt sha256')
        result['receipts'].append(item)
    return result


def _select_deployment_evidence(data, selected):
    """Detailed deployment display follows the same audience/selection as its bytes."""
    deployment = data.get('deployment')
    if not deployment:
        return
    by_id = {record['id']:record for record in selected}
    def included(record, hash_key):
        artifact = by_id.get(record['evidence_artifact_id'])
        if artifact is None:
            return False
        require(artifact['sha256'] == record[hash_key], 'Deployment evidence changed: ' + record['evidence_artifact_id'])
        return True
    if deployment.get('plan') and not included(deployment['plan'], 'evidence_sha256'):
        deployment.pop('plan')
        deployment['plan_omitted'] = 'Plan details are outside this export; request the selected deployment evidence from the agent.'
    if deployment.get('plan'):
        by_path = {record.get('path'):record for record in selected}
        for item in deployment['plan'].get('files', []):
            artifact = by_path.get(item['path'])
            if artifact:
                require(artifact['sha256'] == item['sha256'], 'Deployment plan file changed: ' + item['path'])
    deployment['receipts'] = [item for item in deployment['receipts'] if included(item, 'sha256')]


def _presentation(state, review=None, audience='engineer'):
    data={'engagement':_summary(state),'audience':audience,'review':{},'files':[]}
    deployment = _deployment_presentation(state, audience)
    if deployment:
        data['deployment'] = deployment
    if review:
        validate_review(state, review)
        data['review']=json.loads(json.dumps({k:review.get(k, [] if k not in ('title','description') else '') for k in ('title','description','models','relationships','changes','decisions','validation')}))
        if review.get('quality_checks'):
            data['review']['quality_checks'] = [dict(_quality_data(row), **{key:row[key]
                for key in ('context_sha256', 'evidence_artifact_id', 'sha256')}) for row in review['quality_checks']]
        if 'metadata' in review:
            data['review']['metadata'] = dict(review['metadata'])
        if audience == 'reviewer':
            data['review']['validation']=[{k:v.get(k) for k in ('id','label','scope','status','details','evidence_id')} for v in review.get('validation',[])]
        if audience == 'audit':
            data['review']={}
    return data


def _html(data):
    template=(ASSETS/'portal.html').read_text(encoding='utf-8')
    encoded=json.dumps(data,ensure_ascii=True,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return template.replace('/*__PORTAL_CSS__*/',(ASSETS/'portal.css').read_text(encoding='utf-8')).replace('/*__PORTAL_JS__*/',(ASSETS/'portal.js').read_text(encoding='utf-8')).replace('/*__PORTAL_DATA__*/',encoded)


def _atomic_write(path, content, overwrite=False):
    path=_path(path)
    require(path.parent.is_dir(), 'Output parent must exist')
    require(overwrite or not path.exists(), 'Output exists; choose a new version')
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.delivery-',delete=False) as stream:
            temp=Path(stream.name); stream.write(content); stream.flush(); os.fsync(stream.fileno())
        if overwrite:
            os.replace(str(temp),str(path))
        else:
            os.link(str(temp),str(path)); temp.unlink()
        temp=None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def render_engagement(state, output_path, review=None):
    """Render local status with no artifact payloads. May refresh an existing status page."""
    source=state.get('inputs',{}).get('source',{}).get('path')
    if source:
        destination=_path(output_path); source_root=_path(source)
        require(destination != source_root and source_root not in destination.parents, 'Review output must stay outside the source repository')
    data=_presentation(state,review)
    _select_quality_evidence(data, [])
    _select_metadata_evidence(data, [])
    if review and review.get('models'):
        data['diagrams']=diagram_views(review['models'],review.get('relationships',[]))
    rendered = _html(data).encode('utf-8')
    _check_disclosure_bytes(rendered, 'START_HERE.html')
    _atomic_write(output_path,rendered,overwrite=True)
    return str(output_path)


def resolve_selection(state, audience='reviewer', include=None):
    """Resolve saved/default deliverables once for registration and packaging."""
    require(audience in AUDIENCES, 'Unknown audience')
    defaults={'reviewer':['documentation','diagrams','dictionary','validation'],
              'engineer':['documentation','diagrams','dictionary','implementation','validation'], 'audit':['technical_audit']}
    if include is None:
        requested=state.get('answers',{}).get('deliverables')
        permitted={'reviewer':set(defaults['reviewer']),'engineer':CATEGORIES-{'technical_audit'},'audit':{'technical_audit'}}[audience]
        include=([item for item in requested if item in permitted] if isinstance(requested,list) and audience!='audit' else defaults[audience])
    else:
        include=list(include)
    return include


def package_delivery(state, review, artifact_root, output_path, audience='reviewer', include=None):
    validate_review(state,review)
    include=resolve_selection(state,audience,include)
    source=state.get('inputs',{}).get('source',{}).get('path')
    if source:
        destination=_path(output_path); source_root=_path(source)
        require(destination != source_root and source_root not in destination.parents, 'Package output must stay outside the source repository')
    selected=select_artifacts(review,artifact_root,audience,include)
    require(selected, 'No artifacts match this audience and selection')
    data=_presentation(state,review,audience)
    _select_deployment_evidence(data, selected)
    _select_quality_evidence(data, selected)
    _select_metadata_evidence(data, selected)
    # Data-heavy views must also obey deliverable selection, not just file omission.
    if not set(include)&{'documentation','dictionary','diagrams'}:
        data['review'].pop('models',None); data['review'].pop('relationships',None)
    elif 'dictionary' not in include:
        for model in data['review'].get('models',[]):
            model.pop('columns',None)
    if 'validation' not in include:
        data['review'].pop('validation',None)
    if 'diagrams' in include and data['review'].get('models'):
        data['diagrams']=diagram_views(data['review']['models'],data['review'].get('relationships',[]))
    disclosure = _check_share_policy(state, review, selected, data, audience)
    files={a['destination']:a['content'] for a in selected}
    for artifact in selected:
        data['files'].append({'id':artifact['id'],'path':artifact['destination'],'category':artifact['category'],
                              'description':artifact.get('description',''),'requires':artifact.get('requires',[]),
                              'sha256':artifact['sha256'],'size':len(artifact['content']),
                              'base64':base64.b64encode(artifact['content']).decode()})
    files['START_HERE.html']=_html(data).encode('utf-8')
    scans = {name: _check_disclosure_bytes(body, name) for name, body in files.items()}
    manifest={'schema_version':1,'kind':'portable_delivery_integrity','engagement_id':state['engagement_id'],
              'export_origin': 'agent_packager',
              'disclosure_scans': scans,
              'migration_scope': state.get('answers', {}).get('migration_scope'),
              'acceptance_ready': False,
              'deployment_authorized': False,
              'disclosure_policy_status': disclosure,
              'source_fingerprint':source_fingerprint(state),'context_sha256':context_fingerprint(state),
              'target':review['target'],'audience':audience,
              'deliverables':sorted(include),'authority':'File integrity only; not execution, business approval or deployment.',
              'files':[{'path':name,'sha256':_sha(body),'bytes':len(body)} for name,body in sorted(files.items())]}
    files['DELIVERY_MANIFEST.json']=json.dumps(manifest,indent=2,sort_keys=True).encode()+b'\n'
    require(sum(map(len,files.values())) <= MAX_PACKAGE_BYTES*3, 'Rendered package exceeds size limit')
    import io
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,body in sorted(files.items()):
            archive.writestr(name,body)
    payload = stream.getvalue()
    _check_disclosure_bytes(payload, 'delivery.zip')
    _atomic_write(output_path,payload)
    return manifest


def verify_delivery(path):
    """Verify a relocated ZIP in memory. Does not trust paths or extract archives."""
    with zipfile.ZipFile(_path(path)) as archive:
        infos=archive.infolist()
        require(len(infos) <= MAX_ARTIFACTS+2, 'Too many package entries')
        require(sum(i.file_size for i in infos) <= MAX_PACKAGE_BYTES*3, 'Package expands beyond limit')
        names=[i.filename for i in infos]
        require(len(set(n.casefold() for n in names)) == len(names), 'Duplicate package entry')
        for info in infos:
            _relative(info.filename)
            require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), 'Unexpected archive entry')
        require('DELIVERY_MANIFEST.json' in names, 'Delivery manifest missing')
        manifest=json.loads(archive.read('DELIVERY_MANIFEST.json'))
        require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'portable_delivery_integrity', 'Unknown manifest format')
        context = manifest.get('context_sha256')
        if 'context_sha256' in manifest:
            require(isinstance(context, str) and re.fullmatch(r'[0-9a-f]{64}', context) is not None,
                    'Invalid workflow context_sha256 in delivery manifest')
            require('START_HERE.html' in names, 'Context-bound package requires its Start Here page')
            match = re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>',
                              archive.read('START_HERE.html').decode('utf-8'), re.S)
            require(match is not None, 'Start Here context is missing')
            embedded = json.loads(match.group(1))
            require(embedded.get('engagement', {}).get('context_sha256') == context,
                    'Package workflow context differs from its Start Here page')
        elif 'START_HERE.html' in names:
            match = re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>',
                              archive.read('START_HERE.html').decode('utf-8'), re.S)
            if match:
                require(not json.loads(match.group(1)).get('review', {}).get('metadata'),
                        'Metadata review requires a context-bound delivery manifest')
        declared=manifest.get('files',[])
        require(len({f['path'] for f in declared})==len(declared), 'Duplicate manifest path')
        require(set(names) == {'DELIVERY_MANIFEST.json'} | {f['path'] for f in declared}, 'Package inventory differs from manifest')
        for item in declared:
            body=archive.read(item['path'])
            require(len(body)==item['bytes'] and _sha(body)==item['sha256'], 'Package bytes differ: '+item['path'])
        if context is not None:
            _validate_markdown_links([{'id':item['path'],'destination':item['path'],'path':item['path'],
                                       'content':archive.read(item['path'])} for item in declared])
            if embedded.get('deployment'):
                evidence = [{'id':item['id'], 'path':item['path'].split('/', 1)[-1], 'sha256':_sha(archive.read(item['path']))}
                            for item in embedded.get('files', []) if item.get('path') in names]
                before = json.dumps(embedded['deployment'], sort_keys=True)
                _select_deployment_evidence(embedded, evidence)
                require(json.dumps(embedded['deployment'], sort_keys=True) == before,
                        'Deployment evidence is absent from the package')
            if embedded.get('review', {}).get('quality_checks'):
                evidence = [{'id':item['id'], 'sha256':_sha(archive.read(item['path'])),
                             'content':archive.read(item['path'])}
                            for item in embedded.get('files', []) if item.get('path') in names]
                before = json.dumps(embedded['review']['quality_checks'], sort_keys=True)
                _select_quality_evidence(embedded, evidence)
                require(json.dumps(embedded['review']['quality_checks'], sort_keys=True) == before,
                        'Quality evidence is absent or differs from the package summary')
            if embedded.get('review', {}).get('metadata'):
                evidence = []
                ref = embedded['review']['metadata']
                require(all(embedded['engagement']['target'].get(key) == manifest.get('target', {}).get(key)
                            for key in ('framework', 'warehouse')), 'Metadata package target differs from its Start Here page')
                for item in embedded.get('files', []):
                    if item.get('id') != ref.get('plan_artifact_id'):
                        continue
                    require(item.get('path') in names, 'Metadata artifact is absent from package')
                    body = archive.read(item['path'])
                    try:
                        displayed_bytes = base64.b64decode(item.get('base64', ''), validate=True)
                    except (ValueError, TypeError) as error:
                        raise ValueError('Invalid embedded metadata artifact bytes') from error
                    require(displayed_bytes == body and item.get('sha256') == _sha(body) and item.get('size') == len(body),
                            'Embedded metadata artifact differs from package bytes')
                    evidence.append({'id': item['id'], 'sha256': _sha(body), 'content': body})
                before = json.dumps(ref, sort_keys=True)
                _select_metadata_evidence(embedded, evidence)
                require(json.dumps(embedded['review']['metadata'], sort_keys=True) == before,
                        'Metadata evidence is absent or differs from the package summary')
    return {'status':'integrity_verified','files':len(declared),'context_sha256':context,
            'authority':'Integrity only; does not verify frozen benchmark authority or target execution.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('render','package'):
        p=sub.add_parser(name); p.add_argument('--state',required=True); p.add_argument('--review'); p.add_argument('--output',required=True)
        if name=='package':
            p.add_argument('--artifacts',required=True); p.add_argument('--audience',choices=sorted(AUDIENCES),default='reviewer')
            p.add_argument('--include',help='Comma-separated deliverable categories')
    p=sub.add_parser('verify'); p.add_argument('package')
    args=parser.parse_args(argv)
    try:
        if args.command=='verify': result=verify_delivery(args.package)
        else:
            # Durable state is verified and current inputs are reassessed before handoff.
            from guided_workflow import assess_engagement
            state_path=_path(args.state)
            require(state_path.name == 'state.json', 'Use the engagement state.json created by guided_workflow')
            state=assess_engagement(state_path.parent)
            review=load_json(args.review) if args.review else None
            if args.command=='render': result={'page':render_engagement(state,args.output,review)}
            else:
                require(review is not None,'Packaging requires a reviewed content manifest')
                result=package_delivery(state,review,args.artifacts,args.output,args.audience,args.include.split(',') if args.include is not None else None)
        print(json.dumps(result,indent=2)); return 0
    except (ValueError,OSError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print('Delivery blocked: '+str(exc),file=sys.stderr); return 2


if __name__=='__main__':
    raise SystemExit(main())
