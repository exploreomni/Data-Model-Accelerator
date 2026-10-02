#!/usr/bin/env python3
"""Validate only the bundled synthetic SQLite example, never input-repository SQL.

Stdlib only. In-memory databases; optional local JSON report. This is development
evidence, not platform compilation, production acceptance, or access enforcement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Callable


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
REQUIRED_FILES = (
    "source_fixture.json", "report_contract.json", "expected_saas_export.json",
    "candidate.sql", "report_rows.sql", "legacy.sql", "CASE.md",
)
EXPECTED_CHECK_IDS = (
    "fixture_contract", "source_event_consistency", "source_duplicate_deliveries",
    "source_history_nonoverlap", "initial_rows_match_export",
    "source_composite_grain", "source_to_gold_relationship", "final_rows_match_export", "final_groups_match_export",
    "filter_context_matches_contract", "ratio_recomputed_after_filter",
    "tenant_functional_isolation", "historical_boundaries", "late_arrival_and_delete",
    "replay_idempotence", "full_rebuild_equivalence", "mutation_fanout_caught",
    "mutation_cross_tenant_caught", "mutation_filter_caught",
    "mutation_last_arrival_caught", "mutation_delete_resurrection_caught",
    "legacy_superficial_match", "legacy_hidden_defects_caught",
)
LIMITATIONS = [
    "Synthetic local SQLite demonstrator; no real SaaS export or customer data.",
    "No input-repository SQL is accepted or executed by this CLI.",
    "Append-only ingestion plus recomputed views; not a production incremental materialization test.",
    "Tenant query filtering is only a functional isolation probe, not warehouse authorization or RLS.",
    "Real platform compilation, execution, CDC integration, RLS, performance, and production acceptance remain unverified.",
]
SOURCE_COLUMNS = [
    "batch", "source_event_id", "tenant_id", "invoice_id", "source_sequence",
    "operation", "customer_id", "invoice_date", "status", "gross_cents", "paid_cents",
]
SCHEMA = """
CREATE TABLE bronze_invoice_cdc (
    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch INTEGER NOT NULL, source_event_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL,
    source_sequence INTEGER NOT NULL, operation TEXT NOT NULL,
    customer_id TEXT NOT NULL, invoice_date TEXT NOT NULL, status TEXT NOT NULL,
    gross_cents INTEGER NOT NULL, paid_cents INTEGER NOT NULL
);
CREATE TABLE customer_history (
    tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL, segment TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_to TEXT,
    PRIMARY KEY (tenant_id, customer_id, valid_from)
);
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: object, expected: object, location: str = "result") -> None:
    """Exact shapes, strings and integer cents; tolerance only for float ratios."""
    if isinstance(expected, float):
        require(isinstance(actual, (int, float)) and math.isclose(
            actual, expected, rel_tol=1e-12, abs_tol=1e-12),
            f"{location}: expected {expected!r}, got {actual!r}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected),
                f"{location}: expected {len(expected)} items, got {actual!r}")
        for index, (left, right) in enumerate(zip(actual, expected)):
            assert_equal(left, right, f"{location}[{index}]")
    else:
        require(type(actual) is type(expected) and actual == expected,
                f"{location}: expected {expected!r}, got {actual!r}")


def params(filters: dict | None = None) -> dict:
    result = {"tenant_id": None, "segment": None, "month": None, "invoice_id": None}
    if filters:
        require(not (set(filters) - set(result)), "Unknown fixture filter")
        result.update(filters)
    return result


def fetch(db: sqlite3.Connection, sql: str, filters: dict | None = None,
          columns: list | None = None) -> list:
    cursor = db.execute(sql, params(filters))
    if columns is not None:
        assert_equal([entry[0] for entry in cursor.description], columns, "columns")
    return [list(row) for row in cursor.fetchall()]


def group_sql(row_sql: str) -> str:
    return f"""WITH filtered AS ({row_sql})
    SELECT tenant_id, month, segment, COUNT(*) AS invoice_count,
           SUM(gross_cents) AS gross_cents, SUM(paid_cents) AS paid_cents,
           1.0 * SUM(paid_cents) / NULLIF(SUM(gross_cents), 0) AS payment_rate
    FROM filtered GROUP BY tenant_id, month, segment ORDER BY tenant_id, month, segment"""


def total_sql(row_sql: str) -> str:
    return f"""WITH filtered AS ({row_sql})
    SELECT COUNT(*) AS invoice_count, COALESCE(SUM(gross_cents), 0) AS gross_cents,
           COALESCE(SUM(paid_cents), 0) AS paid_cents,
           1.0 * SUM(paid_cents) / NULLIF(SUM(gross_cents), 0) AS payment_rate
    FROM filtered"""


def ingest(db: sqlite3.Connection, deliveries: list) -> None:
    db.executemany(
        f"INSERT INTO bronze_invoice_cdc ({', '.join(SOURCE_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in SOURCE_COLUMNS)})", deliveries)


def database(source: dict, sql: str, deliveries: list) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    # Defense in depth: bundled example SQL cannot attach a disk database.
    db.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in
                      (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
    try:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO customer_history VALUES (?, ?, ?, ?, ?, ?)",
                       source["customer_history"])
        ingest(db, deliveries)
        db.executescript(sql)
        return db
    except Exception:
        db.close()
        raise


def replace_once(sql: str, original: str, replacement: str) -> str:
    require(sql.count(original) == 1, f"Mutation anchor missing or ambiguous: {original!r}")
    return sql.replace(original, replacement, 1)


class Checks:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, check_id: str, action: Callable[[], object]) -> None:
        require(check_id in EXPECTED_CHECK_IDS, f"Unregistered check: {check_id}")
        require(check_id not in {r["id"] for r in self.results}, f"Duplicate check: {check_id}")
        try:
            evidence = action()
            self.results.append({"id": check_id, "status": "passed", "evidence": evidence})
        except (AssertionError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            self.results.append({"id": check_id, "status": "failed", "error": str(exc)})


def validate_contract(source: dict, contract: dict, expected: dict) -> str:
    require(source["fixture_kind"] == "synthetic-local-sqlite-demonstrator", "Wrong source kind")
    require(contract["contract_version"] == 1, "Unsupported fixture contract version")
    require(expected["fixture_kind"] == "synthetic-hand-authored-expected-export", "Wrong expected export kind")
    assert_equal(contract["source_columns"], SOURCE_COLUMNS)
    assert_equal(contract["fact_grain"], ["tenant_id", "invoice_id"])
    require(len(source["invoice_deliveries"]) > 0 and len(source["customer_history"]) > 0,
            "Source fixture must not be empty")
    for row in source["invoice_deliveries"]:
        require(len(row) == 11, "Malformed CDC delivery")
        require(all(type(row[index]) is int for index in (0, 4, 9, 10)), "CDC counters and cents must be integers")
        require(row[0] in (1, 2) and row[4] > 0, "Unexpected batch or source sequence")
        require(all(isinstance(row[index], str) and row[index] for index in (1, 2, 3, 5, 6, 7, 8)),
                "CDC identifiers and attributes must be nonempty strings")
        require(row[5] in ("upsert", "delete") and row[8] in ("posted", "draft"), "Unexpected source operation or status")
        require(row[9] >= 0 and 0 <= row[10] <= row[9], "Invalid synthetic invoice amount")
        dt.date.fromisoformat(row[7])
    for row in source["customer_history"]:
        require(len(row) == 6, "Malformed customer history row")
        require(all(isinstance(value, str) and value for value in row[:5]), "Invalid customer attributes")
        dt.date.fromisoformat(row[4])
        if row[5] is not None:
            dt.date.fromisoformat(row[5])
            require(row[4] < row[5], "Invalid effective interval")
    for key, columns in (("initial_rows", "row_columns"), ("final_rows", "row_columns"), ("final_groups", "group_columns")):
        require(bool(expected[key]), f"Missing expected {key}")
        require(all(len(row) == len(contract[columns]) for row in expected[key]), f"Malformed {key}")
    require({s["name"] for s in expected["scenarios"]} == {
        "all", "tenant_a", "tenant_b", "a_startup", "a_enterprise_feb", "zero_denominator", "empty_selection"
    }, "Required interaction scenarios missing or changed")
    for scenario in expected["scenarios"]:
        params(scenario["filters"])
        require(len(scenario["totals"]) == 4, "Missing expected scenario totals")
    return "Required schemas, explicit contract, and independent expected fixtures are present."


def validate_events(source: dict) -> str:
    versions: dict[tuple, tuple] = {}
    identities: dict[tuple, tuple] = {}
    for row in source["invoice_deliveries"]:
        semantic = tuple(row[1:])  # Delivery batch is not source event identity.
        version = (row[2], row[3], row[4])
        identity = (row[2], row[1])
        require(version not in versions or versions[version] == semantic,
                f"Conflicting payloads at source sequence {version}")
        require(identity not in identities or identities[identity] == semantic,
                f"Conflicting source event identity {identity}")
        versions[version] = semantic
        identities[identity] = semantic
    return f"{len(versions)} unique tenant/invoice/source-sequence events; no conflicting equal-sequence payloads."


def validate_histories(source: dict) -> str:
    rows = source["customer_history"]
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if left[:2] == right[:2]:
                require(not (left[4] < (right[5] or "9999-12-31") and
                             right[4] < (left[5] or "9999-12-31")),
                        f"Overlapping customer history for {left[:2]}")
    return "Tenant/customer effective intervals do not overlap."


def run_validation(examples_dir: Path = EXAMPLES_DIR) -> dict:
    """The path override exists for isolated unit fixtures, not as a CLI input."""
    checks = Checks()
    db = None
    error = None
    try:
        missing = [name for name in REQUIRED_FILES if not (examples_dir / name).is_file()]
        require(not missing, f"Missing required bundled example input: {', '.join(missing)}")
        source = json.loads((examples_dir / "source_fixture.json").read_text())
        contract = json.loads((examples_dir / "report_contract.json").read_text())
        expected = json.loads((examples_dir / "expected_saas_export.json").read_text())
        candidate_sql = (examples_dir / "candidate.sql").read_text()
        row_sql = (examples_dir / "report_rows.sql").read_text().strip().rstrip(";")
        legacy_sql = (examples_dir / "legacy.sql").read_text()
        checks.check("fixture_contract", lambda: validate_contract(source, contract, expected))
        if checks.results[-1]["status"] != "passed":
            raise ValueError("Invalid fixture contract; SQL execution blocked")
        checks.check("source_event_consistency", lambda: validate_events(source))
        checks.check("source_duplicate_deliveries", lambda: (
            require(len(source["invoice_deliveries"]) - len({tuple(r[1:]) for r in source["invoice_deliveries"]}) == 3,
                    "Expected three duplicate/replayed source deliveries"),
            "Three redundant deliveries intentionally preserve source event identity."
        )[-1])
        checks.check("source_history_nonoverlap", lambda: validate_histories(source))
        if any(c["status"] != "passed" for c in checks.results):
            raise ValueError("Invalid source fixture; SQL execution blocked")

        batch1 = [row for row in source["invoice_deliveries"] if row[0] == 1]
        batch2 = [row for row in source["invoice_deliveries"] if row[0] == 2]
        db = database(source, candidate_sql, batch1)

        def match_rows(sql: str = row_sql, target: str = "final_rows") -> str:
            rows = fetch(db, sql, columns=contract["row_columns"])
            assert_equal(rows, expected[target], target)
            return f"{len(rows)} rows match independent expected values in every column."

        checks.check("initial_rows_match_export", lambda: match_rows(target="initial_rows"))
        ingest(db, batch2)

        def source_grain() -> str:
            rows = fetch(db, "SELECT tenant_id, invoice_id FROM silver_invoice_current ORDER BY tenant_id, invoice_id")
            require(len(rows) == len({tuple(r) for r in rows}) == 8, "Current source fact grain is not unique")
            require(["A", "I100"] in rows and ["B", "I100"] in rows, "Tenant-shared invoice IDs were collapsed")
            return "Eight current rows at tenant/invoice grain; shared IDs remain separate."

        checks.check("source_composite_grain", source_grain)

        def relationship_probe() -> str:
            rows = fetch(db, """SELECT s.tenant_id, s.invoice_id, COUNT(g.invoice_id)
                FROM silver_invoice_current AS s LEFT JOIN gold_invoice_fact AS g
                  ON s.tenant_id = g.tenant_id AND s.invoice_id = g.invoice_id
                GROUP BY s.tenant_id, s.invoice_id ORDER BY s.tenant_id, s.invoice_id""")
            require(bool(rows) and all(row[2] == 1 for row in rows),
                    f"Each current invoice needs exactly one temporal dimension match; observed {rows}")
            return "Every current invoice has exactly one gold row; orphan histories and join fanout fail this relationship gate."

        checks.check("source_to_gold_relationship", relationship_probe)
        checks.check("final_rows_match_export", match_rows)
        checks.check("final_groups_match_export", lambda: (
            assert_equal(fetch(db, group_sql(row_sql), columns=contract["group_columns"]), expected["final_groups"], "groups"),
            "Five tenant/month/segment groups match count, integer cents, and recomputed ratio."
        )[-1])

        def check_scenarios() -> str:
            for scenario in expected["scenarios"]:
                actual = fetch(db, row_sql, scenario["filters"])
                assert_equal([row[:2] for row in actual], scenario["row_keys"], scenario["name"] + " rows")
                assert_equal(fetch(db, total_sql(row_sql), scenario["filters"], contract["total_columns"])[0],
                             scenario["totals"], scenario["name"] + " totals")
            return "Seven interaction scenarios match explicit row populations and totals, including zero and empty selections."

        checks.check("filter_context_matches_contract", check_scenarios)

        def ratio_probe() -> str:
            filters = {"tenant_id": "A", "segment": "Startup"}
            rate = fetch(db, total_sql(row_sql), filters)[0][-1]
            wrong = fetch(db, f"WITH filtered AS ({row_sql}) SELECT AVG(payment_rate) FROM filtered", filters)[0][0]
            assert_equal(rate, 0.32, "weighted filtered ratio")
            require(not math.isclose(rate, wrong), "Fixture failed to distinguish average-of-ratios")
            return f"Filtered ratio is {rate}; incorrect average-of-ratios would be {wrong}."

        checks.check("ratio_recomputed_after_filter", ratio_probe)

        def isolation_probe() -> str:
            leaks = fetch(db, "SELECT COUNT(*) FROM gold_invoice_fact WHERE tenant_id <> dimension_tenant_id")[0][0]
            require(leaks == 0, "Cross-tenant dimension data leaked through join")
            for tenant in ("A", "B"):
                wanted = [row for row in expected["final_rows"] if row[0] == tenant]
                assert_equal(fetch(db, row_sql, {"tenant_id": tenant}), wanted, f"tenant {tenant}")
            return "Both tenant-filtered outputs and dimension tenant identity match; functional probe only, not RLS."

        checks.check("tenant_functional_isolation", isolation_probe)
        checks.check("historical_boundaries", lambda: (
            assert_equal(fetch(db, "SELECT invoice_id, segment FROM gold_invoice_fact WHERE tenant_id = 'A' AND invoice_id IN ('I100','I101','I106','I107') ORDER BY invoice_id"),
                         [["I100", "Startup"], ["I101", "Enterprise"], ["I106", "Startup"], ["I107", "Enterprise"]]),
            "January 31 and late January 30 remain Startup; February 1 uses Enterprise."
        )[-1])
        checks.check("late_arrival_and_delete", lambda: (
            assert_equal(fetch(db, "SELECT invoice_id, paid_cents FROM silver_invoice_current WHERE tenant_id = 'A' AND invoice_id IN ('I100','I102','I106') ORDER BY invoice_id"), [["I100", 6000], ["I106", 10000]]),
            assert_equal(fetch(db, "SELECT paid_cents FROM silver_invoice_current WHERE tenant_id = 'B' AND invoice_id = 'I104'"), [[5000]]),
            "Late older events do not overwrite corrections; late historical insert appears; deleted I102 stays absent."
        )[-1])

        def replay_probe() -> str:
            before = fetch(db, row_sql)
            ingest(db, batch2)
            assert_equal(fetch(db, row_sql), before, "replay rows")
            assert_equal(fetch(db, group_sql(row_sql)), expected["final_groups"], "replay groups")
            return "Replaying the entire second batch preserves exact rows and grouped outputs."

        checks.check("replay_idempotence", replay_probe)

        def rebuild_probe() -> str:
            for deliveries in (source["invoice_deliveries"], list(reversed(source["invoice_deliveries"]))):
                rebuilt = database(source, candidate_sql, deliveries)
                try:
                    assert_equal(fetch(rebuilt, row_sql), expected["final_rows"], "rebuild rows")
                    assert_equal(fetch(rebuilt, group_sql(row_sql)), expected["final_groups"], "rebuild groups")
                    assert_equal(fetch(rebuilt, row_sql), fetch(db, row_sql), "incremental ingestion versus rebuild")
                finally:
                    rebuilt.close()
            return "One-shot normal and reverse delivery-order rebuilds equal append-only batch ingestion and the independent export."

        checks.check("full_rebuild_equivalence", rebuild_probe)

        def mutation_probe(kind: str) -> str:
            mutated = candidate_sql
            mutated_rows = row_sql
            if kind == "fanout":
                mutated = replace_once(mutated, " AND i.invoice_date >= h.valid_from\n AND (h.valid_to IS NULL OR i.invoice_date < h.valid_to)", "")
            elif kind == "cross_tenant":
                mutated = replace_once(mutated, "ON i.tenant_id = h.tenant_id\n AND i.customer_id = h.customer_id", "ON i.customer_id = h.customer_id")
            elif kind == "filter":
                mutated_rows = replace_once(row_sql, "AND (:segment IS NULL OR segment = :segment)", "AND 1 = 1 -- DEFECT: segment filter dropped")
            elif kind == "last_arrival":
                mutated = replace_once(mutated, "ORDER BY source_sequence DESC, delivery_id DESC", "ORDER BY delivery_id DESC")
            elif kind == "delete_resurrection":
                mutated = replace_once(mutated, "FROM bronze_invoice_cdc", "FROM bronze_invoice_cdc WHERE operation = 'upsert'")
            else:
                raise ValueError(f"Unknown mutation: {kind}")
            mutant = database(source, mutated, source["invoice_deliveries"])
            try:
                actual = fetch(mutant, mutated_rows)
                if kind == "filter":
                    # This defect passes the unfiltered export, demonstrating why interaction evidence matters.
                    assert_equal(actual, expected["final_rows"], "unfiltered mutation control")
                    scenario = next(s for s in expected["scenarios"] if s["name"] == "a_startup")
                    actual_total = fetch(mutant, total_sql(mutated_rows), scenario["filters"])[0]
                    require(actual_total != scenario["totals"], "Filter mutation escaped the filtered-total oracle")
                    return f"Unfiltered rows still match, but filtered totals differ: {actual_total} versus {scenario['totals']}."
                require(actual != expected["final_rows"], f"{kind} mutation escaped row-level oracle")
                if kind == "fanout":
                    require(len(actual) > len({tuple(r[:2]) for r in actual}), "Fanout mutation did not create duplicate fact keys")
                    return f"Rejected duplicate fact keys: {len(actual)} report rows versus 8 expected."
                if kind == "cross_tenant":
                    leaks = fetch(mutant, "SELECT COUNT(*) FROM gold_invoice_fact WHERE tenant_id <> dimension_tenant_id")[0][0]
                    require(leaks > 0, "Cross-tenant mutation failed to exercise dimension leakage")
                    return f"Rejected {leaks} cross-tenant dimension joins, despite filtering on the fact tenant."
                if kind == "last_arrival":
                    require(fetch(mutant, mutated_rows, {"tenant_id": "A", "invoice_id": "I100"})[0][7] == 2000,
                            "Last-arrival mutation failed to exercise correction regression")
                    return "Rejected a late old delivery regressing A/I100 paid amount from 6000 to 2000 cents."
                require(any(row[:2] == ["A", "I102"] for row in actual), "Delete mutation did not resurrect tombstone")
                return "Rejected resurrected deleted invoice A/I102."
            finally:
                mutant.close()

        for kind in ("fanout", "cross_tenant", "filter", "last_arrival", "delete_resurrection"):
            checks.check(f"mutation_{kind}_caught", lambda kind=kind: mutation_probe(kind))

        db.executescript(legacy_sql)

        # Only query filter keys are forwarded; expected amounts are assertions.
        def legacy_smoke_checked() -> str:
            smoke = contract["legacy_smoke_test"]
            filters = {"tenant_id": smoke["tenant_id"], "month": smoke["month"]}
            assert_equal(fetch(db, "SELECT SUM(gross_cents), SUM(paid_cents) FROM legacy_report WHERE tenant_id = :tenant_id AND month = :month", filters)[0],
                         [smoke["gross_cents"], smoke["paid_cents"]])
            return "Legacy B/January gross and paid totals match the narrow smoke report."

        checks.check("legacy_superficial_match", legacy_smoke_checked)

        def legacy_defects() -> str:
            rows = fetch(db, "SELECT * FROM legacy_report ORDER BY tenant_id, invoice_id", columns=contract["row_columns"])
            require(rows != expected["final_rows"], "Legacy escaped row-level oracle")
            require(any(row[:2] == ["A", "I102"] for row in rows), "Expected legacy tombstone defect absent")
            require(any(row[:2] == ["A", "I100"] and row[5] == "Enterprise" and row[7] == 2000 for row in rows),
                    "Expected legacy historical and late-arrival defects absent")
            return "Wider evidence rejects legacy history rewrite, lost correction, and deleted invoice resurrection."

        checks.check("legacy_hidden_defects_caught", legacy_defects)
    except (OSError, ValueError, AssertionError, KeyError, TypeError, sqlite3.Error) as exc:
        error = str(exc)
    finally:
        if db is not None:
            db.close()

    executed = [entry["id"] for entry in checks.results]
    missing_checks = [check_id for check_id in EXPECTED_CHECK_IDS if check_id not in executed]
    coverage = executed == list(EXPECTED_CHECK_IDS)
    passed = coverage and not error and all(entry["status"] == "passed" for entry in checks.results)
    return {
        "schema_version": 1, "status": "passed" if passed else "failed",
        "evidence_class": "local_synthetic_development_validation",
        "checks_expected": len(EXPECTED_CHECK_IDS), "checks_executed": len(executed),
        "all_checks_executed": coverage, "missing_checks": missing_checks,
        "checks": checks.results, "error": error, "limitations": LIMITATIONS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a local JSON evidence report to this path")
    args = parser.parse_args(argv)
    report = run_validation()
    if args.output:
        try:
            # Do not silently overwrite one of the authoritative example inputs.
            require(args.output.resolve() not in {(EXAMPLES_DIR / name).resolve() for name in REQUIRED_FILES},
                    "Output path must not overwrite a bundled example input")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        except (OSError, AssertionError) as exc:
            print(f"FAILED: cannot write report: {exc}", file=sys.stderr)
            return 1
    count = sum(entry["status"] == "passed" for entry in report["checks"])
    print(f"{report['status'].upper()}: {count}/{report['checks_expected']} checks passed; "
          f"{report['checks_executed']} executed. Local synthetic SQLite evidence only.")
    if report["error"]:
        print(report["error"], file=sys.stderr)
    for check in report["checks"]:
        if check["status"] != "passed":
            print(f"  {check['id']}: {check['error']}", file=sys.stderr)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
