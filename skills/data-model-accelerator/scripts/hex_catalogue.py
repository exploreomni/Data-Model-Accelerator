"""Build and verify metadata for the synthetic Hex case only; no warehouse access."""
from __future__ import annotations
import csv
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from hex_source import inspect_repo
from hex_execution import RAW_COLUMNS, CONNECTION_ID, PLATFORM
from verify_catalogue import verify, valid_sha, unique_object, METADATA_FIELDS

PINNED_EXPORTS = {
    'exports/objects.json': '47a0e3435721442bcf9b294092b25f5764cea94644d96b0db4ab4b05b4a2d4e2',
    'exports/columns.json': 'c4d59c343cf8eec97bfcaa06e6c2fa1d221f6aaa05d063a09581080a970363bf',
}
CONTEXT = {'platform_instance':PLATFORM,'connection_id':CONNECTION_ID,'catalog':'DMA_HEX','schema':'RAW',
           'location':'synthetic-location-not-a-real-region'}


def _sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _json(path): return json.loads(Path(path).read_text(),object_pairs_hook=unique_object)
def _write(path,value): Path(path).write_text(json.dumps(value,indent=2)+'\n')


def _normal_type(column):
    dtype=column['DATA_TYPE']
    if dtype=='TEXT': return 'VARCHAR'
    if dtype=='NUMBER':
        if type(column.get('NUMERIC_PRECISION')) is not int or type(column.get('NUMERIC_SCALE')) is not int:
            raise ValueError('Native numeric precision/scale missing or invalid')
        return f"NUMBER({column['NUMERIC_PRECISION']},{column['NUMERIC_SCALE']})"
    if dtype in ('VARCHAR','BOOLEAN'): return dtype
    raise ValueError('Unsupported native metadata type: '+str(dtype))


def _ddl_columns(case):
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ErrorLevel
    result={}
    path=case/'target/snowflake/00_raw_contract.sql'
    for tree in sqlglot.parse(path.read_text(),read='snowflake',error_level=ErrorLevel.RAISE):
        if not isinstance(tree,exp.Create) or str(tree.args.get('kind')).upper()!='TABLE': continue
        if not isinstance(tree.this,exp.Schema): raise ValueError('Raw bootstrap requires explicit column declarations')
        table=tree.this.this
        if (table.catalog,table.db)!=('DMA_HEX','RAW'): raise ValueError('Raw DDL namespace mismatch')
        if table.name in result: raise ValueError('Duplicate bootstrap table identity')
        result[table.name]=[]
        for column in tree.this.expressions:
            if not isinstance(column,exp.ColumnDef): raise ValueError('Unsupported bootstrap table constraint')
            native_type=column.args['kind'].sql(dialect='snowflake').replace(' ','').replace('DECIMAL(', 'NUMBER(')
            nullable=not any(isinstance(c.args.get('kind'),exp.NotNullColumnConstraint) for c in column.args.get('constraints',[]))
            result[table.name].append({'path':[column.name],'data_type':native_type,'nullable':nullable})
    return result


def _validate_inputs(case, ddl):
    raw=_json(case/'input/raw-data.json')
    if not isinstance(raw,dict) or set(raw)!={'origin','snapshot_at','INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY'} or raw['origin']!='synthetic':
        raise ValueError('Raw fixture identity/table inventory mismatch')
    csv_path=case/'input/repo/adjustments.csv'
    with csv_path.open(newline='') as stream:
        reader=csv.DictReader(stream)
        if reader.fieldnames!=list(RAW_COLUMNS['ADJUSTMENTS']): raise ValueError('CSV column inventory/order mismatch')
        adjustments=list(reader)
    if set(ddl)!=set(RAW_COLUMNS): raise ValueError('Raw DDL table inventory differs from simulation contract')
    for table,columns in RAW_COLUMNS.items():
        if [c['path'][0] for c in ddl[table]]!=list(columns): raise ValueError('Raw DDL column inventory differs from simulation contract: '+table)
        rows=adjustments if table=='ADJUSTMENTS' else raw[table]
        if not isinstance(rows,list) or (not rows and table!='ADJUSTMENTS'):
            raise ValueError('Empty or missing synthetic raw table: '+table)
        for row in rows:
            if not isinstance(row,dict) or set(row)!=set(columns): raise ValueError('Raw fixture column inventory mismatch: '+table)
            for name,kind in columns.items():
                value=row[name]
                if value is None:
                    if table!='CUSTOMER_HISTORY' or name!='VALID_TO': raise ValueError('Required logical raw value missing: '+table+'.'+name)
                elif kind=='BIGINT':
                    if table=='ADJUSTMENTS':
                        if not isinstance(value,str) or not re.fullmatch(r'[+-]?\d+',value): raise ValueError('Invalid CSV integer value')
                    elif type(value) is not int: raise ValueError('Raw integer value required: '+name)
                elif kind=='BOOLEAN' and type(value) is not bool: raise ValueError('Raw boolean value required')
                elif kind=='DATE':
                    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value: raise ValueError('Raw ISO date text required')
                elif kind=='VARCHAR' and (not isinstance(value,str) or not value): raise ValueError('Raw nonempty text required')
    return {'raw_snapshot_at':raw['snapshot_at'],'raw_sha256':_sha(case/'input/raw-data.json'),'csv_sha256':_sha(csv_path),
            'row_counts':{t:len(adjustments if t=='ADJUSTMENTS' else raw[t]) for t in RAW_COLUMNS}}


def _read_receipts(case):
    folder=case/'input/catalogue';provenance=_json(folder/'provenance.json')
    if provenance.get('origin')!='synthetic' or provenance.get('kind')!='synthetic_hex_catalogue_provenance' or provenance.get('context')!=CONTEXT:
        raise ValueError('Synthetic catalogue provenance/account/connection context mismatch')
    if provenance.get('exports')!=PINNED_EXPORTS: raise ValueError('Input export pins differ from the reviewed synthetic receipts')
    receipts={}
    for relative,pin in PINNED_EXPORTS.items():
        path=folder/relative
        if path.is_symlink() or not path.is_file() or _sha(path)!=pin: raise ValueError('Pinned synthetic export hash mismatch: '+relative)
        value=_json(path)
        if value.get('origin')!='synthetic' or value.get('context')!=CONTEXT or value.get('captured_at')!=provenance.get('captured_at'):
            raise ValueError('Synthetic native receipt context/capture mismatch')
        receipts[Path(relative).stem]=value
    return provenance,receipts


def normalize_receipts(objects, columns, ddl):
    """Validate native-shaped rows against independently parsed bootstrap schema."""
    identities={}
    for row in objects:
        if set(row)!={'TABLE_CATALOG','TABLE_SCHEMA','TABLE_NAME','TABLE_TYPE'}: raise ValueError('Native object metadata shape mismatch')
        if (row['TABLE_CATALOG'],row['TABLE_SCHEMA'])!=('DMA_HEX','RAW') or row['TABLE_TYPE']!='BASE TABLE': raise ValueError('Native object identity/type mismatch')
        name=row['TABLE_NAME']
        if name in identities or name not in ddl: raise ValueError('Duplicate/unknown/case-mismatched native object')
        identities[name]=[]
    if set(identities)!=set(ddl): raise ValueError('Native object inventory incomplete')
    seen=set()
    for row in columns:
        if set(row)!={'TABLE_CATALOG','TABLE_SCHEMA','TABLE_NAME','COLUMN_NAME','ORDINAL_POSITION','DATA_TYPE','NUMERIC_PRECISION','NUMERIC_SCALE','IS_NULLABLE'}:
            raise ValueError('Native column metadata shape mismatch')
        name=row['TABLE_NAME'];key=(name,row['COLUMN_NAME'])
        if (row['TABLE_CATALOG'],row['TABLE_SCHEMA'])!=('DMA_HEX','RAW') or name not in identities: raise ValueError('Native column namespace mismatch')
        if key in seen: raise ValueError('Duplicate native column')
        seen.add(key)
        if type(row['ORDINAL_POSITION']) is not int or row['ORDINAL_POSITION']!=len(identities[name])+1: raise ValueError('Native column ordinal order mismatch')
        if row['IS_NULLABLE'] not in ('YES','NO'): raise ValueError('Native column nullability invalid')
        identities[name].append({'path':[row['COLUMN_NAME']],'data_type':_normal_type(row),'nullable':row['IS_NULLABLE']=='YES'})
    if identities!=ddl: raise ValueError('Native metadata does not exactly match bootstrap column names/types/nullability/order')
    return identities


def build_catalogue(case, output_dir, source_snapshot_sha256):
    """Reconstruct current synthetic metadata only, with original receipt timestamps.

    The caller supplies the canonical source-inventory hash and must confirm it
    against that inventory. This function also records current Hex asset hashes.
    """
    case=Path(case).resolve();output=Path(output_dir).resolve()
    if not valid_sha(source_snapshot_sha256): raise ValueError('Canonical source snapshot SHA-256 required')
    provenance,receipts=_read_receipts(case)
    ddl=_ddl_columns(case);input_evidence=_validate_inputs(case,ddl)
    normalized=normalize_receipts(receipts['objects']['rows'],receipts['columns']['rows'],ddl)
    graph=inspect_repo(case/'input/repo')
    if graph['counts']['errors']: raise ValueError('Hex source graph has unresolved static errors')
    source_cells={c['id']:c for c in graph['cells']}
    references=[];warehouse_names=set()
    for edge in graph['edges']:
        if edge['kind']!='warehouse_read': continue
        cell=source_cells[edge['to']];physical=edge['evidence'];parts=physical.split('.')
        if cell.get('connection_id')!=CONNECTION_ID or len(parts)!=3 or parts[:2]!=['DMA_HEX','RAW'] or parts[2] not in RAW_COLUMNS or parts[2]=='ADJUSTMENTS':
            raise ValueError('Unknown/unapproved Hex warehouse source binding: '+physical)
        table=parts[2];warehouse_names.add(table)
        rid='hex:'+cell['id']+':'+physical
        references.append({'reference_id':rid,'source_reference':cell['path']+'#'+str(cell['cell_id'])+': '+physical,
            'status':'resolved','object_id':'snowflake:'+PLATFORM+':'+physical,'column_paths':[c['path'] for c in normalized[table]],
            'namespace':{'platform_instance':PLATFORM,'catalog':'DMA_HEX','schema':'RAW'},
            'connection_id':CONNECTION_ID,'source_kind':'hex_warehouse_query',
            'evidence':'Schema-parsed Hex warehouse read in this scoped source cell; the synthetic scenario supplies the account binding. Full raw input columns are explicitly selected as modeling context, not claimed as column-level SQL lineage.'})
    if warehouse_names!={'INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY'}: raise ValueError('Hex warehouse source inventory differs from three-table synthetic contract')
    file_edges=[e for e in graph['edges'] if e['kind']=='file_read' and e['from']=='file:adjustments.csv']
    if not file_edges or any(e['sha256']!=input_evidence['csv_sha256'] for e in file_edges): raise ValueError('CSV source dependency/hash is missing from Hex graph')
    references.append({'reference_id':'proposed-csv-landing:DMA_HEX.RAW.ADJUSTMENTS','source_reference':'input/repo/adjustments.csv -> proposed DMA_HEX.RAW.ADJUSTMENTS',
        'status':'resolved','object_id':'snowflake:'+PLATFORM+':DMA_HEX.RAW.ADJUSTMENTS',
        'column_paths':[c['path'] for c in normalized['ADJUSTMENTS']],
        'namespace':{'platform_instance':PLATFORM,'catalog':'DMA_HEX','schema':'RAW'},
        'source_kind':'proposed_governed_csv_landing','source_file_sha256':input_evidence['csv_sha256'],
        'evidence':'Proposed modeled input from the supplied CSV and candidate bootstrap DDL; not an existing Hex warehouse query or evidence that this table is deployed. File read edges: '+', '.join(e['to'] for e in file_edges)})
    output.mkdir(parents=True,exist_ok=True);(output/'exports').mkdir(exist_ok=True)
    extractions=[]
    for component in ('objects','columns'):
        relative='exports/'+component+'.json';source=case/'input/catalogue'/relative;dest=output/relative
        if source.resolve()!=dest.resolve(): shutil.copyfile(source,dest)
        extractions.append({'extraction_id':component,'scope_id':'dma-hex-raw','component':component,'status':'complete','artifact_path':relative,
                            'sha256':PINNED_EXPORTS[relative],'query_id':None,'pagination_complete':True})
    catalogue={'schema_version':1,'kind':'warehouse_raw_catalogue','provider':'snowflake','origin':'synthetic',
        'captured_at':datetime.now(timezone.utc).isoformat(),
        'capture_basis':'Fresh local reconstruction validated against current synthetic inputs and bootstrap DDL; no warehouse query and no change to pinned receipt capture times.',
        'source_receipt_captured_at':provenance['captured_at'],
        'context':{'platform_instance':PLATFORM,'principal':'synthetic_metadata_builder','connection_id':CONNECTION_ID,
                   'scope':[{'scope_id':'dma-hex-raw','catalog':'DMA_HEX','schema':'RAW','location':CONTEXT['location']}]},
        'coverage':{'status':'complete_for_visible_scope','gaps':[],'scope_meaning':'Exactly four authored synthetic bootstrap objects, including one proposed CSV landing; not a discovered account inventory.'},
        'extractions':extractions,'objects':[],'input_evidence':input_evidence,'bootstrap_sha256':_sha(case/'target/snowflake/00_raw_contract.sql')}
    for table,columns in normalized.items():
        catalogue['objects'].append({'object_id':'snowflake:'+PLATFORM+':DMA_HEX.RAW.'+table,'scope_id':'dma-hex-raw',
            'identity':{'catalog':'DMA_HEX','schema':'RAW','name':table},'object_type':'BASE TABLE','columns':columns,
            'metadata_status':{field:'unknown' for field in METADATA_FIELDS},
            'lifecycle':'proposed_governed_csv_landing' if table=='ADJUSTMENTS' else 'synthetic_replication_source_contract',
            'evidence':[{'extraction_id':c,'locator':"rows[TABLE_NAME='"+table+"']"} for c in ('objects','columns')],
            'logical_nullability':'Scenario requires every field except CUSTOMER_HISTORY.VALID_TO; physical bootstrap columns all allow null. Validation is separate from enforcement.',
            'simulation_types':RAW_COLUMNS[table],
            'simulation_type_note':'DATE runtime fields parse physical VARCHAR date strings; BIGINT runtime fields simulate physical NUMBER(38,0). This is not Snowflake native type introspection.'})
    catalogue_path=output/'warehouse-catalogue.json';_write(catalogue_path,catalogue)
    bindings={'schema_version':1,'kind':'warehouse_catalogue_bindings','catalogue_sha256':_sha(catalogue_path),
        'source_snapshot_sha256':source_snapshot_sha256,'expected_reference_ids':[r['reference_id'] for r in references],
        'references':references,'source_assets':graph['assets'],'source_snapshot_binding_note':'Caller supplies canonical inventory hash; current parsed source asset hashes are retained for independent alignment.'}
    bindings_path=output/'catalogue-bindings.json';_write(bindings_path,bindings)
    verification=verify(catalogue_path,bindings_path)
    verification['native_metadata_consistency']={'objects':len(normalized),'columns':sum(len(v) for v in normalized.values()),
        'bootstrap_types_nulls_case_match':True,'raw_fixture_columns_match':True,'pinned_export_hashes_match':True,
        'source_graph_physical_refs_match':True,'native_warehouse_execution':False}
    if not verification['catalogue_context_complete']: raise ValueError('Generated synthetic catalogue failed verification: '+repr(verification))
    _write(output/'catalogue-verification.json',verification)
    return {'catalogue_path':str(catalogue_path),'bindings_path':str(bindings_path),'verification':verification}
