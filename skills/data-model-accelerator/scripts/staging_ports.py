"""Optional staging-port policy and additive candidate register, not a copier.

All identities resolve through retained upstream extraction. A missing target
means absent from the supplied identity inventory, never proven absent globally.
"""
import copy
import csv
import io

from ae_common import hash_json, require
from engagement_stages import DIMENSIONS, SHA, fields, ids, text
import upstream_context as context

QUALIFICATION = ('Candidate port/reuse planning only. Target absence is limited to supplied extraction; '
                 'no source writes, naming approval, native validation or deployment authority.')


def read(state):
    saved = state.get('workflow', {}).get('staging_ports')
    if saved is None: return {'schema_version': 1, 'policies': {}, 'rows': {}}
    require(saved.get('schema_version') == 1 and saved.get('sha256') == hash_json(saved['document']), 'Staging port register changed')
    return copy.deepcopy(saved['document'])


def _save(state, value):
    context._safe(value)
    state['workflow']['staging_ports'] = {'schema_version': 1, 'document': value, 'sha256': hash_json(value)}


def _models(state):
    return {e['id']: e for e in (state.get('workflow', {}).get('design') or {}).get('entities', [])}


def configure(state, request):
    fields(request, {'schema_version', 'domain_id', 'target_root_id', 'source_root_ids', 'candidate_model_ids',
                     'missing_staging', 'version_preference', 'request_reference'}, {'staging_object_ids'})
    require(request['schema_version'] == 1 and type(state.get('workflow')) is dict, 'Unsupported staging policy')
    from source_roots import _rows
    roots = {r['id'] for r in _rows(state)}
    text(request['domain_id']); text(request['request_reference'])
    ids(request['source_root_ids'], roots, True)
    require(request['target_root_id'] in roots and request['target_root_id'] not in request['source_root_ids'],
            'Choose distinct registered staging and target roots')
    require(request['missing_staging'] in {'propose_port', 'unresolved'}, 'Invalid missing-staging policy')
    require(request['version_preference'] in {'compatible_target', 'explicit_order'}, 'Invalid version preference')
    ids(request['candidate_model_ids'], _models(state))
    ids(request.get('staging_object_ids', []))
    if request.get('staging_object_ids'):
        document = context.read(state)
        require(document is not None, 'Retain extraction before selecting exact staging objects')
        nodes = context.graph(document)[0]
        require(all(key in nodes and nodes[key]['root_id'] in request['source_root_ids'] for key in request['staging_object_ids']),
                'Staging object selection is outside the chosen source roots')
    from domain_workflow import ledger, _domain, _models as domain_models
    if ledger(state):
        domain = _domain(state, request['domain_id'])
        require(set(request['candidate_model_ids']) <= domain_models(state, domain), 'Port policy exceeds its chosen domain')
    intent = state['workflow'].get('migration_intents', {}).get(request['domain_id'], {}).get('intent')
    if intent:
        roles = intent['source_roles']
        require(any(r['root_id'] == request['target_root_id'] and r['role'] == 'target_implementation' for r in roles),
                'Port target conflicts with migration repository roles')
        require(all(any(r['root_id'] == key and r['role'] in {'legacy_baseline', 'raw_staging'} for r in roles)
                    for key in request['source_root_ids']), 'Port source conflicts with migration repository roles')
    value = read(state)
    value['policies'][request['domain_id']] = copy.deepcopy(request)
    _save(state, value)
    return summarize(state, request['candidate_model_ids'])


def _pins(values, files):
    context._rows(values)
    result = []
    for pin in values:
        fields(pin, {'reference', 'sha256'})
        require(files.get(pin['reference'], {}).get('sha256') == pin['sha256'], 'Port evidence is absent or stale in extraction')
        require(pin not in result, 'Duplicate port evidence'); result.append(copy.deepcopy(pin))
    return result


def _material(state, policy, row, nodes, files):
    keys = {row['source_object_id'], *row.get('target_match_ids', [])}
    existing = next((e for e in (state.get('workflow', {}).get('design') or {}).get('existing_models', [])
                     if e['id'] == row.get('existing_id')), None)
    intent = state.get('workflow', {}).get('migration_intents', {}).get(policy['domain_id'], {}).get('intent')
    document = context.read(state) or {'extracts': {}}
    target_search = {key: item['result_sha256'] for key, item in document['extracts'].items()
                     if item['root_id'] == policy['target_root_id']}
    return {'policy': policy, 'objects': {k: nodes.get(k) for k in sorted(keys)},
            'files': {p['reference']: files.get(p['reference']) for p in row['pinned_files']},
            'models': {k: _models(state).get(k) for k in row['model_ids']},
            'existing_model': existing, 'migration_intent': intent, 'target_search': target_search}


def _staging_selected(state, policy, source):
    if source['id'] in policy.get('staging_object_ids', []): return True
    intent = state['workflow'].get('migration_intents', {}).get(policy['domain_id'], {}).get('intent') or {}
    for role in intent.get('source_roles', []):
        if role['root_id'] != source['root_id'] or role['role'] != 'raw_staging': continue
        prefix = context.reference(role['root_id'], role['path_prefix']) if role.get('path_prefix') else None
        if any(prefix is None or p['reference'] == prefix or p['reference'].startswith(prefix + '/') for p in source['evidence']):
            return True
    return False


def register(state, request, run_dir=None):
    fields(request, {'schema_version', 'domain_id', 'rows'})
    require(request['schema_version'] == 1, 'Unsupported staging port request')
    value = read(state); policy = value['policies'].get(request['domain_id'])
    require(policy, 'Record the staging port policy before proposing ports')
    document = context.read(state); require(document is not None, 'Retain source extraction before proposing ports')
    nodes, files, _, _, _ = context.graph(document)
    models = _models(state)
    seen, normalized, all_pins = set(), {}, {}
    for row in context._rows(request['rows']):
        fields(row, {'id', 'model_ids', 'source_object_id', 'target_native_ids', 'decision', 'rationale', 'evidence_refs'},
               {'target_object_id', 'candidate_path', 'comparisons', 'support_files', 'version_order', 'existing_id', 'naming_resource_id'})
        text(row['id']); text(row['rationale'])
        require(row['id'] not in seen, 'Duplicate port row'); seen.add(row['id'])
        ids(row['model_ids'], policy['candidate_model_ids'], True); ids(row['model_ids'], models, True)
        source = nodes.get(row['source_object_id'])
        require(source is not None and not source['disabled'] and source['root_id'] in policy['source_root_ids'], 'Unknown or disallowed staging source')
        require(_staging_selected(state, policy, source),
                'Select the exact staging object or a matching migration raw_staging path; do not infer its layer from its name')
        reached = {n['id'] for n in context.derive(state, row['model_ids'])['nodes']}
        require(source['id'] in reached, 'Port source is outside the selected models upstream context')
        ids(row['target_native_ids'], nonempty=True)
        matches = sorted(n['id'] for n in nodes.values() if n['root_id'] == policy['target_root_id']
                         and n['native_id'] in row['target_native_ids'] and not n['disabled'])
        require(any(e['root_id'] == policy['target_root_id'] for e in document['extracts'].values()),
                'Missing target extraction is not evidence that a target is absent')
        require(row['decision'] in {'reuse_target', 'port_missing', 'unresolved'}, 'Invalid staging disposition')
        pins = _pins(row['evidence_refs'], files); require(pins, 'Port decisions need current source evidence')
        # An absence decision depends on the target inventory too. Pin and
        # recheck its supplied files, including the manifest, without rescanning.
        pins.extend({'reference': path, 'sha256': item['sha256']}
                    for extract in document['extracts'].values() if extract['root_id'] == policy['target_root_id']
                    for path, item in extract['files'].items())
        source_refs = {e['reference'] for e in source['evidence']}
        require(source_refs & {p['reference'] for p in pins}, 'Port evidence must include the original staging source')
        support = []
        for item in context._rows(row.get('support_files', [])):
            fields(item, {'reference', 'sha256', 'kind'})
            require(item['kind'] in {'yaml', 'macro', 'configuration', 'test', 'seed', 'other'}, 'Unknown supporting file kind')
            _pins([{k: item[k] for k in ('reference', 'sha256')}], files)
            reference_root = 'primary' if not item['reference'].startswith('@sources/') else item['reference'].split('/')[1]
            require(reference_root in set(policy['source_root_ids']) | {policy['target_root_id']}, 'Supporting file is outside the selected repositories')
            support.append(copy.deepcopy(item)); pins.append({k: item[k] for k in ('reference', 'sha256')})
        comparisons = row.get('comparisons', {})
        require(type(comparisons) is dict and set(comparisons) <= set(matches), 'Comparisons must identify exact target matches')
        compatible = []
        for key, dimensions in comparisons.items():
            require(type(dimensions) is dict and set(dimensions) == DIMENSIONS, 'Compare all canonical reuse dimensions')
            for comparison in dimensions.values():
                fields(comparison, {'status', 'evidence_refs'})
                require(comparison['status'] in {'compatible', 'change_required', 'unknown'}, 'Invalid compatibility observation')
                cp = _pins(comparison['evidence_refs'], files); require(cp, 'Compatibility needs pinned original evidence')
                target_refs = {e['reference'] for e in nodes[key]['evidence']}
                require(target_refs & {p['reference'] for p in cp}, 'Compatibility must cite the target implementation')
                pins.extend(cp)
            if all(d['status'] == 'compatible' for d in dimensions.values()): compatible.append(key)
        target = row.get('target_object_id')
        require(target is None or target in matches, 'Chosen target is outside the exact identity search')
        order = row.get('version_order', [])
        ranks = {}
        for ordered in context._rows(order):
            fields(ordered, {'object_id', 'rank', 'evidence_refs'})
            require(ordered['object_id'] in {source['id'], *matches} and ordered['object_id'] not in ranks,
                    'Version order must use distinct compared object identities')
            require(type(ordered['rank']) is int and ordered['rank'] >= 0 and ordered['rank'] not in ranks.values(), 'Version ranks must be distinct nonnegative integers')
            proof = _pins(ordered['evidence_refs'], files); require(proof, 'Version order requires explicit pinned evidence')
            pins.extend(proof); ranks[ordered['object_id']] = ordered['rank']
        if row['decision'] == 'reuse_target':
            require(target in compatible, 'Reuse requires a compatible target with all comparison dimensions')
            if policy['version_preference'] == 'explicit_order' and len(compatible) > 1:
                require(set(compatible) <= set(ranks), 'Newer target selection needs explicit ordered evidence for every compatible candidate')
                require(target == max(compatible, key=lambda key: ranks[key]), 'Choose the explicitly newer compatible target')
        elif row['decision'] == 'port_missing':
            require(policy['missing_staging'] == 'propose_port', 'Policy does not permit staging port proposals')
            require(not matches, 'Prefer a compatible target or resolve its differences; a present target is not missing')
            require(target is None, 'A missing-target proposal cannot also reuse a target')
            from task_routing import output_path
            output_path(row.get('candidate_path'))
            require(not row['candidate_path'].casefold().startswith(('inputs/', 'evidence/', 'contracts/')), 'Port candidates cannot overwrite retained inputs')
        else:
            require(row.get('candidate_path') is None, 'Unresolved ports do not assign output paths')
        if row.get('existing_id') is not None:
            known = {e['id'] for e in (state['workflow'].get('design') or {}).get('existing_models', [])}
            require(row['existing_id'] in known, 'Unknown canonical existing-model reference')
        if row.get('naming_resource_id') is not None: text(row['naming_resource_id'])
        saved = {**copy.deepcopy(row), 'domain_id': request['domain_id'], 'target_match_ids': matches,
                 'support_files': support, 'compatibility': 'evidence_recorded' if target in compatible else 'unresolved',
                 'target_presence': 'present' if matches else 'absent_from_supplied_identity_inventory',
                 'version_status': 'explicit_order_recorded' if ranks else 'not_established',
                 'naming_status': 'requires_governed_candidate_check',
                 'pinned_files': sorted({p['reference']: p for p in pins}.values(), key=lambda p: p['reference'])}
        old = value['rows'].get(row['id'])
        require(not old or (old['domain_id'], old['source_object_id']) == (saved['domain_id'], saved['source_object_id']), 'Port row identities cannot be reassigned')
        saved['binding_sha256'] = hash_json(_material(state, policy, saved, nodes, files))
        normalized[row['id']] = saved
        all_pins.update({p['reference']: p for p in saved['pinned_files']})
    actual = context.verify_files(state, list(all_pins.values()))
    require(all(actual[p] == pin['sha256'] for p, pin in all_pins.items()), 'Port evidence bytes changed or are unavailable')
    value['rows'].update(normalized)  # Omitted rows remain visible, including unresolved rows.
    from task_routing import outputs_overlap
    assigned = [(row['id'], row['candidate_path']) for row in value['rows'].values()
                if row['decision'] == 'port_missing']
    require(all(not outputs_overlap([path], [other]) for index, (_, path) in enumerate(assigned)
                for _, other in assigned[index + 1:]), 'Port candidates have conflicting output ownership')
    _save(state, value)
    return summarize(state)


def summarize(state, selected=None):
    value = read(state); document = context.read(state)
    nodes, files = context.graph(document)[:2] if document else ({}, {})
    allowed = None if selected is None else set(selected)
    rows = []
    for saved in value['rows'].values():
        if allowed is not None and not set(saved['model_ids']) <= allowed: continue
        policy = value['policies'].get(saved['domain_id'])
        stale = not policy or hash_json(_material(state, policy, saved, nodes, files)) != saved['binding_sha256']
        if not stale:
            actual = context.verify_files(state, saved['pinned_files'])
            stale = any(actual[p['reference']] != p['sha256'] for p in saved['pinned_files'])
        rows.append({key: copy.deepcopy(saved.get(key)) for key in ('id', 'domain_id', 'model_ids', 'source_object_id', 'target_object_id',
                    'decision', 'compatibility', 'target_presence', 'version_status', 'naming_status', 'existing_id')})
        rows[-1].update(status='stale' if stale else 'unresolved' if saved['decision'] == 'unresolved' else 'candidate',
                        support_file_count=len(saved['support_files']), evidence_file_count=len(saved['pinned_files']),
                        target_match_count=len(saved['target_match_ids']))
        for side in ('source', 'target'):
            node = nodes.get(saved.get(side + '_object_id'), {})
            rows[-1][side + '_root_id'] = context._public_token(node.get('root_id', '')) or ''
            rows[-1][side + '_native_id'] = context._public_token(node.get('native_id', '')) or ''
    return {'schema_version': 1, 'status': 'unassessed' if not value['policies'] else 'recorded', 'rows': sorted(rows, key=lambda r: r['id']),
            'counts': {key: sum(r['status'] == key for r in rows) for key in ('candidate', 'unresolved', 'stale')},
            'qualification': QUALIFICATION}


def scope_bindings(state):
    value = read(state)
    if not value['policies']: return {}
    summary = summarize(state)
    result = {}
    for policy in value['policies'].values():
        for key in policy['candidate_model_ids']:
            result[key] = hash_json({'policy': policy, 'rows': [r for r in summary['rows'] if key in r['model_ids']],
                                    'records': [r for r in value['rows'].values() if key in r['model_ids']]})
    return result


def csv_export(state, selected=None):
    """Complete scoped public rows; no source paths, excerpts or freeform notes."""
    rows = summarize(state, selected)['rows']
    columns = ['id', 'domain_id', 'model_ids', 'source_object_id', 'target_object_id', 'decision', 'status',
               'source_root_id', 'source_native_id', 'target_root_id', 'target_native_id',
               'target_presence', 'compatibility', 'version_status', 'naming_status', 'support_file_count', 'evidence_file_count']
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore'); writer.writeheader()
    for row in rows:
        clean = {**row, 'model_ids': '; '.join(row['model_ids'])}
        for key, val in clean.items():
            if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@')): clean[key] = "'" + val
        writer.writerow(clean)
    return out.getvalue()
