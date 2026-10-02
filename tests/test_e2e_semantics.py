"""Execute tiny definition-driven probes; no external fixture/oracle is read."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/data-model-accelerator/scripts/e2e_semantics.py"
SPEC = importlib.util.spec_from_file_location("e2e_semantics", SCRIPT)
semantics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(semantics)

try:
    import duckdb
    import sqlglot
    import yaml
    import lkml
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False


@unittest.skipUnless(DEPENDENCIES, "E2E semantic probes require the optional pinned simulation dependencies")
class E2ESemanticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "repo"
        self.omni = self.root / "omni"
        for folder in ("views", "models", "dashboards"):
            (self.repo / folder).mkdir(parents=True)
        self.omni.mkdir()
        self.model_path = self.repo / "models/billing.model.lkml"
        self.model_path.write_text('''connection: "offline"
include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"
explore: invoices {
  access_filter: { field: invoices.tenant_id user_attribute: tenant_id }
}
''')
        fields = ["tenant_id", "invoice_id", "invoice_date", "currency", "status", "segment", "net_cents", "paid_cents"]
        dimensions = "\n".join(f'dimension: {field} {{ type: string sql: ${{TABLE}}.{field} ;; }}' for field in fields)
        self.view_path = self.repo / "views/invoices.view.lkml"
        self.view_path.write_text('''view: invoices {
derived_table: { sql: SELECT * FROM DMA_SIM.GOLD.SOURCE_INVOICES ;; }
''' + dimensions + '''
measure: invoice_count { type: count filters: [status: "posted"] }
measure: net_cents_sum { type: sum sql: ${net_cents} ;; filters: [status: "posted"] }
measure: paid_cents_sum { type: sum sql: ${paid_cents} ;; filters: [status: "posted"] }
measure: payment_rate { type: number sql: ${paid_cents_sum} / NULLIF(${net_cents_sum}, 0) ;; }
}
''')
        self.context = {
            "model": "billing", "explore": "invoices",
            "filters": [
                {"name": "Reporting Date", "field": "invoices.invoice_date", "default_value": "2026/09/01 to 2026/09/30"},
                {"name": "Currency", "field": "invoices.currency", "default_value": "USD"},
            ],
            "element": {
                "model": "billing", "explore": "invoices",
                "fields": ["invoices.segment", "invoices.invoice_count", "invoices.net_cents_sum", "invoices.paid_cents_sum", "invoices.payment_rate"],
                "filters": {"invoices.status": "posted"},
                "listen": {"Reporting Date": "invoices.invoice_date", "Currency": "invoices.currency"},
                "sorts": ["invoices.segment"], "limit": 500,
            },
        }
        self.dashboard_path = self.repo / "dashboards/report.dashboard.lookml"
        self.write_dashboard()
        omni_dimensions = {field: {"sql": '"' + field.upper() + '"'} for field in fields if field != "segment"}
        omni_dimensions.update(invoice_key={"sql": '"INVOICE_ID"', "primary_key": True}, customer_key={"sql": '"CUSTOMER_KEY"'})
        self.invoice_view = {
            "catalog": "DMA_SIM", "schema": "GOLD", "table_name": "SOURCE_INVOICES",
            "dimensions": omni_dimensions,
            "measures": {
                "invoice_count": {"aggregate_type": "count", "sql": "${invoices.invoice_key}", "filters": {"status": {"is": "posted"}}},
                "raw_net": {"aggregate_type": "sum", "sql": "${invoices.net_cents}", "filters": {"status": {"is": "posted"}}, "hidden": True},
                "raw_paid": {"aggregate_type": "sum", "sql": "${invoices.paid_cents}", "filters": {"status": {"is": "posted"}}, "hidden": True},
                "net_cents_sum": {"sql": "COALESCE(${raw_net}, 0)"},
                "paid_cents_sum": {"sql": "COALESCE(${raw_paid}, 0)"},
                "payment_rate": {"sql": "${paid_cents_sum} / NULLIF(${net_cents_sum}, 0)"},
            },
        }
        self.customer_view = {
            "catalog": "DMA_SIM", "schema": "GOLD", "table_name": "CUSTOMERS",
            "dimensions": {"customer_key": {"sql": '"CUSTOMER_KEY"', "primary_key": True},
                           "tenant_id": {"sql": '"TENANT_ID"'}, "segment": {"sql": '"SEGMENT"'}},
        }
        self.relationship = [{"join_from_view": "invoices", "join_to_view": "customers",
                              "join_type": "always_left", "relationship_type": "many_to_one",
                              "on_sql": "${invoices.customer_key} = ${customers.customer_key}"}]
        self.topic = {"base_view": "invoices", "joins": {"customers": {}},
                      "access_filters": [{"field": "invoices.tenant_id", "user_attribute": "tenant_id"}]}
        self.omni_context = json.loads(json.dumps(self.context))
        self.omni_context["element"]["fields"][0] = "customers.segment"
        self.omni_context["element"]["sorts"] = ["customers.segment"]
        self.write_omni()
        self.db = duckdb.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH ':memory:' AS DMA_SIM")
        self.db.execute("CREATE SCHEMA DMA_SIM.GOLD")
        self.db.execute('''CREATE TABLE DMA_SIM.GOLD.SOURCE_INVOICES (
            TENANT_ID VARCHAR, INVOICE_ID VARCHAR, INVOICE_DATE DATE, CURRENCY VARCHAR,
            STATUS VARCHAR, SEGMENT VARCHAR, NET_CENTS INTEGER, PAID_CENTS INTEGER, CUSTOMER_KEY VARCHAR)''')
        self.db.execute("CREATE TABLE DMA_SIM.GOLD.CUSTOMERS (CUSTOMER_KEY VARCHAR, TENANT_ID VARCHAR, SEGMENT VARCHAR)")
        self.db.executemany("INSERT INTO DMA_SIM.GOLD.SOURCE_INVOICES VALUES (?,?,?,?,?,?,?,?,?)", [
            ("A", "i1", "2026-09-01", "USD", "posted", "Enterprise", 100, 25, "A:c1"),
            ("A", "i2", "2026-09-30", "USD", "posted", "SMB", 300, 150, "A:c2"),
            ("A", "i3", "2026-09-15", "USD", "draft", "Draft only", 900, 900, "A:c3"),
            ("A", "i4", "2026-10-01", "USD", "posted", "Enterprise", 800, 800, "A:c1"),
            ("A", "i5", "2026-09-15", "EUR", "posted", "Enterprise", 700, 700, "A:c1"),
            ("B", "i1", "2026-09-10", "USD", "posted", "Enterprise", 500, 400, "B:c1"),
            ("A", "i6", "2026-09-20", "USD", "posted", "Zero", 0, 50, "A:c4"),
        ])
        self.db.executemany("INSERT INTO DMA_SIM.GOLD.CUSTOMERS VALUES (?,?,?)", [
            ("A:c1", "A", "Enterprise"), ("A:c2", "A", "SMB"),
            ("A:c3", "A", "Draft only"), ("A:c4", "A", "Zero"), ("B:c1", "B", "Enterprise"),
        ])

    def write_dashboard(self):
        self.dashboard_path.write_text(yaml.safe_dump([{"dashboard": "billing", "filters": self.context["filters"], "elements": [self.context["element"]]}]))

    def write_omni(self):
        for filename, value in [("invoices.view", self.invoice_view), ("customers.view", self.customer_view),
                                ("relationships", self.relationship), ("billing.topic", self.topic)]:
            (self.omni / filename).write_text(yaml.safe_dump(value))
        (self.omni / "report-context.json").write_text(json.dumps(self.omni_context))

    def query(self, kind, **parameters):
        diagnostic = parameters.pop("apply_dashboard_filters", True)
        compiler, path = (semantics.compile_looker, self.repo) if kind == "looker" else (semantics.compile_omni, self.omni)
        sql = compiler(path, {"tenant": "A", **parameters}, apply_dashboard_filters=diagnostic)
        return self.db.execute(sqlglot.transpile(sql, read="snowflake", write="duckdb")[0]).fetchall()

    def test_dates_currency_tenant_and_weighted_ratio_execute_from_definitions(self):
        for kind in ("looker", "omni"):
            with self.subTest(kind=kind):
                total = self.query(kind)[0]
                self.assertEqual(total[:3], (3, 400, 225))
                self.assertAlmostEqual(total[3], 225 / 400)
                self.assertEqual(self.query(kind, tenant="B")[0][:3], (1, 500, 400))
                self.assertEqual(self.query(kind, currency="EUR")[0][:3], (1, 700, 700))
                self.assertEqual(self.query(kind, start_date="2026-09-30", end_date="2026-10-01")[0][:3], (1, 300, 150))

    def test_empty_sum_boundary_is_declared_in_target_not_hidden_in_source_compiler(self):
        self.assertEqual(self.query("looker", segment="absent"), [(0, None, None, None)])
        self.assertEqual(self.query("omni", segment="absent"), [(0, 0, 0, None)])
        self.invoice_view["measures"]["net_cents_sum"]["sql"] = "${raw_net}"
        self.write_omni()
        self.assertEqual(self.query("omni", segment="absent")[0][1], None)

    def test_equal_date_endpoints_execute_as_an_empty_half_open_selection(self):
        parameters = {"start_date": "2026-09-01", "end_date": "2026-09-01"}
        self.assertEqual(self.query("looker", **parameters), [(0, None, None, None)])
        self.assertEqual(self.query("omni", **parameters), [(0, 0, 0, None)])
        for kind in ("looker", "omni"):
            self.assertEqual(self.query(kind, group_by=["segment"], **parameters), [])

    def test_diagnostic_removes_tile_status_only_and_preserves_measure_filters(self):
        for kind in ("looker", "omni"):
            rows = self.query(kind, group_by=["segment"], apply_dashboard_filters=False)
            self.assertEqual(rows[0][0], "Draft only")
            self.assertEqual(rows[0][1:], (0, None, None, None) if kind == "looker" else (0, 0, 0, None))
            self.assertEqual(self.query(kind, group_by=["segment"])[0][0], "Enterprise")
            self.assertEqual(self.query(kind, apply_dashboard_filters=False)[0][:3], (3, 400, 225))

    def test_zero_net_is_raw_row_filter_with_null_ratio(self):
        for kind in ("looker", "omni"):
            self.assertEqual(self.query(kind, zero_net_only=True), [(1, 0, 50, None)])

    def test_changed_source_measure_changes_executed_result(self):
        before = self.query("looker")[0]
        self.view_path.write_text(self.view_path.read_text().replace("sql: ${net_cents} ;;", "sql: ${net_cents} * 2 ;;"))
        after = self.query("looker")[0]
        self.assertEqual(after[1], before[1] * 2)
        self.assertAlmostEqual(after[3], before[3] / 2)

    def test_changed_target_measure_changes_executed_result(self):
        self.invoice_view["measures"]["raw_net"]["sql"] = "${invoices.net_cents} * 2"
        self.write_omni()
        self.assertEqual(self.query("omni")[0][:3], (3, 800, 225))

    def test_relationship_sql_is_executed_instead_of_replaced_by_hardcoded_join(self):
        self.db.execute("UPDATE DMA_SIM.GOLD.CUSTOMERS SET TENANT_ID='B' WHERE CUSTOMER_KEY='A:c1'")
        self.assertEqual(self.query("omni", segment="Enterprise")[0][:3], (1, 100, 25))
        self.relationship[0]["on_sql"] += " AND ${invoices.tenant_id} = ${customers.tenant_id}"
        self.write_omni()
        self.assertEqual(self.query("omni", segment="Enterprise")[0][:3], (0, 0, 0))

    def test_missing_misbound_and_invalid_tenant_policies_fail_closed(self):
        for compiler, path in ((semantics.compile_looker, self.repo), (semantics.compile_omni, self.omni)):
            for tenant in (None, "C", "", "A' OR '1'='1"):
                with self.subTest(compiler=compiler.__name__, tenant=tenant):
                    with self.assertRaisesRegex(semantics.SemanticCompileError, "tenant attribute"):
                        compiler(path, {"tenant": tenant})
        self.model_path.write_text(self.model_path.read_text().replace("field: invoices.tenant_id", "field: invoices.currency"))
        with self.assertRaisesRegex(semantics.SemanticCompileError, "Tenant access policy"):
            self.query("looker")
        self.topic["access_filters"] = []
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "Tenant access policy"):
            self.query("omni")

    def test_security_dimension_cannot_be_rebound_to_a_constant(self):
        self.invoice_view["dimensions"]["tenant_id"]["sql"] = "'A'"
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "physical TENANT_ID"):
            self.query("omni")

    def test_listen_and_dashboard_default_are_validated_even_when_overridden(self):
        self.omni_context["element"]["listen"]["Currency"] = "invoices.status"
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "listen"):
            self.query("omni", currency="USD")
        self.context["filters"][0]["default_value"] = "last 30 days"
        self.write_dashboard()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "date default"):
            self.query("looker", start_date="2026-09-01", end_date="2026-10-01")

    def test_sql_literal_escaping_does_not_expand_the_segment_filter(self):
        for kind in ("looker", "omni"):
            self.assertEqual(self.query(kind, segment="Enterprise' OR 1=1 --")[0][0], 0)

    def test_unknown_aggregate_filter_function_and_cycles_are_rejected(self):
        mutations = [
            (lambda: self.invoice_view["measures"]["raw_net"].update(aggregate_type="average"), "aggregate type"),
            (lambda: self.invoice_view["measures"]["raw_net"].update(filters={"status": {"not": "posted"}}), "filter operator"),
            (lambda: self.invoice_view["measures"]["net_cents_sum"].update(sql="MYSTERY(${raw_net})"), "construct"),
            (lambda: self.invoice_view["measures"]["raw_net"].update(sql="${net_cents_sum}"), "references a measure"),
            (lambda: self.invoice_view["dimensions"]["net_cents"].update(sql="${net_cents}"), "Cyclic"),
        ]
        pristine = json.loads(json.dumps(self.invoice_view))
        for mutate, message in mutations:
            self.invoice_view = json.loads(json.dumps(pristine))
            mutate()
            self.write_omni()
            with self.subTest(message=message):
                with self.assertRaisesRegex(semantics.SemanticCompileError, message):
                    self.query("omni")

    def test_snowflake_quoted_case_and_unsupported_join_do_not_pass_duckdb_silently(self):
        self.invoice_view["dimensions"]["net_cents"]["sql"] = '"net_cents"'
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "Quoted physical column"):
            self.query("omni")
        self.invoice_view["dimensions"]["net_cents"]["sql"] = '"NET_CENTS"'
        self.relationship[0]["relationship_type"] = "many_to_many"
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "many_to_one"):
            self.query("omni")

    def test_unknown_semantic_keys_and_unincluded_source_are_rejected(self):
        self.invoice_view["measures"]["raw_net"]["sql_distinct_key"] = "${invoice_key}"
        self.write_omni()
        with self.assertRaisesRegex(semantics.SemanticCompileError, "unsupported keys"):
            self.query("omni")
        self.model_path.write_text(self.model_path.read_text().replace('include: "/views/*.view.lkml"', ""))
        with self.assertRaisesRegex(semantics.SemanticCompileError, "must be included"):
            self.query("looker")

    def test_parameter_contract_rejects_invalid_dates_and_unknown_grouping(self):
        for parameters in ({"start_date": "2026-09-31"}, {"end_date": "2026-08-31"},
                           {"group_by": ["tenant_id"]}, {"currency": "USD'; DROP TABLE x"},
                           {"zero_net_only": "false"}, {"unknown": 1}):
            with self.subTest(parameters=parameters):
                with self.assertRaises(semantics.SemanticCompileError):
                    self.query("omni", **parameters)


if __name__ == "__main__":
    unittest.main()
