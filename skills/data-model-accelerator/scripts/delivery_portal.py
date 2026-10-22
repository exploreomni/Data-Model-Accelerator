#!/usr/bin/env python3
"""Offline, evidence-labelled review and allowlisted portable delivery. No execution.

Rendering is not a verifier: business/target acceptance stays with existing gates.
Python 3.9+, standard library; source artifacts never change.
"""
import argparse
import base64
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import sys
import tempfile
import textwrap
from urllib.parse import quote, unquote, urlsplit
import zipfile

from ae_common import load_json, require, _json_bytes
from plan_specialists import is_secret

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'guided-delivery'
CATEGORIES = {'documentation', 'diagrams', 'dictionary', 'implementation', 'validation', 'sample_data', 'technical_audit'}
AUDIENCES = {'reviewer', 'engineer', 'audit'}
FOLDERS = {'documentation': '01_Model', 'diagrams': '01_Model', 'dictionary': '01_Model',
           'implementation': '02_Implementation', 'validation': '03_Validation',
           'sample_data': '04_Sample_Data', 'technical_audit': 'Technical_Audit'}
SUFFIXES = {'.md', '.txt', '.sql', '.yml', '.yaml', '.json', '.csv', '.tsv', '.svg', '.mmd', '.py', '.toml', '.lock', '.xlsx', '.docx', '.pdf'}
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
HANDOFF_ROLES = {'design_artifact_id': {'documentation'},
                 'implementation_guide_artifact_id': {'documentation', 'implementation'}}
MODEL_SOURCE_QUALIFICATION = 'Editable presentation source; not implementation or approval.'
DICTIONARY_FIELDS = ('model_id', 'model_name', 'layer', 'domain', 'grain',
                     'column_name', 'data_type', 'key', 'description')


def _validate_handoff(review):
    """Choose one maintained narrative per role, without creating status claims."""
    handoff = review.get('handoff', {})
    require(isinstance(handoff, dict) and set(handoff) <= set(HANDOFF_ROLES),
            'Handoff supports only a design document and an implementation guide')
    seen = set()
    for role, identifier in handoff.items():
        require(isinstance(identifier, str) and identifier and identifier not in seen,
                'Handoff artifact IDs must be nonempty and distinct')
        seen.add(identifier)
        matches = [item for item in review.get('artifacts', []) if item.get('id') == identifier]
        require(len(matches) == 1, 'Handoff must reference one uniquely registered artifact')
        artifact = matches[0]
        require(artifact.get('category') in HANDOFF_ROLES[role]
                and _relative(artifact.get('path')).suffix.lower() in {'.md', '.txt', '.docx', '.pdf'},
                'Handoff roles require a registered design document or setup guide in Markdown, text, Word or PDF')
    return handoff


def _select_handoff(data, selected):
    """Navigation follows the same audience/selection boundaries as payloads."""
    identifiers = {item['id'] for item in selected}
    if 'handoff' in data.get('review', {}):
        data['review']['handoff'] = {role: identifier for role, identifier in data['review']['handoff'].items()
                                     if identifier in identifiers}


def _competing_entrypoint(path):
    return PurePosixPath(path).name.casefold() in {'start_here.html', 'start_here.md', 'start_here.txt'}


def _native_omni_artifact(path):
    """Native model text only; no general extensionless-file exception."""
    return path.suffix.lower() in {'.view', '.topic'} or path.name in {'model', 'relationships'}


def _check_disclosure_bytes(content, filename):
    from sensitive_data import scan_bytes
    report = scan_bytes(content, filename)
    require(report['status'] == 'clear',
            'Disclosure scan blocked ' + filename + ': ' + report['status'] +
            '. Inspect value-free scan findings in the approved environment; do not rewrite source logic to hide a finding.')
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


def _validate_omni_reference(review):
    if 'omni' not in review:return
    ref=review['omni']
    require(type(ref) is dict and set(ref)=={'artifact_id','sha256'} and type(ref['artifact_id']) is str
            and type(ref['sha256']) is str and re.fullmatch(r'[a-f0-9]{64}',ref['sha256']), 'Invalid Omni review reference')
    matches=[a for a in review.get('artifacts',[]) if a.get('id')==ref['artifact_id']]
    require(len(matches)==1 and matches[0].get('category')=='documentation' and matches[0].get('sha256')==ref['sha256'],
            'Omni review must pin one registered documentation artifact')


def _omni_omitted(ref):
    return {'artifact_id':ref['artifact_id'],'sha256':ref['sha256'],'evidence_state':'not_included',
            'status':'unknown','summary':'Omni semantic evidence is not included in this page.',
            'next_action':'Include the registered Omni semantic review to inspect topics, metrics, dependencies and gaps.'}


def _select_omni_evidence(data,selected,*,state=None,review=None,root=None):
    """Only selected, pinned curated bytes may populate the Omni review panel.

    Agent packaging additionally rebuilds from registered private inputs without
    embedding those inputs. Portable integrity verification never authenticates
    collection, execution or imported completion claims.
    """
    ref=data.get('review',{}).get('omni')
    if ref is None:return
    matches=[a for a in selected if a.get('id')==ref.get('artifact_id')]
    require(len(matches)<=1,'Duplicate selected Omni artifact')
    included=bool(matches)
    if not included:
        data.get('review', {}).pop('omni_warehouse_bindings', None)
    # Agent packaging verifies the bound private inputs even for a reduced
    # export. Reclassifying an input must not disclose it when the catalog is
    # omitted from the selected categories.
    if not included and state is None:data['review']['omni']=_omni_omitted(ref);return
    if included:artifact=matches[0]
    else:
        records={a['id']:a for a in review['artifacts']}
        registered=records.get(ref['artifact_id'])
        require(registered is not None and registered.get('sha256')==ref['sha256'],'Omni evidence registration is stale')
        artifact_root=_path(root)
        path=_path(artifact_root/_relative(registered['path']),root=artifact_root)
        require(path.is_file() and path.stat().st_size<=MAX_ARTIFACT_BYTES,'Omni evidence is unavailable')
        artifact=dict(registered,content=path.read_bytes())
    require(_sha(artifact['content'])==ref['sha256']==artifact['sha256'],'Omni evidence changed')
    def parse(body):
        def unique(pairs):
            result={}
            for key,value in pairs:
                require(key not in result,'Duplicate Omni JSON key');result[key]=value
            return result
        def invalid(_):raise ValueError('Invalid Omni JSON number')
        try:result=json.loads(body.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)
        except (UnicodeError,ValueError):raise ValueError('Omni evidence must be unambiguous JSON') from None
        from omni_contract import _bounded
        _bounded(result);return result
    summary=parse(artifact['content'])
    from omni_contract import canonical_hash
    require(type(summary) is dict and summary.get('schema_version')==1 and summary.get('kind')=='omni_semantic_handoff'
            and summary.get('handoff_sha256')==canonical_hash({k:v for k,v in summary.items() if k!='handoff_sha256'}),
            'Omni semantic artifact integrity failed')
    pins=summary.get('pins',{})
    require(pins.get('context_sha256')==data['engagement']['context_sha256'] and
            all(pins.get('target',{}).get(k)==data['engagement']['target'].get(k) for k in ('framework','warehouse')),
            'Omni semantic context or target is stale')
    if state is not None:
        from omni_handoff import verify_handoff
        require(pins.get('source_fingerprint')==source_fingerprint(state),'Omni source inventory is stale')
        records={a['id']:a for a in review['artifacts']}
        artifact_root=_path(root)
        def read(record,category,audiences,relative):
            registered=records.get(record.get('artifact_id'))
            require(registered is not None and registered.get('sha256')==record.get('sha256'),'Omni source artifact registration is stale')
            require(registered.get('category')==category and
                    sorted(registered.get('audiences',[]))==sorted(audiences) and
                    registered.get('path')==relative,'Omni source artifact audience boundary changed')
            path=_path(artifact_root/_relative(registered['path']),root=artifact_root)
            require(path.is_file() and path.stat().st_size<=MAX_ARTIFACT_BYTES,'Omni source artifact is unavailable')
            content=path.read_bytes();require(_sha(content)==record['sha256'],'Omni source artifact changed')
            return content
        model_files={entry['path']:read(entry,'implementation',['engineer'],'omni/model/'+entry['path']).decode('utf-8')
                     for entry in summary['inputs']['model_files']}
        from omni_handoff import CONTEXT_PATH
        model_context=parse(read(summary['inputs']['model_context'],'technical_audit',['audit'],CONTEXT_PATH))
        verify_handoff(summary,state,model_files,model_context)
    if not included:data['review']['omni']=_omni_omitted(ref);return
    data['review']['omni']={'artifact_id':ref['artifact_id'],'sha256':ref['sha256'],'evidence_state':'selected',
        'status':'candidate','candidate_sha256':pins['model_candidate_sha256'],'static_status':summary['static_status'],
        'topics':copy_quality(summary['topics']),'metrics':copy_quality(summary['metrics']),
        'views':copy_quality(summary['views']),
        'query_views':copy_quality(summary['query_views']),'dependencies':copy_quality(summary['dependencies']),
        'decisions':copy_quality(summary['decisions']),'unknowns':copy_quality(summary['unknowns']),
        'next_actions':copy_quality(summary['next_actions']),
        'qualification':'Candidate review only. This page does not authenticate native execution, access, AI behavior, business sign-off or deployment.',
        'native_status':'pending','business_status':'pending','deployment_status':'not_authorized','acceptance_ready':False}


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
    from package_layout import version
    version(review)
    require(bool(source_fingerprint(state)), 'Engagement has no source fingerprint; run assessment first')
    require(review.get('source_fingerprint') == source_fingerprint(state), 'Review is stale: source fingerprint differs')
    require(review.get('context_sha256') == context_fingerprint(state), 'Review is stale: input, catalogue, target or runtime context differs')
    current_design = state.get('workflow', {}).get('design')
    if current_design:
        binding = {key:current_design[key] for key in ('id', 'revision', 'sha256')}
        require(review.get('design_binding') == binding,
                'Review is stale or unbound: design_binding must match the current design id, revision and sha256')
    answers = state.get('answers', {})
    target = review.get('target', {})
    require(all(target.get(k) == answers.get(k) and target.get(k) for k in ('framework', 'warehouse')),
            'Review target differs from the engagement selection')
    for name in ('models', 'relationships', 'changes', 'decisions', 'validation', 'artifacts', 'assets'):
        values = review.get(name, [])
        require(isinstance(values, list) and len(values) <= MAX_REVIEW_ITEMS and all(isinstance(x, dict) for x in values),
                'Invalid or oversized review collection: ' + name)
    models = review.get('models', [])
    ids = [m.get('id') for m in models]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), 'Model IDs must be unique')
    asset_ids = [a.get('id') for a in review.get('assets', [])]
    require(all(isinstance(i, str) and i and i != '__unmapped__' for i in asset_ids)
            and len(set(asset_ids)) == len(asset_ids), 'Asset IDs must be unique and not reserved')
    for collection in ('models', 'changes', 'decisions'):
        for item in review.get(collection, []):
            for key, known in (('asset_ids', asset_ids), ('model_ids', ids), ('depends_on', ids)):
                values = item.get(key, [])
                require(isinstance(values, list) and all(isinstance(v, str) and v in known for v in values),
                        'Unknown or invalid ' + key + ' association; retain unresolved mappings explicitly')
    for model in models:
        require(model.get('layer') in LAYERS, 'Model layer must be bronze, silver or gold')
        require(isinstance(model.get('columns', []), list) and all(isinstance(c, dict) and c.get('name') for c in model.get('columns', [])),
                'Model columns must have names')
    for edge in review.get('relationships', []):
        require(edge.get('from') in ids and edge.get('to') in ids, 'Relationship references an absent model')
        require(edge.get('kind') in ('lineage', 'relationship'), 'Relationship kind must distinguish lineage from joins')
    if 'partition' in review:
        from engagement_stages import closure
        partition = review['partition']
        required = {'kind', 'domain', 'owned_model_ids', 'shared_dependency_ids'}
        require(current_design and isinstance(partition, dict) and set(partition) in (
            required, required | {'batch_index', 'batch_size'}) and partition['kind'] == 'domain_design_review',
            'Unsupported design partition contract')
        canonical = {row['id']: row for row in current_design['entities']}
        owned = {key for key, row in canonical.items() if row['domain'] == partition['domain']}
        if 'batch_index' in partition:
            number, size = partition['batch_index'], partition['batch_size']
            require(type(number) is int and type(size) is int and number >= 1 and 1 <= size <= MAX_REVIEW_ITEMS,
                    'Invalid deterministic domain batch')
            owned = set(sorted(owned)[(number - 1) * size:number * size])
        included = set(closure({key: row['depends_on'] for key, row in canonical.items()}, owned))
        require(owned and partition['owned_model_ids'] == sorted(owned)
                and partition['shared_dependency_ids'] == sorted(included - owned) and set(ids) == included,
                'A domain partition must retain every owned entity and declared dependency')
        require(not review.get('artifacts'), 'Domain partition export is design-only; retain implementation in its original delivery')
    from portal_checks import erd_inventory
    erd_inventory(review)
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
    _validate_omni_reference(review)
    bindings = review.get('omni_warehouse_bindings', [])
    require(isinstance(bindings, list) and len(bindings) <= MAX_REVIEW_ITEMS, 'Invalid Omni warehouse bindings')
    require(not bindings or 'omni' in review, 'Omni pipeline bindings require pinned semantic evidence')
    seen_views = set()
    for binding in bindings:
        require(isinstance(binding, dict) and set(binding) == {'view_id', 'model_ids'}
                and isinstance(binding['view_id'], str) and binding['view_id']
                and binding['view_id'] not in seen_views, 'Invalid or duplicate Omni pipeline view')
        seen_views.add(binding['view_id'])
        require(isinstance(binding['model_ids'], list) and binding['model_ids']
                and all(isinstance(i, str) and i in ids for i in binding['model_ids'])
                and len(set(binding['model_ids'])) == len(binding['model_ids']), 'Omni pipeline model binding is outside the review')
    _validate_handoff(review)
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
        require(record['category'] == 'technical_audit' or not _competing_entrypoint(str(relative)),
                'One Start Here entrypoint per handoff; register the maintained design or setup guide instead')
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
        require(not content.startswith(b'PK') or relative.suffix.lower() in {'.xlsx', '.docx'},
                'Nested archives cannot be disguised as text artifacts')
        if relative.suffix.lower() in {'.xlsx', '.docx', '.pdf'}:
            require(record['category'] in {'documentation', 'dictionary'},
                    'Rich documents must be registered as documentation or dictionary')
        if native_omni:
            require('\x00' not in content.decode('utf-8'), 'Native Omni artifacts must be UTF-8 model text')
        if relative.suffix.lower() == '.svg':
            _validate_svg(content)
        _check_disclosure_bytes(content, str(relative))
        if 'diagram_model_ids' in record:
            require(relative.suffix.lower() == '.svg', 'diagram_model_ids requires a registered SVG artifact')
            from portal_checks import _diagram_ids, svg_model_coverage
            scope = _diagram_ids(record['diagram_model_ids'])
            require(set(scope) <= {model['id'] for model in review.get('models', [])},
                    'Registered diagram scope references a model outside this review')
            svg_model_coverage(content, scope)
        total += len(content)
        require(total <= MAX_PACKAGE_BYTES, 'Package size limit exceeded; split by domain')
        from package_layout import artifact_destination, version
        dest = artifact_destination(dict(record, path=str(relative)), version(review), FOLDERS)
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
    if edge.get('from_columns') or edge.get('to_columns'):
        values.append('Columns: ' + ', '.join(edge.get('from_columns', [])) + ' → ' + ', '.join(edge.get('to_columns', [])))
    status = edge.get('status', edge.get('implementation_status'))
    if edge['kind'] == 'relationship':
        values.append('Implementation: ' + (str(status) + ' (declared)' if status else 'not specified'))
    if edge.get('occurrence_id'):
        values.append(edge['occurrence_id'])
    if edge.get('conflicting_definitions'):
        values.append('Conflicting definitions')
    if edge.get('duplicate_occurrences', 0) > 1:
        values.append(str(edge['duplicate_occurrences']) + ' matching occurrences')
    return ' · '.join(values)


def _model_card_lines(model):
    def wrap(value, width=44):
        text = re.sub(r'\s+', ' ', str(value))
        return [text[i:i+width] for i in range(0, len(text), width)] or ['']
    rows = [(line, 'name') for line in wrap(model.get('name') or model['id'], 36)]
    if model.get('reference_only'):
        rows += [('Reference only · definition missing', 'note')]
    elif model.get('object_kind') == 'interface':
        rows += [('External interface · implementation unresolved', 'note')]
    elif model.get('object_kind', 'source' if model.get('layer') == 'bronze' else 'model') == 'source':
        rows += [('Source object', 'note')]
    rows += [(line, 'note') for line in wrap(model.get('grain') or 'Grain unresolved')]
    columns = model.get('columns', [])
    declared = [key for key in model.get('keys', []) if isinstance(key, str)]
    keys = [c for c in columns if c.get('key') or c['name'] in declared]
    missing = [{'name': key, 'key': 'Declared key', 'type': 'Type unverified'}
               for key in declared if not any(c['name'] == key for c in columns)]
    shown = keys + missing or columns[:4]
    for column in shown:
        key = column.get('key') or ('Declared key' if column['name'] in model.get('keys', []) else '')
        rows += [(line, 'key') for line in wrap(str(key) + ' ' + column['name'] + ' · ' + str(column.get('type') or 'unknown'))]
    if not keys and not missing:
        rows.append(('Keys not supplied', 'note'))
    other = len(columns) - (len(keys) if keys or missing else len(shown))
    if other > 0:
        rows.append((str(other) + ' other columns in dictionary', 'note'))
    return rows


def _diagram_layout(models, relationships):
    """Orthogonal routes stay in reserved gutters, never through another table."""
    layers = (*LAYERS, 'reference')
    grouped = {layer: [m for m in models if m['layer'] == layer] for layer in layers}
    active_layers = [layer for layer in layers if grouped[layer]]
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
    card_width = 440
    card_height = max(190, 48 + 22 * max((len(_model_card_lines(m)) for m in models), default=0),
                      48 + 16 * max((len(v) for v in incidents.values()), default=0))
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
            'bottom': top + max(len(grouped[layer]) for layer in layers) * (card_height + 48),
            'column_x': column_x, 'layers': active_layers}


def model_svg(models, relationships):
    """Connected table blocks plus a visible, complete relationship label ledger."""
    from portal_checks import model_inventory
    model_inventory(models, relationships, references=True)
    if not models:
        return ''
    layout = _diagram_layout(models, relationships)
    positions, width = layout['positions'], layout['width']
    card_width, card_height = layout['card_width'], layout['card_height']
    ledger, cursor = [], layout['bottom'] + 30
    for index, edge in enumerate(relationships):
        lines = textwrap.wrap(f"E{index + 1} · {edge['from']} → {edge['to']}", width=120, break_long_words=True)
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
        marker = ' marker-end="url(#arrow)"' if edge['kind'] == 'lineage' else ''
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"{dash}{marker}><title>{e(route["label"] + ": " + _edge_description(edge))}</title></path>')
        x, y = points[0]; goes_right = points[1][0] > x
        parts.append(f'<text x="{x + (5 if goes_right else -5):g}" y="{y - 5:g}" text-anchor="{"start" if goes_right else "end"}" font-family="sans-serif" font-size="9" fill="{color}">{route["label"]}</text>')
    for model in models:
        x, y = positions[model['id']]
        name, grain = str(model.get('name', model['id'])), str(model.get('grain', 'Grain unresolved'))
        interface = model.get('object_kind') == 'interface'
        fill, stroke, dash = ('#eef3ff', '#62549a', ' stroke-dasharray="6 4"') if interface else ('white', '#9aabba', '')
        parts.append(f'<g data-model-id="{e(model["id"])}"><title>{e(name)} — {e(grain)}</title><rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="10" fill="{fill}" stroke="{stroke}"{dash}/>')
        for j, (label, style) in enumerate(_model_card_lines(model)):
            parts.append(f'<text x="{x+14}" y="{y+28+j*22}" font-family="{"monospace" if style == "key" else "sans-serif"}" font-size="{18 if style == "name" else 15}" font-weight="{700 if style == "name" else 400}" fill="#18324a">{e(label)}</text>')
        parts.append('</g>')
    for y, lines, edge in ledger:
        for index, line in enumerate(lines):
            parts.append(f'<text x="34" y="{y+index*22}" font-family="sans-serif" font-size="12" font-weight="{"700" if index == 0 else "400"}" fill="#18324a">{e(line)}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def diagram_views(models, relationships, maximum=36):
    """Partition by domain/node and edge density, retaining cross-view accounting."""
    from portal_checks import model_inventory
    model_inventory(models, relationships, references=True)
    require(type(maximum) is int and maximum > 0, 'Diagram page size must be a positive integer')
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


def _dbt_runtime_summary(state):
    """Recompute the selected contract; never project raw probes or credentials."""
    answers = state.get('answers', {})
    if answers.get('framework') != 'dbt':
        return None
    selection = answers.get('dbt_runtime')
    if selection is None:
        return {'selected': False, 'next_action': 'Retain the existing project and choose an exact dbt distribution/version before native execution. Design and requested draft code can continue.',
                'observed_runtime': 'not_probed', 'native_validation': 'not_run'}
    from dbt_runtime import runtime_contract
    from dbt_compatibility import setup_guidance
    contract = runtime_contract(selection, warehouse=answers.get('warehouse'))
    return {'selected': True, 'selection': contract['selection'],
            'qualification': contract['qualification'], 'features': contract['features'],
            'setup': setup_guidance(selection), 'observed_runtime': 'not_probed',
            'native_validation': 'not_run',
            'next_action': 'Review the runtime and upgrade assessment, then request the selected native checks. Validation results remain in their independent evidence records.'}


def _summary(state):
    answers=state.get('answers', {})
    readiness=state.get('readiness', {})
    platform=readiness.get('platform', {})
    # Explicit projection: never embed absolute roots, full state, answers JSON or receipts.
    delivery = state.get('delivery', {})
    from delivery_assurance import pending_summary
    from run_control import public_summary
    return {'engagement_id':state.get('engagement_id','Unassigned'), 'revision':state.get('revision',0),
            'run_control': public_summary(state),
            'delivery_assurance': pending_summary(answers.get('migration_scope')),
            'context_sha256':context_fingerprint(state),
            'delivery':{key:delivery[key] for key in ('status','artifact_count','assurance','audience','deliverables','qualification') if key in delivery},
            'status':state.get('status','discovery'), 'source_fingerprint':source_fingerprint(state),
            'target':{k:answers.get(k) for k in ('framework','warehouse','semantic_target')},
            'dbt_runtime':_dbt_runtime_summary(state),
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
    data={'engagement':_summary(state),'audience':audience,'review':{},'files':[],
          'page_mode':'status','selected_categories':[],'file_count':0,
          'projection':{'selected_artifact_count':0,'excluded_artifact_count':0,
                        'qualification':'Status projection only. Registered artifact bytes are not read or embedded.'}}
    from source_roots import public_summary as roots_summary
    roots = roots_summary(state)
    if roots:
        data['input_roots'] = roots.get('roots', [])
    deployment = _deployment_presentation(state, audience)
    if deployment:
        data['deployment'] = deployment
    if review:
        validate_review(state, review)
        data['projection']['excluded_artifact_count'] = len(review.get('artifacts', []))
        data['review']=json.loads(json.dumps({k:review.get(k, [] if k not in ('title','description') else '') for k in ('title','description','models','relationships','domain_proposals','changes','decisions','validation','assets')}))
        if review.get('quality_checks'):
            data['review']['quality_checks'] = [dict(_quality_data(row), **{key:row[key]
                for key in ('context_sha256', 'evidence_artifact_id', 'sha256')}) for row in review['quality_checks']]
        if 'metadata' in review:
            data['review']['metadata'] = dict(review['metadata'])
        if 'omni' in review:data['review']['omni']=dict(review['omni'])
        if review.get('omni_warehouse_bindings'):data['review']['omni_warehouse_bindings']=copy_quality(review['omni_warehouse_bindings'])
        if 'handoff' in review:data['review']['handoff']=dict(review['handoff'])
        if audience == 'reviewer':
            data['review']['validation']=[{k:v.get(k) for k in ('id','label','scope','status','details','evidence_id')} for v in review.get('validation',[])]
        if audience == 'audit':
            data['review']={}
    if state.get('workflow') and audience != 'audit':
        from engagement_stages import public_view
        workflow = _workflow_presentation(public_view(state))
        data['workflow'] = workflow
        # A design-only status page is useful before implementation artifacts exist.
        if not review:
            data['review'].update({key:workflow.pop(key, []) for key in ('models', 'relationships', 'assets')})
        else:
            for key in ('models', 'relationships', 'assets'):
                workflow.pop(key, None)
        allowed_models = {m['id'] for m in data['review'].get('models', [])}
        from governance_delivery import project as governance_projection
        governance = governance_projection(state, allowed_models if review is not None else None)
        if governance is not None:
            workflow['governance'] = governance
        if review is not None:
            from delivery_plan import public_summary as delivery_plan_summary
            workflow['delivery_plan'] = delivery_plan_summary(state, allowed_models)
        if review is not None and 'design_readiness' in workflow:
            from design_readiness import summarize
            workflow['design_readiness'] = _readiness_presentation(summarize(state, allowed_models))
        if state['workflow'].get('migration_intents') or 'migration_intent' in workflow:
            from migration_intent import summary as intent_summary
            workflow['migration_intent'] = _intent_presentation(intent_summary(state, allowed_models))
        workflow['authoring_checks'] = [row for row in workflow.get('authoring_checks', [])
                                       if set(row['model_ids']) <= allowed_models]
        workflow['artifact_checks'] = [row for row in workflow.get('artifact_checks', [])
                                      if set(row['model_ids']) <= allowed_models]
        if review and state['workflow'].get('design'):
            from design_consistency import compare_review
            workflow['design_checks'] = _design_check_summary(compare_review(state['workflow']['design'], review))
        if state['workflow'].get('migration_review'):
            from migration_review import public_summary
            # Only an unscoped pre-design status page may show intake records.
            scope = allowed_models if review is not None or state['workflow'].get('design') else None
            summary = public_summary(state, scope)
            if summary is not None:
                data['migration_review'] = _migration_presentation(summary)
        if state['workflow'].get('domain_journey'):
            from domain_workflow import public_summary as domain_summary
            # An unfiltered status page can show unassigned future domains.
            # Every explicit review/package is bounded by its model inventory.
            summary = domain_summary(state, allowed_models if review is not None else None)
            if summary is not None:
                data['domain_journey'] = _domain_presentation(summary)
        if state['workflow'].get('legacy_alignment'):
            from legacy_alignment import public_summary as alignment_summary
            summary = alignment_summary(state, allowed_models if review is not None else None)
            if summary is not None:
                data['legacy_alignment'] = _legacy_alignment_presentation(summary)
        if state['workflow'].get('migration_planning'):
            from migration_planning import public_summary as planning_summary
            summary = planning_summary(state, allowed_models if review is not None else None)
            if summary is not None:
                data['migration_planning'] = summary
        if review is not None and review.get('partition'):
            # Full design binding was checked above. This explicitly declared
            # projection compares only included facts; boundary edges retain
            # their original definitions in domain_proposals and the index.
            scoped = copy_quality(state['workflow']['design'])
            scoped.pop('sha256', None)  # Derived subset; original binding was verified before projection.
            scoped['entities'] = [row for row in scoped['entities'] if row['id'] in allowed_models]
            scoped['relationships'] = [row for row in scoped['relationships'] if {row['from'], row['to']} <= allowed_models]
            scoped['decisions'] = [row for row in scoped['decisions'] if set(row['model_ids']) <= allowed_models]
            compared = {key: value for key, value in review.items() if key != 'design_binding'}
            workflow['design_checks'] = _design_check_summary(compare_review(scoped, compared))
            workflow['design_checks']['qualification'] += ' Scoped to included models and internal relationships; boundary records remain in the relationship ledger.'
            workflow['decisions'] = [row for row in workflow.get('decisions', []) if row.get('model_ids') and set(row['model_ids']) <= allowed_models]
            for key in ('effort', 'task_plan', 'review_assurance'):
                workflow.pop(key, None)
            data.pop('deployment', None)
    return data


def _migration_presentation(raw):
    """Display fields only: no retained paths, source SQL or review receipts."""
    def fields(value, names):
        return {key: json.loads(json.dumps(value[key])) for key in names if key in value}

    def counts(value, names):
        return {key: number for key, number in value.items() if key in names and type(number) is int and number >= 0}

    result = {'schema_version': 1, 'qualification': raw.get('qualification',
        'Supplied migration evidence; local consistency is not native validation or business acceptance.')}
    if 'business_rules' in raw:
        source = raw['business_rules']
        result['business_rules'] = {**fields(source, ('status', 'count', 'proposed', 'qualification')),
            'rows': [fields(row, ('id', 'name', 'statement', 'status', 'model_ids')) for row in source.get('rows', [])],
            'conflicts': [fields(row, ('model_id', 'key', 'rule_ids')) for row in source.get('conflicts', [])]}
    if 'portfolio' in raw:
        source = raw['portfolio']
        result['portfolio'] = {**fields(source, ('status', 'asset_count', 'covered_assets', 'qualification')),
            'counts': counts(source.get('counts', {}), ('total', 'proposed', 'needs_decision', 'stale')),
            'candidates': [fields(row, ('id', 'disposition', 'reason', 'asset_ids', 'model_ids', 'grain',
                                       'dimensions', 'measure_ids', 'rule_ids', 'required_checks'))
                           for row in source.get('candidates', [])],
            'coverage': [fields(row, ('asset_id', 'name', 'model_ids', 'disposition', 'candidate_id', 'reason', 'freshness'))
                         for row in source.get('coverage', [])]}
    if 'source_discovery' in raw:
        source = raw['source_discovery']
        result['source_discovery'] = {**fields(source, ('status', 'freshness', 'qualification')),
            'version': fields(source.get('version', {}), ('workflow', 'workflow_sha256', 'planner_sha256', 'adapter_component_sha256')),
            'coverage': {**fields(source.get('coverage', {}), ('known_file_denominator', 'repository_file_denominator',
                                                             'enumeration_complete', 'export_completeness')),
                         'counts': counts(source.get('coverage', {}).get('counts', {}), ('parsed', 'partial', 'unsupported', 'excluded', 'unreadable'))},
            'gaps': [fields(row, ('code',)) for row in source.get('gaps', [])]}
    if 'parity' in raw:
        source = raw['parity']
        result['parity'] = {**fields(source, ('status', 'stale', 'assurance', 'qualification')),
            'native_verified': False, 'acceptance_ready': False,
            'counts': counts(source.get('counts', {}), ('pass', 'fail', 'pending', 'unsupported')),
            'crosswalk': [{**fields(row, ('dashboard_label', 'source_label', 'model_ids', 'topic_ids', 'status', 'case_count', 'required')),
                           'issues': [fields(issue, ('code', 'status')) for issue in row.get('issues', [])]}
                          for row in source.get('crosswalk', [])]}
    result['summary_markdown'] = _migration_markdown(result)
    return result


def _domain_presentation(raw):
    """A scoped journey view; never expose receipts, private paths or authority."""
    def fields(value, names):
        return {key: json.loads(json.dumps(value[key])) for key in names if key in value}

    result = {'schema_version': 1, 'kind': 'domain_journey',
              **fields(raw, ('active_domain_id', 'needs_selection', 'next_action', 'qualification', 'candidates_sha256'))}
    result['domains'] = [fields(row, ('id', 'name', 'description', 'status', 'model_ids', 'asset_count',
                                      'shared_dependency_ids', 'design_status', 'implementation_status',
                                      'semantic_status', 'completion_kind', 'next_action'))
                         for row in raw.get('domains', [])]
    for projected, row in zip(result['domains'], raw.get('domains', [])):
        if row.get('scope_preview'):
            projected['scope_preview'] = fields(row['scope_preview'], ('models', 'columns', 'source_files', 'assets',
                                                                        'batching_recommended', 'qualification'))
    if raw.get('active_batch'):
        result['active_batch'] = fields(raw['active_batch'], ('batch_id', 'name', 'entity_ids', 'dependency_ids', 'status',
            'design_status', 'implementation_status', 'semantic_status', 'next_action', 'qualification'))
    result['counts'] = {key: count for key, count in raw.get('counts', {}).items()
                        if key in ('total', 'proposed', 'queued', 'active', 'paused', 'completed', 'stale')
                        and type(count) is int and count >= 0}
    return result


def _legacy_alignment_presentation(raw):
    """Only curated comparison fields; source documents and raw evidence stay private."""
    def fields(value, names):
        return {key: json.loads(json.dumps(value[key])) for key in names if key in value}

    def coverage(value):
        return {kind: {key: count for key, count in value.get(kind, {}).items()
                       if key in ('total', 'mapped', 'unmatched', 'unsupported', 'excluded') and type(count) is int and count >= 0}
                for kind in ('tables', 'columns', 'rules') if kind in value}

    def source(row):
        return fields(row, ('table_id', 'table_name', 'kind', 'field_id', 'label'))

    result = {'schema_version': 1, **fields(raw, ('status', 'qualification')), 'domains': []}
    for domain in raw.get('domains', []):
        item = fields(domain, ('domain_id', 'mode', 'comparison_requested', 'behavior', 'baseline_status',
                              'alignment_status', 'freshness', 'model_ids', 'comparison_sha256', 'omitted_details'))
        item['coverage'] = coverage(domain.get('coverage', {}))
        item['tables'] = [{**fields(row, ('id', 'name', 'model_ids')),
                           'completeness': fields(row.get('completeness', {}), ('columns', 'rules')),
                           'coverage': coverage(row.get('coverage', {}))} for row in domain.get('tables', [])]
        item['mappings'] = [{**fields(row, ('id', 'model_ids', 'relationship', 'disposition', 'status', 'behavior', 'basis',
                                           'rationale', 'review_status', 'evidence_labels')),
                             'legacy_sources': [source(value) for value in row.get('legacy_sources', [])],
                             'targets': [fields(value, ('model_id', 'kind', 'field')) for value in row.get('targets', [])]}
                            for row in domain.get('mappings', [])]
        item['unmatched'] = [source(row) for row in domain.get('unmatched', [])]
        result['domains'].append(item)
    result['rows'] = _legacy_alignment_rows(result)
    result['summary_csv'] = _legacy_alignment_csv(result)
    result['summary_markdown'] = _legacy_alignment_markdown(result)
    return result


def _legacy_alignment_rows(summary):
    """The UI and exports share explicit mappings and uncovered baseline items."""
    rows = []
    for domain in summary.get('domains', []):
        if not domain.get('comparison_requested'):
            continue
        seen, seen_tables = set(), set()
        def key(source):
            return (source.get('table_id'), source.get('kind'), source.get('field_id'))
        for mapping in domain.get('mappings', []):
            rows.append(dict(mapping, domain_id=domain['domain_id'], freshness=domain.get('freshness')))
            for source in mapping['legacy_sources']:
                seen.add(key(source)); seen_tables.add(source.get('table_id'))
        unmatched = [row for row in domain.get('unmatched', []) if key(row) not in seen]
        seen_tables.update(row.get('table_id') for row in unmatched)
        unmatched.extend({'table_id': row['id'], 'table_name': row['name'], 'kind': 'table', 'label': row['name']}
                         for row in domain.get('tables', []) if row['id'] not in seen_tables)
        for index, source in enumerate(unmatched):
            rows.append({'id': 'unmatched:' + str(index + 1), 'domain_id': domain['domain_id'],
                'freshness': domain.get('freshness'), 'legacy_sources': [source], 'targets': [], 'model_ids': [],
                'relationship': 'unmatched', 'status': 'unmatched', 'behavior': 'undecided',
                'review_status': 'proposed', 'basis': 'No explicit mapping supplied.',
                'rationale': 'Review this uncovered baseline item with the agent.', 'evidence_labels': []})
    return rows


def _alignment_source_text(row):
    return '; '.join((source.get('table_name') or source.get('table_id') or 'Unknown table') +
        (' · ' + (source.get('label') or source.get('field_id') or source.get('kind', 'item'))
         if source.get('kind') != 'table' else '') for source in row.get('legacy_sources', [])) or 'No source supplied'


def _alignment_target_text(row):
    return '; '.join(target.get('model_id', 'Unknown model') + ' · ' + target.get('kind', 'table') +
                    (': ' + target['field'] if target.get('field') else '') for target in row.get('targets', [])) or 'Unmapped'


def _legacy_alignment_csv(summary):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n', quoting=csv.QUOTE_ALL)
    writer.writerow(('domain_id', 'mapping_id', 'existing_sources', 'target_models', 'relationship', 'disposition', 'status',
                     'behavior', 'review_status', 'basis', 'rationale', 'evidence_labels', 'freshness'))
    for row in summary.get('rows', []):
        values = [row.get('domain_id'), row.get('id'), _alignment_source_text(row), _alignment_target_text(row),
                  *[row.get(key) for key in ('relationship', 'disposition', 'status', 'behavior', 'review_status', 'basis', 'rationale')],
                  '; '.join(row.get('evidence_labels', [])), row.get('freshness')]
        writer.writerow([_csv_cell(str(value) if value is not None else '') for value in values])
    return stream.getvalue()


def _legacy_alignment_markdown(summary):
    def value(item):
        return _markdown_cell('Not supplied' if item is None else item)
    lines = ['# Compare with existing tables', '', value(summary.get('qualification')), '',
             'All comparison rows permitted in this package are included below; screen filters do not reduce this export.',
             'Supplied baseline completeness and mapping coverage do not establish behavioral parity, native validation or approval.', '']
    for domain in summary.get('domains', []):
        if not domain.get('comparison_requested'): continue
        lines.extend(['## Domain: ' + value(domain['domain_id']), '',
            'Baseline: ' + value(domain.get('baseline_status')) + ' · Alignment: ' + value(domain.get('alignment_status')) +
            ' · Freshness: ' + value(domain.get('freshness')), ''])
        for kind, counts in domain.get('coverage', {}).items():
            lines.append(kind.capitalize() + ': ' + '; '.join(key + ' ' + str(counts.get(key, 'unknown'))
                         for key in ('total', 'mapped', 'unmatched', 'unsupported', 'excluded') if key in counts))
        if domain.get('omitted_details'): lines.append('Some baseline details are omitted from this permitted scope.')
        rows = [row for row in summary.get('rows', []) if row['domain_id'] == domain['domain_id']]
        if not rows: lines.append('No baseline comparison rows are available. Supply or refresh the requested baseline with the agent.')
        for row in rows:
            lines.extend(['', '### Mapping: ' + value(row['id']), 'Existing: ' + value(_alignment_source_text(row)),
                'Proposed: ' + value(_alignment_target_text(row))])
            for label, key in (('Relationship', 'relationship'), ('Disposition', 'disposition'), ('Mapping status', 'status'), ('Behavior', 'behavior'),
                               ('Human review', 'review_status'), ('Basis', 'basis'), ('Explanation', 'rationale')):
                lines.append(label + ': ' + value(row.get(key)))
            lines.append('Evidence categories: ' + value(', '.join(row.get('evidence_labels', [])) or 'None supplied'))
        lines.extend(['', '### Target model to existing tables', ''])
        for model_id in domain.get('model_ids', []):
            sources = [_alignment_source_text(row) for row in rows if any(t.get('model_id') == model_id for t in row['targets'])]
            lines.append(value(model_id) + ': ' + value(' | '.join(sources) if sources else 'No legacy association supplied.'))
        lines.append('')
    return '\n'.join(lines) + '\n'


def _migration_markdown(summary):
    """One complete, deterministic text summary for print and portable delivery."""
    def value(item):
        if item is None: return 'Not supplied'
        if isinstance(item, list): return ', '.join(value(part) for part in item) or 'None supplied'
        if type(item) is bool: return 'Yes' if item else 'No'
        return _markdown_cell(item)

    def detail(label, item):
        lines.append(label + ': ' + value(item))

    lines = ['# Migration review', '', value(summary.get('qualification')), '',
             'Recorded evidence only. Native verification, business acceptance and deployment authority remain separate.', '']
    for key, title in (('business_rules', 'Business rules and human decisions'), ('portfolio', 'Shared model proposals'),
                       ('source_discovery', 'Source discovery coverage'), ('parity', 'Source-to-target parity')):
        section = summary.get(key)
        lines.extend(['## ' + title, ''])
        if section is None:
            lines.extend(['Not supplied in this review scope.', '']); continue
        detail('Status', section.get('status'))
        if section.get('qualification'): detail('Qualification', section['qualification'])
        if key == 'business_rules':
            for row in section.get('rows', []):
                lines.append('')
                detail('Rule', row.get('name') or row.get('id')); detail('Rule ID', row.get('id'))
                detail('Statement', row.get('statement')); detail('Recorded decision', row.get('status'))
                detail('Models', row.get('model_ids', []))
            if not section.get('rows'): lines.append('No business rules are included in this review scope.')
            for row in section.get('conflicts', []):
                detail('Conflict', [row.get('model_id'), row.get('key'), *row.get('rule_ids', [])])
            lines.extend(['', 'To record a human decision, ask the agent to run guided_workflow review-business-rules with a human_business_rule_review document for this engagement. Imported wording remains proposed until reviewed; rule acceptance is not design approval.'])
        elif key == 'portfolio':
            detail('Included source assets', section.get('asset_count'))
            for row in section.get('candidates', []):
                lines.append(''); detail('Candidate', row.get('id')); detail('Proposal', row.get('disposition'))
                for label, field in (('Reason', 'reason'), ('Models', 'model_ids'), ('Source assets', 'asset_ids'),
                                     ('Grain', 'grain'), ('Dimensions', 'dimensions'), ('Measures', 'measure_ids'),
                                     ('Business rules', 'rule_ids'), ('Required checks', 'required_checks')):
                    detail(label, row.get(field))
            if not section.get('candidates'): lines.append('No shared model candidates are included in this review scope.')
            for row in section.get('coverage', []):
                lines.append(''); detail('Source asset', row.get('name') or row.get('asset_id'))
                for label, field in (('Disposition', 'disposition'), ('Candidate', 'candidate_id'), ('Models', 'model_ids'),
                                     ('Freshness', 'freshness'), ('Reason', 'reason')):
                    detail(label, row.get(field))
        elif key == 'source_discovery':
            detail('Freshness', section.get('freshness'))
            version = section.get('version', {})
            detail('Collector version', version.get('workflow') if isinstance(version, dict) else version)
            coverage = section.get('coverage', {})
            for name, count in sorted(coverage.get('counts', {}).items()): detail(name.replace('_', ' ').capitalize(), count)
            detail('Known file denominator', coverage.get('known_file_denominator'))
            detail('Repository file denominator', coverage.get('repository_file_denominator'))
            detail('Supplied repository enumeration complete', coverage.get('enumeration_complete'))
            detail('Source export completeness', coverage.get('export_completeness'))
            detail('Gaps', [row.get('code') for row in section.get('gaps', [])])
        else:
            detail('Stale evidence', section.get('stale'))
            for name, count in sorted(section.get('counts', {}).items()): detail(name.replace('_', ' ').capitalize(), count)
            detail('Assurance', section.get('assurance')); detail('Native verification established', False)
            detail('Business acceptance established', False)
            lines.append('Only selected comparisons determine parity status. Retained out-of-scope rows remain visible for context.')
            for row in section.get('crosswalk', []):
                lines.append(''); detail('Dashboard', row.get('dashboard_label')); detail('Source', row.get('source_label'))
                for label, field in (('Models', 'model_ids'), ('Topics', 'topic_ids'), ('Selected comparison', 'required'),
                                     ('Status', 'status'), ('Cases', 'case_count')):
                    detail(label, row.get(field))
                for issue in row.get('issues', []): detail('Issue', [issue.get('code'), issue.get('status')])
            if not section.get('crosswalk'): lines.append('No parity cases are included in this review scope.')
        lines.append('')
    return '\n'.join(lines) + '\n'


def _design_check_summary(report):
    return {'status': report['status'], 'finding_count': len(report['findings']),
            'unknown_count': len(report['unknowns']), 'qualification': report['qualification'],
            'findings': [{k: row[k] for k in ('code', 'status', 'scope', 'message', 'model_id') if k in row}
                         for row in report['findings'] + report['unknowns']]}


def _readiness_presentation(raw):
    """Keep separate scoped checks, never transport source paths or receipts."""
    def fields(value, names):
        return {key: json.loads(json.dumps(value[key])) for key in names if isinstance(value, dict) and key in value}

    def counts(value, names):
        return {key: value[key] for key in names if isinstance(value, dict) and type(value.get(key)) is int and value[key] >= 0}

    result = fields(raw, ('schema_version', 'qualification'))
    result['counts'] = counts(raw.get('counts'), ('objects', 'models', 'sources', 'interfaces', 'new_models', 'reused_models', 'changed_models', 'undetermined_models'))
    result['counts']['by_layer'] = counts(raw.get('counts', {}).get('by_layer'), LAYERS)
    for key in ('structural', 'coverage', 'evidence', 'independent_review', 'human_review', 'native_validation'):
        item = fields(raw.get(key), ('status', 'qualification'))
        if key == 'structural':
            item.update(counts(raw.get(key), ('findings', 'unknowns')))
        elif key == 'coverage':
            value = raw.get(key, {})
            item['counts'] = counts(value.get('counts'), ('sources', 'files', 'objects', 'consumers', 'assigned', 'excluded', 'unresolved', 'interfaces', 'findings'))
            item['findings'] = [fields(row, ('code', 'message', 'model_ids', 'domain_ids')) for row in value.get('findings', [])]
        elif key == 'evidence':
            item['counts'] = counts(raw.get(key, {}).get('counts'), ('observed_metadata', 'repository_declaration', 'user_assertion', 'proposal'))
        elif key == 'independent_review':
            item.update(counts(raw.get(key), ('reviewed_models', 'expected_objects')))
        result[key] = item
    return result


def _intent_presentation(raw):
    """Architecture intent and conformance are separate from readiness/approval."""
    def fields(value, names):
        return {key: json.loads(json.dumps(value[key])) for key in names if isinstance(value, dict) and key in value}
    result = fields(raw, ('schema_version', 'status', 'qualification', 'native_validation', 'business_acceptance'))
    result['domains'] = []
    for row in raw.get('domains', []):
        item = fields(row, ('domain_id', 'status', 'structural_objective', 'behavior', 'model_ids', 'objective_ids', 'gaps', 'review_authority'))
        for key in ('transitional_dependency_count', 'semantic_purpose_count'):
            if type(row.get(key)) is int and row[key] >= 0:
                item[key] = row[key]
        item['model_disposition_counts'] = {key: row['model_disposition_counts'][key]
            for key in ('create', 'reuse', 'extend', 'replace', 'undetermined')
            if type(row.get('model_disposition_counts', {}).get(key)) is int and row['model_disposition_counts'][key] >= 0}
        result['domains'].append(item)
    return result


def _workflow_presentation(raw):
    """Allowlisted review prose only; never transport full state or approval receipts."""
    def fields(value, names):
        return {key:json.loads(json.dumps(value[key])) for key in names if isinstance(value, dict) and key in value}
    result = fields(raw, ('schema_version', 'engagement_id', 'design_id', 'design_revision', 'design_sha256',
                          'current_stage', 'next_action', 'qualification', 'delivery_status', 'requested_stages'))
    if raw.get('delivery_plan'):
        plan = raw['delivery_plan']
        result['delivery_plan'] = fields(plan, ('status', 'deferred_stages', 'unplanned_code_stages', 'qualification'))
        result['delivery_plan']['stages'] = [fields(row, ('stage', 'plan_status', 'reason', 'task_count')) for row in plan.get('stages', [])]
    if raw.get('design_readiness'):
        result['design_readiness'] = _readiness_presentation(raw['design_readiness'])
    if raw.get('migration_intent'):
        result['migration_intent'] = _intent_presentation(raw['migration_intent'])
    if raw.get('review_assurance'):
        assurance = raw['review_assurance']
        projected = fields(assurance, ('schema_version', 'qualification'))
        for kind in ('coverage', 'reuse', 'reconciliation'):
            value = assurance.get(kind, {})
            item = fields(value, ('status', 'unit', 'qualification', 'omitted_detail_rows'))
            if kind == 'coverage':
                item.update(fields(value, ('requirements', 'targets', 'export_completeness', 'native_parity', 'orphan_requirements')))
                item['counts'] = fields(value.get('counts', {}), ('total', 'mapped', 'unresolved', 'unsupported', 'excluded_by_review', 'stale'))
                supplied = value.get('supplied_files', {})
                item['supplied_files'] = fields(supplied, ('expected', 'observed', 'missing', 'denominator_basis', 'unit'))
                item['supplied_files']['statuses'] = fields(supplied.get('statuses', {}), ('parsed', 'partial', 'unsupported'))
                item['groups'] = [fields(row, ('asset', 'domain', 'total', 'mapped', 'unresolved', 'unsupported', 'excluded_by_review', 'stale', 'model_ids'))
                                  for row in value.get('groups', [])]
                item['rows'] = [fields(row, ('id', 'asset', 'name', 'domain', 'model_ids', 'status', 'rationale'))
                                for row in value.get('rows', [])]
            elif kind == 'reuse':
                item.update(fields(value, ('stale', 'canonical_total', 'uninventoried_existing_ids', 'removed_existing_ids', 'native_compatibility', 'review_authority')))
                item['counts'] = fields(value.get('counts', {}), ('total', 'unassigned'))
                item['counts']['by_disposition'] = fields(value.get('counts', {}).get('by_disposition', {}),
                    ('reuse', 'extend', 'replace', 'defer', 'undetermined', 'out_of_scope'))
                item['rows'] = [fields(row, ('name', 'existing_id', 'owner_domain', 'disposition', 'model_ids', 'requirement_ids', 'compatibility', 'freshness', 'rationale'))
                                for row in value.get('rows', [])]
            else:
                for key in ('findings', 'unknowns'):
                    item[key] = [fields(row, ('code', 'message', 'model_ids')) for row in value.get(key, [])]
            projected[kind] = item
        result['review_assurance'] = projected
    result['stages'] = [fields(row, ('id', 'label', 'status', 'next_action')) for row in raw.get('stages', [])]
    if raw.get('task_plan'):
        result['task_plan'] = {
            'qualification': 'Proposed work only. Reuse retains the original run and its evidence limits.',
            'tasks': [fields(row, ('id', 'stage', 'entity_ids', 'action', 'reason', 'original_run_id', 'generation_mode'))
                      for row in raw['task_plan'].get('tasks', [])]}
    result['decisions'] = []
    result['authoring_checks'] = []
    result['artifact_checks'] = [fields(row, ('task_id', 'stage', 'model_ids', 'status', 'counts', 'qualification'))
                                 for row in raw.get('artifact_checks', [])]
    if raw.get('design_checks'):
        result['design_checks'] = _design_check_summary(raw['design_checks'])
    for row in raw.get('authoring_checks', []):
        item = fields(row, ('task_id', 'status', 'mode', 'counts', 'model_ids', 'unresolved_assumptions', 'qualification'))
        item['findings'] = [fields(f, ('code', 'status', 'model_id')) for f in row.get('findings', [])]
        result['authoring_checks'].append(item)
    for row in raw.get('decisions', []):
        item = fields(row, ('id', 'question', 'status', 'answer', 'recommendation', 'reviewer_role', 'model_ids',
                            'asset_ids', 'blocking_stages', 'rationale', 'evidence_summary'))
        item['options'] = [fields(option, ('id', 'label', 'consequences')) for option in row.get('options', [])]
        result['decisions'].append(item)
    if raw.get('effort'):
        keys = ('category', 'confidence', 'readiness', 'breadth', 'summary', 'rationale', 'assumptions',
                'prerequisites', 'dependencies', 'included_work', 'excluded_work', 'uncertainty', 'dimensions')
        result['effort'] = fields(raw['effort'], keys)
        result['effort']['work_packages'] = [fields(row, ('id', 'name', 'model_ids', *keys))
                                            for row in raw['effort'].get('work_packages', [])]
    # Used only for status pages without a separately supplied review contract.
    result['models'] = []
    for row in raw.get('models', raw.get('entities', [])):
        item = fields(row, ('id', 'name', 'layer', 'domain', 'grain', 'asset_ids', 'depends_on', 'mapping_status', 'disposition',
                            'object_kind', 'keys', 'history', 'security', 'description', 'display_label'))
        item['columns'] = [fields(column, ('name', 'type', 'key', 'description', 'nullable')) for column in row.get('columns', [])]
        result['models'].append(item)
    result['assets'] = [fields(row, ('id', 'name', 'kind', 'mapping_status')) for row in raw.get('assets', [])]
    result['relationships'] = [fields(row, ('from', 'to', 'kind', 'label', 'predicate', 'cardinality', 'role', 'status', 'evidence', 'from_columns', 'to_columns'))
                               for row in raw.get('relationships', [])]
    return result


def _trim_workflow_details(data):
    """A code-only subset must not retain unselected design narratives or decisions."""
    data.pop('migration_review', None)
    data.pop('domain_journey', None)
    data.pop('legacy_alignment', None)
    data.pop('migration_planning', None)
    for key in ('assets', 'models', 'relationships', 'domain_proposals', 'decisions', 'changes'):
        data.get('review', {}).pop(key, None)
    if data.get('workflow'):
        for key in ('decisions', 'effort', 'models', 'relationships', 'assets', 'task_plan', 'authoring_checks', 'design_checks', 'artifact_checks', 'review_assurance', 'design_readiness', 'migration_intent', 'governance'):
            data['workflow'].pop(key, None)


def _html(data):
    template=(ASSETS/'portal.html').read_text(encoding='utf-8')
    encoded=json.dumps(data,ensure_ascii=True,allow_nan=False,separators=(',', ':') if data.get('package_layout_version') == 2 else None).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    rendered = (template.replace('/*__PORTAL_CSS__*/',(ASSETS/'portal.css').read_text(encoding='utf-8'))
                .replace('/*__PORTAL_SVG_JS__*/',(ASSETS/'portal-svg.js').read_text(encoding='utf-8'))
                .replace('/*__PORTAL_JS__*/',(ASSETS/'portal.js').read_text(encoding='utf-8'))
                .replace('/*__PORTAL_DATA__*/',encoded))
    from portal_checks import validate_page
    validate_page(rendered, expected_data=data)
    return rendered


def _set_diagram_coverage(data):
    """Bind new output to its included graph; never relabel frozen legacy pages."""
    from portal_checks import diagram_coverage
    data['diagram_contract_version'] = 1
    data['diagram_coverage'] = diagram_coverage(data)


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


def _pipeline_semantics(review):
    """Use explicit warehouse IDs plus the selected, verified semantic inventory."""
    evidence = review.get('omni', {})
    if evidence.get('evidence_state') != 'selected':
        review.pop('omni_warehouse_bindings', None)
        return None
    bindings = review.get('omni_warehouse_bindings', [])
    if not bindings:
        return None
    inventory = evidence.get('views', {})
    known = {row['view_id'] for row in bindings}
    require(known <= set(inventory), 'Omni pipeline view is absent from pinned semantic evidence')
    topics = []
    for topic in evidence.get('topics', []):
        members = topic.get('scope', {}).get('views', [])
        # Only fully bound topic populations are drawn; never imply a partial
        # membership is complete or guess a physical binding from similar names.
        if members and set(members) <= known:
            topics.append({'id': topic['id'], 'name': topic.get('label') or topic['id'], 'view_ids': sorted(set(members))})
    return {'views': [{'id': row['view_id'], 'name': row['view_id'], 'warehouse_model_ids': row['model_ids']} for row in bindings], 'topics': topics}


def _review_diagrams(data, *, pipelines=False):
    from portal_checks import erd_inventory
    nodes, edges = erd_inventory(data['review'])
    if pipelines:
        from pipeline_diagrams import pipeline_views
        platform = data.get('engagement', {}).get('readiness', {}).get('platform')
        if isinstance(platform, dict):
            platform = copy_quality(platform)
            data['engagement']['readiness']['platform'] = platform
            for finding in (platform.get('findings') or []) + (platform.get('detected_sources') or []):
                if len(finding.get('paths', [])) > 20:
                    finding['paths_total'] = len(finding['paths'])
                    finding['paths'] = finding['paths'][:20]
            coverage = platform.get('coverage') or {}
            for key in ('gaps', 'exclusions'):
                if len(coverage.get(key, [])) > 100:
                    coverage[key + '_total'] = len(coverage[key])
                    coverage[key] = coverage[key][:100]
        semantic = _pipeline_semantics(data['review'])
        data['diagram_view_mode'] = 'pipelines'
        data['pipeline_semantic_status'] = ('Explicit candidate bindings shown; native validation remains separate.' if semantic else
            'Semantic views and topics are not drawn: selected evidence with explicit warehouse bindings is not available.')
        def views(rows, binding):
            pages = pipeline_views(rows, edges, semantic=binding)
            for index, page in enumerate(pages, 1):
                # The canonical review retains every relationship and proposal.
                # Per-output display records need routing identities and counts,
                # not repeated copies of every outside join and its evidence.
                page.pop('external_connections', None)
                page['join_relationship_count'] = len(page.pop('join_relationships', []))
                page['edges'] = [{key: edge[key] for key in ('id', 'from', 'to', 'kind', 'occurrence_count')} for edge in page['edges']]
                page['export_path'] = diagram_export_path(page, index, 2)
            return pages
        reduced = [{key: value for key, value in node.items() if key != 'columns'} for node in nodes]
        data['diagrams'] = views(nodes, semantic)
        reduced_by_id = {page['id']: page for page in views(reduced, semantic)}
        for page in data['diagrams']:
            page['without_dictionary_base64'] = reduced_by_id[page['id']]['base64']
        if semantic:
            data['warehouse_diagrams'] = views(nodes, None)
            warehouse_reduced = {page['id']: page for page in views(reduced, None)}
            for page in data['warehouse_diagrams']:
                page['without_dictionary_base64'] = warehouse_reduced[page['id']]['base64']

    else:
        data['diagrams'] = diagram_views(nodes, edges)


def diagram_export_path(page, index, layout_version):
    if layout_version == 2 and page.get('id'):
        label = page.get('target_model_id') or page.get('label') or 'additional-inputs'
        name = re.sub(r'[^A-Za-z0-9._-]+', '-', str(label)).strip('-.')[:100] or 'pipeline'
        suffix = _sha(str(page['id']).encode())[:8]
        return '03_Design_Documents/Pipelines/' + name + '-' + suffix + '.svg'
    return f'01_Model/ERD/model-{index:03d}.svg'


def render_engagement(state, output_path, review=None):
    """Render local status with no artifact payloads. May refresh an existing status page."""
    from source_roots import ensure_output
    if state.get('inputs', {}).get('source', {}).get('path'):
        ensure_output(state, output_path)
    source=state.get('inputs',{}).get('source',{}).get('path')
    if source:
        destination=_path(output_path); source_root=_path(source)
        require(destination != source_root and source_root not in destination.parents, 'Review output must stay outside the source repository')
    data=_presentation(state,review)
    _select_handoff(data, [])
    _select_quality_evidence(data, [])
    _select_metadata_evidence(data, [])
    _select_omni_evidence(data, [])
    if data['review'].get('models'):
        _review_diagrams(data, pipelines=bool(state.get('workflow', {}).get('design')))
    _set_diagram_coverage(data)
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


def _dictionary_rows(models):
    rows = []
    for model in models:
        for column in model.get('columns', []) or [{}]:
            values = (model['id'], model.get('name', model['id']), model['layer'], model.get('domain'),
                      model.get('grain'), column.get('name'), column.get('type'), column.get('key'),
                      column.get('description', 'Column definitions not supplied.' if not column else ''))
            rows.append(['' if value is None else str(value) for value in values])
    return rows


def _csv_cell(value):
    # Spreadsheet applications must not execute a model name or description.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r')) else value


def _markdown_cell(value):
    value = html.escape(str(value), quote=False).replace('\\', '\\\\')
    return re.sub(r'([`*_[\]()!|])', r'\\\1', value).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')


def generated_deliverables(data):
    """Portable projections of the selected review, never registered source edits."""
    from portal_checks import model_inventory
    review = data.get('review', {})
    models, relationships = review.get('models', []), review.get('relationships', [])
    model_inventory(models, relationships)
    if data.get('audience') == 'audit':
        return []
    selected, records = set(data.get('selected_categories', [])), []
    def add(identifier, path, category, description, body, model_ids=None):
        from package_layout import generated_path
        path = generated_path(path, data.get('package_layout_version', 1))
        require(len(body) <= MAX_ARTIFACT_BYTES, 'Generated deliverable exceeds size limit; partition explicitly')
        record = {'id': identifier, 'path': path, 'category': category, 'description': description,
                  'requires': [], 'origin': 'review_projection', 'sha256': _sha(body), 'size': len(body),
                  'base64': base64.b64encode(body).decode()}
        if model_ids is not None:
            record['diagram_model_ids'] = list(model_ids)
        records.append(record)
    if 'documentation' in selected and data.get('migration_review'):
        add('generated:migration-review', '01_Model/migration-review.md', 'documentation',
            'Scoped business rules, shared model proposals, source coverage and parity evidence.',
            _migration_markdown(data['migration_review']).encode())
    if {'documentation','dictionary'} <= selected and data.get('workflow', {}).get('governance'):
        from governance_delivery import files as governance_files
        for file in governance_files(data['workflow']['governance']):
            add('generated:governance:' + file['path'], file['path'], 'documentation',
                'Complete selected naming, requested scope and consumer-change review.', file['content'])
    if {'documentation', 'dictionary'} <= selected and data.get('migration_planning'):
        from migration_plan_exports import export_files
        for file in export_files(data['migration_planning']):
            add('generated:migration-planning:' + file['path'], file['path'], 'documentation',
                'Migration planning: ' + file['path'].rsplit('/', 1)[-1] + '. Templates only; no live tickets or deployment.',
                file['content'])
    if 'documentation' in selected and any(domain.get('comparison_requested') for domain in data.get('legacy_alignment', {}).get('domains', [])):
        add('generated:legacy-alignment-csv', '01_Model/legacy-table-alignment.csv', 'documentation',
            'All scoped existing-table mappings and unresolved baseline items; spreadsheet formulas are escaped.',
            _legacy_alignment_csv(data['legacy_alignment']).encode())
        add('generated:legacy-alignment-markdown', '01_Model/legacy-table-alignment.md', 'documentation',
            'Readable existing-table comparison, coverage and both mapping directions.',
            _legacy_alignment_markdown(data['legacy_alignment']).encode())
    def finish():
        from package_layout import section_guides
        for guide in section_guides(data, records):
            add(guide['id'], guide['path'], guide['category'], guide['description'], guide['body'])
        return records
    if not models:
        return finish()
    if 'diagrams' in selected:
        for index, page in enumerate(data.get('diagrams', []), 1):
            add(f'generated:erd:{index:03d}', diagram_export_path(page, index, data.get('package_layout_version', 1)), 'diagrams',
                f'Model view {index}; part of the complete included table inventory.',
                base64.b64decode(page['base64'], validate=True), page['model_ids'])
        source = {'schema_version': 1, 'kind': 'portable_model_source',
                  'qualification': MODEL_SOURCE_QUALIFICATION, 'models': models, 'relationships': relationships}
        if review.get('domain_proposals'):
            from portal_checks import erd_inventory
            source['domain_proposals'] = review['domain_proposals']
            source['relationship_ledger'] = erd_inventory(review)[1]
        add('generated:erd-source', '01_Model/ERD/model-source.json', 'diagrams',
            'Editable model source with every included table and declared connection, including cross-view connections.',
            (json.dumps(source, indent=None if data.get('package_layout_version') == 2 else 2, separators=(',', ':') if data.get('package_layout_version') == 2 else None, ensure_ascii=False, sort_keys=True) + '\n').encode())
    if 'dictionary' in selected:
        rows = _dictionary_rows(models)
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, lineterminator='\n', quoting=csv.QUOTE_ALL)
        writer.writerow(DICTIONARY_FIELDS)
        writer.writerows([_csv_cell(value) for value in row] for row in rows)
        add('generated:dictionary-csv', '01_Model/Dictionary/data-dictionary.csv', 'dictionary',
            'All supplied column definitions for the included table inventory; spreadsheet formulas are escaped.',
            stream.getvalue().encode())
        lines = ['# Data dictionary', '',
                 'Generated from the selected review inventory. Missing definitions remain unspecified; this is not native validation.', '',
                 '| ' + ' | '.join(DICTIONARY_FIELDS) + ' |', '| ' + ' | '.join(['---'] * len(DICTIONARY_FIELDS)) + ' |']
        if data.get('package_layout_version') == 2:
            lines = ['# Data dictionary', '', 'Open [data-dictionary.csv](data-dictionary.csv) for every supplied column, type, key and definition. The same columns are searchable in START_HERE.html.', '',
                     'Missing definitions remain unspecified; this is not native validation.', '',
                     '| Table | Layer | Supplied columns |', '| --- | --- | --- |']
            lines.extend('| ' + _markdown_cell(model.get('name') or model['id']) + ' | ' + _markdown_cell(model['layer']) + ' | ' + str(len(model.get('columns', []))) + ' |' for model in models)
        else:
            lines.extend('| ' + ' | '.join(_markdown_cell(value) for value in row) + ' |' for row in rows)
        add('generated:dictionary-markdown', '01_Model/Dictionary/data-dictionary.md', 'dictionary',
            ('Table index linking the complete column CSV.' if data.get('package_layout_version') == 2 else 'Readable dictionary with the same table and column inventory as the CSV.'), ('\n'.join(lines) + '\n').encode())
    return finish()


def validate_generated_deliverables(data):
    """Check generated inventory, selected scope and bytes; SVG layout may differ."""
    from portal_checks import svg_model_coverage
    require(type(data.get('package_layout_version')) is int and data['package_layout_version'] in (1, 2),
            'Unsupported portable package layout version')
    actual = data.get('generated_deliverables')
    require(isinstance(actual, list), 'Generated deliverables must be a list')
    expected = generated_deliverables(data)
    require(len(actual) == len(expected), 'Generated deliverable inventory differs from selected review')
    by_path = {record['path']: record for record in expected}
    identifiers = {record['id'] for record in data.get('files', [])}
    paths = {record['path'].casefold() for record in data.get('files', [])}
    decoded = {}
    for record in actual:
        require(isinstance(record, dict), 'Generated deliverable must be an object')
        path, identifier = record.get('path'), record.get('id')
        require(isinstance(path, str) and path in by_path and path.casefold() not in paths,
                'Generated deliverable path is unexpected or collides with a registered file')
        wanted = by_path[path]
        require(identifier == wanted['id'] and identifier not in identifiers,
                'Generated deliverable ID is unexpected or collides with a registered artifact')
        require(all(record.get(key) == wanted.get(key) for key in ('category', 'requires', 'origin', 'diagram_model_ids')),
                'Generated deliverable category or model scope differs from selected review')
        paths.add(path.casefold()); identifiers.add(identifier)
        try:
            body = base64.b64decode(record.get('base64', ''), validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Generated deliverable has invalid base64') from error
        require(len(body) <= MAX_ARTIFACT_BYTES and type(record.get('size')) is int and len(body) == record['size']
                and _sha(body) == record.get('sha256'), 'Generated deliverable bytes differ: ' + path)
        expected_body = base64.b64decode(wanted['base64'])
        if path.endswith('.svg'):
            svg_model_coverage(body, record['diagram_model_ids'])
        elif path.endswith('.json'):
            require(json.loads(body) == json.loads(expected_body), 'Editable model source differs from selected review')
        elif path.endswith('.csv'):
            require(list(csv.reader(io.StringIO(body.decode()))) == list(csv.reader(io.StringIO(expected_body.decode()))),
                    'Dictionary inventory differs from selected review')
        else:
            require(body == expected_body, 'Readable dictionary differs from selected review')
        decoded[path] = body
    require(len(paths) <= MAX_ARTIFACTS, 'Package file count limit exceeded; split by domain')
    return decoded


def package_readme(data):
    """A compact index to one Start Here page and the selected portable files."""
    engagement = data.get('engagement', {})
    registered, generated = data.get('files', []), data.get('generated_deliverables', [])
    target = engagement.get('target', {})
    checkpoint = data.get('checkpoint')
    if data.get('package_layout_version') == 2:
        from package_layout import SECTIONS
        lines = ['# Model review handoff', '', 'Open [START_HERE.html](START_HERE.html). Choose a gold table to trace its pipeline, then inspect its columns and code.', '',
                 'Status: ' + ('Incomplete checkpoint; outstanding work remains.' if checkpoint else 'Candidate delivery; native validation and approval remain separate.') , '',
                 '| Folder | What to review |', '| --- | --- |']
        for folder, title, description in SECTIONS.values():
            link = folder + '/README.md'
            if any(row['path'] == link for row in generated):
                lines.append('| [' + title + '](' + link + ') | ' + description + ' |')
        lines += ['', 'Original repositories, previous drafts and run history are outside this handoff. Registered artifacts keep their original bytes.',
                  'Missing code or context is stated in its folder. A folder or diagram is not proof of completed implementation.', '']
        return ('\n'.join(lines)).encode()
    lines = ['# Checkpoint package' if checkpoint else '# Delivery package', '', 'Open [START_HERE.html](START_HERE.html) for the guided review.', '',
             'Audience: ' + _markdown_cell(data.get('audience', 'unresolved')) + '.',
             'Target: ' + _markdown_cell(target.get('framework') or 'unresolved') + ' / ' + _markdown_cell(target.get('warehouse') or 'unresolved') + '.',
             'Selected categories: ' + ', '.join(_markdown_cell(value) for value in sorted(data.get('selected_categories', []))) + '.',
             f'Registered files: {len(registered)}. Generated review deliverables: {len(generated)}.', '',
             '## Readiness', '',
             'Candidate review only. File generation and package integrity do not establish native validation, business acceptance or deployment authority.',
             'Use the selected validation evidence and guided review for reported checks, unresolved decisions and the next action.', '',
             '## Selected files', '']
    if checkpoint:
        lines[4:4] = ['Work is incomplete. This checkpoint preserves available outputs; it is not a final delivery.',
                      'Missing selected categories: ' + (', '.join(checkpoint['missing_categories']) or 'None; task and validation status still require review.') + '.',
                      'Resume the same engagement and repair only the outstanding work.', '']
    if data.get('migration_planning_omitted'):
        lines.extend([data['migration_planning_omitted'], ''])
    if any(row['path'].startswith('05_Migration/') for row in generated):
        lines.extend(['Open the **Migration plan** tab in START_HERE.html. In **05_Migration/**, start with '
                      '**inventory.xlsx**, then **migration-plan.docx**, then **tickets.md** and the selected '
                      'import file. Google selections contain pending content for native creation instead. '
                      'Templates and imports have not created live tickets.', ''])
    for record in sorted(registered + generated, key=lambda row: row['path']):
        origin = 'generated review projection' if record.get('origin') == 'review_projection' else 'registered artifact; original bytes'
        lines.append(f"- [{_markdown_cell(record['path'])}]({quote(record['path'], safe='/')}) — {record['category']}; {origin}.")
    runtime = engagement.get('dbt_runtime')
    if runtime:
        lines.extend(['', '## dbt runtime', '', runtime['next_action']])
        if runtime.get('selected'):
            selected = runtime['selection']
            lines.extend(['', 'Selected: ' + selected['distribution'] + ' ' + selected['version'] + '; requested analysis: ' + selected['analysis_mode'] + '.',
                          'Selection is not an installed-runtime observation or a successful native check.', '',
                          'Review-only setup (not installation or execution approval):', '', '```text',
                          *runtime['setup']['commands'], '```', '', *['- ' + item for item in runtime['setup']['prerequisites']]])
    if any(record['category'] == 'diagrams' for record in generated):
        lines.extend(['', 'ERD pages collectively cover the included tables. The editable model source retains all declared connections, including those crossing pages.'])
    if any(record['category'] == 'dictionary' for record in generated):
        lines.extend(['', 'Dictionary files contain supplied definitions only.'])
    return ('\n'.join(lines) + '\n').encode()


def package_file_inventory(data, files):
    roles = {'START_HERE.html': {'role': 'entrypoint', 'embedded': False},
             'README.md': {'role': 'index', 'embedded': False}}
    for key, role in (('files', 'registered_artifact'), ('generated_deliverables', 'generated_deliverable')):
        for record in data.get(key, []):
            require(record['path'].casefold() not in {path.casefold() for path in roles},
                    'Root README.md, package entrypoint or another deliverable collides with a selected file')
            roles[record['path']] = {'role': role, 'embedded': True, 'category': record['category']}
    require(set(files) == set(roles), 'Package inventory differs from its registered and generated deliverables')
    return [dict(path=path, sha256=_sha(body), bytes=len(body), **roles[path]) for path, body in sorted(files.items())]


def package_delivery(state, review, artifact_root, output_path, audience='reviewer', include=None, *, checkpoint=False):
    validate_review(state,review)
    include=resolve_selection(state,audience,include)
    from source_roots import ensure_output
    if state.get('inputs', {}).get('source', {}).get('path'):
        ensure_output(state, output_path)
    source=state.get('inputs',{}).get('source',{}).get('path')
    if source:
        destination=_path(output_path); source_root=_path(source)
        require(destination != source_root and source_root not in destination.parents, 'Package output must stay outside the source repository')
    selected=select_artifacts(review,artifact_root,audience,include)
    data=_presentation(state,review,audience)
    from package_layout import version
    data.update(page_mode='package', package_layout_version=version(review), selected_categories=sorted(set(include)), file_count=len(selected))
    data['projection']={'selected_artifact_count':len(selected),
                        'excluded_artifact_count':len(review.get('artifacts',[]))-len(selected),
                        'qualification':'Only selected audience-permitted artifact bytes are embedded. Excluded artifacts remain outside this package.'}
    if data['package_layout_version'] == 2:
        from package_layout import SECTIONS
        data['layout_sections'] = [dict(id=key, folder=value[0], title=value[1], description=value[2]) for key, value in SECTIONS.items()]
    _select_handoff(data, selected)
    _select_deployment_evidence(data, selected)
    _select_quality_evidence(data, selected)
    _select_metadata_evidence(data, selected)
    _select_omni_evidence(data, selected, state=state, review=review, root=artifact_root)
    # Planning documents are an indivisible domain export and contain column
    # metadata. Do not retain their nested payload or binaries after exclusion.
    if data.get('migration_planning') and not {'documentation', 'dictionary'} <= set(include):
        data.pop('migration_planning')
        data['migration_planning_omitted'] = ('Migration planning files were omitted: include both documentation '
            'and dictionary to export their complete mapping and column inventory.')
    if not {'documentation','dictionary'} <= set(include):
        data.get('workflow',{}).pop('governance',None)
    # Data-heavy views must also obey deliverable selection, not just file omission.
    if not set(include)&{'documentation','dictionary','diagrams'}:
        _trim_workflow_details(data)
    elif 'dictionary' not in include:
        for model in data['review'].get('models',[]):
            model.pop('columns',None)
    if 'validation' not in include:
        data['review'].pop('validation',None)
        data.get('workflow', {}).pop('authoring_checks', None)
        data.get('workflow', {}).pop('artifact_checks', None)
    if 'diagrams' in include and data['review'].get('models'):
        _review_diagrams(data, pipelines=data.get('package_layout_version') == 2)
    files={a['destination']:a['content'] for a in selected}
    for artifact in selected:
        data['files'].append({'id':artifact['id'],'path':artifact['destination'],'category':artifact['category'],
                              'description':artifact.get('description',''),'requires':artifact.get('requires',[]),
                              'sha256':artifact['sha256'],'size':len(artifact['content']),
                              'base64':base64.b64encode(artifact['content']).decode()})
        if 'diagram_model_ids' in artifact:
            data['files'][-1]['diagram_model_ids'] = sorted(artifact['diagram_model_ids'])
    _set_diagram_coverage(data)
    data['generated_deliverables'] = generated_deliverables(data)
    require(checkpoint or selected or data['generated_deliverables'], 'No artifacts or model deliverables match this audience and selection')
    generated = validate_generated_deliverables(data)
    require(not ({path.casefold() for path in files} & {path.casefold() for path in generated}),
            'Generated deliverable path collides with a registered artifact')
    files.update(generated)
    if checkpoint:
        available = {a['category'] for a in selected if a['content'].strip()} | {
            a['category'] for a in data['generated_deliverables'] if a['size'] > 0}
        data['checkpoint'] = {'status': 'incomplete', 'requested_categories': sorted(include),
                              'missing_categories': sorted(set(include) - available),
                              'qualification': 'Checkpoint only. Retained files may be partial, provisional or unchecked; resume the same engagement.'}
    require('readme.md' not in {path.casefold() for path in files}, 'Root README.md collides with a selected file')
    files['README.md'] = package_readme(data)
    from delivery_preflight import completion
    data['completion'] = completion(state, checkpoint)
    from portable_site import should_partition, package as partitioned_package
    if should_partition(data):
        return partitioned_package(state, review, selected, data, files, output_path, checkpoint)
    disclosure = _check_share_policy(state, review, selected, data, audience)
    files['START_HERE.html']=_html(data).encode('utf-8')
    from portal_checks import validate_page
    validate_page(files['START_HERE.html'], expected_files={a['destination']:a['content'] for a in selected})
    scans = {name: _check_disclosure_bytes(body, name) for name, body in files.items()}
    manifest={'schema_version':1,'kind':'portable_delivery_integrity','engagement_id':state['engagement_id'],
              'package_layout_version':data['package_layout_version'],
              'export_origin': 'agent_packager',
              'disclosure_scans': scans,
              'migration_scope': state.get('answers', {}).get('migration_scope'),
              'acceptance_ready': False,
              'deployment_authorized': False,
              'disclosure_policy_status': disclosure,
              'source_fingerprint':source_fingerprint(state),'context_sha256':context_fingerprint(state),
              'target':review['target'],'audience':audience,
              'deliverables':sorted(include),'authority':'File integrity only; not execution, business approval or deployment.',
              'files':package_file_inventory(data, files)}
    if checkpoint:
        manifest.update(delivery_kind='checkpoint', checkpoint=data['checkpoint'])
    files['DELIVERY_MANIFEST.json']=json.dumps(manifest,indent=2,sort_keys=True).encode()+b'\n'
    require(sum(map(len,files.values())) <= MAX_PACKAGE_BYTES*3, 'Rendered package exceeds size limit')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info,body)
    payload = stream.getvalue()
    _check_disclosure_bytes(payload, 'delivery.zip')
    _atomic_write(output_path,payload)
    return manifest


def verify_delivery(path):
    """Verify a relocated ZIP in memory. Does not trust paths or extract archives."""
    coverage = {'status':'unverified_legacy',
                'qualification':'This frozen package has no checked diagram coverage contract; integrity does not establish coverage.'}
    with zipfile.ZipFile(_path(path)) as archive:
        infos=archive.infolist()
        require(len(infos) <= MAX_ARTIFACTS+3, 'Too many package entries')
        require(sum(i.file_size for i in infos) <= MAX_PACKAGE_BYTES*3, 'Package expands beyond limit')
        names=[i.filename for i in infos]
        require(len(set(n.casefold() for n in names)) == len(names), 'Duplicate package entry')
        for info in infos:
            _relative(info.filename)
            require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), 'Unexpected archive entry')
        require('DELIVERY_MANIFEST.json' in names, 'Delivery manifest missing')
        manifest=json.loads(archive.read('DELIVERY_MANIFEST.json'))
        if manifest.get('presentation_contract') == 'partitioned_v1':
            from portable_site import verify
            return verify(archive, manifest)
        require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'portable_delivery_integrity', 'Unknown manifest format')
        context = manifest.get('context_sha256')
        require('package_layout_version' not in manifest or context is not None,
                'Portable package layout requires its workflow context')
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
            if 'checkpoint' in manifest or 'checkpoint' in embedded:
                require(manifest.get('delivery_kind') == 'checkpoint'
                        and manifest.get('checkpoint') == embedded.get('checkpoint')
                        and embedded['checkpoint'].get('status') == 'incomplete',
                        'Checkpoint label differs from the Start Here page')
        elif 'START_HERE.html' in names:
            match = re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>',
                              archive.read('START_HERE.html').decode('utf-8'), re.S)
            if match:
                legacy_data = json.loads(match.group(1))
                require('package_layout_version' not in legacy_data, 'Portable package layout requires its workflow context')
                require(not legacy_data.get('review', {}).get('metadata'),
                        'Metadata review requires a context-bound delivery manifest')
        declared=manifest.get('files',[])
        require(len({f['path'] for f in declared})==len(declared), 'Duplicate manifest path')
        require(set(names) == {'DELIVERY_MANIFEST.json'} | {f['path'] for f in declared}, 'Package inventory differs from manifest')
        for item in declared:
            body=archive.read(item['path'])
            require(len(body)==item['bytes'] and _sha(body)==item['sha256'], 'Package bytes differ: '+item['path'])
        if context is not None:
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
            if embedded.get('review',{}).get('omni'):
                ref=embedded['review']['omni'];evidence=[]
                for item in embedded.get('files',[]):
                    if item.get('id')!=ref.get('artifact_id'):continue
                    require(item.get('path') in names,'Omni artifact is absent from package')
                    body=archive.read(item['path'])
                    require(base64.b64decode(item.get('base64',''),validate=True)==body and item.get('sha256')==_sha(body),
                            'Embedded Omni artifact differs from package bytes')
                    evidence.append({'id':item['id'],'sha256':_sha(body),'content':body})
                before=json.dumps(ref,sort_keys=True)
                _select_omni_evidence(embedded,evidence)
                # Frozen pages predating the explicit page-mode contract did not
                # project the curated view inventory. Preserve that exact legacy
                # shape, while comparing any supplied/new view inventory in full.
                if 'page_mode' not in embedded and 'views' not in ref:
                    embedded['review']['omni'].pop('views', None)
                require(json.dumps(embedded['review']['omni'],sort_keys=True)==before,
                        'Omni evidence is absent or differs from the package summary')
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
            # Keep the established evidence gates and their actionable diagnostics
            # first, then check every displayed payload against the archive.
            _validate_markdown_links([{'id':item['path'],'destination':item['path'],'path':item['path'],
                                       'content':archive.read(item['path'])} for item in declared])
            from portal_checks import validate_page
            if 'package_layout_version' in manifest or 'package_layout_version' in embedded:
                require(type(manifest.get('package_layout_version')) is int and manifest['package_layout_version'] in (1, 2)
                        and embedded.get('package_layout_version') == manifest['package_layout_version'], 'Package layout version differs from its Start Here page')
                generated = validate_generated_deliverables(embedded)
                require(all(path in names and archive.read(path) == body for path, body in generated.items()),
                        'Generated delivery inventory differs from selected archive bytes')
                expected_inventory = package_file_inventory(embedded, {row['path']: archive.read(row['path']) for row in declared})
                require(sorted(declared, key=lambda row: row['path']) == expected_inventory,
                        'Manifest file roles differ from the selected package inventory')
                registered_paths = {item['path'] for item in embedded.get('files', [])}
            else:
                registered_paths = {item['path'] for item in declared if item['path'] != 'START_HERE.html'}
            page_check = validate_page(archive.read('START_HERE.html'),
                          expected_files={path:archive.read(path) for path in registered_paths},
                          require_current=embedded.get('page_mode') is not None)
            coverage = page_check['diagram_coverage']
    return {'status':'integrity_verified','files':len(declared),'context_sha256':context,
            'diagram_coverage':coverage,
            'authority':'Integrity only; does not verify frozen benchmark authority or target execution.'}


def check_page(path, javascript=False):
    """Explicit self-check of saved HTML or a relocated portable ZIP.

    Node is optional and is invoked only with javascript=True. No target code is
    executed; the normal Python render/package workflow has no Node dependency.
    """
    from portal_checks import check_javascript, validate_page
    path = _path(path)
    if path.suffix.lower() == '.zip':
        verify_delivery(path)
        with zipfile.ZipFile(path) as archive:
            page = archive.read('START_HERE.html')
            manifest = json.loads(archive.read('DELIVERY_MANIFEST.json'))
            if manifest.get('presentation_contract') == 'partitioned_v1':
                from portable_site import check_page as check_partition
                result = check_partition(page)
                if javascript:
                    # Each of the two maintained programs is checked once. Every
                    # emitted page is structurally checked by verify_delivery.
                    representatives = [page]
                    detail = next((r for r in manifest['files'] if r['role'] == 'review_page'), None)
                    if detail:
                        representatives.append(archive.read(detail['path']))
                    result['javascript'] = [check_javascript(body) for body in representatives]
                return result
    else:
        require(path.stat().st_size <= MAX_PACKAGE_BYTES*3, 'Page exceeds size limit')
        page = path.read_bytes()
    result = validate_page(page)
    if javascript:
        result['javascript'] = check_javascript(page)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('render','package'):
        p=sub.add_parser(name); p.add_argument('--state',required=True); p.add_argument('--review'); p.add_argument('--output',required=True)
        if name=='package':
            p.add_argument('--artifacts',required=True); p.add_argument('--audience',choices=sorted(AUDIENCES),default='reviewer')
            p.add_argument('--include',help='Comma-separated deliverable categories')
    p=sub.add_parser('verify'); p.add_argument('package')
    p=sub.add_parser('check-page',help='Check a generated page or ZIP; JavaScript checks are opt-in')
    p.add_argument('page'); p.add_argument('--javascript',action='store_true',help='Also check every executable inline script with Node')
    args=parser.parse_args(argv)
    try:
        if args.command=='verify': result=verify_delivery(args.package)
        elif args.command=='check-page': result=check_page(args.page,args.javascript)
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
