"""Synthetic, offline reference expectations independent of native dbt execution."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from dbt_references import extract_references, parse_literal_call
from authoring_provenance import mask_static_dbt_sql


class LiteralReferenceTests(unittest.TestCase):
    def test_spacing_newlines_package_source_and_version_share_canonical_identity(self):
        text = ("select * from {{ ref (\n'orders'\n) }} a join {{- ref( 'pkg',\n\"users\", v = 2 ) -}} b "
                "on a.id=b.id join {{ source ( 'raw',\n 'events' ) }} c on b.id=c.id")
        result = extract_references(text)
        self.assertEqual([r['key'] for r in result['references']],
                         ['ref:orders', 'ref:pkg.users@version=2', 'source:raw.events'])
        self.assertFalse(result['unresolved'])
        self.assertFalse(result['execution_performed'])
        self.assertEqual(parse_literal_call("ref('pkg','users',version=2)")['key'], result['references'][1]['key'])
        self.assertEqual(parse_literal_call("ref('users',version='2026.1')")['key'], 'ref:users@version=2026%2E1')
        self.assertEqual([text[r['span']['start']:r['span']['end']][:2] for r in result['references']], ['{{'] * 3)

    def test_sql_comments_quoted_identifiers_and_values_cannot_invent_edges(self):
        cases = ["-- {{ ref('fake') }}", "# {{ ref('fake') }}", "/* nested /* {{ ref('fake') }} */ */",
                 "'{{ ref(\"fake\") }}'", '"{{ ref(\'fake\') }}"', "`{{ ref('fake') }}`",
                 "[{{ ref('fake') }}]", "$body${{ ref('fake') }}$body$", "$$ {{ ref('fake') }} $$",
                 "'escaped '' {{ ref(\"fake\") }}'", "'backslash \\' {{ ref(\"fake\") }}'"]
        for protected in cases:
            with self.subTest(protected=protected):
                result = extract_references(protected + "\nselect * from {{ ref('real') }}")
                self.assertEqual([r['key'] for r in result['references']], ['ref:real'])
                self.assertEqual(result['unresolved'][0]['reason'], 'template_in_literal_or_comment')

    def test_jinja_comments_strings_and_raw_macro_blocks_are_inert(self):
        ignored = ["{# {{ ref('fake') }} #}", "{{ \"ref('fake')\" }}",
                   "{% raw %}{{ ref('fake') }} ' {% endraw %}",
                   "{% macro helper() %}{{ ref('fake') }}{% endmacro %}"]
        for template in ignored:
            result = extract_references(template + " select * from {{ ref('real') }}")
            self.assertEqual([r['key'] for r in result['references']], ['ref:real'])
        self.assertFalse(extract_references(ignored[0])['unresolved'])

    def test_dynamic_and_unsupported_calls_remain_explicit_without_execution(self):
        expressions = ["ref(model_name)", "source('raw', var('table'))", "ref('prefix_' ~ name)",
                       "ref('a' + 'b')", "ref('a' 'b')", "ref('a', version=var('v'))",
                       "ref('a', v=True)", "ref('a', v=1, version=2)", "ref('a', unknown=1)",
                       "ref('a', v='1' '2')", "ref('a', v=0x10)", "ref('a') # not Jinja",
                       "source('raw', 'a', version=1)", "ref(*names)", "ref(**names)",
                       "ref('a').render()", "custom_macro()", "run_query('drop table important')",
                       "__import__('os').system('false')"]
        with patch('subprocess.run', side_effect=AssertionError('must not execute')), patch('os.system', side_effect=AssertionError('must not execute')):
            for expression in expressions:
                with self.subTest(expression=expression):
                    result = extract_references('{{ ' + expression + ' }}')
                    self.assertFalse(result['references'])
                    self.assertEqual(len(result['unresolved']), 1)

    def test_control_flow_and_malformed_templates_do_not_become_complete(self):
        for text in ("{% if flag %}{{ ref('conditional') }}{% endif %}",
                     "{% for n in names %}{{ ref(n) }}{% endfor %}", "{{ ref('broken')"):
            result = extract_references(text)
            self.assertFalse(result['references'])
            self.assertTrue(result['unresolved'])

    def test_braces_inside_names_and_escaped_separators_do_not_truncate_or_collide(self):
        result = extract_references("{{ ref('a}}b') }} {{ ref('p.q', 'r') }} {{ ref('p', 'q.r') }}")
        self.assertEqual([r['key'] for r in result['references']], ['ref:a%7D%7Db', 'ref:p%2Eq.r', 'ref:p.q%2Er'])
        self.assertFalse(result['unresolved'])

    def test_authoring_mask_reuses_keys_and_keeps_dynamic_bytes(self):
        text = "select id from {{\n ref ('pkg', 'orders', version = 2)\n}} -- ordinary comment"
        masked, calls, gaps = mask_static_dbt_sql(text)
        self.assertEqual(len(masked), len(text))
        self.assertFalse(gaps)
        self.assertEqual(calls[0]['key'], 'ref:pkg.orders@version=2')
        dynamic = "select id from {{ ref(var('table')) }}"
        masked, calls, gaps = mask_static_dbt_sql(dynamic)
        self.assertEqual(masked, dynamic)
        self.assertFalse(calls)
        self.assertIn('sql_template_unsupported', gaps)


if __name__ == '__main__':
    unittest.main()
