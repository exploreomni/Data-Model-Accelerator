"""Focused draft transport and independent readback-boundary checks; offline only."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_dashboard_native as draft
import omni_contract


class DraftTransportTests(unittest.TestCase):
    def test_transport_has_no_publish_create_archive_or_existing_draft_write(self):
        with patch.dict('os.environ', {'OMNI_API_TOKEN': 'synthetic-unit-token'}):
            transport = draft.HTTPSOmniDraftTransport('https://synthetic-unit.omniapp.co')
        forbidden = [('POST','/api/v2/documents'), ('POST','/api/v2/documents/sample/draft/publish'),
                     ('PATCH','/api/v2/documents/sample/draft/publish'),
                     ('PATCH','/api/v2/documents/sample/draft/previous'),
                     ('DELETE','/api/v2/documents/sample/draft/previous'),
                     ('POST','/api/unstable/documents/import'),
                     ('GET','/api/v2/documents/sample/draft/../../else')]
        with patch.object(transport._opener, 'open', side_effect=AssertionError('network forbidden')):
            for method, path in forbidden:
                with self.subTest(method=method,path=path), self.assertRaises(ValueError):
                    transport.request(method,path)

    def test_shallow_merge_cannot_preserve_unmapped_tiles_or_controls(self):
        published = {'queryPresentations': {'data': {'1': {'type':'blank'},'2':{'type':'blank'}},'order':['1','2']},
                     'controls': {'data':{},'order':[]}}
        payload = {'queryPresentations': {'data': {'1': {'type':'blank'}},'order':['1']},
                   'controls': {'data':{},'order':[]},'containers':[{'type':'synthetic'}]}
        with self.assertRaisesRegex(ValueError,'unmapped_existing_content'):
            draft._expected_document(published,payload)
        del published['queryPresentations']['data']['2'];published['queryPresentations']['order']=['1']
        self.assertEqual(draft._expected_document(published,payload)['containers'],payload['containers'])
        published['controls']['data']['existing']={'field':'x'};published['controls']['order']=['existing']
        with self.assertRaisesRegex(ValueError,'unmapped_existing_content'):
            draft._expected_document(published,payload)

    def test_server_anchor_normalization_does_not_erase_behavior(self):
        base={'modelId':'base','workbookModelId':'old','draftOf':{'identifier':'parent'},
              'queryPresentations':{'data':{'1':{'type':'query','model_extension_id':'server','query':{'fields':['v.id']}}},'order':['1']}}
        normalized=draft._comparable_document(base)
        self.assertNotIn('workbookModelId',normalized);self.assertNotIn('draftOf',normalized)
        self.assertNotIn('model_extension_id',normalized['queryPresentations']['data']['1'])
        self.assertEqual(normalized['queryPresentations']['data']['1']['query']['fields'],['v.id'])
        changed=copy.deepcopy(base);changed['queryPresentations']['data']['1']['query']['fields']=['v.other']
        self.assertNotEqual(draft._comparable_document(changed),normalized)

    def test_access_digest_covers_both_pages_and_rejects_partial_inventory(self):
        rows=[{'id':str(i),'type':'userGroup','role':'VIEWER','accessSource':'direct','accessBoost':False} for i in (1,2)]
        class Remote:
            def __init__(self):self.calls=[]
            def request(self,method,path,params=None,body=None):
                self.calls.append(params)
                return draft.native.Response(200,draft.native._json_bytes({'principals':[rows[0 if len(self.calls)==1 else 1]],
                    'pageInfo':{'hasNextPage':len(self.calls)==1,'nextCursor':'page-two' if len(self.calls)==1 else None,'totalRecords':2}}))
        remote=Remote();result=draft._access(remote,'synthetic')
        self.assertEqual(result['sha256'],draft.canonical_hash(sorted(rows,key=draft.canonical_hash)))
        self.assertEqual(remote.calls[1]['cursor'],'page-two')
        rows[1]=copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError,'access_duplicate'):
            draft._access(Remote(),'synthetic')

    @unittest.skipUnless(omni_contract.yaml is not None, 'Optional PyYAML required for model binding')
    def test_known_topic_field_inherited_timeframe_and_alias_guard(self):
        files={'fleet.view':'extends: [base]\n','fleet.topic':'base_view: fleet\njoins: {}\nfields:\n  - fleet.departed[month]\n'}
        context={'inherited_views':{'base':{'definition':{'dimensions':{'departed':{'sql':'departure','timeframes':['month']}}}}}}
        payload={'queryPresentations':{'data':{'1':{'type':'query','topicName':'fleet','query':{'fields':['fleet.departed[month]']}}}}}
        draft._query_bindings(payload,files,context)
        for field in ('fleet.departed[time]','fleet.missing','other.departed[month]','alias'):
            changed=copy.deepcopy(payload);changed['queryPresentations']['data']['1']['query']['fields']=[field]
            with self.subTest(field=field), self.assertRaises(ValueError):draft._query_bindings(changed,files,context)
        changed=copy.deepcopy(payload);changed['queryPresentations']['data']['1']['isSql']=True
        with self.assertRaisesRegex(ValueError,'raw_sql_mode'):draft._query_bindings(changed,files,context)
        changed=copy.deepcopy(payload);changed['queryPresentations']['data']['1']['topicName']='missing'
        with self.assertRaisesRegex(ValueError,'topic_unresolved'):draft._query_bindings(changed,files,context)
        changed=copy.deepcopy(payload);changed['queryPresentations']['data']['1']['query']['calculations']=[{'expression':'something'}]
        with self.assertRaisesRegex(ValueError,'calculations_or_sql_unqualified'):draft._query_bindings(changed,files,context)


if __name__ == '__main__':unittest.main()
