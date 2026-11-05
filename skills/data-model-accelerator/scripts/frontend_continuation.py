"""Optional DMA to Omni Artifact Accelerator continuation; no native execution."""
import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from ae_common import require, safe_relative

PROTOCOL = 1
PROTOCOLS = (1, 2)
SURFACES = ('dashboard', 'app')
TASK_MODES = {'net-new', 'migration', 'enhancement'}
EVIDENCE_PURPOSES = {'native_validation', 'topic_readback'}
COMMON_SKILLS = ('omni-artifact-accelerator', 'omni-backend-handoff', 'omni-artifact-translator',
                 'omni-bi-engineer', 'omni-data-analyst', 'omni-qa-analyst')
CHOICES = {'continue_now', 'prepare_handoff', 'not_now'}
QUALIFICATION = ('Optional frontend follow-up. Recorded choices, files and host observations '
                 'do not establish live Topic availability, dashboard parity or publication.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def scoped_context(state, domain_id):
    """Stable domain design closure; retain global pins when source coverage is unknown."""
    from engagement_stages import closure
    wf = state.get('workflow', {})
    design = wf.get('design') or {}
    domains = (wf.get('domain_journey') or {}).get('domains', [])
    domain = next((d for d in domains if d['id'] == domain_id), None)
    require(domain_id is None or domain is not None, 'Unknown domain; select a registered domain, including completed domains')
    entities = design.get('entities', [])
    labels = {domain['id'].casefold(), domain['name'].casefold()} if domain else set()
    chosen = [e['id'] for e in entities if not domain or e['domain'].casefold() in labels]
    graph = {e['id']: e.get('depends_on', []) for e in entities}
    selected = set(closure(graph, chosen)) if chosen else set()
    # Joins can carry security or population dependencies outside depends_on.
    while True:
        neighbors = {r['to'] for r in design.get('relationships', []) if r['from'] in selected}
        expanded = set(closure(graph, sorted(selected | neighbors))) if selected | neighbors else set()
        if expanded == selected:
            break
        selected = expanded
    rows = [e for e in entities if e['id'] in selected]
    assets = {a for e in rows for a in e.get('asset_ids', [])} | set((domain or {}).get('asset_ids', []))
    existing = {e['reuse']['existing_id'] for e in rows if e.get('reuse')}
    decisions = [d for d in design.get('decisions', []) if not d.get('model_ids') or set(d['model_ids']) & selected]
    from naming_context import packet_contract
    return copy.deepcopy({
        'domain': domain, 'entity_ids': sorted(selected),
        'design': {'id': design.get('id'), 'entities': rows,
            'relationships': [r for r in design.get('relationships', []) if r['from'] in selected],
            'assets': [a for a in design.get('assets', []) if a['id'] in assets], 'decisions': decisions,
            'responses': [r for r in wf.get('responses', []) if r.get('decision_id') in {d['id'] for d in decisions}],
            'existing_models': [r for r in design.get('existing_models', []) if r['id'] in existing]},
        'inputs': {k: digest(v) for k, v in state.get('inputs', {}).items()},
        'source_coverage': 'conservative_global_input_pins',
        'naming': packet_contract(state, sorted(selected)) if selected else None})


def _strings(value):
    require(type(value) is list and len(value) <= 20000 and
            all(type(v) is str and 0 < len(v) <= 500 and v.strip() == v for v in value)
            and len(set(value)) == len(value), 'Supply distinct bounded identifiers')


def _mode(state, request):
    includes_dashboard = 'dashboard' in request.get('target_surfaces', ['dashboard'])
    return 'integrated' if includes_dashboard and state['answers'].get('migration_scope') == 'full_dashboard' else 'independent'


def choose(state, document):
    from engagement_stages import fields, text
    version = document.get('schema_version') if type(document) is dict else None
    require(type(version) is int and version in PROTOCOLS, 'Unsupported continuation choice')
    common = {'schema_version', 'domain_id', 'choice', 'request_reference', 'topic_names'}
    optional = {'semantic_review', 'context_files', 'destination'}
    if version == 2:
        fields(document, common | {'target_surfaces', 'task_mode'}, optional | {'dashboard_ids', 'app_ids'})
        document = copy.deepcopy(document)
        for key in ('dashboard_ids', 'app_ids'):
            document.setdefault(key, [])
            _strings(document[key])
        _strings(document['target_surfaces'])
        require(document['target_surfaces'] and set(document['target_surfaces']) <= set(SURFACES), 'Select app, dashboard or both')
        document['target_surfaces'] = [s for s in SURFACES if s in document['target_surfaces']]
        require(type(document['task_mode']) is str and document['task_mode'] in TASK_MODES, 'Unknown frontend task mode')
    else:
        fields(document, common | {'dashboard_ids'}, optional)
    require(state['answers'].get('semantic_target') == 'omni', 'Frontend continuation requires the selected Omni target')
    require(document['choice'] in CHOICES, 'Choose continue_now, prepare_handoff or not_now')
    text(document['request_reference'])
    _strings(document['dashboard_ids']); _strings(document['topic_names'])
    snapshot = scoped_context(state, document['domain_id'])
    if document.get('semantic_review') is not None:
        safe_relative(document['semantic_review'])
    context = document.get('context_files', [])
    require(type(context) is list and len(context) <= 64, 'At most 64 selected context files')
    purposes = {'source_inventory', 'independent_source_listing', 'requirements', 'decisions', 'expectations',
                'mapping', 'topic_readback'} | ({'native_validation'} if version == 2 else set())
    for row in context:
        fields(row, {'path', 'purpose'}, {'sha256'} if version == 2 else ()); safe_relative(row['path'])
        require(row['purpose'] in purposes, 'Unsupported context purpose')
        require(Path(row['path']).suffix == '.json', 'Context must be selected nonsecret JSON, not source code')
        if version == 2 and ('sha256' in row or row['purpose'] in EVIDENCE_PURPOSES):
            require(type(row.get('sha256')) is str and re.fullmatch(r'[a-f0-9]{64}', row['sha256']), 'Pin the selected evidence bytes')
    if version == 2:
        require(len({r['path'] for r in context}) == len(context), 'Duplicate context file')
        require(all(sum(r['purpose'] == p for r in context) <= 1 for p in EVIDENCE_PURPOSES), 'Select one current file per evidence purpose')
    if document.get('destination') is not None:
        fields(document['destination'], {'base_url', 'model_id', 'branch_id'}, {'model_version_id'} if version == 2 else ())
        from urllib.parse import urlsplit
        parsed = urlsplit(document['destination']['base_url'])
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment and parsed.path in ('', '/'), 'Destination must be an HTTPS origin')
        text(document['destination']['model_id'])
        if document['destination']['branch_id'] is not None: text(document['destination']['branch_id'])
        if document['destination'].get('model_version_id') is not None: text(document['destination']['model_version_id'])
        if version == 2:
            for k in ('model_id', 'branch_id', 'model_version_id'):
                val = document['destination'].get(k)
                require(val is None or isinstance(val, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', val),
                        'Use bounded destination identifiers')
    key = {'engagement': state['engagement_id'], 'domain': document['domain_id'],
           'dashboard_ids': sorted(document['dashboard_ids']), 'topic_names': sorted(document['topic_names'])}
    if version == 2:
        key.update(schema_version=2, app_ids=sorted(document['app_ids']), task_mode=document['task_mode'],
                   target_surfaces=document['target_surfaces'])
    identity = 'frontend-' + digest(key)[:24]
    ledger = state['workflow'].setdefault('frontend_continuations', {'schema_version': 1, 'items': []})
    old = next((r for r in ledger['items'] if r['id'] == identity), None)
    mode = _mode(state, document)
    if old and old['request'] == document and old['scope_sha256'] == digest(snapshot) and (version == 1 or old['mode'] == mode):
        return identity
    if old:
        require(old['request']['request_reference'] != document['request_reference'] or old['request'] == document,
                'Changed continuation choices need their actual new user request reference')
    record = {'id': identity, 'request': copy.deepcopy(document), 'scope_sha256': digest(snapshot),
              'entity_ids': snapshot['entity_ids'],
              'mode': mode,
              'history': copy.deepcopy(old['history']) + [copy.deepcopy({k: v for k, v in old.items() if k != 'history'})] if old else [],
              'progress': None, 'assurance': 'host_reported_user_choice'}
    if old: ledger['items'].remove(old)
    ledger['items'].append(record)
    return identity


def item(state, identity):
    row = next((r for r in state.get('workflow', {}).get('frontend_continuations', {}).get('items', [])
                if r['id'] == identity), None)
    require(row is not None, 'Unknown continuation')
    require(row['scope_sha256'] == digest(scoped_context(state, row['request']['domain_id'])),
            'Continuation is stale; reconcile the affected domain before preparing a new handoff')
    if row['request']['schema_version'] == 2:
        require(row['mode'] == _mode(state, row['request']), 'Backend scope changed; reconcile the frontend selection')
    return row


def discover(skills_root, *, target_surfaces=None, protocol_version=None, task_mode='migration'):
    """Read a host-selected installation; never execute discovered files."""
    from ae_common import _path
    surfaces = ['dashboard'] if target_surfaces is None else target_surfaces
    _strings(surfaces)
    require(surfaces and set(surfaces) <= set(SURFACES), 'Unknown requested frontend surfaces')
    require(protocol_version is None or type(protocol_version) is int and protocol_version in PROTOCOLS, 'Unsupported requested protocol')
    require(type(task_mode) is str and task_mode in TASK_MODES, 'Unsupported frontend task mode')
    root = _path(skills_root)
    companion = root / 'omni-backend-handoff'
    descriptor = companion / 'capabilities.json'
    if not (root / 'omni-artifact-accelerator' / 'SKILL.md').is_file():
        return {'status': 'missing', 'next_action': 'Install Omni Artifact Accelerator explicitly, or retain the portable handoff.'}
    if not descriptor.is_file():
        return {'status': 'unknown', 'next_action': 'Existing installation has no continuation capability descriptor; use its manual handoff or explicitly update it.'}
    from guided_workflow import _nonsecret_json
    value, sha = _nonsecret_json(descriptor)
    compatible = (type(value) is dict and type(value.get('schema_version')) is int
                  and value.get('schema_version') == 1
                  and value.get('kind') == 'omni_frontend_capabilities'
                  and type(value.get('continuation_protocol_versions')) is list
                  and all(type(n) is int for n in value['continuation_protocol_versions'])
                  and type(value.get('semantic_handoff_versions')) is list
                  and 'omni-handoff-v1' in value['semantic_handoff_versions']
                  and value.get('entrypoint') == 'scripts/continuation.py'
                  and value.get('authorizes_target_write') is False)
    offered = set(value['continuation_protocol_versions']) & set(PROTOCOLS) if compatible else set()
    eligible = offered & ({protocol_version} if protocol_version is not None else set(PROTOCOLS))
    if 'app' in surfaces or task_mode != 'migration':
        eligible.discard(1)
    if 2 in eligible and not (type(value.get('target_surfaces')) is list and all(s in value['target_surfaces'] for s in surfaces)
                              and type(value.get('task_modes')) is list and task_mode in value['task_modes']):
        eligible.discard(2)
    chosen = max(eligible, default=None)
    required = list(COMMON_SKILLS)
    if chosen == 2: required.extend(['omni-product-owner', 'omni-design-systems'])
    if 'dashboard' in surfaces: required.append('omni-dashboard-designer')
    if 'app' in surfaces: required.extend(['omni-app-designer', 'omni-app-engineer'])
    missing = [name for name in required if not _path(root / name / 'SKILL.md', must_exist=False).is_file()]
    entry = companion / 'scripts' / 'continuation.py'
    runtime = ['omni-artifact-accelerator/scripts/analyst_project.py',
               'omni-backend-handoff/scripts/dma_frontend.py',
               'omni-backend-handoff/scripts/migration.py', 'omni-backend-handoff/scripts/cowork.py']
    missing_runtime = [name for name in runtime if not _path(root / name, must_exist=False).is_file()]
    compatible = chosen is not None and not missing and not missing_runtime and _path(entry, must_exist=False).is_file()
    return {'status': 'compatible' if compatible else 'incompatible', 'descriptor_sha256': sha,
            'missing_skills': missing, 'missing_runtime': missing_runtime,
            'protocol_version': chosen if compatible else None, 'target_surfaces': surfaces,
            'next_action': 'Use the host to invoke the bounded assignment.' if compatible
            else 'Retain the handoff; explicitly install a compatible complete bundle. No files were executed.',
            'agents_dispatched': False}


def _native_context(evidence, destination, review):
    """Check associations only. Provenance and live freshness belong to the host."""
    require(type(evidence) is dict and evidence.get('kind') == 'omni_native_receipt'
            and evidence.get('schema_version') == 1 and type(evidence.get('schema_version')) is int
            and evidence.get('contract_version') == 'omni-native-v1-2026-10-05'
            and evidence.get('operation') in ('validate', 'update_and_validate'), 'Expected a DMA native model validation receipt')
    target = evidence.get('target')
    require(type(target) is dict and destination is not None and
            [target.get(k) for k in ('instance_url', 'model_id', 'branch_id')] ==
            [destination[k] for k in ('base_url', 'model_id', 'branch_id')], 'Native validation belongs to another destination')
    require(review is not None and evidence.get('candidate_sha256') == review['pins']['model_candidate_sha256']
            and evidence.get('context_sha256') == review['pins']['model_context_sha256'], 'Native validation belongs to another candidate')
    mode, status = evidence.get('execution_mode'), evidence.get('status')
    require(mode in ('live', 'simulation') and status in ('passed', 'simulated_passed', 'failed', 'pending', 'blocked')
            and evidence.get('native_verified') is (mode == 'live' and status == 'passed')
            and (status != 'passed' or mode == 'live') and (status != 'simulated_passed' or mode == 'simulation'),
            'Native validation declares conflicting execution evidence')


def prepare(state, identity, input_root, output, disclosure_reference, *, skills_root=None):
    """Create-only portable packet, repeatable for exact bytes; host owns disclosure review."""
    from ae_common import _path
    from guided_workflow import _nonsecret_json, _secrets
    from source_roots import ensure_output
    row = item(state, identity); request = row['request']
    require(request['choice'] != 'not_now', 'Continuation was declined; no package is created')
    require(type(disclosure_reference) is str and disclosure_reference.strip(), 'Record the host disclosure review reference first')
    root, destination = _path(input_root), _path(output, must_exist=False)
    ensure_output(state, destination)
    require(destination != root and root not in destination.parents and destination not in root.parents,
            'Keep the continuation separate from selected input files')
    contents = {}; records = []
    selections = list(request.get('context_files', []))
    if request.get('semantic_review'):
        selections.append({'path': request['semantic_review'], 'purpose': 'semantic_review'})
    version = request['schema_version']
    semantic, review_value, native_value = None, None, None
    evidence_pins = {'native_validation': None, 'topic_readback': None}
    for index, selected in enumerate(selections):
        source = _path(root / safe_relative(selected['path']))
        value, sha = _nonsecret_json(source)
        raw = source.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == sha, 'Input changed while preparing handoff')
        if 'sha256' in selected:
            require(selected['sha256'] == sha, 'Selected evidence bytes changed; reconcile the continuation')
        name = 'inputs/' + str(index).zfill(2) + '-' + selected['purpose'] + '.json'
        contents[name] = raw
        records.append({'path': name, 'sha256': sha, 'purpose': selected['purpose']})
        if version == 2 and selected['purpose'] in EVIDENCE_PURPOSES:
            require(type(value) is dict, 'Selected evidence requires a JSON object')
            evidence_pins[selected['purpose']] = {'path': name, 'sha256': sha}
            if selected['purpose'] == 'native_validation': native_value = value
        if selected['purpose'] == 'semantic_review':
            require(value.get('kind') == 'omni_semantic_handoff' and value.get('schema_version') == 1
                    and value.get('version') == 'omni-handoff-v1', 'Unsupported semantic handoff')
            from omni_contract import canonical_hash
            require(value.get('handoff_sha256') == canonical_hash({k: v for k, v in value.items() if k != 'handoff_sha256'}),
                    'Semantic review self-seal mismatch')
            from delivery_portal import context_fingerprint, source_fingerprint
            pins = value.get('pins', {})
            require(pins.get('context_sha256') == context_fingerprint(state) and
                    pins.get('source_fingerprint') == source_fingerprint(state) and
                    pins.get('target') == {k: state['answers'].get(k) for k in ('framework', 'warehouse')},
                    'Semantic review does not match this engagement')
            require(set(request['topic_names']) <= {t['id'] for t in value.get('topics', [])}, 'Selected Topic is missing from the candidate')
            semantic = {'path': name, 'sha256': sha}
            review_value = value
    if native_value is not None:
        _native_context(native_value, request.get('destination'), review_value)
    context = scoped_context(state, request['domain_id'])
    context_raw = (json.dumps(context, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()
    _secrets(context)
    contents['inputs/domain-context.json'] = context_raw
    records.append({'path': 'inputs/domain-context.json', 'sha256': hashlib.sha256(context_raw).hexdigest(), 'purpose': 'domain_context'})
    require(sum(map(len, contents.values())) <= 16 * 1024 * 1024, 'Handoff exceeds 16 MiB; select a smaller dependency-complete scope')
    unresolved = [] if semantic else ['Semantic candidate unavailable; draft design only until bindings are supplied.']
    if version == 2 and not request['topic_names']:
        unresolved.append('Selected Topic names are missing; retain provisional scope until the Topic selection is resolved.')
    if version == 1 and not request['dashboard_ids']:
        unresolved.append('Dashboard scope is not selected; clarify it before building target content.')
    migration = version == 1 or request['task_mode'] == 'migration'
    if version == 2 and migration and not (request['dashboard_ids'] or request['app_ids']):
        unresolved.append('Source artifact IDs are not selected for the frontend migration.')
    if migration and not any(r['purpose'] == 'source_inventory' for r in records):
        unresolved.append('Source dashboard inventory is missing; requested IDs do not prove complete migration scope.' if version == 1
                          else 'Source artifact inventory is missing; the migration denominator is unresolved.')
    if migration and not any(r['purpose'] == 'independent_source_listing' for r in records):
        unresolved.append('Independent source listing is missing; export completeness is unverified.')
    value = {'schema_version': version, 'kind': 'dma_frontend_continuation', 'continuation_id': identity,
        'engagement_id': state['engagement_id'], 'domain_id': request['domain_id'], 'mode': row['mode'],
        'choice': request['choice'], 'request_reference': request['request_reference'],
        'scope_sha256': row['scope_sha256'], 'semantic_review': semantic, 'files': records,
        'dashboard_ids': request['dashboard_ids'], 'topic_names': request['topic_names'],
        'destination': request.get('destination'), 'source_migration_scope': state['answers'].get('migration_scope'),
        'unresolved': unresolved, 'allowed_actions': ['design', 'candidate_artifacts'],
        'authorizes_target_write': False, 'disclosure_reference': disclosure_reference,
        'disclosure_assurance': 'host_reported_not_authenticated'}
    if version == 2:
        value.update(target_surfaces=request['target_surfaces'], task_mode=request['task_mode'], app_ids=request['app_ids'],
                     **evidence_pins)
    value['sha256'] = digest(value)
    contents['continuation.json'] = (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode()
    prompt = ('Use $omni-artifact-accelerator to continue ' + identity + '. Read continuation.json, verify its '
        'selected files and preserve the dashboard IDs and Topic names. Reuse decisions; ask only for missing '
        'experience requirements. Resume the linked frontend project. Send real model gaps through '
        '$omni-backend-handoff. This packet permits design and candidate artifacts only. Native validation, '
        'access, publication and business acceptance remain separate. Do not load unrelated source repositories.')
    if version == 2:
        prompt = ('Continue the ' + request['task_mode'] + ' task for ' + ' and '.join(request['target_surfaces']) +
            ' using $omni-artifact-accelerator and continuation.json. Preserve the source IDs, selected Topics, '
            'destination, decisions and unknowns. Verify current Topic evidence before native work.')
    contents['CONTINUE.txt'] = (prompt + '\n').encode()
    require(sum(map(len, contents.values())) <= 16 * 1024 * 1024,
            'Complete handoff exceeds 16 MiB; reduce selected context without dropping dependencies')
    destination.mkdir(mode=0o700, parents=False, exist_ok=True)
    for parent, directories, names in os.walk(destination, followlinks=False):
        for name in directories + names:
            existing = _path(Path(parent) / name)
            relative = existing.relative_to(destination).as_posix()
            require(relative == 'inputs' or relative in contents,
                    'Output folder contains unrelated files; use a separate versioned handoff folder')
    # Preflight existing files before any write, then repair interrupted exact-byte exports.
    for name, raw in contents.items():
        target = _path(destination / name, must_exist=False)
        require(not target.exists() or target.read_bytes() == raw, 'Existing handoff differs; retain it and use a new versioned folder')
    # Publish complete members without replacement. A killed write remains in a
    # private sibling staging folder, never as a truncated member of the handoff.
    with tempfile.TemporaryDirectory(prefix='.dma-continuation-', dir=destination.parent) as staging:
        for index, (name, raw) in enumerate(contents.items()):
            target = _path(destination / name, must_exist=False)
            target.parent.mkdir(mode=0o700, exist_ok=True)
            if target.exists():
                require(target.read_bytes() == raw, 'Existing handoff differs; retain a separate version')
                continue
            staged = Path(staging) / str(index)
            with os.fdopen(os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(staged, target, follow_symlinks=False)
            except FileExistsError:
                require(_path(target).read_bytes() == raw, 'Concurrent handoff differs; retain a separate version')
    result = {'status': 'handoff_prepared', 'continuation_id': identity, 'sha256': value['sha256'],
            'manifest': str(destination / 'continuation.json'), 'agents_dispatched': False,
            'authorizes_target_write': False, 'unresolved': unresolved}
    if skills_root is not None:
        partner = discover(skills_root, target_surfaces=request.get('target_surfaces', ['dashboard']), protocol_version=version,
                           task_mode=request.get('task_mode', 'migration'))
        result.update(companion=partner, route='compatible_companion' if partner['status'] == 'compatible' else 'portable_handoff')
    return result


def record_progress(state, document):
    from engagement_stages import fields, text, identifier
    fields(document, {'schema_version', 'continuation_id', 'scope_sha256', 'status', 'reference'},
           {'project_id', 'worker_id', 'artifact_ids'})
    require(document['schema_version'] == 1, 'Unsupported continuation progress')
    row = item(state, document['continuation_id'])
    require(document['scope_sha256'] == row['scope_sha256'], 'Progress belongs to an old scope')
    require(row['request']['choice'] != 'not_now', 'Declined continuation cannot advance')
    require(document['status'] in {'handoff_prepared', 'started', 'blocked', 'returned'}, 'Unknown continuation status')
    text(document['reference'])
    if document['status'] == 'started':
        text(document.get('worker_id')); text(document.get('project_id'))
    _strings(document.get('artifact_ids', []))
    for artifact_id in document.get('artifact_ids', []): identifier(artifact_id)
    row['progress'] = copy.deepcopy(document)
    row['progress']['assurance'] = 'host_reported_not_authenticated'


def public_summary(state, selected=None, artifact_ids=()):
    rows = []
    for row in state.get('workflow', {}).get('frontend_continuations', {}).get('items', []):
        if selected is not None and (not row['entity_ids'] or not set(row['entity_ids']) <= set(selected)):
            continue
        request = row['request']
        missing_domain = request['domain_id'] is not None and not any(
            d['id'] == request['domain_id'] for d in (state.get('workflow', {}).get('domain_journey') or {}).get('domains', []))
        stale = missing_domain or row['scope_sha256'] != digest(scoped_context(state, request['domain_id']))
        status = 'stale' if stale else 'deferred' if request['choice'] == 'not_now' else (row.get('progress') or {}).get('status', 'selected')
        rows.append({'id': row['id'], 'domain_id': request['domain_id'], 'mode': row['mode'], 'status': status,
            'dashboard_ids': request['dashboard_ids'], 'topic_names': request['topic_names'],
            **({k: request[k] for k in ('app_ids', 'target_surfaces', 'task_mode')} if request['schema_version'] == 2 else {}),
            'artifact_ids': [key for key in (row.get('progress') or {}).get('artifact_ids', []) if key in artifact_ids],
            'next_action': 'This domain is no longer registered; select its replacement with the agent.' if missing_domain else
                'Reconcile the changed scope with the agent.' if stale else
                'Ask the agent to resume this continuation.' if request['choice'] != 'not_now' else 'Continue later when requested.'})
    return {'qualification': QUALIFICATION, 'items': rows} if rows else None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('discover'); d.add_argument('--skills-root', required=True)
    d.add_argument('--surface', choices=SURFACES, action='append'); d.add_argument('--protocol-version', type=int, choices=PROTOCOLS)
    d.add_argument('--task-mode', choices=sorted(TASK_MODES), default='migration')
    q = sub.add_parser('prepare')
    q.add_argument('--skills-root', help='Optionally check compatibility of an explicitly selected installed bundle')
    for key in ('run', 'id', 'input-root', 'output', 'disclosure-reference'): q.add_argument('--' + key, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'discover': result = discover(args.skills_root, target_surfaces=args.surface,
                                                        protocol_version=args.protocol_version, task_mode=args.task_mode)
        else:
            from guided_workflow import status_engagement
            result = prepare(status_engagement(args.run, refresh=True), args.id, args.input_root, args.output, args.disclosure_reference,
                             skills_root=args.skills_root)
        print(json.dumps(result, indent=2)); return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        p.exit(1, 'Frontend continuation: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
