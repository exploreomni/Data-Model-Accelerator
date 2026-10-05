"""Authorized existing-document draft creation; never publishes or clears drafts."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request
from pathlib import Path

import omni_native as native
from deployment_authority import load_policy, verify_attestation, canonical_path, outside
from omni_contract import canonical_hash, check_model, _load, _merge
from sensitive_data import scan_bytes

CONTRACT = 'omni-dashboard-draft-v1-2026-10-05'
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
MAX_ACCESS_PAGES = 10
need = native._need


def _id(value):
    return type(value) is str and ID.fullmatch(value) is not None and value != 'publish'


class HTTPSOmniDraftTransport(native.HTTPSOmniTransport):
    """Same TLS/credential boundary; only document GETs and create-draft PATCH."""
    def request(self, method, path, params=None, body=None):
        if method == 'GET' and path.startswith('/api/v1/'):
            return super().request(method, path, params, body)
        match = re.fullmatch(r'/api/v2/documents/([A-Za-z0-9_-]+)(?:/draft(?:/([A-Za-z0-9_-]+))?)?', path)
        need(match and _id(match.group(1)) and (match.group(2) is None or _id(match.group(2))), 'draft.transport_route')
        need(self.available and (method == 'GET' and (path.count('/') == 4 or match.group(2))
             or method == 'PATCH' and path.endswith('/draft')), 'draft.transport_method')
        need(not params, 'draft.transport_query_unsupported')
        req = Request(self.instance_url + path, data=native._json_bytes(body) if body is not None else None,
                      method=method, headers={'Authorization': 'Bearer ' + self._token,
                      'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with self._opener.open(req, timeout=self.timeout) as reply:
                data = reply.read(native.MAX_BYTES + 1)
                if len(data) > native.MAX_BYTES:
                    raise native.TransportError('transport.size', uncertain=method == 'PATCH')
                return native.Response(reply.status, data, reply.headers.get_content_type())
        except HTTPError as error:
            raise native.TransportError('transport.http', error.code,
                                        method == 'PATCH' and (error.code >= 500 or error.code == 408)) from None
        except (TimeoutError, socket.timeout):
            raise native.TransportError('transport.timeout', uncertain=method == 'PATCH') from None
        except (URLError, OSError):
            raise native.TransportError('transport.failure', uncertain=method == 'PATCH') from None


def _policy(path, candidate_root, request):
    root = canonical_path(candidate_root)
    need(root.is_dir(), 'draft.candidate_root')
    policy, digest = load_policy(path, excluded_roots=(root,))
    destination = dict(request['target'], document_id=request['document_id'])
    need('deploy_development' in policy['allowed_actions']
         and policy['destinations'].get(request['destination_id']) == destination, 'draft.destination_not_provisioned')
    return policy, digest


def request_bindings(request, policy_sha256):
    return {'adapter': CONTRACT, 'action': 'deploy_development', 'operation': 'create_document_draft',
            'request_sha256': canonical_hash(request), 'target_sha256': canonical_hash(request['target']),
            'document_id': request['document_id'], 'build_sha256': request['build_spec']['build_sha256'],
            'candidate_sha256': canonical_hash(request['model_files']),
            'context_sha256': canonical_hash(request['model_context']), 'policy_sha256': policy_sha256}


def validate_request(request):
    from omni_dashboard import verify_build
    native._json_bytes(request)
    keys = {'schema_version','kind','run_id','destination_id','target','document_id','build_spec',
            'model_files','model_context','expected_model','expected_document_sha256','expected_drafts_sha256',
            'expected_access_sha256'}
    need(type(request) is dict and set(request) == keys and request['schema_version'] == 1
         and type(request['schema_version']) is int and request['kind'] == 'omni_dashboard_native_request', 'draft.request_schema')
    need(type(request['run_id']) is str and native.RUN_ID.fullmatch(request['run_id'])
         and type(request['destination_id']) is str and native.RUN_ID.fullmatch(request['destination_id'])
         and _id(request['document_id']), 'draft.request_identity')
    native.validate_target(request['target'])
    for key in ('expected_document_sha256','expected_drafts_sha256','expected_access_sha256'):
        need(native._sha(request[key]), 'draft.expected_snapshot_required')
    need(type(request['expected_model']) is dict and set(request['expected_model']) == native.SNAPSHOT_KEYS
         and all(native._sha(x) for x in request['expected_model'].values()), 'draft.expected_model_required')
    spec = verify_build(request['build_spec'])
    need(spec['status'] == 'complete' and spec['candidate_sha256'] == canonical_hash(request['model_files'])
         and spec['target_model_id'] == request['target']['model_id'], 'draft.build_not_bound_or_complete')
    payload = spec['native_payload']
    need(type(payload) is dict and payload.get('modelId') == request['target']['model_id']
         and set(payload) <= {'modelId','name','description','summary','queryPresentations','controls','settings','containers'}
         and {'queryPresentations','controls','containers'} <= set(payload), 'draft.native_payload_scope')
    if 'summary' in payload:
        need(type(payload['summary']) is str and 0 < len(payload['summary']) <= 255, 'draft.summary_bounds')
    _inventory(payload['queryPresentations'], 'tiles', numeric=True)
    _inventory(payload['controls'], 'controls')
    need(len(payload['queryPresentations']['data']) <= 48 and type(payload['containers']) is list
         and payload['containers'], 'draft.native_payload_bounds')
    need(type(request['model_context']) is dict and request['model_context'].get('environment') == 'development'
         and check_model(request['model_files'], request['model_context'])['status'] == 'passed', 'draft.static_model_not_passed')
    _query_bindings(payload, request['model_files'], request['model_context'])
    scan = scan_bytes(native._json_bytes(request), 'request.json')
    need(scan['status'] == 'clear' and scan['coverage']['complete'], 'draft.disclosure_scan_not_clear')
    return copy.deepcopy(request)


def _query_bindings(payload, files, context):
    """Reject known dangling topic/field references, not a query compiler."""
    definitions, topics = {}, {}
    for path, text in files.items():
        name = Path(path).name
        if name.endswith(('.yaml','.yml')): name = name.rsplit('.',1)[0]
        if name.endswith('.view'): definitions[name[:-5]] = _load(text)
        elif name.endswith('.topic'): topics[name[:-6]] = _load(text)
    for name, inherited in context['inherited_views'].items():
        definitions[name] = _merge(inherited['definition'], definitions.get(name, {}))
    resolved = {}
    def resolve(name, trail=()):
        need(name in definitions and name not in trail and len(trail) < 32, 'draft.query_inheritance_unresolved')
        if name not in resolved:
            view = definitions[name]; combined = {}
            for base in view.get('extends', []): combined = _merge(combined, resolve(base, trail + (name,)))
            resolved[name] = _merge(combined, view)
        return resolved[name]
    for tile in payload['queryPresentations']['data'].values():
        if tile['type'] != 'query': continue
        need(tile.get('isSql') is None or tile.get('isSql') is False, 'draft.raw_sql_mode_unqualified')
        name, query = tile['topicName'], tile['query']
        need(name in topics, 'draft.query_topic_unresolved')
        need(not query.get('calculations') and not query.get('userEditedSQL') and not query.get('sql'),
             'draft.query_calculations_or_sql_unqualified')
        topic = topics[name]; included = {topic['base_view']}
        def collect(tree):
            for child, nested in tree.items(): included.add(child); collect(nested)
        collect(topic.get('joins', {}))
        for field in query['fields']:
            match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)(?:\[([A-Za-z_][A-Za-z0-9_]*)\])?', field) if type(field) is str else None
            need(match is not None and match.group(1) in included, 'draft.query_field_unresolved')
            view, dimension, timeframe = match.groups(); definition = resolve(view)
            fields = dict(definition.get('dimensions', {}), **definition.get('measures', {}))
            need(dimension in fields, 'draft.query_field_unresolved')
            if timeframe:
                need(timeframe.lower() in [value.lower() for value in fields[dimension].get('timeframes', [])],
                     'draft.query_timeframe_unresolved')
            if 'fields' in topic:
                need(field in topic['fields'], 'draft.query_field_outside_topic')


def _inventory(value, label, numeric=False):
    need(type(value) is dict and set(value) == {'data','order'} and type(value['data']) is dict
         and type(value['order']) is list and all(type(x) is str for x in value['order'])
         and len(value['order']) == len(set(value['order'])) and set(value['order']) == set(value['data'])
         and all(type(item) is dict for item in value['data'].values()), 'draft.' + label + '_inventory')
    need(all(re.fullmatch(r'[1-9][0-9]*', key) if numeric else _id(key) for key in value['data']),
         'draft.' + label + '_keys')


def _approval(request, policy, digest, envelope):
    try:
        payload = verify_attestation(envelope, policy, purpose='deployment_approval',
                                     bindings=request_bindings(request, digest))
    except (ValueError, TypeError, KeyError):
        raise native.AdapterError('draft.approval_invalid') from None
    claims = payload.get('claims')
    preflight = claims.get('preflight') if type(claims) is dict else None
    need(type(preflight) is dict and preflight.get('target_sha256') == canonical_hash(request['target'])
         and preflight.get('document_id') == request['document_id']
         and preflight.get('audience_sha256') == request['expected_access_sha256']
         and all(preflight.get(k) is True for k in ('principal_namespace_verified','permissions_verified',
             'existing_destination_approved','synthetic_data_only','isolated_destination','branch_exclusive','document_exclusive'))
         and native._sha(preflight.get('access_policy_sha256')) and native._sha(preflight.get('evidence_sha256'))
         and type(preflight.get('evidence_reference')) is str and preflight['evidence_reference'].strip(),
         'draft.preflight_required')
    return payload


def _client(policy, target, transport):
    if transport is not None:
        return transport, 'simulation'
    need(policy['mode'] == 'live', 'draft.simulation_requires_injected_transport')
    return HTTPSOmniDraftTransport(target['instance_url']), 'live'


def _access(transport, document_id):
    rows, seen, cursor, totals = [], set(), None, set()
    for _ in range(MAX_ACCESS_PAGES):
        params = {'pageSize': 100}
        if cursor: params['cursor'] = cursor
        data = native._get(transport, '/api/v1/documents/' + document_id + '/access-list', params)
        need(type(data) is dict and type(data.get('principals')) is list
             and type(data.get('pageInfo')) is dict, 'draft.access_inventory')
        page = data['pageInfo']
        need(type(page.get('hasNextPage')) is bool and type(page.get('totalRecords')) is int
             and 0 <= page['totalRecords'] <= MAX_ACCESS_PAGES * 100 and len(data['principals']) <= 100,
             'draft.access_pagination')
        totals.add(page['totalRecords'])
        for row in data['principals']:
            need(type(row) is dict and type(row.get('id')) is str and row['id']
                 and row.get('type') in ('user','userGroup')
                 and row.get('role') in ('VIEWER','INTERACTOR','EDITOR','MANAGER','OWNER')
                 and row.get('accessSource') in ('direct','folder')
                 and type(row.get('accessBoost')) is bool, 'draft.access_principal')
            need(row['accessBoost'] is False, 'draft.accessboost_not_qualified')
            signature = canonical_hash(row)
            need(signature not in seen, 'draft.access_duplicate')
            seen.add(signature); rows.append(row)
        if not page['hasNextPage']:
            need(page.get('nextCursor') is None and len(totals) == 1 and len(rows) == page['totalRecords'],
                 'draft.access_incomplete')
            return {'sha256': canonical_hash(sorted(rows, key=canonical_hash)), 'count': len(rows)}
        next_cursor = page.get('nextCursor')
        need(type(next_cursor) is str and next_cursor and len(next_cursor) <= 4096 and next_cursor != cursor,
             'draft.access_cursor')
        cursor = next_cursor
    raise native.AdapterError('draft.access_page_limit')


def _document(transport, target, document_id, draft_id=None):
    path = '/api/v2/documents/' + document_id + ('/draft/' + draft_id if draft_id else '')
    data = native._get(transport, path)
    need(type(data) is dict and data.get('modelId') == target['model_id']
         and native._uuid(data.get('workbookModelId')) and type(data.get('name')) is str
         and 'description' in data and (data['description'] is None or type(data['description']) is str)
         and 'app' not in data, 'draft.document_identity')
    _inventory(data.get('queryPresentations'), 'remote_tiles', numeric=True)
    if 'controls' in data: _inventory(data['controls'], 'remote_controls')
    need('containers' not in data or type(data['containers']) is list, 'draft.remote_layout')
    if draft_id:
        need(data.get('draftOf') == {'identifier': document_id}, 'draft.parent_mismatch')
    else:
        need('draftOf' not in data, 'draft.published_document_required')
    return data


def _drafts(transport, document_id):
    data = native._get(transport, '/api/v1/documents/' + document_id + '/drafts')
    need(type(data) is list and len(data) <= 100, 'draft.inventory_incomplete')
    ids = set()
    for row in data:
        need(type(row) is dict and _id(row.get('identifier')) and row['identifier'] not in ids
             and row.get('publishedIdentifier') == document_id and row.get('status') == 'active'
             and native._uuid(row.get('workbookModelId')) and type(row.get('draftOutOfDate')) is bool,
             'draft.inventory_item')
        branch = row.get('branch')
        need('branch' in row and (branch is None or type(branch) is dict and native._uuid(branch.get('id'))),
             'draft.inventory_branch')
        ids.add(row['identifier'])
    return sorted(data, key=lambda x: x['identifier'])


def _state(transport, request):
    model = native._state(transport, request['target'])
    document = _document(transport, request['target'], request['document_id'])
    drafts = _drafts(transport, request['document_id'])
    access = _access(transport, request['document_id'])
    return {'model': model, 'document': document, 'drafts': drafts, 'access': access,
            'hashes': {'model': model['hashes'], 'document_sha256': canonical_hash(document),
                       'drafts_sha256': canonical_hash(drafts), 'access_sha256': access['sha256']}}


def _assert_stable(state, request):
    need(state['hashes']['model'] == request['expected_model'] and state['hashes']['document_sha256'] == request['expected_document_sha256']
         and state['hashes']['access_sha256'] == request['expected_access_sha256'], 'draft.snapshot_changed')
    need(state['model']['snapshots']['authored']['files'] == request['model_files'], 'draft.model_candidate_mismatch')
    need('UPDATE' in state['model']['identity']['permissions'], 'draft.model_permission_missing')


def _expected_document(published, payload):
    # A complete source inventory must not hide old tiles or controls under the
    # API's shallow merge semantics. The seed blank at key 1 may be replaced.
    for key in ('queryPresentations','controls'):
        old = published.get(key, {'data': {}, 'order': []})
        need(set(old['data']) <= set(payload[key]['data']), 'draft.unmapped_existing_content')
    expected = copy.deepcopy(published)
    for key, value in payload.items():
        if key == 'summary': continue
        if key == 'settings':
            settings = expected.setdefault('settings', {})
            for name, item in value.items():
                if name == 'controlBar' and type(item) is dict:
                    settings.setdefault(name, {}).update(copy.deepcopy(item))
                else: settings[name] = copy.deepcopy(item)
        else: expected[key] = copy.deepcopy(value)
    return expected


def _comparable_document(value):
    normalized = copy.deepcopy(value)
    normalized.pop('workbookModelId', None); normalized.pop('draftOf', None)
    for tile in normalized['queryPresentations']['data'].values():
        tile.pop('model_extension_id', None)
    return normalized


def _confirm(transport, request, state, baseline_drafts, draft_id, expected):
    _assert_stable(state, request)
    current = {row['identifier']: row for row in state['drafts']}
    old = baseline_drafts
    need(all(key in current and canonical_hash(current[key]) == digest for key, digest in old.items())
         and set(current) - set(old) == {draft_id}, 'draft.other_drafts_changed')
    row = current[draft_id]
    need(row['branch'] is not None and row['branch']['id'] == request['target']['branch_id']
         and row['draftOutOfDate'] is False, 'draft.branch_or_freshness_mismatch')
    document = _document(transport, request['target'], request['document_id'], draft_id)
    need(document['workbookModelId'] == row['workbookModelId'], 'draft.workbook_mismatch')
    need(_comparable_document(document) == _comparable_document(expected), 'draft.readback_mismatch')
    return canonical_hash(document)


def run(request, *, policy_path, candidate_root, approval=None, transport=None):
    receipt = {'schema_version': 1, 'kind': 'omni_dashboard_native_receipt', 'contract_version': CONTRACT,
               'status': 'blocked', 'execution_mode': 'simulation' if transport is not None else 'live',
               'native_verified': False, 'native_qualification': 'pending', 'draft_created': False,
               'dashboard_tested': False, 'published': False, 'code': None,
               'observed_at': datetime.now(timezone.utc).isoformat()}
    journal = None
    try:
        request = validate_request(request)
        policy, policy_hash = _policy(policy_path, candidate_root, request)
        receipt.update(request_bindings(request, policy_hash), target=request['target'])
        client, mode = _client(policy, request['target'], transport); receipt['execution_mode'] = mode
        if mode == 'live' and not client.available:
            receipt.update(status='pending', code='credentials.unavailable'); return receipt
        def authorize():
            current, digest = _policy(policy_path, candidate_root, request)
            need(digest == policy_hash, 'draft.policy_changed')
            return _approval(request, current, digest, approval)
        authorized = authorize(); receipt['approval_id'] = authorized['id']
        # One durable identity per provisioned document/branch also prevents a
        # new run ID from duplicating an unresolved create on the same target.
        journal_request = copy.deepcopy(request)
        journal_request['run_id'] = 'draft-' + canonical_hash({'target': request['target'], 'document': request['document_id']})[:40]
        journal = native._Journal(policy, candidate_root, journal_request, policy_hash)
        state = _state(client, request); _assert_stable(state, request)
        operation = journal.data.get('draft_operation')
        if operation is None:
            need(state['hashes']['drafts_sha256'] == request['expected_drafts_sha256'], 'draft.inventory_changed')
            need(all(row['branch'] is None or row['branch']['id'] != request['target']['branch_id'] for row in state['drafts']),
                 'draft.existing_branch_draft_preserved')
            expected = _expected_document(state['document'], request['build_spec']['native_payload'])
            operation = {'state': 'prepared', 'baseline_drafts': {row['identifier']: canonical_hash(row) for row in state['drafts']},
                         'expected_content_sha256': canonical_hash(_comparable_document(expected)), 'draft_id': None}
            journal.data['draft_operation'] = operation; journal.save()
        else:
            need(type(operation) is dict and operation.get('state') in ('prepared','intent','unknown','created','confirmed'), 'draft.journal_shape')
            expected = _expected_document(state['document'], request['build_spec']['native_payload'])
            need(operation['expected_content_sha256'] == canonical_hash(_comparable_document(expected)), 'draft.journal_content_changed')
        if operation['state'] == 'prepared':
            # A second complete read immediately before the write narrows races;
            # this is not a server-side CAS and exclusive ownership is required.
            fresh = _state(client, request); _assert_stable(fresh, request)
            need({row['identifier']: canonical_hash(row) for row in fresh['drafts']} == operation['baseline_drafts'], 'draft.concurrent_draft')
            authorize()
            body = dict(request['build_spec']['native_payload'], branchId=request['target']['branch_id'])
            operation['state'] = 'intent'; journal.save()
            try:
                reply = client.request('PATCH', '/api/v2/documents/' + request['document_id'] + '/draft', body=body)
                need(type(reply) is native.Response and type(reply.status) is int and type(reply.body) is bytes,
                     'draft.response_shape')
                if reply.status != 200:
                    raise native.TransportError('transport.http', reply.status, reply.status >= 500 or reply.status == 408)
                result = native._json(reply.body)
                need(type(result) is dict and result.get('identifier') == request['document_id']
                     and _id(result.get('draftIdentifier')), 'draft.creation_response_unconfirmed')
                operation.update(state='created', draft_id=result['draftIdentifier']); journal.save()
            except (native.TransportError, ValueError, TypeError):
                operation['state'] = 'unknown'; journal.save(); raise
            state = _state(client, request)
        if operation['draft_id'] is None:
            old = set(operation['baseline_drafts'])
            added = [row for row in state['drafts'] if row['identifier'] not in old]
            if not added:
                receipt.update(status='pending', code='draft.unknown_creation_requires_reconciliation'); return receipt
            need(len(added) == 1, 'draft.ambiguous_creation')
            operation['draft_id'] = added[0]['identifier']
        draft_id = operation['draft_id']
        content_hash = _confirm(client, request, state, operation['baseline_drafts'], draft_id, expected)
        # Read published/model/access/draft inventory again after reading draft
        # content; repeat the exact draft read so a concurrent edit cannot pass.
        after = _state(client, request)
        need(after['hashes'] == state['hashes'], 'draft.changed_during_readback')
        need(_confirm(client, request, after, operation['baseline_drafts'], draft_id, expected) == content_hash,
             'draft.changed_during_readback')
        operation.update(state='confirmed', draft_id=draft_id, readback_sha256=content_hash); journal.save()
        receipt.update(status='passed' if mode == 'live' else 'simulated_passed', native_verified=mode == 'live',
                       draft_created=True, draft_id=draft_id, readback_sha256=content_hash,
                       remote_before=state['hashes'], remote_after=after['hashes'],
                       coverage=copy.deepcopy(request['build_spec']['coverage']),
                       recovery={'automatic_rollback': False, 'published_document_unchanged': True,
                                 'next_step': 'Review this exact branch draft; discard only with separate authorization.'})
    except native.TransportError as error:
        receipt.update(status='pending' if error.uncertain or error.status in (408,429,500,502,503,504) else 'failed',
                       code=error.code, http_status=error.status)
    except native.AdapterError as error:
        receipt.update(status='blocked', code=str(error))
    except (ValueError, TypeError, OSError, RecursionError, KeyError, UnicodeError, AttributeError):
        receipt.update(status='blocked', code='draft.invalid_or_unverified_state')
    finally:
        if journal:
            saved = journal.data.get('draft_operation')
            if type(saved) is dict:
                receipt['remote_write_state'] = saved.get('state')
                if saved.get('draft_id'): receipt['draft_id'] = saved['draft_id']
            journal.close()
    return receipt


def inspect_remote(target, document_id, *, policy_path, candidate_root, destination_id, transport=None):
    native.validate_target(target); need(_id(document_id), 'draft.document_id')
    request = {'target': target, 'document_id': document_id, 'destination_id': destination_id}
    policy, _ = _policy(policy_path, candidate_root, request)
    client, mode = _client(policy, target, transport)
    if mode == 'live' and not client.available:
        return {'status': 'pending', 'code': 'credentials.unavailable', 'native_verified': False}
    state = _state(client, request)
    return {'schema_version': 1, 'kind': 'omni_dashboard_remote_snapshot', 'status': 'private_snapshot',
            'execution_mode': mode, 'native_verified': False, 'target': target, 'document_id': document_id,
            'expected_model': state['hashes']['model'], 'expected_document_sha256': state['hashes']['document_sha256'],
            'expected_drafts_sha256': state['hashes']['drafts_sha256'], 'expected_access_sha256': state['hashes']['access_sha256'],
            'document': state['document'], 'drafts': state['drafts'], 'access_count': state['access']['count']}


def verify_receipt(request, receipt, policy_sha256):
    result = {'status': 'failed', 'authenticated': False, 'native_qualification': 'pending'}
    try:
        validate_request(request); native._json_bytes(receipt)
        need(type(receipt) is dict and receipt.get('kind') == 'omni_dashboard_native_receipt'
             and receipt.get('schema_version') == 1 and receipt.get('contract_version') == CONTRACT, 'draft.receipt_schema')
        need(all(receipt.get(key) == value for key, value in request_bindings(request, policy_sha256).items())
             and receipt.get('target') == request['target'], 'draft.receipt_bindings')
        mode, status = receipt.get('execution_mode'), receipt.get('status')
        need(mode in ('live','simulation') and status in ('passed','simulated_passed','blocked','pending','failed')
             and type(receipt.get('native_verified')) is bool and receipt.get('published') is False
             and receipt.get('dashboard_tested') is False, 'draft.receipt_scope')
        if status in ('passed','simulated_passed'):
            need((mode == 'live' and status == 'passed' and receipt['native_verified'])
                 or (mode == 'simulation' and status == 'simulated_passed' and not receipt['native_verified']), 'draft.receipt_mode')
            before, after = receipt.get('remote_before'), receipt.get('remote_after')
            need(type(before) is dict and before == after and before.get('model') == request['expected_model']
                 and before.get('document_sha256') == request['expected_document_sha256']
                 and before.get('access_sha256') == request['expected_access_sha256']
                 and native._sha(before.get('drafts_sha256')) and native._sha(receipt.get('readback_sha256'))
                 and _id(receipt.get('draft_id')) and receipt.get('draft_created') is True
                 and receipt.get('coverage') == request['build_spec']['coverage'], 'draft.receipt_readback')
        else: need(receipt['native_verified'] is False, 'draft.receipt_not_passed')
        result['status'] = 'integrity_verified'
    except (ValueError, TypeError, KeyError, RecursionError): pass
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect','bindings','run'))
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = native._json(native._read(args.request))
        approval = native._json(native._read(args.approval)) if args.approval else None
        if args.action == 'inspect':
            result = inspect_remote(request['target'], request['document_id'], policy_path=args.policy,
                                    candidate_root=args.candidate_root, destination_id=request['destination_id'])
        elif args.action == 'bindings':
            validate_request(request); _, digest = _policy(args.policy, args.candidate_root, request)
            result = request_bindings(request, digest)
        else:
            result = run(request, policy_path=args.policy, candidate_root=args.candidate_root, approval=approval)
        native._private_file(outside(args.output, (args.candidate_root,)), result)
        print(json.dumps({'status': result.get('status','private_bindings'), 'native_verified': result.get('native_verified',False)}))
        return 0 if args.action == 'bindings' or result.get('status') in ('passed','private_snapshot') else 1
    except (ValueError, TypeError, OSError, KeyError, native.TransportError):
        print(json.dumps({'status':'blocked','code':'draft.invalid_or_unavailable_input','native_verified':False})); return 1


if __name__ == '__main__': raise SystemExit(main())
