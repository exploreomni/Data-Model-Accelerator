"""SQL rules share the authoring receipt, source pins and provisional boundary."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_authoring_evidence import contract
import authoring_quality as quality
from authoring_evidence import validate_contract
try:
    import sqlglot
except ImportError:
    sqlglot = None


@unittest.skipUnless(sqlglot, 'Optional dialect-aware SQL parser')
class AuthoringSqlRulesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.candidate, self.source = root/'candidate', root/'source'
        self.candidate.mkdir(); self.source.mkdir()
        (self.candidate/'orders.sql').write_text("select x.id from {{ ref('upstream') }} x")
        (self.source/'upstream.sql').write_text('select 1 as id')
        self.contract = contract(); self.contract['assumptions'] = []
        self.contract['models'][0]['depends_on'] = ['ref:upstream']
        self.contract['sql_rules'] = {'contract': {'schema_version': 1,
            'keys': [{'id': 'order', 'column': 'id', 'models': ['orders']}]},
            'upstream_paths': ['upstream.sql']}
        quality._OBSERVATION_CACHE.clear()

    def evaluate(self):
        return quality.evaluate(self.candidate, self.source, self.contract, ['orders.sql'], 'snowflake')

    def test_optional_rules_pin_upstream_and_do_not_authorize_provisional_code(self):
        result = self.evaluate()
        self.assertIn('upstream.sql', result['source_evidence'])
        self.assertEqual(result['mode'], 'provisional')
        self.assertIn('sql_contract_scope', [f['code'] for f in result['findings']])
        self.assertNotIn('approval', result)
        self.contract['sql_rules']['contract']['keys'][0]['column'] = 'absent'
        self.assertEqual(self.evaluate()['status'], 'failed')

    def test_cache_requires_exact_source_bytes_and_contract(self):
        first = self.evaluate()
        self.assertEqual(first['status'], 'passed')
        with patch('authoring_conformance.check_conformance', side_effect=AssertionError('should reuse checked bytes')):
            self.assertEqual(first, self.evaluate())
        (self.source/'upstream.sql').write_text('select 1 as different')
        changed = self.evaluate()
        self.assertEqual(changed['status'], 'failed')
        self.assertNotEqual(first['source_evidence'], changed['source_evidence'])

    def test_contract_prevents_unbounded_or_escaping_upstream_scope(self):
        bad = copy.deepcopy(self.contract)
        bad['sql_rules']['upstream_paths'] = ['../escape.sql']
        with self.assertRaises(ValueError): validate_contract(bad)
        bad['sql_rules']['upstream_paths'] = ['credentials.json']
        with self.assertRaises(ValueError): validate_contract(bad)
