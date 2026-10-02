"""Expected-state-first tests: equal wrong environments must never pass."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
from metadata_contract import build_contract
from metadata_observation import seal
from verify_warehouse_metadata import verify_metadata, compare_environments
from test_metadata_contract import dictionary,configuration
from test_warehouse_metadata_plan import observation,tagged_contract


class MetadataReadbackTests(unittest.TestCase):
    def setUp(self):
        self.contract=build_contract(dictionary(),configuration())

    def production(self):
        config=configuration();config['environment']='production';config['metadata_policy']['environments']=['production']
        config['target']['id']='production';config['resources'][0]['relation']['namespace'][0]='production_db'
        return build_contract(dictionary(),config)

    def test_same_empty_comments_are_not_accurate_parity(self):
        prod=self.production()
        with self.assertRaisesRegex(ValueError,'Each environment'):
            compare_environments(self.contract,observation(self.contract),prod,observation(prod))

    def test_correct_different_physical_names_have_logical_parity(self):
        prod=self.production()
        result=compare_environments(self.contract,observation(self.contract,expected=True),prod,observation(prod,expected=True))
        self.assertTrue(result['passed'])
        self.assertFalse(result['release_parity_verified'])

    def test_unrelated_candidate_cannot_establish_parity(self):
        prod=self.production();config=copy.deepcopy(prod['configuration']);config['candidate_sha256']='f'*64
        prod=build_contract(dictionary(),config)
        with self.assertRaisesRegex(ValueError,'candidate bindings differ'):
            compare_environments(self.contract,observation(self.contract,expected=True),prod,observation(prod,expected=True))

    def test_stale_pair_cannot_establish_current_parity(self):
        prod=self.production();old=observation(prod,expected=True);old['observed_at']='2000-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'stale'):
            compare_environments(self.contract,observation(self.contract,expected=True),prod,seal(old))

    def test_missing_object_is_not_an_ignored_intersection(self):
        actual=observation(self.contract,expected=True);actual['resources']=[]
        result=verify_metadata(self.contract,seal(actual))
        self.assertFalse(result['passed']);self.assertEqual(result['counts']['observed_required_resources'],0)

    def test_unseen_physical_column_makes_coverage_fail(self):
        actual=observation(self.contract,expected=True)
        actual['resources'][0]['columns'].append({'name':'undocumented','data_type':'VARCHAR','comment':'unexpected','tags':[]})
        self.assertFalse(verify_metadata(self.contract,seal(actual))['passed'])

    def test_role_visibility_and_complete_pagination_are_required(self):
        for flag in ('visibility_verified','identity_verified','complete'):
            actual=observation(self.contract,expected=True);actual['collection'][flag]=False
            self.assertFalse(verify_metadata(self.contract,seal(actual))['passed'])

    def test_punctuation_case_and_units_are_not_normalized_away(self):
        actual=observation(self.contract,expected=True)
        actual['resources'][0]['columns'][0]['comment']=actual['resources'][0]['columns'][0]['comment'].upper()
        self.assertFalse(verify_metadata(self.contract,seal(actual))['passed'])

    def test_direct_and_inherited_assignments_count_separately(self):
        contract=tagged_contract();actual=observation(contract,expected=True)
        actual['governance']=[{'name':['fixture_db','governance','sensitivity'],'allowed_values':None,
                               'policy_effects':'none_verified','evidence_reference':'synthetic-policy-review'}]
        actual['resources'][0]['tags'].append({'name':['fixture_db','governance','unmanaged'],'value':'example','application':'inherited'})
        result=verify_metadata(contract,seal(actual))
        self.assertTrue(result['passed']);self.assertEqual(result['counts']['matching_direct_tag_assignments'],2)
        self.assertEqual(result['counts']['observed_tag_associations'],3)
        actual['resources'][0]['tags'][0]['application']='inherited'
        self.assertFalse(verify_metadata(contract,seal(actual))['passed'])

    def test_exclusions_remain_visible_without_claiming_whole_estate(self):
        value=dictionary();second=copy.deepcopy(value['models'][0]);second['model_id']='excluded';second['columns'][0]['column_id']='excluded:id';value['models'].append(second)
        config=configuration();secondbinding=copy.deepcopy(config['resources'][0]);secondbinding.update(resource_id='excluded',disposition='documented_only',reason='Shared owner read-only');secondbinding['relation']['name']='shared';config['resources'].append(secondbinding)
        contract=build_contract(value,config);actual=observation(contract,expected=True);actual['resources']=actual['resources'][:1]
        result=verify_metadata(contract,seal(actual));self.assertTrue(result['passed']);self.assertEqual(result['counts']['excluded_resources'],1)

    def test_all_excluded_scope_cannot_pass(self):
        config=configuration();config['resources'][0].update(disposition='documented_only',reason='Read only')
        contract=build_contract(dictionary(),config)
        self.assertFalse(verify_metadata(contract,observation(contract,expected=True))['passed'])

    def test_release_binding_is_required_when_supplied(self):
        with self.assertRaisesRegex(ValueError,'release differs'):
            verify_metadata(self.contract,observation(self.contract,expected=True),release_id='different')


if __name__=='__main__':
    unittest.main()
