"""Shared recommendations preserve metric populations and aggregation behavior."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import shared_model_candidates as portfolio


def fixture():
    contract = {'base_entity': 'orders', 'grain': ['day', 'tenant'], 'dimensions': ['country'],
                'population': 'completed', 'filters': ['not internal'], 'time': 'UTC calendar day',
                'currency': 'USD', 'history': 'event', 'security': 'tenant', 'rule_ids': [],
                'measures': [{'id': 'revenue', 'expression': 'sum(net)', 'aggregation': 'sum', 'additivity': 'additive'}]}
    return {'schema_version': 1, 'assets': [
        {'id': 'chart.' + name, 'name': name, 'domain': 'commerce', 'model_ids': ['orders'],
         'evidence_refs': ['source.' + name], 'contract': copy.deepcopy(contract)} for name in ('finance', 'operations')]}


class SharedModelCandidatesTests(unittest.TestCase):
    def test_two_dashboards_share_one_candidate_and_keep_coverage(self):
        result = portfolio.propose(fixture())
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['disposition'], 'shared_aggregate_candidate')
        self.assertEqual(result['covered_assets'], 2)

    def test_different_projections_retain_union_for_drilldown(self):
        request = fixture(); request['assets'][1]['contract']['dimensions'] = ['channel']
        result = portfolio.propose(request)
        self.assertEqual(result['candidates'][0]['dimensions'], ['channel', 'country'])
        self.assertEqual(len(result['candidates']), 1)

    def test_population_time_security_currency_history_and_grain_separate(self):
        for field, value in [('population', 'all'), ('time', 'local day'), ('currency', 'EUR'),
                             ('security', 'global'), ('history', 'current'), ('grain', ['month']),
                             ('filters', ['not internal', 'region west'])]:
            request = fixture(); request['assets'][1]['contract'][field] = value
            result = portfolio.propose(request)
            self.assertTrue(all(r['disposition'] == 'keep_separate' for r in result['coverage']), field)

    def test_distinct_ratio_window_and_semiadditive_never_roll_up(self):
        for aggregation in ('count_distinct', 'ratio', 'window', 'min', 'max'):
            request = fixture()
            for asset in request['assets']:
                asset['contract']['measures'][0].update(aggregation=aggregation, additivity='non_additive')
            result = portfolio.propose(request)
            self.assertEqual(result['candidates'][0]['disposition'], 'shared_detail_candidate')

    def test_same_metric_name_conflict_does_not_merge(self):
        request = fixture(); request['assets'][1]['contract']['measures'][0]['expression'] = 'sum(gross)'
        self.assertEqual(portfolio.propose(request)['candidates'][0]['disposition'], 'needs_decision')

    def test_unknown_contract_stays_in_denominator(self):
        request = fixture(); request['assets'][1]['contract']['security'] = 'unknown'
        result = portfolio.propose(request)
        self.assertEqual(result['covered_assets'], 2)
        self.assertEqual(result['status'], 'needs_decision')
        self.assertIn('needs_decision', [r['disposition'] for r in result['coverage']])

    def test_existing_model_requires_all_measures_and_dimensions(self):
        request = fixture(); contract = copy.deepcopy(request['assets'][0]['contract'])
        request['existing_models'] = [{'id': 'existing.orders', 'name': 'Existing orders', 'evidence_refs': ['catalogue.orders'], 'contract': contract}]
        self.assertEqual(portfolio.propose(request)['candidates'][0]['disposition'], 'reuse_candidate')
        contract['dimensions'] = []
        self.assertEqual(portfolio.propose(request)['candidates'][0]['disposition'], 'shared_aggregate_candidate')

    def test_duplicate_source_ids_and_empty_evidence_rejected(self):
        request = fixture(); request['assets'][1]['id'] = request['assets'][0]['id']
        with self.assertRaises(ValueError): portfolio.propose(request)
        request = fixture(); request['assets'][0]['evidence_refs'] = []
        with self.assertRaises(ValueError): portfolio.propose(request)

    def test_input_is_immutable(self):
        request = fixture(); before = copy.deepcopy(request)
        self.assertEqual(portfolio.propose(request), portfolio.propose(request))
        self.assertEqual(request, before)


if __name__ == '__main__': unittest.main()
