"""Native parameter-domain behavior must survive the local source replay."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];CASE=ROOT/'skills/data-model-accelerator/examples/tableau-omni-e2e'
sys.path.insert(0,str(ROOT/'skills/data-model-accelerator/scripts'))
OPTIONAL=all(importlib.util.find_spec(x) for x in ('duckdb','sqlglot','pandas','yaml'))
if OPTIONAL:
    import tableau_execution as t
    from tableau_source import inspect_repo

@unittest.skipUnless(OPTIONAL,'Optional replay engines required')
class TableauParameterDomainTests(unittest.TestCase):
    def setUp(self):
        self.graph=inspect_repo(CASE/'input/repo');self.raw,self.adjustments=t.load_inputs(CASE)
    def replay(self,parameters): return t.replay_source(CASE,self.graph,self.raw,self.adjustments,parameters)[0]
    def test_authored_free_text_segment_produces_empty_marks(self):
        parameter=next(p for p in self.graph['parameters'] if p['caption']=='Segment')
        self.assertEqual(parameter['domain_type'],'any')
        self.assertTrue(all(not rows for rows in self.replay({'segment':'NOT_AN_EXISTING_SEGMENT'}).values()))
    def test_native_list_cannot_accept_an_unlisted_value(self):
        parameter=next(p for p in self.graph['parameters'] if p['caption']=='Segment')
        parameter.update(domain_type='list',members=['"ALL"','"SMB"','"Enterprise"'])
        with self.assertRaisesRegex(t.TableauExecutionError,'outside native domain'):
            self.replay({'segment':'NOT_AN_EXISTING_SEGMENT'})
    def test_changed_tenant_domain_is_not_ignored(self):
        parameter=next(p for p in self.graph['parameters'] if p['caption']=='Tenant')
        parameter['members']=['"A"']
        with self.assertRaisesRegex(t.TableauExecutionError,'outside native domain'): self.replay({'tenant':'B'})
    def test_range_domain_requires_implementation(self):
        parameter=next(p for p in self.graph['parameters'] if p['caption']=='Multiplier')
        parameter.update(domain_type='range',range={'min':0,'max':1})
        with self.assertRaisesRegex(t.TableauExecutionError,'Unqualified native'): self.replay({'multiplier':2})

if __name__=='__main__': unittest.main()
