"""Generate a deterministic private Omni candidate from explicitly reviewed maps.

This compiler chooses no business definitions, relationships, access policies or
AI context. The review and input pins are declarations, not authenticated signoff.
Sharing/deployment require the separate disclosure and native evidence gates.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

from omni_contract import (CONTRACT_VERSION, NAME, DIALECTS, canonical_hash,
                           check_model, _bounded, _sha, _text, yaml)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _quote(identifier, warehouse):
    quote = '`' if warehouse in ('bigquery','databricks','clickhouse') else '"'
    return quote + identifier.replace(quote, quote * 2) + quote


def _source_reference(reference, versions):
    prefix, separator, pointer = reference.partition('#')
    _require(separator and prefix in versions and pointer.startswith('/') and len(pointer)>1,
             'generation.source_reference_invalid')
    current=versions[prefix]
    for encoded in pointer[1:].split('/'):
        # JSON Pointer escapes are the only decoding; never fetch URI targets.
        _require('~' not in encoded.replace('~0','').replace('~1',''),'generation.source_reference_invalid')
        key=encoded.replace('~1','/').replace('~0','~')
        if type(current) is dict:
            _require(key in current,'generation.source_reference_unresolved'); current=current[key]
        elif type(current) is list:
            _require(key.isdigit() and str(int(key))==key and int(key)<len(current),'generation.source_reference_unresolved')
            current=current[int(key)]
        else:
            raise ValueError('generation.source_reference_unresolved')


def generate_model(spec, context, model_version, placement_version):
    """Return files/check/manifest; no file writes or remote access in this API.

    Every emitted field must have an explicit mapping and source references.
    Physical mappings use exact catalogue names; derived SQL stays as reviewed;
    inherited overrides require a hash-bound resolved base definition.
    """
    for value in (spec, context, model_version, placement_version):
        _bounded(value)
        _require(type(value) is dict and bool(value), 'generation.object_required')
    _require(set(spec)=={'schema_version','kind','contract_version','review','pins','model','views','topics','relationships'},'generation.spec_fields')
    _require(type(spec['schema_version']) is int and spec['schema_version']==1
             and spec['kind']=='omni_generation_spec' and spec['contract_version']==CONTRACT_VERSION,'generation.version')
    _require(yaml is not None,'generation.yaml_runtime_unavailable')
    review=spec['review']
    _require(type(review) is dict and set(review)=={'status','reference','evidence_sha256','spec_sha256'}
             and review['status']=='approved' and _text(review['reference']) and _sha(review['evidence_sha256'])
             and review.get('spec_sha256')==canonical_hash({k:v for k,v in spec.items() if k!='review'}), 'generation.review_required')
    pins=spec['pins']; expected={'model_sha256':canonical_hash(model_version),
        'placement_sha256':canonical_hash(placement_version), 'context_sha256':canonical_hash(context),
        'catalogue_sha256':context.get('catalogue_sha256')}
    _require(type(pins) is dict and set(pins)==set(expected)
             and all(_sha(v) for v in pins.values()) and pins==expected,'generation.stale_pins')
    _require(type(context.get('warehouse')) is str and context['warehouse'] in DIALECTS,'generation.warehouse')
    _require(type(context.get('bindings')) is dict and type(context.get('inherited_views')) is dict,'generation.context')
    _require(type(spec['model']) is dict and type(spec['views']) is dict and bool(spec['views'])
             and type(spec['topics']) is dict and type(spec['relationships']) is list,'generation.shapes')
    files={}; mappings=[]
    if spec['model']:
        files['model']=yaml.safe_dump(spec['model'],sort_keys=True,allow_unicode=False)
    for view,item in sorted(spec['views'].items()):
        _require(NAME.fullmatch(view) is not None and type(item) is dict
                 and set(item)=={'kind','definition','field_mappings'}
                 and item['kind'] in ('physical','inherited_override')
                 and type(item['definition']) is dict and type(item['field_mappings']) is dict,'generation.view_mapping')
        definition=copy.deepcopy(item['definition']); binding=context['bindings'].get(view)
        _require(type(binding) is dict and type(binding.get('namespace')) is dict
                 and type(binding.get('columns')) is dict,'generation.binding_required')
        if item['kind']=='physical':
            ns=binding['namespace']; native={'catalog':ns.get('database',ns.get('catalog',ns.get('project'))),
                                          'schema':ns.get('schema',ns.get('dataset')),'table_name':ns.get('table')}
            for key,value in native.items():
                if value is not None:
                    _require(_text(value),'generation.namespace')
                    _require(key not in definition or definition[key]==value,'generation.namespace_conflict')
                    definition[key]=value
        else:
            _require(view in context['inherited_views'],'generation.inherited_definition_required')
        all_fields={}
        for category in ('dimensions','measures'):
            entries=definition.get(category,{})
            _require(type(entries) is dict,'generation.field_collection')
            for name,field in entries.items():
                _require(NAME.fullmatch(name) is not None and name not in all_fields
                         and type(field) is dict,'generation.field_definition')
                all_fields[name]=(category,field)
        _require(set(item['field_mappings'])==set(all_fields),'generation.mapping_coverage')
        for name,(category,field) in all_fields.items():
            mapping=item['field_mappings'][name]
            _require(type(mapping) is dict and set(mapping)<= {'kind','source_refs','column'}
                     and {'kind','source_refs'}<=set(mapping),'generation.field_mapping')
            refs=mapping['source_refs']
            _require(type(refs) is list and refs and all(_text(v) for v in refs)
                     and len(refs)==len(set(refs)),'generation.source_references')
            for reference in refs:
                _source_reference(reference,{'model':model_version,'placement':placement_version})
            kind=mapping['kind']
            _require(type(kind) is str and kind in ('physical','derived','aggregate','inherited'),'generation.mapping_kind')
            if kind=='physical':
                column=mapping.get('column')
                _require(category=='dimensions' and type(column) is str and column in binding['columns'], 'generation.column_unresolved')
                quoted=_quote(column,context['warehouse'])
                if 'sql' in field:
                    from omni_contract import sqlglot, exp
                    _require(sqlglot is not None and _text(field['sql']),'generation.sql_runtime_unavailable')
                    try:
                        trees=sqlglot.parse(field['sql'],read=DIALECTS[context['warehouse']],error_message_context=0)
                    except Exception:
                        raise ValueError('generation.physical_sql_invalid') from None
                    _require(len(trees)==1 and type(trees[0]) is exp.Column and not trees[0].table,'generation.physical_sql_invalid')
                    physical=trees[0].name.upper() if context['warehouse']=='snowflake' and not trees[0].this.args.get('quoted') else trees[0].name
                    _require(physical==column,'generation.physical_sql_conflict')
                else:
                    field['sql']=quoted
            else:
                _require('column' not in mapping,'generation.nonphysical_column')
                if kind=='derived':
                    _require(_text(field.get('sql')),'generation.derived_sql_required')
                elif kind=='aggregate':
                    _require(category=='measures' and (_text(field.get('sql')) or field.get('aggregate_type')=='count'), 'generation.aggregate_required')
                else:
                    inherited=context['inherited_views'].get(view,{})
                    _require(type(inherited) is dict and type(inherited.get('definition')) is dict
                             and name in inherited['definition'].get(category,{}),'generation.inherited_field_required')
            mappings.append({'target':view+'.'+name,'kind':kind,'source_refs':list(refs)})
        files[view+'.view']=yaml.safe_dump(definition,sort_keys=True,allow_unicode=False)
    for name,definition in sorted(spec['topics'].items()):
        _require(NAME.fullmatch(name) is not None and type(definition) is dict,'generation.topic')
        files[name+'.topic']=yaml.safe_dump(definition,sort_keys=True,allow_unicode=False)
    if spec['relationships']:
        files['relationships']=yaml.safe_dump(spec['relationships'],sort_keys=True,allow_unicode=False)
    checked=check_model(files,context)
    manifest={'schema_version':1,'kind':'omni_generation_candidate','contract_version':CONTRACT_VERSION,
              'spec_sha256':canonical_hash(spec),'pins':copy.deepcopy(pins),
              'candidate_sha256':checked['candidate_sha256'],
              'files':{name:hashlib.sha256(value.encode()).hexdigest() for name,value in sorted(files.items())},
              'field_mappings':mappings,'review_authority_authenticated':False,
              'native_verified':False,'deployment_authorized':False,
              'status':'private_candidate','static_status':checked['status']}
    return {'files':files,'check':checked,'manifest':manifest}


def write_candidate(result, output):
    """Write only a statically passed candidate into a new mode0700 directory."""
    from ae_common import _path, _json_bytes
    _require(type(result) is dict and result.get('check',{}).get('status')=='passed','generation.static_check_not_passed')
    _require(canonical_hash(result['files'])==result['check']['candidate_sha256'],'generation.candidate_changed')
    output=_path(output,must_exist=False)
    _require(not output.exists() and output.parent.is_dir(),'generation.new_output_required')
    output.mkdir(mode=0o700)
    try:
        contents={**{name:value.encode() for name,value in result['files'].items()},
                  'GENERATION_MANIFEST.json':_json_bytes(result['manifest'])+b'\n',
                  'STATIC_CHECK.json':_json_bytes(result['check'])+b'\n'}
        for name,content in contents.items():
            _require('/' not in name and '\\' not in name and name not in ('.','..'),'generation.output_path')
            fd=os.open(output/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream: stream.write(content)
    except BaseException:
        shutil.rmtree(output)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('spec','context','model-version','placement-version','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        from ae_common import load_json
        result=generate_model(load_json(args.spec),load_json(args.context),load_json(args.model_version),load_json(args.placement_version))
        if result['check']['status']!='passed':
            print(json.dumps(result['check'],sort_keys=True)); return 1
        write_candidate(result,args.output)
        summary={'status':'private_candidate','files':len(result['files']),'static_status':'passed',
                 'candidate_sha256':result['check']['candidate_sha256'],'native_verified':False,'deployment_authorized':False}
    except (ValueError,OSError,TypeError,KeyError,RecursionError,UnicodeError):
        summary={'status':'blocked','reason':'generation.invalid_or_unavailable_input','native_verified':False}
    print(json.dumps(summary,sort_keys=True))
    return 0 if summary['status']=='private_candidate' else 1


if __name__=='__main__':
    raise SystemExit(main())
