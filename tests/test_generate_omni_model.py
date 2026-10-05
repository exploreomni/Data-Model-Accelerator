"""Explicit synthetic mapping generation; never native/customer acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import generate_omni_model as generator
import omni_contract as omni
from test_omni_contract import context, files


def inputs():
    binding=context()
    model={'schema_version':1,'kind':'synthetic_model_version','tables':['events'],'version':'test-model-v1',
           'fields':{name:{'source':'synthetic-only'} for name in ('id','recorded_at','value','tenant_id')}}
    placement={'schema_version':1,'kind':'synthetic_placement_version','version':'test-placement-v1',
               'aggregate_total':'semantic','event_grain':'warehouse',
               'semantic':{name:{'placement':'semantic'} for name in ('count','total','average')}}
    definition=omni.yaml.safe_load(files()['events.view'])
    for key in ('catalog','schema','table_name'): definition.pop(key)
    fields={}
    for name,column in [('id','ID'),('recorded_at','RECORDED_AT'),('value','VALUE'),('tenant_id','TENANT_ID')]:
        definition['dimensions'][name].pop('sql')
        fields[name]={'kind':'physical','column':column,'source_refs':['model#/fields/'+name]}
    for name in ('count','total','average'):
        fields[name]={'kind':'aggregate' if name!='average' else 'derived','source_refs':['placement#/semantic/'+name]}
    spec={'schema_version':1,'kind':'omni_generation_spec','contract_version':omni.CONTRACT_VERSION,
          'review':{},'pins':{'model_sha256':omni.canonical_hash(model),'placement_sha256':omni.canonical_hash(placement),
                            'context_sha256':omni.canonical_hash(binding),'catalogue_sha256':binding['catalogue_sha256']},
          'model':{'week_start_day':'Monday'},'views':{'events':{'kind':'physical','definition':definition,'field_mappings':fields}},
          'topics':{'activity':omni.yaml.safe_load(files()['activity.topic'])},'relationships':[]}
    approve(spec)
    return spec,binding,model,placement


def approve(spec):
    # Test fixture only: this is not an authenticated approval mechanism.
    spec['review']={'status':'approved','reference':'synthetic-review-only','evidence_sha256':'d'*64,
                    'spec_sha256':omni.canonical_hash({k:v for k,v in spec.items() if k!='review'})}


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned PyYAML and sqlglot runtime required')
class GenerateOmniModelTests(unittest.TestCase):
    def test_deterministic_generation_preserves_explicit_semantic_meaning(self):
        args=inputs(); before=copy.deepcopy(args)
        result=generator.generate_model(*args)
        self.assertEqual(result['check']['status'],'passed',result['check'])
        self.assertEqual(result,generator.generate_model(*args))
        self.assertEqual(args,before)
        view=omni.yaml.safe_load(result['files']['events.view'])
        self.assertEqual(view['dimensions']['id']['sql'],'"ID"')
        self.assertEqual(view['measures'],args[0]['views']['events']['definition']['measures'])
        self.assertEqual(view['catalog'],'ANALYTICS')
        self.assertEqual(omni.yaml.safe_load(result['files']['activity.topic']),args[0]['topics']['activity'])
        self.assertEqual(len(result['manifest']['field_mappings']),7)
        for key in ('native_verified','deployment_authorized','review_authority_authenticated'):
            self.assertFalse(result['manifest'][key])

    def test_every_exact_input_pin_is_checked(self):
        for index in (1,2,3):
            args=list(inputs()); args[index]['changed']='synthetic change'
            with self.assertRaisesRegex(ValueError,'generation.stale_pins'):
                generator.generate_model(*args)
        args=list(inputs()); args[0]['pins']['catalogue_sha256']='b'*64; approve(args[0])
        with self.assertRaisesRegex(ValueError,'generation.stale_pins'): generator.generate_model(*args)

    def test_review_is_bound_to_all_spec_content_and_not_just_a_boolean(self):
        args=list(inputs()); args[0]['topics']['activity']['description']='Changed after review'
        with self.assertRaisesRegex(ValueError,'generation.review_required'): generator.generate_model(*args)
        args=list(inputs()); args[0]['review']['status']='proposed'
        with self.assertRaisesRegex(ValueError,'generation.review_required'): generator.generate_model(*args)

    def test_missing_extra_or_unmapped_fields_cannot_be_silently_dropped(self):
        for change in ('missing','extra','field'):
            args=list(inputs()); item=args[0]['views']['events']
            if change=='missing': item['field_mappings'].pop('id')
            elif change=='extra': item['field_mappings']['not_a_field']={'kind':'derived','source_refs':['synthetic']}
            else: item['definition']['dimensions']['new']={'sql':'1'}
            approve(args[0])
            with self.assertRaisesRegex(ValueError,'generation.mapping_coverage'): generator.generate_model(*args)

    def test_physical_mapping_must_exist_in_catalogue_and_match_supplied_sql(self):
        for change in ('missing','wrong_sql','expression'):
            args=list(inputs()); item=args[0]['views']['events']
            if change=='missing': item['field_mappings']['id']['column']='MISSING'
            elif change=='wrong_sql': item['definition']['dimensions']['id']['sql']='"VALUE"'
            else: item['definition']['dimensions']['id']['sql']='ID + 1'
            approve(args[0])
            with self.assertRaises(ValueError): generator.generate_model(*args)

    def test_explicit_derived_mapping_cannot_be_generated_without_sql(self):
        args=list(inputs()); args[0]['views']['events']['definition']['measures']['average'].pop('sql'); approve(args[0])
        with self.assertRaisesRegex(ValueError,'generation.derived_sql_required'): generator.generate_model(*args)

    def test_inherited_override_requires_resolved_base_and_keeps_omissions(self):
        args=list(inputs()); base=omni.yaml.safe_load(files()['events.view'])
        args[1]['inherited_views']['events']={'definition':base,'sha256':omni.canonical_hash(base)}
        args[0]['views']['events']={'kind':'inherited_override',
            'definition':{'dimensions':{'id':{'label':'Event identity'}}},
            'field_mappings':{'id':{'kind':'inherited','source_refs':['model#/fields/id']}}}
        args[0]['pins']['context_sha256']=omni.canonical_hash(args[1]); approve(args[0])
        result=generator.generate_model(*args)
        self.assertEqual(result['check']['status'],'passed',result['check'])
        emitted=omni.yaml.safe_load(result['files']['events.view'])
        self.assertNotIn('sql',emitted['dimensions']['id'])
        args[1]['inherited_views']={}; args[0]['pins']['context_sha256']=omni.canonical_hash(args[1]); approve(args[0])
        with self.assertRaisesRegex(ValueError,'generation.inherited_definition_required'): generator.generate_model(*args)

    def test_unknown_native_feature_is_preserved_but_blocks_candidate_write(self):
        args=list(inputs()); args[0]['topics']['activity']['future_feature']={'synthetic':True}; approve(args[0])
        result=generator.generate_model(*args)
        self.assertEqual(result['check']['status'],'unsupported')
        self.assertIn('future_feature',omni.yaml.safe_load(result['files']['activity.topic']))
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve()/'candidate'
            with self.assertRaises(ValueError): generator.write_candidate(result,output)
            self.assertFalse(output.exists())

    def test_other_domain_and_bigquery_mapping_are_not_fixture_specific(self):
        args=list(inputs()); spec,binding=args[:2]
        spec['views']['shipments']=spec['views'].pop('events')
        spec['topics']['activity']['base_view']='shipments'
        spec['topics']['activity']['fields']=['shipments.recorded_at[date]','shipments.total']
        spec['topics']['activity']['access_filters'][0]['field']='shipments.tenant_id'
        binding['warehouse']='bigquery'; binding['bindings']['shipments']=binding['bindings'].pop('events')
        binding['bindings']['shipments']['namespace']={'project':'synthetic-project','dataset':'freight','table':'shipments'}
        spec['pins']['context_sha256']=omni.canonical_hash(binding); approve(spec)
        result=generator.generate_model(*args)
        self.assertEqual(result['check']['status'],'passed',result['check'])
        view=omni.yaml.safe_load(result['files']['shipments.view'])
        self.assertEqual((view['catalog'],view['schema'],view['table_name']),('synthetic-project','freight','shipments'))
        self.assertEqual(view['dimensions']['id']['sql'],'`ID`')

    def test_unknown_top_level_spec_keys_are_rejected(self):
        args=list(inputs()); args[0]['silent_extra']={}; approve(args[0])
        with self.assertRaisesRegex(ValueError,'generation.spec_fields'): generator.generate_model(*args)

    def test_source_references_must_resolve_against_pinned_inputs(self):
        for reference in ('model#/missing','placement#/semantic/missing','https://example.invalid/private','model#/fields/id/unknown'):
            args=list(inputs()); args[0]['views']['events']['field_mappings']['id']['source_refs']=[reference]; approve(args[0])
            with self.assertRaises(ValueError): generator.generate_model(*args)

    def test_private_write_is_new_only_and_cleans_failed_output(self):
        result=generator.generate_model(*inputs())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); output=root/'candidate'
            generator.write_candidate(result,output)
            self.assertEqual(output.stat().st_mode&0o777,0o700)
            self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in output.iterdir()))
            with self.assertRaises(ValueError): generator.write_candidate(result,output)
            failed=root/'failed'
            original_open=generator.os.open
            def fail_writes(path,flags,*args,**kwargs):
                if flags & generator.os.O_WRONLY: raise OSError('synthetic-only')
                return original_open(path,flags,*args,**kwargs)
            with patch.object(generator.os,'open',side_effect=fail_writes):
                with self.assertRaises(OSError): generator.write_candidate(result,failed)
            self.assertFalse(failed.exists()); self.assertTrue(output.exists())

    def test_changed_files_cannot_reuse_static_result(self):
        result=generator.generate_model(*inputs()); result['files']['events.view']+='unknown: true\n'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'generation.candidate_changed'):
                generator.write_candidate(result,Path(tmp).resolve()/'candidate')

    def test_cli_is_runnable_and_does_not_print_source_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); command=[sys.executable,'-B',generator.__file__]
            for name,value in zip(('spec','context','model-version','placement-version'),inputs()):
                path=root/(name+'.json'); path.write_text(json.dumps(value)); command+=['--'+name,str(path)]
            command+=['--output',str(root/'candidate')]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'],'private_candidate')
            self.assertNotIn('NULLIF',result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
