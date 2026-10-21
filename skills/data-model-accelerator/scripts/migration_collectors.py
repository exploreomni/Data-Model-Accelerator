"""Bounded private parity collection with exact existing execution authority.

Omni reuses its native runner's policy, signed approval, snapshot, journal and
query contracts. BigQuery uses a separately signed, SELECT-only jobs.query
request. No network happens on import. No automatic retry/resubmission occurs.
Live execution observation is not authenticated imported parity or acceptance.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler

from ae_common import hash_json, load_json, require, _json_bytes
from deployment_authority import canonical_path, load_policy, outside, verify_attestation
import omni_native as native

CONTRACT='migration-bigquery-v1-2026-10-20'
MAX_BYTES=native.MAX_BYTES
MAX_BILLED=1_000_000_000


def public_summary(result):
    """Safe to serialize to ordinary status/UI; no query text, rows or errors."""
    return {k:result[k] for k in ('schema_version','kind','provider','status','code','execution_mode',
            'native_verified','evidence_authenticated','acceptance_ready','request_sha256','response_sha256',
            'row_count','truncated') if k in result}


def _result(provider, request, simulated):
    return {'schema_version':1,'kind':'migration_private_collection','provider':provider,'status':'pending','code':None,
            'execution_mode':'simulation' if simulated else 'live','native_verified':False,
            'evidence_authenticated':False,'acceptance_ready':False,'request_sha256':hash_json(request),
            'observed_at':datetime.now(timezone.utc).isoformat()}


class _Tap:
    def __init__(self, transport): self.transport=transport; self.response=None
    def request(self, method, path, params=None, body=None):
        reply=self.transport.request(method,path,params=params,body=body)
        if path in ('/api/v1/query/run','/api/v1/query/wait') and reply.status==200 and reply.content_type.split(';')[0]=='application/json':
            self.response=reply.body
        return reply


def omni_body(request):
    """Exact request-body value whose hash should be frozen in the parity plan."""
    native.validate_request(request)
    require(request['operation']=='query' and request['query_mode']=='execute','collector.query_execute_only')
    return {'query':copy.deepcopy(request['query']),'branchId':request['target']['branch_id'],
            'environmentConnectionId':request['target']['environment_connection_id'],'cache':'SkipCache',
            'timezone':request['timezone'],'resultType':'json','formatResults':False}


def collect_omni(request, *, policy_path, candidate_root, approval=None, transport=None):
    """Supported JSON row capture, preserving native runner policy and recovery.

    Returned payload is private. Any injected transport is simulation. Native
    evidence authentication still belongs to the separately trusted observer.
    NDJSON/Arrow completion is unsupported here, even if the runner accepts it.
    """
    result=_result('omni',request,transport is not None); journal=None
    try:
        body=omni_body(request)
        policy,digest=native._policy(policy_path,candidate_root,request['destination_id'],request['target'])
        client,mode=native._transport(policy,request['target'],transport)
        result['execution_mode']=mode
        if mode=='live' and not client.available:
            result['code']='credentials.unavailable'; return result
        def authorize():
            current,current_hash=native._policy(policy_path,candidate_root,request['destination_id'],request['target'])
            native._need(current_hash==digest,'authorization.policy_changed')
            return native._approval(request,current,current_hash,approval)
        authorize()
        before=native._state(client,request['target'])
        native._need(bool(set(before['identity']['permissions']) & {'QUERY_TOPICS','QUERY_FULL_MODEL'}),'authorization.query_permission_missing')
        native._need(before['hashes']==request['expected_remote'],'snapshot.baseline_changed')
        native._assert_candidate(before,request)
        journal=native._Journal(policy,candidate_root,request,digest)
        baseline=journal.data.get('baseline')
        if baseline is not None:
            native._need(baseline['hashes']==before['hashes'],'snapshot.resume_dependencies_changed')
        else:
            journal.data['baseline']={'hashes':before['hashes'],'files':{k:native.canonical_hash(v) for k,v in before['snapshots']['authored']['files'].items()}}
            journal.save()
        tap=_Tap(client)
        evidence=native._query(tap,request,journal,authorize)
        after=native._state(client,request['target'])
        native._assert_candidate(after,request)
        native._need(before['hashes']==after['hashes'],'snapshot.changed_during_validation')
        if evidence.get('pending'):
            result['code']='query.pending'; return result
        if tap.response is None:
            result.update(status='unsupported',code='query.json_capture_unavailable'); return result
        rows=native._json(tap.response)
        native._need(type(rows) is list and all(type(x) is dict for x in rows) and len(rows)<=1000,'query.result_rows_required')
        digest_response=hashlib.sha256(tap.response).hexdigest()
        native._need(digest_response in evidence['response_sha256'],'query.response_binding')
        truncated=len(rows)>=request['query']['limit']
        result.update(status='unsupported' if truncated else 'collected',code='query.limit_reached' if truncated else None,
                      row_count=len(rows),truncated=truncated,response_sha256=digest_response,
                      query_sha256=hash_json(body),query=body,payload=rows,remote_before=before['hashes'],remote_after=after['hashes'],
                      native_verified=False, execution_observed=mode=='live')
    except native.TransportError as error:
        result.update(status='pending' if error.uncertain else 'failed',code=error.code)
    except native.AdapterError as error:
        result.update(status='blocked',code=str(error))
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        result.update(status='blocked',code='collector.invalid_or_unverified_state')
    finally:
        if journal: journal.close()
    return result


def validate_bigquery_request(request):
    require(type(request) is dict and set(request)=={'schema_version','kind','run_id','destination_id','target',
            'sql','allowed_tables','maximum_bytes_billed','max_rows','timeout_ms'},'collector.bigquery_request')
    require(type(request['schema_version']) is int and request['schema_version']==1 and request['kind']=='migration_bigquery_request', 'collector.version')
    require(len(_json_bytes(request))<=MAX_BYTES, 'collector.byte_limit')
    for k in ('run_id','destination_id'): require(type(request[k]) is str and native.RUN_ID.fullmatch(request[k]),'collector.identity')
    target=request['target']
    require(type(target) is dict and set(target)=={'project_id','location','principal_id','environment'} and
            target['environment']=='development' and type(target['project_id']) is str and
            re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',target['project_id']) and
            type(target['location']) is str and re.fullmatch(r'[A-Za-z0-9-]{2,40}',target['location']) and
            type(target['principal_id']) is str and 0<len(target['principal_id'])<=200,'collector.target')
    for field,lower,upper in (('maximum_bytes_billed',1,MAX_BILLED),('max_rows',1,1000),('timeout_ms',1,30000)):
        require(type(request[field]) is int and lower<=request[field]<=upper,'collector.bounds')
    require(type(request['sql']) is str and 0<len(request['sql'])<=100000, 'collector.sql')
    allowed=request['allowed_tables']
    require(type(allowed) is list and allowed and len(allowed)<=30 and len(set(allowed))==len(allowed)
            and all(type(t) is str and re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*',t) for t in allowed), 'collector.tables')
    # A deliberately narrow grammar: no scripts, DDL/DML, remote functions,
    # wildcard tables, external queries, dynamic SQL, UDFs or unqualified tables.
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.scope import traverse_scope
        trees=sqlglot.parse(request['sql'],read='bigquery')
        require(len(trees)==1 and isinstance(trees[0],exp.Select), 'collector.select_only')
        tree=trees[0]
        require(not any(isinstance(n,(exp.DDL,exp.DML,exp.Command)) or type(n).__name__ in {'Into','Lock','Execute','Parameter','Placeholder'} for n in tree.walk()), 'collector.sql_unsupported')
        functions={'Sum','Count','Avg','Min','Max','Coalesce','Cast','TryCast','Date','DateTrunc','Abs','Round','If','Case','Nullif'}
        require(all(type(n).__name__ in functions for n in tree.find_all(exp.Func)), 'collector.function_unsupported')
        for scope in traverse_scope(tree):
            for node,source in scope.selected_sources.values():
                if isinstance(source,exp.Table):
                    require(isinstance(source.this,exp.Identifier) and '.'.join((source.catalog,source.db,source.name)) in allowed, 'collector.table_outside_scope')
    except ImportError: raise ValueError('collector.sqlglot_unavailable') from None
    except Exception as error:
        if isinstance(error,ValueError): raise
        raise ValueError('collector.sql_unsupported') from None
    return request


def bigquery_body(request):
    validate_bigquery_request(request)
    return {'query':request['sql'],'useLegacySql':False,'useQueryCache':False,'location':request['target']['location'],
            'maxResults':request['max_rows'],'maximumBytesBilled':str(request['maximum_bytes_billed']),
            'timeoutMs':request['timeout_ms'],'jobTimeoutMs':str(request['timeout_ms'])}


def bigquery_bindings(request, policy_sha256):
    validate_bigquery_request(request)
    return {'adapter':CONTRACT,'action':'deploy_development','operation':'read_only_query',
            'request_sha256':hash_json(request),'target_sha256':hash_json(request['target']),'policy_sha256':policy_sha256}


class HTTPSBigQueryTransport:
    """Fixed Google HTTPS endpoint, bounded body/time, no redirects or proxies."""
    def __init__(self, timeout=30):
        self.token=os.environ.get('BIGQUERY_ACCESS_TOKEN')
        require(not self.token or not any(c in self.token for c in '\r\n'),'collector.token')
        require(type(timeout) is int and 1<=timeout<=30,'collector.timeout')
        self.timeout=timeout
        self.opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context()),native._NoRedirect())
    @property
    def available(self): return bool(self.token)
    def query(self, project, body):
        require(self.available and re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]',project),'collector.http_target')
        request=Request('https://bigquery.googleapis.com/bigquery/v2/projects/'+project+'/queries',data=_json_bytes(body),method='POST',
                        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                data=response.read(MAX_BYTES+1)
                require(response.status==200 and len(data)<=MAX_BYTES,'collector.http_response')
                return data
        except (HTTPError,URLError,TimeoutError,socket.timeout,OSError):
            raise ValueError('collector.bigquery_transport_unknown') from None


def collect_bigquery(request, *, policy_path, candidate_root, approval=None, transport=None):
    """One signed, bounded query submission; unknown outcomes never auto-retry."""
    result=_result('bigquery',request,transport is not None); claim=None
    try:
        body=bigquery_body(request)
        root=canonical_path(candidate_root); require(root.is_dir(),'collector.candidate_root')
        policy,digest=load_policy(policy_path,excluded_roots=(root,))
        require('deploy_development' in policy['allowed_actions'] and policy['destinations'].get(request['destination_id'])==request['target'],'collector.destination')
        payload=verify_attestation(approval,policy,purpose='deployment_approval',bindings=bigquery_bindings(request,digest))
        preflight=payload.get('claims',{}).get('preflight',{})
        require(all(preflight.get(k) is True for k in ('principal_namespace_verified','read_only_query','synthetic_data_only','isolated_destination','cost_limit_verified'))
                and preflight.get('target_sha256')==hash_json(request['target']),'collector.preflight')
        require(transport is not None or policy['mode']=='live','collector.simulation_requires_transport')
        client=transport or HTTPSBigQueryTransport(timeout=max(1,(request['timeout_ms']+999)//1000))
        if transport is None and not client.available:
            result['code']='credentials.unavailable'; return result
        if transport is None:
            require(policy.get('runtime_env',{}).get('BIGQUERY_ACCESS_TOKEN')==hashlib.sha256(client.token.encode()).hexdigest(), 'collector.credential_changed')
        state=outside(policy['state_root'],(root,));state.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(state.is_dir() and state.stat().st_mode & 0o077==0,'collector.private_state')
        claim=state/('migration-bigquery-'+request['run_id']+'.json')
        # Exclusive create happens before submission. An interrupted/pending run
        # must be reconciled externally; changing the payload cannot reuse its ID.
        native._private_file(claim,{'state':'intent','request_sha256':hash_json(request),'policy_sha256':digest})
        current,current_hash=load_policy(policy_path,excluded_roots=(root,))
        require(current_hash==digest,'collector.policy_changed')
        verify_attestation(approval,current,purpose='deployment_approval',bindings=bigquery_bindings(request,digest))
        raw=client.query(request['target']['project_id'],body)
        require(type(raw) is bytes and len(raw)<=MAX_BYTES,'collector.response_bounds')
        response=native._json(raw)
        require(type(response) is dict,'collector.response_shape')
        result['response_sha256']=hashlib.sha256(raw).hexdigest()
        if response.get('jobComplete') is not True:
            result.update(code='query.pending',job_reference=response.get('jobReference'))
        elif response.get('errors') or 'dmlStats' in response or 'numDmlAffectedRows' in response:
            result.update(status='failed',code='query.errors_or_mutation')
        else:
            require(type(response.get('schema')) is dict and type(response['schema'].get('fields')) is list, 'collector.response_schema')
            rows=response.get('rows',[])
            require(type(rows) is list and len(rows)<=request['max_rows'],'collector.row_limit')
            truncated=bool(response.get('pageToken')) or response.get('totalRows')!=str(len(rows))
            billed=response.get('totalBytesBilled')
            require(billed is None or type(billed) is str and billed.isdigit() and int(billed)<=request['maximum_bytes_billed'],'collector.cost_limit')
            result.update(status='unsupported' if truncated else 'collected',code='query.truncated' if truncated else None,
                          row_count=len(rows),truncated=truncated,query=body,query_sha256=hash_json(body),payload=response,
                          execution_observed=transport is None)
        native._private_file(claim,{'state':result['status'],'request_sha256':hash_json(request),'result':public_summary(result)},replace=True)
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        # Neither provider text nor input values can appear in public diagnostics.
        result.update(status='blocked',code='collector.invalid_or_unverified_state')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('provider',choices=('omni','bigquery'));p.add_argument('--request',type=Path,required=True)
    p.add_argument('--policy',type=Path,required=True);p.add_argument('--candidate-root',type=Path,required=True)
    p.add_argument('--approval',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        output=outside(args.output,(args.candidate_root,))
        require(not output.exists() and output.parent.is_dir(),'collector.output_exists')
        collect=collect_omni if args.provider=='omni' else collect_bigquery
        result=collect(load_json(args.request,MAX_BYTES),policy_path=args.policy,candidate_root=args.candidate_root,approval=load_json(args.approval))
        native._private_file(output,result)
        print(json.dumps(public_summary(result)))
        return 0 if result['status']=='collected' else 1
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        print(json.dumps({'status':'blocked','code':'collector.invalid_input'}));return 1


if __name__=='__main__':raise SystemExit(main())
