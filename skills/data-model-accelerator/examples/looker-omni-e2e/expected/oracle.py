"""Independent synthetic billing oracle: pure Python, no SQL or target artifacts.

recompute(raw_data) -> invoice dictionaries sorted by (tenant_id, invoice_id).
report(raw_data, tenant, currency, start_date, end_date, group_by=None,
       segment=None, zero_net_only=False) -> a deterministic list of dictionaries.
Report money is integer cents; payment_rate is Decimal or None in Python.
Decimal values are serialized as strings in expected_reports.json.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import re
from zoneinfo import ZoneInfo


CHICAGO = ZoneInfo("America/Chicago")
DECIMAL_PRECISION = 50
IDENTIFIER = re.compile(r"[A-Za-z0-9]+\Z")
INTEGER_TEXT = re.compile(r"[+-]?[0-9]+\Z")
DIMENSIONS = {"tenant_id", "invoice_id", "customer_id", "invoice_date", "currency", "status", "segment"}


class OracleContractError(ValueError):
    """The synthetic input violates or cannot safely satisfy the stated contract."""


def require(condition, message):
    if not condition:
        raise OracleContractError(message)


def identifier(value, label):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value), label + " must be a nonempty ASCII alphanumeric ID")
    return value


def cents(value, label, null_is_zero=False):
    if value is None and null_is_zero:
        return 0
    require(isinstance(value, str) and INTEGER_TEXT.fullmatch(value), label + " must contain integer cents encoded as text")
    return int(value)


def instant(value):
    require(isinstance(value, str) and bool(value), "Timestamp must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise OracleContractError("Invalid timestamp: " + value) from exc
    # The supplied exercise explicitly defines offset-free source timestamps as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def currency_code(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value), "Currency must be an explicit uppercase three-letter code")
    return value


def normalized_status(value):
    require(isinstance(value, str) and bool(value.strip()), "Status must be a nonempty string")
    return value.strip().lower()


def latest_versions(events, entity_field):
    """Validate every version before selection; arrival order is never precedence."""
    require(isinstance(events, list), "CDC source must be an array")
    seen_versions = {}
    latest = {}
    for event in events:
        require(isinstance(event, dict), "CDC event must be an object")
        tenant = identifier(event.get("tenant_id"), "tenant_id")
        entity = identifier(event.get(entity_field), entity_field)
        seq = event.get("source_seq")
        require(type(seq) is int, "source_seq must be an integer")
        require(event.get("op") in ("UPSERT", "DELETE"), "CDC op must be UPSERT or DELETE")
        payload = {key: value for key, value in event.items() if key != "arrival_seq"}
        version = (tenant, entity, seq)
        if version in seen_versions:
            require(seen_versions[version] == payload, "Conflicting CDC payload for version " + repr(version))
        else:
            seen_versions[version] = deepcopy(payload)
        key = (tenant, entity)
        if key not in latest or seq > latest[key]["source_seq"]:
            latest[key] = deepcopy(payload)
    return latest


def customer_intervals(rows):
    require(isinstance(rows, list), "customer_history must be an array")
    grouped = defaultdict(list)
    for row in rows:
        require(isinstance(row, dict), "Customer history row must be an object")
        key = (identifier(row.get("tenant_id"), "tenant_id"), identifier(row.get("customer_id"), "customer_id"))
        start = instant(row.get("valid_from"))
        end = None if row.get("valid_to") is None else instant(row["valid_to"])
        require(end is None or start < end, "Customer history interval must have positive duration")
        segment = row.get("segment")
        require(isinstance(segment, str) and bool(segment), "History segment must be a nonempty string")
        grouped[key].append((start, end, segment))
    for key, intervals in grouped.items():
        intervals.sort(key=lambda item: item[0])
        previous = None
        for interval in intervals:
            if previous is not None:
                require(previous[1] is not None and interval[0] >= previous[1], "Overlapping customer history for " + repr(key))
            previous = interval
    return grouped


def posted_ledger_totals(events, invoice_states, ledger_name):
    totals = defaultdict(int)
    states = latest_versions(events, "entry_id")
    for event in states.values():
        # Version selection precedes delete handling and posted-status filtering.
        if event["op"] == "DELETE" or normalized_status(event.get("status")) != "posted":
            continue
        tenant = identifier(event.get("tenant_id"), "tenant_id")
        invoice = identifier(event.get("invoice_id"), "invoice_id")
        currency = currency_code(event.get("currency"))
        state = invoice_states.get((tenant, invoice))
        require(state is not None, "Posted " + ledger_name + " references an unknown invoice; orphan treatment is not defined by the exercise")
        require(currency == currency_code(state.get("currency")), "Currency mismatch in posted " + ledger_name + " for " + repr((tenant, invoice)))
        totals[(tenant, invoice, currency)] += cents(event.get("amount_cents"), ledger_name + ".amount_cents")
    return totals


def recompute(data):
    """Return all current invoice rows, retaining draft/currency/date diversity."""
    require(isinstance(data, dict), "Raw data must be an object")
    for key in ("invoice_cdc", "payment_cdc", "credit_cdc", "customer_history"):
        require(key in data, "Missing raw source: " + key)
    invoices = latest_versions(data["invoice_cdc"], "invoice_id")
    histories = customer_intervals(data["customer_history"])
    # Deliberately independent summation passes: payments never multiply credits.
    payments = posted_ledger_totals(data["payment_cdc"], invoices, "payment")
    credits = posted_ledger_totals(data["credit_cdc"], invoices, "credit")
    result = []
    for (tenant, invoice_id), invoice in sorted(invoices.items()):
        if invoice["op"] == "DELETE":
            continue
        customer_id = identifier(invoice.get("customer_id"), "customer_id")
        issued_at = instant(invoice.get("issued_at"))
        currency = currency_code(invoice.get("currency"))
        gross = cents(invoice.get("gross_cents"), "gross_cents")
        discount = cents(invoice.get("discount_cents"), "discount_cents", null_is_zero=True)
        credit = credits[(tenant, invoice_id, currency)]
        segments = [segment for start, end, segment in histories.get((tenant, customer_id), [])
                    if start <= issued_at and (end is None or issued_at < end)]
        require(len(segments) <= 1, "More than one customer history matches invoice " + repr((tenant, invoice_id)))
        result.append({
            "tenant_id": tenant, "invoice_id": invoice_id, "customer_id": customer_id,
            "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
            "invoice_date": issued_at.astimezone(CHICAGO).date().isoformat(),
            "currency": currency, "status": normalized_status(invoice.get("status")),
            "segment": segments[0] if segments else "Unknown",
            "gross_cents": gross, "discount_cents": discount, "credit_cents": credit,
            "net_cents": gross - discount - credit,
            "paid_cents": payments[(tenant, invoice_id, currency)],
        })
    return result


def business_date(value):
    if type(value) is date:
        return value
    require(isinstance(value, str), "Report date must be an ISO date string or date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise OracleContractError("Invalid report date: " + value) from exc


def decimal_ratio(numerator, denominator):
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return Decimal(numerator) / Decimal(denominator)


def report(data, tenant, currency, start_date, end_date, group_by=None,
           segment=None, zero_net_only=False):
    """Return grouped posted-invoice metrics with all filters applied first.

    No grouping yields one total, including an empty total. Empty grouped queries
    yield no groups. Dates are inclusive start/exclusive end. A or B is required.
    """
    if tenant not in ("A", "B"):
        raise PermissionError("An explicit A or B tenant persona is required")
    currency = currency_code(currency)
    start, end = business_date(start_date), business_date(end_date)
    require(start <= end, "Report start date must not exceed end date")
    dimensions = [] if group_by is None else list(group_by)
    require(all(isinstance(name, str) and name in DIMENSIONS for name in dimensions), "Unsupported report grouping dimension")
    require(len(set(dimensions)) == len(dimensions), "Duplicate report grouping dimension")
    require(type(zero_net_only) is bool, "zero_net_only must be boolean")
    require(segment is None or isinstance(segment, str), "segment must be a string or None")
    selected = [row for row in recompute(data)
                if row["tenant_id"] == tenant and row["currency"] == currency
                and row["status"] == "posted"
                and start <= business_date(row["invoice_date"]) < end
                and (segment is None or row["segment"] == segment)
                and (not zero_net_only or row["net_cents"] == 0)]
    groups = defaultdict(list)
    if not dimensions:
        groups[()] = selected
    else:
        for row in selected:
            groups[tuple(row[name] for name in dimensions)].append(row)
    result = []
    for key, rows in sorted(groups.items()):
        net = sum(row["net_cents"] for row in rows)
        paid = sum(row["paid_cents"] for row in rows)
        result.append(dict(zip(dimensions, key), invoice_count=len(rows), net_cents=net,
                           paid_cents=paid, payment_rate=decimal_ratio(paid, net)))
    return result


SCENARIOS = [
    ("a_usd_september_total", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01"}),
    ("a_usd_september_by_segment", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01","group_by":["segment"]}),
    ("a_usd_september_daily", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01","group_by":["invoice_date"]}),
    ("a_usd_september_smb", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01","segment":"SMB"}),
    ("a_eur_september_total", {"tenant":"A","currency":"EUR","start_date":"2026-09-01","end_date":"2026-10-01"}),
    ("b_usd_september_total", {"tenant":"B","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01"}),
    ("a_usd_august_total", {"tenant":"A","currency":"USD","start_date":"2026-08-01","end_date":"2026-09-01"}),
    ("a_usd_september_zero_net", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-10-01","zero_net_only":True}),
    ("a_usd_empty_interval", {"tenant":"A","currency":"USD","start_date":"2026-09-01","end_date":"2026-09-01"}),
]


def baseline_arithmetic_checks(data, rows, reports):
    """Independently hand-reconciled cents/dates/segments; no target output reuse."""
    # Each tuple: gross, discount, posted credit, net, posted payment, date, segment, status.
    expected = {
        ("A","I1"):(10000,500,1500,8000,6000,"2026-09-03","SMB","posted"),
        ("A","I2"):(20000,0,2000,18000,9000,"2026-09-20","Enterprise","posted"),
        ("A","I3"):(10000,0,0,10000,1000,"2026-09-05","MidMarket","draft"),
        ("A","I5"):(8000,0,0,8000,8000,"2026-08-31","MidMarket","posted"),
        ("A","I6"):(6000,0,0,6000,6000,"2026-08-31","MidMarket","posted"),
        ("A","I7"):(7000,0,0,7000,7000,"2026-09-30","MidMarket","posted"),
        ("A","I8"):(0,0,0,0,0,"2026-09-13","MidMarket","posted"),
        ("A","I9"):(9000,0,0,9000,4500,"2026-09-14","MidMarket","posted"),
        ("A","I10"):(3000,0,0,3000,1000,"2026-09-16","Unknown","posted"),
        ("A","I11"):(4000,100,0,3900,0,"2026-09-22","MidMarket","posted"),
        ("B","I1"):(99900,0,900,99000,70000,"2026-09-09","Government","posted"),
        ("B","I2"):(10000,1000,0,9000,1000,"2026-09-21","Government","posted"),
    }
    fields = ("gross_cents","discount_cents","credit_cents","net_cents","paid_cents","invoice_date","segment","status")
    observed = {(row["tenant_id"],row["invoice_id"]):tuple(row[field] for field in fields) for row in rows}
    require(observed == expected, "Oracle differs from hand-reconciled invoice arithmetic")
    # Manually summed report controls, independently checked with exact fractions.
    totals = {
        "a_usd_september_total":(6,39900,23000), "a_usd_september_smb":(1,8000,6000),
        "a_eur_september_total":(1,9000,4500), "b_usd_september_total":(2,108000,71000),
        "a_usd_august_total":(2,14000,14000), "a_usd_september_zero_net":(1,0,0),
        "a_usd_empty_interval":(0,0,0),
    }
    by_id = {item["scenario_id"]:item["rows"] for item in reports}
    for name, (count, net, paid) in totals.items():
        row = by_id[name][0]
        require((row["invoice_count"],row["net_cents"],row["paid_cents"]) == (count,net,paid), "Manual report-total mismatch: " + name)
        fraction = None if net == 0 else Fraction(paid,net)
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            expected_ratio = None if fraction is None else Decimal(fraction.numerator) / Decimal(fraction.denominator)
        require(row["payment_rate"] == expected_ratio, "Exact-fraction rate mismatch: " + name)
    segments = [(r["segment"],r["invoice_count"],r["net_cents"],r["paid_cents"]) for r in by_id["a_usd_september_by_segment"]]
    require(segments == [("Enterprise",1,18000,9000),("MidMarket",3,10900,7000),("SMB",1,8000,6000),("Unknown",1,3000,1000)], "Manual segment control mismatch")
    daily = [(r["invoice_date"],r["invoice_count"],r["net_cents"],r["paid_cents"]) for r in by_id["a_usd_september_daily"]]
    require(daily == [("2026-09-03",1,8000,6000),("2026-09-13",1,0,0),("2026-09-16",1,3000,1000),("2026-09-20",1,18000,9000),("2026-09-22",1,3900,0),("2026-09-30",1,7000,7000)], "Manual daily control mismatch")
    for grouped in (by_id["a_usd_september_by_segment"], by_id["a_usd_september_daily"]):
        require(tuple(sum(r[field] for r in grouped) for field in ("invoice_count","net_cents","paid_cents")) == (6,39900,23000), "Grouped additive measures do not reconcile to manual total")
    return "12 invoice arithmetic controls, nine report scenarios, and exact-fraction total-rate controls passed."


def invariant_checks(data, original_rows):
    replayed = deepcopy(data)
    for source in ("invoice_cdc","payment_cdc","credit_cdc"):
        copies = deepcopy(replayed[source])
        for index, row in enumerate(copies):
            row["arrival_seq"] = 10000 + index
        replayed[source].extend(copies)
    require(recompute(replayed) == original_rows, "Replay changed oracle rows")
    shuffled = deepcopy(data)
    randomizer = random.Random(83417)
    for source in ("invoice_cdc","payment_cdc","credit_cdc"):
        randomizer.shuffle(shuffled[source])
        for index, row in enumerate(shuffled[source]):
            row["arrival_seq"] = index
    randomizer.shuffle(shuffled["customer_history"])
    require(recompute(shuffled) == original_rows, "Arrival permutation changed oracle rows")
    invalid_cases = []
    conflicting = deepcopy(data)
    bad_version = deepcopy(conflicting["invoice_cdc"][0]); bad_version["gross_cents"] = "12345"
    conflicting["invoice_cdc"].append(bad_version); invalid_cases.append((conflicting,"Conflicting CDC"))
    mismatch = deepcopy(data)
    next(row for row in mismatch["payment_cdc"] if row["tenant_id"]=="A" and row["entry_id"]=="P2")["currency"] = "EUR"
    invalid_cases.append((mismatch,"Currency mismatch"))
    overlap = deepcopy(data); overlap["customer_history"].append(deepcopy(overlap["customer_history"][0]))
    invalid_cases.append((overlap,"Overlapping customer history"))
    for invalid, fragment in invalid_cases:
        try:
            recompute(invalid)
        except OracleContractError as exc:
            require(fragment in str(exc), "Negative control failed for an unrelated reason")
        else:
            raise AssertionError("Invalid source was not rejected: " + fragment)
    for tenant in (None,"C",""):
        try:
            report(data,tenant,"USD","2026-09-01","2026-10-01")
        except PermissionError:
            pass
        else:
            raise AssertionError("Missing or unknown tenant persona was not denied")
    return "Replay, changed arrival order, source-conflict/currency/history negatives, and three denied personas passed."


def main():
    expected_dir = Path(__file__).resolve().parent
    input_dir = expected_dir.parent / "input"
    source_bytes = (input_dir / "raw-data.json").read_bytes()
    scenario_bytes = (input_dir / "scenario.md").read_bytes()
    data = json.loads(source_bytes)
    rows = recompute(data)
    reports = [{"scenario_id":name,"parameters":parameters,"rows":report(data,**parameters)} for name,parameters in SCENARIOS]
    arithmetic = baseline_arithmetic_checks(data,rows,reports)
    invariants = invariant_checks(data,rows)
    (expected_dir / "expected_rows.json").write_text(json.dumps(rows,indent=2)+"\n")
    (expected_dir / "expected_reports.json").write_text(json.dumps({"schema_version":1,"origin":"synthetic_independent_oracle","scenarios":reports},indent=2,default=str)+"\n")
    notes = f"""# Independent billing oracle

Only `input/raw-data.json` and `input/scenario.md` supplied the business evidence.
No legacy LookML, generated SQL, semantic YAML, migration runner, or target result
was inspected. This is independently specified synthetic expected data, not
business approval or live warehouse/security evidence.

- Raw-data SHA-256: `{hashlib.sha256(source_bytes).hexdigest()}`
- Scenario SHA-256: `{hashlib.sha256(scenario_bytes).hexdigest()}`
- {arithmetic}
- {invariants}

## API and output

`recompute(data)` accepts the raw JSON dictionary and returns all 12 current
invoice dictionaries, including the draft, EUR invoice and August dates. It
does not create or assume a target surrogate key. Rows sort lexically by
`(tenant_id, invoice_id)`; identifiers and currency case are preserved. Status is
trimmed/lowercased. `issued_at` is canonical UTC ISO8601 ending in Z;
`invoice_date` is its America/Chicago calendar date.

`report(data, tenant, currency, start_date, end_date, group_by=None, segment=None,
zero_net_only=False)` returns a list of dictionaries. Each has grouping fields,
`invoice_count`, `net_cents`, `paid_cents` and `payment_rate`. Date bounds are
inclusive start/exclusive end. `group_by` accepts a list of invoice identity,
customer, date, tenant, currency, status or segment field names. Results sort
lexically by the requested grouping tuple. A total has one row even when empty;
an empty grouped query has no groups. Missing/unknown tenant persona raises
PermissionError; only A and B are admitted in this local simulator.

Amounts/counts compare exactly as integers. Rates are Decimal at {DECIMAL_PRECISION}
significant digits, exported as strings to avoid binary-float loss; null rates
remain JSON null. Exact Fraction controls independently verify report arithmetic.
When comparing a target floating ratio, use absolute tolerance no larger than
`1e-12`; never apply that tolerance to cents/counts/identity. Money display is
`Decimal(cents) / Decimal(100)` and is separate from all aggregation.

`expected_rows.json` is the complete invoice list. `expected_reports.json` contains
`scenarios`, each with its scenario_id, explicit parameters and expected rows.
The callable recompute/report functions also support independently recomputing
mutated raw input; baseline fixture constants are checked only by main().

## Explicit contract decisions and limits

The unspecified empty-date scenario uses the literal empty half-open interval
`[2026-09-01, 2026-09-01)`. Segment and daily breakdowns are two report scenarios.
No ambiguity affects the supplied numeric results.

Every CDC version is checked for conflicting payloads before latest-version
selection; only arrival_seq is excluded from that payload. DELETE is processed
after version selection. Payments and credits are independently aggregated from
their current posted entries. Currency is validated for those contributing
entries against the latest invoice state, including a retained invoice tombstone.
No posted orphan ledger exists in the supplied data; if a mutation introduces an
unknown invoice reference, the oracle raises an explicit contract error because
orphan treatment is unspecified. It does not invent conversion or allocation.

Customer history is tenant-scoped, start-inclusive/end-exclusive and evaluated
at the UTC issued_at instant; missing history yields Unknown. The oracle rejects
overlapping intervals for a tenant/customer, including duplicate intervals.
Discount null becomes zero; amounts are not clamped. Invoice source sequence,
currency, report date, status and persona are kept as separate concerns.

Local persona rejection is only a functional simulator check. It does not
establish warehouse row-access policy, Omni access enforcement, or production
readiness. No source SQL, macros, external systems or deployment were executed.
"""
    (expected_dir / "oracle-notes.md").write_text(notes)
    print(json.dumps({"gold_rows":len(rows),"report_scenarios":len(reports),"report_result_rows":sum(len(s["rows"]) for s in reports),"arithmetic_checks":arithmetic,"invariant_checks":invariants},indent=2))


if __name__ == "__main__":
    main()
