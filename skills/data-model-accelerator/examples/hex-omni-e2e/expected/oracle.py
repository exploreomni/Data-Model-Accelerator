#!/usr/bin/env python3
"""Independent, stdlib-only business oracle for the synthetic Hex exercise.

Derived only from input/scenario.md, input/raw-data.json and the supplied
adjustments.csv. No SQL, notebook, parser, target, or migration runner is read.
Running this file verifies manual controls and writes the frozen expected JSON.
"""
from collections import defaultdict
from copy import deepcopy
import csv
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re


RATIO_TOLERANCE = Decimal("0.000000000001")
INPUT_PATHS = ("input/scenario.md", "input/raw-data.json", "input/repo/adjustments.csv")
DEFAULTS = {"tenant": "A", "start_date": "2026-01-01", "end_date": "2026-03-01",
            "segment": "ALL", "authorized": True}


class OracleContractError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code, message):
    if not condition:
        raise OracleContractError(code, message)


def identifier(value):
    require(isinstance(value, str) and bool(value.strip()) and "|" not in value,
            "invalid_key", "Keys must be nonempty strings without the fixture key delimiter")
    return value


def day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
            "invalid_date", "Expected a YYYY-MM-DD calendar date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise OracleContractError("invalid_date", "Invalid calendar date") from error


def cents(value, *, csv_value=False):
    if csv_value and isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    require(type(value) is int, "invalid_amount", "Amounts must be exact integer cents")
    return value


def ratio(numerator, denominator):
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return Decimal(numerator) / Decimal(denominator)


def read_adjustments(value):
    """Accept CSV text or a list of uppercase-column dictionaries; never a path."""
    required = {"TENANT_ID", "INVOICE_ID", "ADJUSTMENT_CENTS", "REASON"}
    if isinstance(value, str):
        reader = csv.DictReader(io.StringIO(value))
        require(reader.fieldnames is not None and len(reader.fieldnames) == len(required)
                and set(reader.fieldnames) == required,
                "missing_adjustments", "Adjustment CSV must include the declared header")
        value = list(reader)
    require(isinstance(value, list), "missing_adjustments", "Adjustment source content is required")
    result = {}
    for row in value:
        require(isinstance(row, dict) and set(row) == required,
                "invalid_adjustments", "Adjustment rows must contain the four declared fields")
        key = (identifier(row["TENANT_ID"]), identifier(row["INVOICE_ID"]))
        require(key not in result, "duplicate_adjustment", "Adjustment tenant/invoice key is duplicated")
        require(isinstance(row["REASON"], str) and bool(row["REASON"].strip()),
                "invalid_adjustments", "Manual adjustment reason is required")
        result[key] = cents(row["ADJUSTMENT_CENTS"], csv_value=True)
    return result


def current(rows, kind):
    key_name = "INVOICE_ID" if kind == "invoice" else "PAYMENT_ID"
    required = {"TENANT_ID", key_name, "INVOICE_ID", "IS_DELETED", "SEQUENCE"}
    required |= {"CUSTOMER_ID", "INVOICE_DATE", "AMOUNT_CENTS", "STATUS"} if kind == "invoice" else {"PAID_CENTS"}
    require(isinstance(rows, list), "missing_source", "Required CDC stream is missing")
    versions, latest = {}, {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == required,
                "invalid_source_shape", "CDC row fields differ from the supplied source contract")
        key = (identifier(row["TENANT_ID"]), identifier(row[key_name]))
        identifier(row["INVOICE_ID"])
        require(type(row["SEQUENCE"]) is int and row["SEQUENCE"] > 0,
                "invalid_sequence", "Source sequence must be a positive integer")
        require(type(row["IS_DELETED"]) is bool, "invalid_tombstone", "IS_DELETED must be boolean")
        if kind == "invoice":
            identifier(row["CUSTOMER_ID"])
            day(row["INVOICE_DATE"])
            cents(row["AMOUNT_CENTS"])
            require(isinstance(row["STATUS"], str) and bool(row["STATUS"]),
                    "invalid_status", "Invoice status must be nonempty; no normalization is specified")
        else:
            cents(row["PAID_CENTS"])
        version = (*key, row["SEQUENCE"])
        require(version not in versions or versions[version] == row,
                "cdc_conflict", "Different full after-images share the same source version")
        versions[version] = dict(row)
        if key not in latest or row["SEQUENCE"] > latest[key]["SEQUENCE"]:
            latest[key] = dict(row)
    return {key: row for key, row in latest.items() if not row["IS_DELETED"]}


def history_index(rows):
    required = {"TENANT_ID", "CUSTOMER_ID", "SEGMENT", "VALID_FROM", "VALID_TO"}
    require(isinstance(rows, list), "missing_source", "Customer history source is missing")
    seen, grouped = set(), defaultdict(list)
    for row in rows:
        require(isinstance(row, dict) and set(row) == required,
                "invalid_source_shape", "History row fields differ from the supplied source contract")
        key = (identifier(row["TENANT_ID"]), identifier(row["CUSTOMER_ID"]))
        require(isinstance(row["SEGMENT"], str) and bool(row["SEGMENT"].strip()),
                "invalid_segment", "History segment must be nonempty")
        start, end = day(row["VALID_FROM"]), day(row["VALID_TO"]) if row["VALID_TO"] is not None else None
        require(end is None or start < end, "invalid_history", "History interval must have positive length")
        fingerprint = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        grouped[key].append((start, end, dict(row)))
    for intervals in grouped.values():
        intervals.sort(key=lambda item: item[0])
        for previous, following in zip(intervals, intervals[1:]):
            require(previous[1] is not None and previous[1] <= following[0],
                    "history_overlap", "Customer history intervals overlap")
    return grouped


def parameters(params):
    require(params is None or isinstance(params, dict), "invalid_parameters", "Parameters must be a mapping")
    params = {} if params is None else dict(params)
    require(set(params) <= set(DEFAULTS) | {"what_if_multiplier"},
            "unknown_parameter", "Unknown report parameter")
    result = dict(DEFAULTS, **params)
    require(type(result["authorized"]) is bool and result["authorized"],
            "unauthorized_persona", "The supplied local persona is not authorized")
    require(type(result["tenant"]) is str and result["tenant"] in ("A", "B"),
            "unknown_tenant", "Only tenant A or B is allowed by the synthetic report contract")
    start, end = day(result["start_date"]), day(result["end_date"])
    require(start <= end, "reversed_window", "Report date window is reversed")
    require(isinstance(result["segment"], str) and bool(result["segment"].strip()),
            "invalid_segment", "Segment must be an exact name or ALL")
    if "what_if_multiplier" in result:
        try:
            multiplier = Decimal(str(result["what_if_multiplier"]))
            require(multiplier.is_finite(), "invalid_multiplier", "What-if multiplier must be finite")
        except ArithmeticError as error:
            raise OracleContractError("invalid_multiplier", "What-if multiplier must be numeric") from error
        # Deliberately excluded from all shared-model/report computations.
    return result


def calculate(raw, adjustments, params=None):
    """Return full gold rows plus filtered Revenue/Retention/Executive report lists.

    `adjustments`: CSV text or list of uppercase-field records, never a file path.
    `params`: tenant/start_date/end_date/segment/authorized plus an optional
    what_if_multiplier that cannot affect shared outputs. Ratios are Decimal;
    money/counts are exact integers, activity flags booleans, dates ISO strings.
    """
    p = parameters(params)
    require(isinstance(raw, dict) and raw.get("origin") == "synthetic",
            "invalid_origin", "This oracle accepts the declared synthetic fixture only")
    invoices = current(raw.get("INVOICE_CDC"), "invoice")
    payments = current(raw.get("PAYMENT_CDC"), "payment")
    histories = history_index(raw.get("CUSTOMER_HISTORY"))
    corrections = read_adjustments(adjustments)
    require(set(corrections) <= set(invoices), "orphan_adjustment", "Adjustment references no retained current invoice")
    paid = defaultdict(int)
    for row in payments.values():
        key = (row["TENANT_ID"], row["INVOICE_ID"])
        require(key in invoices, "orphan_payment", "Payment references no retained current invoice")
        paid[key] += row["PAID_CENTS"]

    facts = []
    for key, row in sorted(invoices.items()):
        issued = day(row["INVOICE_DATE"])
        matches = [h for start, end, h in histories.get((row["TENANT_ID"], row["CUSTOMER_ID"]), [])
                   if start <= issued and (end is None or issued < end)]
        require(len(matches) == 1, "orphan_history", "Invoice must match exactly one historical customer")
        historical = matches[0]
        adjustment = corrections.get(key, 0)
        net = row["AMOUNT_CENTS"] + adjustment
        facts.append({"tenant_id": key[0], "invoice_id": key[1], "customer_id": row["CUSTOMER_ID"],
            "customer_key": "|".join((key[0], row["CUSTOMER_ID"], historical["VALID_FROM"])),
            "invoice_date": row["INVOICE_DATE"], "month": issued.replace(day=1).isoformat(),
            "segment": historical["SEGMENT"], "status": row["STATUS"], "amount_cents": row["AMOUNT_CENTS"],
            "adjustment_cents": adjustment, "net_cents": net, "paid_cents": paid[key],
            "outstanding_cents": net - paid[key]})

    first_paid = {}
    for row in facts:
        if row["status"] == "posted" and row["paid_cents"] > 0:
            key = (row["tenant_id"], row["customer_id"])
            first_paid[key] = min(row["month"], first_paid.get(key, row["month"]))
    months = {}
    for row in facts:
        key = (row["tenant_id"], row["customer_id"], row["month"])
        entry = months.setdefault(key, {"tenant_id": key[0], "customer_id": key[1], "month": key[2],
            "net_cents": 0, "paid_cents": 0, "has_invoice": False, "has_paid_invoice": False,
            "first_paid_month": first_paid.get(key[:2])})
        entry["net_cents"] += row["net_cents"]
        entry["paid_cents"] += row["paid_cents"]
        entry["has_invoice"] |= row["status"] == "posted" and row["net_cents"] > 0
        entry["has_paid_invoice"] |= row["status"] == "posted" and row["paid_cents"] > 0

    selected = [row for row in facts if row["tenant_id"] == p["tenant"] and row["status"] == "posted"
                and p["start_date"] <= row["invoice_date"] < p["end_date"]
                and (p["segment"] == "ALL" or row["segment"] == p["segment"])]
    grouped = defaultdict(list)
    retention = {}
    for row in selected:
        grouped[(row["month"], row["segment"])].append(row)
        if row["net_cents"] > 0:
            key = (row["tenant_id"], row["customer_id"], row["month"], row["segment"])
            retention[key] = {"tenant_id": key[0], "customer_id": key[1], "month": key[2], "segment": key[3],
                              "first_paid_month": first_paid.get(key[:2])}
    revenue, executive = [], []
    for (month, segment), rows in sorted(grouped.items()):
        net, amount_paid = sum(r["net_cents"] for r in rows), sum(r["paid_cents"] for r in rows)
        revenue.append({"month": month, "segment": segment, "invoice_count": len(rows),
            "net_cents": net, "paid_cents": amount_paid, "outstanding_cents": net - amount_paid,
            "payment_rate": ratio(amount_paid, net)})
        executive.append({"month": month, "segment": segment, "net_cents": net, "paid_cents": amount_paid,
            "payment_rate": ratio(amount_paid, net),
            "invoiced_active_customers": len({r["customer_id"] for r in rows if r["net_cents"] > 0}),
            "paying_active_customers": len({r["customer_id"] for r in rows if r["paid_cents"] > 0})})
    return {"invoices": facts, "customer_months": [months[k] for k in sorted(months)],
            "revenue": revenue, "retention": [retention[k] for k in sorted(retention)], "executive": executive}


SCENARIOS = [
    ("default_a", {}), ("tenant_b", {"tenant": "B"}),
    ("january_a", {"end_date": "2026-02-01"}),
    ("february_a", {"start_date": "2026-02-01"}),
    ("february_boundary_a", {"start_date": "2026-02-01", "end_date": "2026-02-02"}),
    ("segment_smb_a", {"segment": "SMB"}), ("segment_enterprise_a", {"segment": "Enterprise"}),
    ("segment_smb_b", {"tenant": "B", "segment": "SMB"}),
    ("segment_enterprise_b", {"tenant": "B", "segment": "Enterprise"}),
    ("empty_equal_bounds", {"end_date": "2026-01-01"}),
    ("empty_after_snapshot", {"start_date": "2026-04-01", "end_date": "2026-05-01"}),
    ("zero_revenue_a", {"start_date": "2026-02-20", "end_date": "2026-02-21"}),
    ("retained_what_if_double", {"what_if_multiplier": "2"}),
]
ERROR_SCENARIOS = [
    ("unknown_tenant", {"tenant": "C"}, "unknown_tenant"),
    ("null_tenant", {"tenant": None}, "unknown_tenant"),
    ("unauthorized_persona", {"authorized": False}, "unauthorized_persona"),
    ("reversed_window", {"start_date": "2026-03-01", "end_date": "2026-01-01"}, "reversed_window"),
    ("invalid_calendar_date", {"start_date": "2026-02-30"}, "invalid_date"),
]


def self_check(raw, adjustments):
    result = calculate(raw, adjustments)
    # Manually reconciled controls: amount, adjustment, net, paid, outstanding,
    # historical segment and month. These are not copied from any candidate.
    manual = {
        ("A", "I1"): (12000, -1000, 11000, 10000, 1000, "SMB", "2026-01-01"),
        ("A", "I2"): (8000, 1000, 9000, 4000, 5000, "SMB", "2026-01-01"),
        ("A", "I3"): (5000, 0, 5000, 0, 5000, "Enterprise", "2026-01-01"),
        ("A", "I4"): (7000, 0, 7000, 7000, 0, "Enterprise", "2026-02-01"),
        ("A", "I5"): (9000, -2000, 7000, 1000, 6000, "SMB", "2026-02-01"),
        ("A", "I6"): (6000, 0, 6000, 0, 6000, "Enterprise", "2026-02-01"),
        ("A", "I7"): (0, 0, 0, 0, 0, "SMB", "2026-02-01"),
        ("A", "I9"): (11000, 0, 11000, 0, 11000, "SMB", "2026-03-01"),
        ("B", "I1"): (30000, 500, 30500, 30000, 500, "Enterprise", "2026-01-01"),
        ("B", "I2"): (20000, 0, 20000, 5000, 15000, "SMB", "2026-02-01"),
    }
    fields = ("amount_cents", "adjustment_cents", "net_cents", "paid_cents", "outstanding_cents", "segment", "month")
    assert {(r["tenant_id"], r["invoice_id"]): tuple(r[f] for f in fields) for r in result["invoices"]} == manual
    assert len(result["customer_months"]) == 10
    by_month = {(r["tenant_id"], r["customer_id"], r["month"]): r for r in result["customer_months"]}
    manual_months = {
        ("A", "C1", "2026-01-01"): (11000, 10000, True, True, "2026-01-01"),
        ("A", "C1", "2026-02-01"): (7000, 7000, True, True, "2026-01-01"),
        ("A", "C2", "2026-01-01"): (9000, 4000, True, True, "2026-01-01"),
        ("A", "C2", "2026-02-01"): (7000, 1000, True, True, "2026-01-01"),
        ("A", "C2", "2026-03-01"): (11000, 0, True, False, "2026-01-01"),
        ("A", "C3", "2026-01-01"): (5000, 0, True, False, None),
        ("A", "C3", "2026-02-01"): (6000, 0, False, False, None),
        ("A", "C4", "2026-02-01"): (0, 0, False, False, None),
        ("B", "C1", "2026-01-01"): (30500, 30000, True, True, "2026-01-01"),
        ("B", "C2", "2026-02-01"): (20000, 5000, True, True, "2026-02-01"),
    }
    month_fields = ("net_cents", "paid_cents", "has_invoice", "has_paid_invoice", "first_paid_month")
    assert {key: tuple(row[f] for f in month_fields) for key, row in by_month.items()} == manual_months
    invoice_keys = {(r["tenant_id"], r["invoice_id"]): r["customer_key"] for r in result["invoices"]}
    assert invoice_keys[("A", "I1")] == "A|C1|2025-01-01"
    assert invoice_keys[("A", "I4")] == "A|C1|2026-02-01"
    assert invoice_keys[("B", "I1")] == "B|C1|2025-01-01"
    draft = by_month[("A", "C3", "2026-02-01")]
    assert (draft["net_cents"], draft["has_invoice"], draft["has_paid_invoice"], draft["first_paid_month"]) == (6000, False, False, None)
    assert by_month[("A", "C2", "2026-03-01")]["first_paid_month"] == "2026-01-01"
    manual_groups = {("2026-01-01", "Enterprise"): (1, 5000, 0, 1, 0),
                     ("2026-01-01", "SMB"): (2, 20000, 14000, 2, 2),
                     ("2026-02-01", "Enterprise"): (1, 7000, 7000, 1, 1),
                     ("2026-02-01", "SMB"): (2, 7000, 1000, 1, 1)}
    for revenue, executive in zip(result["revenue"], result["executive"]):
        count, net, paid, invoiced, paying = manual_groups[(revenue["month"], revenue["segment"])]
        assert (revenue["invoice_count"], revenue["net_cents"], revenue["paid_cents"], executive["invoiced_active_customers"], executive["paying_active_customers"]) == (count, net, paid, invoiced, paying)
        assert abs(Fraction(revenue["payment_rate"]) - Fraction(paid, net)) < Fraction(1, 10**45)
    assert (sum(r["net_cents"] for r in result["revenue"]), sum(r["paid_cents"] for r in result["revenue"])) == (39000, 22000)
    assert len(result["retention"]) == 5
    b = calculate(raw, adjustments, {"tenant": "B"})
    assert (sum(r["net_cents"] for r in b["revenue"]), sum(r["paid_cents"] for r in b["revenue"])) == (50500, 35000)
    assert calculate(raw, adjustments, {"what_if_multiplier": "2"}) == result
    replayed = deepcopy(raw)
    for stream in ("INVOICE_CDC", "PAYMENT_CDC", "CUSTOMER_HISTORY"):
        replayed[stream] = list(reversed(raw[stream] + deepcopy(raw[stream])))
    assert calculate(replayed, adjustments) == result
    for _, params, code in ERROR_SCENARIOS:
        try:
            calculate(raw, adjustments, params)
        except OracleContractError as error:
            assert error.code == code
        else:
            raise AssertionError("Invalid context was accepted")
    mutations = []
    bad = deepcopy(raw); bad["INVOICE_CDC"].append(dict(bad["INVOICE_CDC"][0], AMOUNT_CENTS=1)); mutations.append((bad, adjustments, "cdc_conflict"))
    bad = deepcopy(raw); bad["CUSTOMER_HISTORY"].append(dict(bad["CUSTOMER_HISTORY"][0], SEGMENT="Different")); mutations.append((bad, adjustments, "history_overlap"))
    bad = deepcopy(raw); bad["INVOICE_CDC"][0]["TENANT_ID"] = None; mutations.append((bad, adjustments, "invalid_key"))
    csv_rows = list(csv.DictReader(io.StringIO(adjustments)))
    mutations += [(raw, csv_rows + [dict(csv_rows[0])], "duplicate_adjustment"), (raw, None, "missing_adjustments"),
                  (raw, csv_rows + [{"TENANT_ID": "A", "INVOICE_ID": "Missing", "ADJUSTMENT_CENTS": "1", "REASON": "probe"}], "orphan_adjustment")]
    for bad_raw, bad_adjustments, code in mutations:
        try:
            calculate(bad_raw, bad_adjustments)
        except OracleContractError as error:
            assert error.code == code
        else:
            raise AssertionError("Invalid source was accepted")
    overpaid = deepcopy(raw)
    overpaid["PAYMENT_CDC"].append(dict(overpaid["PAYMENT_CDC"][0], PAYMENT_ID="Overpay", PAID_CENTS=2000))
    assert next(r for r in calculate(overpaid, adjustments)["invoices"] if (r["tenant_id"], r["invoice_id"]) == ("A", "I1"))["outstanding_cents"] == -1000
    changed = deepcopy(csv_rows)
    changed[0]["ADJUSTMENT_CENTS"] = "-900"  # +100 SMB
    changed.append({"TENANT_ID": "A", "INVOICE_ID": "I3", "ADJUSTMENT_CENTS": "-100", "REASON": "cancelling_error"})
    changed_reports = calculate(raw, changed)["revenue"]
    assert sum(r["net_cents"] for r in changed_reports) == 39000 and changed_reports != result["revenue"]
    return result


def main():
    case = Path(__file__).resolve().parent.parent
    hashes = {p: hashlib.sha256((case / p).read_bytes()).hexdigest() for p in INPUT_PATHS}
    raw = json.loads((case / "input/raw-data.json").read_text())
    adjustments = (case / "input/repo/adjustments.csv").read_text()
    result = self_check(raw, adjustments)
    rows = {"schema_version": 1, "origin": "synthetic_independent_oracle", "input_sha256": hashes,
            "invoices": result["invoices"], "customer_months": result["customer_months"]}
    reports = {"schema_version": 1, "origin": "synthetic_independent_oracle", "input_sha256": hashes,
        "ratio_absolute_tolerance": str(RATIO_TOLERANCE), "scenarios": [], "error_scenarios": []}
    for scenario_id, params in SCENARIOS:
        output = calculate(raw, adjustments, params)
        reports["scenarios"].append({"scenario_id": scenario_id, "parameters": params,
            "outputs": {k: output[k] for k in ("revenue", "retention", "executive")}})
    for scenario_id, params, code in ERROR_SCENARIOS:
        reports["error_scenarios"].append({"scenario_id": scenario_id, "parameters": params,
                                           "expected_error_code": code})
    for name, value in (("expected_rows.json", rows), ("expected_reports.json", reports)):
        (case / "expected" / name).write_text(json.dumps(value, indent=2, default=str) + "\n")
    print(json.dumps({"invoice_rows": len(result["invoices"]), "customer_month_rows": len(result["customer_months"]),
        "report_scenarios": len(SCENARIOS), "error_scenarios": len(ERROR_SCENARIOS),
        "report_rows": sum(len(v) for s in reports["scenarios"] for v in s["outputs"].values()),
        "manual_controls_and_mutation_checks": "passed", "input_sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
