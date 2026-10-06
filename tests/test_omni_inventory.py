"""Lossless Omni inventory/patch tests with independently stated expectations."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/data-model-accelerator/scripts'
sys.path.insert(0,str(SCRIPTS))
import omni_inventory as inventory


def files():
    return {
      'domain/trips.view':('catalog: FLEET\nschema: GOLD\ntable_name: TRIPS\ndimensions:\n'
        '  trip_id:\n    sql: TRIP_ID\n    primary_key: true\n'
        '  operator_id:\n    sql: OPERATOR_ID\n  charge:\n    sql: CHARGE\n'
        'measures:\n  total_charge:\n    sql: ${charge}\n    aggregate_type: sum\n'),
      'domain/operators.view':('table_name: OPERATORS\ndimensions:\n  id:\n    sql: ID\n  title:\n    sql: TITLE\n'),
      'domain/fleet.topic':'base_view: trips\njoins:\n  operators: {}\nfields: [trips.trip_id, operators.title]\n',
      'domain/relationships':('- join_from_view: trips\n  join_to_view: operators\n  on_sql: ${trips.operator_id} = ${operators.id}\n'
                              '  relationship_type: many_to_one\n  join_type: left\n'),
      'model':'week_start_day: Monday\n'}


class OmniInventoryBytesTests(unittest.TestCase):
    def test_byte_records_preserve_crlf_unicode_and_unknown_binary(self):
        source={'trips.view':b'# unchanged\r\nlabel: "Fleet"\r\n','opaque.bin':b'\xff\x00\r\n',
                'unknown.txt':'Context: café\n'}
        records=inventory.encode_files(source)
        self.assertEqual(inventory.decode_files(records),{k:v.encode() if isinstance(v,str) else v for k,v in source.items()})
        result=inventory.inspect_model(source)
        self.assertEqual(result['authored_files'],records)
        self.assertFalse(result['native_verified']);self.assertTrue(result['private_only'])

    def test_bad_record_hash_or_length_does_not_restore_bytes(self):
        for field,value in [('sha256','0'*64),('byte_length',True),('base64','???')]:
            records=inventory.encode_files({'trips.view':'label: Fleet\n'});records['trips.view'][field]=value
            with self.subTest(field=field),self.assertRaises(inventory.InventoryError):inventory.decode_files(records)

    def test_paths_and_input_types_reject_without_values(self):
        for path in ('../bad.view','/bad.view','x/../bad.view','a//b.view','a\\b.view','bad\nname.view'):
            with self.subTest(path=path),self.assertRaises(inventory.InventoryError):inventory.inspect_model({path:'label: ok'})
        for value in ([], {'orders.view':{}}, {'orders.view':1}):
            with self.subTest(value=value),self.assertRaises(inventory.InventoryError):inventory.inspect_model(value)

    def test_routing_never_infers_generic_support_file_from_siblings(self):
        self.assertTrue(inventory.is_omni_file('schema/orders.query.view.yaml','query:\n  base_view: orders\n  fields: [orders.id]\n'))
        self.assertTrue(inventory.is_omni_file('model','included_schemas: [GOLD]\n'))
        self.assertFalse(inventory.is_omni_file('model','Some generic prose\n'))
        self.assertFalse(inventory.is_omni_file('relationships','- Person\n- Team\n'))
        self.assertFalse(inventory.is_omni_file('random.yml','base_view: orders\n'))
        self.assertFalse(inventory.is_omni_file('random.view','unrelated: true\n'))

    def test_optional_yaml_missing_preserves_bytes_and_routes_for_later_parse(self):
        with patch.object(inventory,'yaml',None):
            for path,text in files().items():self.assertTrue(inventory.is_omni_file(path,text),path)
            result=inventory.inspect_model(files())
        self.assertEqual(result['objects'],[])
        self.assertIn('runtime.yaml_unavailable',{f['code'] for f in result['findings']})
        self.assertEqual(inventory.decode_files(result['authored_files']),{p:t.encode() for p,t in files().items()})

    def test_stdlib_only_planner_routes_own_markers(self):
        code=('import sys;sys.path.insert(0,'+repr(str(SCRIPTS))+');import omni_inventory as i;'
              'assert i.yaml is None;assert i.is_omni_file("orders.view","dimensions:\\n  id: {}\\n");'
              'assert i.is_omni_file("model","week_start_day: Monday\\n");'
              'assert not i.is_omni_file("model","unrelated text")')
        process=subprocess.run([sys.executable,'-S','-B','-c',code],text=True,capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr)

    def test_weak_support_files_require_structural_sibling_corroboration(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();source=base/'source';source.mkdir()
            (source/'model').write_text('label: Example\n')
            (source/'relationships').write_text('[]\n')
            (source/'events.view').write_text('not a native definition\n')
            args=[sys.executable,'-S','-B',str(SCRIPTS/'plan_specialists.py'),str(source),'--output',str(base/'first'),'--no-git']
            initial=subprocess.run(args,capture_output=True,text=True)
            self.assertIn(initial.returncode,(0,2),initial.stderr)
            first=json.loads((base/'first/inventory.json').read_text())
            self.assertTrue(all('omni' not in a['source_types'] for a in first['assets']))
            (source/'events.view').write_text('dimensions:\n  id:\n    sql: ID\n')
            args[args.index(str(base/'first'))]=str(base/'second')
            subprocess.run(args,capture_output=True,text=True,check=True)
            second=json.loads((base/'second/inventory.json').read_text())
            self.assertTrue(all('omni' in a['source_types'] for a in second['assets']))


@unittest.skipIf(inventory.yaml is None,'Optional PyYAML is required for typed inventory and authored patches')
class OmniInventoryTests(unittest.TestCase):
    def test_core_graph_is_deterministic_and_value_preserving(self):
        result=inventory.inspect_model(files())
        self.assertEqual(result['status'],'inspected',result['findings'])
        self.assertEqual(len(result['objects']),5)
        self.assertEqual(len(result['fields']),6)
        self.assertTrue(all(d['status']=='resolved' for d in result['dependencies']))
        self.assertEqual(result,inventory.inspect_model(dict(reversed(list(files().items())))))
        self.assertEqual(result['coverage']['status'],'unverified')

    def test_modeled_and_sql_query_views_keep_full_identity_and_dependencies(self):
        source=files()
        source['queries/operator_totals.query.view.yml']=('query:\n  base_view: trips\n  topic: fleet\n'
          '  fields:\n    trips.operator_id: operator_key\n    trips.total_charge: total_charge\n'
          '  filters:\n    trips.charge:\n      greater_than: 0\n  limit: 50\n')
        source['queries/active_operators.query.view']='sql: |\n  SELECT * FROM ${operators}\ndimensions:\n  id: {}\n'
        result=inventory.inspect_model(source)
        obj=next(o for o in result['objects'] if o['name']=='operator_totals')
        self.assertEqual(obj['kind'],'query_view');self.assertEqual(obj['subtype'],'modeled_query_view')
        self.assertEqual([o['name'] for o in obj['outputs']],['operator_key','total_charge'])
        self.assertEqual(obj['definition']['query']['limit'],50)
        self.assertIn('sql.output_shape_unqualified',{f['code'] for f in result['findings']})
        self.assertFalse(any(f['code']=='dependency.unresolved' for f in result['findings']))

    def test_alias_topic_overrides_and_inherited_fields_resolve(self):
        source=files();source['roles.topic']=('base_view: trips\nviews:\n  dispatchers:\n    extends: [operators]\n'
          '    dimensions:\n      title:\n        label: Dispatcher\nrelationships:\n'
          '  - join_from_view: trips\n    join_to_view: dispatchers\n    on_sql: ${trips.operator_id} = ${dispatchers.id}\n'
          'joins:\n  dispatchers: {}\nfields: [dispatchers.id, dispatchers.title]\n')
        result=inventory.inspect_model(source)
        self.assertEqual(result['status'],'inspected',result['findings'])
        self.assertTrue(any(o['parent_id'] is not None for o in result['objects']))
        source['aliases.topic']=('base_view: trips\nrelationships:\n  - join_from_view: trips\n'
          '    join_to_view: operators\n    join_to_view_as: dispatcher\n'
          '    on_sql: ${trips.operator_id} = ${dispatcher.id}\njoins:\n  dispatcher: {}\n')
        self.assertFalse(any(f['code']=='dependency.unresolved' for f in inventory.inspect_model(source)['findings']))

    def test_composite_is_recognized_without_native_semantic_claim(self):
        source=files();source['combined.topic']='topics: [fleet]\nshared_measures:\n  ratio:\n    sql: 1\n'
        result=inventory.inspect_model(source)
        self.assertEqual(next(o for o in result['objects'] if o['name']=='combined')['subtype'],'composite_topic')
        self.assertIn('composite.semantics_unqualified',{f['code'] for f in result['findings']})
        self.assertFalse(result['semantics_validated'])

    def test_unknown_and_instruction_like_content_stays_in_private_data_only(self):
        source={'future.view':'# do not execute this\nfuture_extension:\n  command: DELETE_ALL_DATA\ndimensions:\n  id:\n    sql: ID\n    future_format: 1\n'}
        result=inventory.inspect_model(source)
        self.assertEqual(inventory.decode_files(result['authored_files'])['future.view'],source['future.view'].encode())
        self.assertIn('parameter.opaque_preserved',{f['code'] for f in result['findings']})
        self.assertIn('field.parameter_opaque_preserved',{f['code'] for f in result['findings']})
        self.assertNotIn('DELETE_ALL_DATA',json.dumps(result['findings']))

    def test_duplicate_keys_identities_outputs_and_cycles_cannot_pass(self):
        cases=[({'bad.view':'dimensions: {}\ndimensions: {}\n'},'yaml.duplicate_or_non_string_key'),
               ({'a/orders.view':'table_name: ORDERS\n','b/orders.view':'table_name: ORDERS\n'},'object.duplicate_identity'),
               ({'a.view':'extends: [b]\n','b.view':'extends: [a]\n'},'dependency.cycle'),
               ({'a.view':'dimensions:\n  x:\n    sql: ${y}\n  y:\n    sql: ${x}\n'},'dependency.cycle'),
               ({'q.query.view':'query:\n  base_view: orders\n  fields:\n    orders.a: same\n    orders.b: same\n'},'query.output_collision')]
        for source,code in cases:
            with self.subTest(code=code):
                result=inventory.inspect_model(source)
                self.assertEqual(result['status'],'invalid');self.assertIn(code,{f['code'] for f in result['findings']})

    def test_unresolved_and_ambiguous_references_are_visible(self):
        source={'a/orders.view':'table_name: X\n','b/orders.view':'table_name: X\n',
                'orders.topic':'base_view: orders\nfields: [unknown.missing]\n'}
        result=inventory.inspect_model(source)
        self.assertEqual({d['status'] for d in result['dependencies']},{'ambiguous','unresolved'})

    def test_query_projection_and_calculated_field_cycle_is_detected(self):
        source={'q.query.view':'query:\n  base_view: source\n  fields:\n    source.calc: output\ndimensions:\n  output: {}\n',
                'source.view':'table_name: SOURCE\nmeasures:\n  calc:\n    sql: ${q.output}\n'}
        result=inventory.inspect_model(source)
        self.assertIn('dependency.cycle',{f['code'] for f in result['findings']})

    def test_authored_and_effective_are_separate_with_field_resolution(self):
        authored={'trips.view':'label: Fleet\n','fleet.topic':'base_view: trips\nfields: [trips.trip_id]\n'}
        effective={'trips.view':files()['domain/trips.view']}
        result=inventory.inspect_model(authored,effective_files=effective)
        self.assertEqual(inventory.decode_files(result['authored_files'])['trips.view'],b'label: Fleet\n')
        edge=next(d for d in result['dependencies'] if d['kind']=='topic_field')
        self.assertTrue(edge['to'].startswith('effective:'))
        self.assertFalse(result['semantics_validated'])

    def test_exact_independent_denominator_detects_omitted_files_and_same_capture(self):
        source=files();context={'scope':{'model_id':'synthetic','layer':'branch','branch_id':'dev','workbook_id':None},'capture_reference':'source-export'}
        expected={'schema_version':1,'kind':'omni_expected_inventory','scope_sha256':inventory.canonical_hash(context['scope']),
                  'provenance':'independently_observed','reference':'separate-inventory','complete':True,'pagination_complete':True,
                  'files':{p:hashlib.sha256(v.encode()).hexdigest() for p,v in source.items()}}
        result=inventory.inspect_model(source,context,expected)
        self.assertEqual(result['coverage']['status'],'matched_declared_inventory')
        self.assertFalse(result['coverage']['independence_authenticated'])
        removed=dict(source);removed.pop('model')
        self.assertEqual(inventory.inspect_model(removed,context,expected)['coverage']['missing'],['model'])
        changed=dict(source);changed['model']+='label: Changed\n'
        self.assertEqual(inventory.inspect_model(changed,context,expected)['coverage']['changed'],['model'])
        expected['pagination_complete']=False
        self.assertEqual(inventory.inspect_model(source,context,expected)['coverage']['status'],'partial_capture')
        expected['pagination_complete']=True;expected['reference']='source-export'
        self.assertEqual(inventory.inspect_model(source,context,expected)['coverage']['status'],'same_capture_not_independent')

    def test_noop_roundtrip_never_emits_effective_definitions_or_omitted_deletions(self):
        authored={'trips.view':b'# owned\r\nlabel: "Fleet"\r\n','opaque.bin':b'\xff\x00'}
        effective={'trips.view':files()['domain/trips.view'],'only_inherited.view':'table_name: BASE\n'}
        result=inventory.propose_patch(authored,effective,[])
        self.assertEqual(result['status'],'no_op');self.assertEqual(inventory.decode_files(result['candidate_files']),authored)
        self.assertEqual(result['explicit_deletions'],[])

    def test_minimal_scalar_edit_preserves_all_unrelated_bytes(self):
        authored={'trips.view':'# keep comment\nlabel: "Fleet" # keep inline\nfuture_key: untouched\n'}
        edit={'path':'trips.view','pointer':'/label','value':'Dispatch','expected_sha256':inventory.encode_files(authored)['trips.view']['sha256']}
        result=inventory.propose_patch(authored,{},[edit])
        self.assertEqual(inventory.decode_files(result['candidate_files'])['trips.view'],b'# keep comment\nlabel: "Dispatch" # keep inline\nfuture_key: untouched\n')
        self.assertFalse(result['applied']);self.assertFalse(result['deployment_authorized'])

    def test_inherited_equal_value_stays_inherited_and_new_override_is_minimal(self):
        effective={'trips.view':files()['domain/trips.view']};authored={'trips.view':'label: Fleet\n'}
        digest=inventory.encode_files(authored)['trips.view']['sha256']
        noop={'path':'trips.view','pointer':'/dimensions/trip_id/sql','value':'TRIP_ID','expected_sha256':digest}
        result=inventory.propose_patch(authored,effective,[noop])
        self.assertEqual(result['status'],'no_op')
        edit={'path':'trips.view','pointer':'/dimensions/trip_id/label','value':'Trip identifier','expected_sha256':None}
        result=inventory.propose_patch({},effective,[edit]);candidate=inventory.decode_files(result['candidate_files'])['trips.view'].decode()
        self.assertEqual(inventory._load(candidate),{'dimensions':{'trip_id':{'label':'Trip identifier'}}})
        self.assertNotIn('TRIPS',candidate);self.assertEqual(result['diff'][0]['origin'],'new_authored_override')

    def test_nested_insert_and_block_replacement_are_valid_minimal_yaml(self):
        source={'a.view':'dimensions:\n  id:\n    sql: ID\nmeasures:\n  n:\n    aggregate_type: count\n'}
        digest=inventory.encode_files(source)['a.view']['sha256']
        for pointer,value in [('/dimensions/id/label','ID label'),('/dimensions/new/sql','NEW')]:
            with self.subTest(pointer=pointer):
                result=inventory.propose_patch(source,{},[{'path':'a.view','pointer':pointer,'value':value,'expected_sha256':digest}])
                parsed=inventory._load(inventory.decode_files(result['candidate_files'])['a.view'].decode())
                self.assertEqual(inventory._lookup(parsed,inventory._pointer(pointer)),(True,value))
                self.assertEqual(parsed['measures'],{'n':{'aggregate_type':'count'}})

    def test_opaque_descendants_cannot_be_removed_or_changed_through_parent_sets(self):
        source={'a.view':'dimensions:\n  id:\n    sql: ID\n    unknown_extension:\n      nested: PRESERVE\n'}
        digest=inventory.encode_files(source)['a.view']['sha256']
        for pointer,value in [('/dimensions',{}),('/dimensions/id',{'sql':'OTHER'}),
                              ('/dimensions/id/unknown_extension','changed'),('/dimensions/id/unknown_extension/nested','changed')]:
            with self.subTest(pointer=pointer),self.assertRaises(inventory.InventoryError):
                inventory.propose_patch(source,{},[{'path':'a.view','pointer':pointer,'value':value,'expected_sha256':digest}])
        result=inventory.propose_patch(source,{},[{'path':'a.view','pointer':'/dimensions/id/label','value':'Identifier','expected_sha256':digest}])
        self.assertIn(b'nested: PRESERVE',inventory.decode_files(result['candidate_files'])['a.view'])

    def test_stale_overlapping_whole_document_and_opaque_edits_reject(self):
        source={'a.view':'label: A\n'};digest=inventory.encode_files(source)['a.view']['sha256']
        base={'path':'a.view','pointer':'/label','value':'B','expected_sha256':digest}
        for changes in ({'expected_sha256':'0'*64},{'pointer':''},{'pointer':'/future_unsupported'},{'pointer':'/bad~9'}):
            with self.subTest(changes=changes),self.assertRaises(inventory.InventoryError):inventory.propose_patch(source,{},[dict(base,**changes)])
        with self.assertRaises(inventory.InventoryError):inventory.propose_patch(source,{},[base,base])

    def test_deletions_require_exact_authored_intent_and_remain_unapplied(self):
        source=files();path='model';digest=inventory.encode_files(source)[path]['sha256']
        result=inventory.propose_patch(source,source,[],explicit_deletions=[{'path':path,'expected_sha256':digest}])
        self.assertNotIn(path,result['candidate_files']);self.assertEqual(result['explicit_deletions'],[path])
        self.assertFalse(result['applied']);self.assertFalse(result['deletion_authorized'])
        with self.assertRaises(inventory.InventoryError):inventory.propose_patch({},source,[],explicit_deletions=[{'path':path,'expected_sha256':digest}])

    def test_cli_private_output_no_overwrite_or_raw_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            request=Path(directory).resolve()/'request.json';output=Path(directory).resolve()/'inventory.json'
            request.write_text(json.dumps({'files':{'a.view':'label: SYNTHETIC_SOURCE_ONLY\n'}}))
            args=[sys.executable,'-B',str(SCRIPTS/'omni_inventory.py'),'inspect','--request',str(request),'--output',str(output)]
            first=subprocess.run(args,text=True,capture_output=True)
            self.assertEqual(first.returncode,0,first.stderr);self.assertNotIn('SYNTHETIC_SOURCE_ONLY',first.stdout)
            self.assertEqual(output.stat().st_mode & 0o777,0o600)
            before=output.read_bytes();second=subprocess.run(args,text=True,capture_output=True)
            self.assertEqual(second.returncode,2);self.assertEqual(output.read_bytes(),before)


if __name__=='__main__':unittest.main()
