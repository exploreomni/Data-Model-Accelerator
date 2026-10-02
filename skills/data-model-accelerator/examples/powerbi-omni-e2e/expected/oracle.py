"""Independent Power BI business-logic oracle; no SQL, DAX or candidate imports.

Authored using only this case's scenario, raw JSON and adjustments CSV. Monetary
facts use exact integers; report ratios use Decimal; None represents DAX BLANK.
"""
import argparse
import csv
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import io
import json
from pathlib import Path


class OracleContractError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ': ' + message)


def reject(code, message):
    raise OracleContractError(code, message)


DEFAULTS = {'tenant': 'A', 'start_date': '2026-01-01', 'end_date': '2026-03-01',
            'segment': 'ALL', 'status': 'posted', 'multipliers': [1]}
SCHEMA = {
    'INVOICE_CDC': {'TENANT_ID', 'INVOICE_ID', 'CUSTOMER_ID', 'INVOICE_DATE', 'AMOUNT_CENTS', 'STATUS', 'IS_DELETED', 'SEQUENCE'},
    'PAYMENT_CDC': {'TENANT_ID', 'PAYMENT_ID', 'INVOICE_ID', 'PAID_CENTS', 'IS_DELETED', 'SEQUENCE'},
    'CUSTOMER_HISTORY': {'TENANT_ID', 'CUSTOMER_ID', 'SEGMENT', 'VALID_FROM', 'VALID_TO'},
    'ADJUSTMENTS': {'TENANT_ID', 'INVOICE_ID', 'ADJUSTMENT_CENTS', 'REASON'},
}


def calendar_date(value):
    if type(value) is not str:
        reject('invalid_date', 'Canonical YYYY-MM-DD text is required')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        reject('invalid_date', 'Invalid calendar date')
    if parsed.isoformat() != value:
        reject('invalid_date', 'Canonical YYYY-MM-DD text is required')
    return parsed


def parameters(overrides=None):
    if overrides is not None and not isinstance(overrides, dict):
        reject('invalid_parameters', 'Expected a parameter mapping')
    provided = {} if overrides is None else overrides
    if set(provided) - set(DEFAULTS) - {'role', 'persona_tenant', 'authorized'}:
        reject('invalid_parameters', 'Unknown parameter')
    p = dict(DEFAULTS)
    p.update(provided)
    if p['tenant'] not in ('A', 'B'):
        reject('unknown_tenant', 'A known synthetic tenant is required')
    if p.get('authorized', True) is not True:
        reject('unauthorized', 'Synthetic authorization is denied')
    selected_role = p.get('role', 'Tenant' + p['tenant'])
    if selected_role not in ('TenantA', 'TenantB'):
        reject('unknown_role', 'A known synthetic role is required')
    if selected_role != 'Tenant' + p['tenant']:
        reject('role_mismatch', 'Role and requested tenant differ')
    if p.get('persona_tenant', p['tenant']) != p['tenant']:
        reject('persona_mismatch', 'Supplied persona and requested tenant differ')
    if calendar_date(p['start_date']) > calendar_date(p['end_date']):
        reject('reversed_dates', 'Start must not exceed the exclusive end')
    if type(p['segment']) is not str:
        reject('invalid_segment', 'Segment must be a string')
    if p['status'] not in ('posted', 'draft'):
        reject('unknown_status', 'Only posted and draft report statuses are supported')
    values = p['multipliers']
    if not isinstance(values, list) or any(type(value) is not int or value not in (1, 2) for value in values):
        reject('invalid_multipliers', 'Multiplier selections must be a list of integers from 1 and 2')
    if len(values) != len(set(values)):
        reject('invalid_multipliers', 'Multiplier selections must be unique')
    p['role'] = selected_role
    p['persona_tenant'] = p.get('persona_tenant', p['tenant'])
    p['multipliers'] = list(values)
    return p


def validate_record(table, row):
    if not isinstance(row, dict) or set(row) != SCHEMA[table]:
        reject('source_schema', 'Source row differs from the exact declared columns')
    for name, value in row.items():
        if name.endswith('_ID'):
            if type(value) is not str or not value or '|' in value:
                reject('invalid_identity', 'Fixture identities must be nonempty strings without pipes')
        elif name.endswith('_CENTS') or name == 'SEQUENCE':
            if type(value) is not int:
                reject('invalid_integer', 'Cents and source sequences must be exact integers')
            if name == 'SEQUENCE' and value < 1:
                reject('invalid_sequence', 'Source sequence must be positive')
        elif name == 'IS_DELETED':
            if type(value) is not bool:
                reject('invalid_tombstone', 'Source tombstone must be boolean')
        elif name in ('INVOICE_DATE', 'VALID_FROM', 'VALID_TO'):
            if name != 'VALID_TO' or value is not None:
                calendar_date(value)
        elif type(value) is not str or not value:
            reject('invalid_text', 'A nonempty source string is required')


def read_adjustments(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        reject('missing_adjustments', 'Complete CSV content or adjustment records are required')
    reader = csv.DictReader(io.StringIO(value))
    if reader.fieldnames is None or len(reader.fieldnames) != 4 or set(reader.fieldnames) != SCHEMA['ADJUSTMENTS']:
        reject('missing_adjustments', 'CSV header must contain all declared adjustment columns exactly once')
    records = []
    for row in reader:
        if set(row) != SCHEMA['ADJUSTMENTS']:
            reject('source_schema', 'Adjustment row has unexpected fields')
        try:
            cents = int(row['ADJUSTMENT_CENTS'])
        except (TypeError, ValueError):
            reject('invalid_integer', 'Adjustment CSV amount must be integer cents')
        if str(cents) != row['ADJUSTMENT_CENTS']:
            reject('invalid_integer', 'Adjustment CSV amount must be canonical integer cents')
        records.append(dict(row, ADJUSTMENT_CENTS=cents))
    return records


def latest(records, table, key_field):
    if not isinstance(records, list):
        reject('missing_source', 'Source records must be an array')
    observed, current = {}, {}
    for row in records:
        validate_record(table, row)
        identity = (row['TENANT_ID'], row[key_field])
        version = (identity, row['SEQUENCE'])
        if version in observed and observed[version] != row:
            reject('cdc_conflict', 'Conflicting payloads share the same source identity and sequence')
        observed[version] = row
        if identity not in current or row['SEQUENCE'] > current[identity]['SEQUENCE']:
            current[identity] = row
    return {key: row for key, row in current.items() if not row['IS_DELETED']}


def build_invoices(raw, adjustments):
    if not isinstance(raw, dict) or set(raw) != {'origin', 'snapshot_at', 'INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'} or raw['origin'] != 'synthetic':
        reject('source_schema', 'Only the declared synthetic source contract is accepted')
    invoices = latest(raw['INVOICE_CDC'], 'INVOICE_CDC', 'INVOICE_ID')
    payments = latest(raw['PAYMENT_CDC'], 'PAYMENT_CDC', 'PAYMENT_ID')
    payment_amounts = {}
    for row in payments.values():
        key = (row['TENANT_ID'], row['INVOICE_ID'])
        if key not in invoices:
            reject('payment_orphan', 'A current payment references no current invoice')
        payment_amounts[key] = payment_amounts.get(key, 0) + row['PAID_CENTS']
    adjustment_amounts = {}
    for row in read_adjustments(adjustments):
        validate_record('ADJUSTMENTS', row)
        key = (row['TENANT_ID'], row['INVOICE_ID'])
        if key in adjustment_amounts:
            reject('duplicate_adjustment', 'Manual adjustments must have one row per tenant/invoice')
        if key not in invoices:
            reject('adjustment_orphan', 'An adjustment references no current invoice')
        adjustment_amounts[key] = row['ADJUSTMENT_CENTS']
    if not isinstance(raw['CUSTOMER_HISTORY'], list):
        reject('missing_source', 'Customer history records must be an array')
    history_by_customer, history_seen = {}, set()
    for row in raw['CUSTOMER_HISTORY']:
        validate_record('CUSTOMER_HISTORY', row)
        signature = tuple(row[name] for name in sorted(SCHEMA['CUSTOMER_HISTORY']))
        if signature in history_seen:
            continue
        history_seen.add(signature)
        start = calendar_date(row['VALID_FROM'])
        end = None if row['VALID_TO'] is None else calendar_date(row['VALID_TO'])
        if end is not None and start >= end:
            reject('invalid_history', 'Customer interval must have positive width')
        history_by_customer.setdefault((row['TENANT_ID'], row['CUSTOMER_ID']), []).append((start, end, row))
    for intervals in history_by_customer.values():
        intervals.sort(key=lambda interval: interval[0])
        for left, right in zip(intervals, intervals[1:]):
            if left[1] is None or right[0] < left[1]:
                reject('history_overlap', 'Customer history intervals overlap')
    rows = []
    for key, invoice in sorted(invoices.items()):
        effective = calendar_date(invoice['INVOICE_DATE'])
        intervals = history_by_customer.get((key[0], invoice['CUSTOMER_ID']), [])
        matches = [row for start, end, row in intervals if start <= effective and (end is None or effective < end)]
        if len(matches) != 1:
            reject('history_orphan', 'Invoice must bind exactly one effective customer version')
        customer = matches[0]
        adjustment = adjustment_amounts.get(key, 0)
        net = invoice['AMOUNT_CENTS'] + adjustment
        paid = payment_amounts.get(key, 0)
        rows.append({'tenant_id': key[0], 'invoice_id': key[1], 'invoice_key': '|'.join(key),
                     'customer_id': invoice['CUSTOMER_ID'],
                     'customer_key': '|'.join((key[0], invoice['CUSTOMER_ID'], customer['VALID_FROM'])),
                     'invoice_date': invoice['INVOICE_DATE'], 'invoice_month': effective.replace(day=1).isoformat(),
                     'status': invoice['STATUS'], 'segment': customer['SEGMENT'],
                     'amount_cents': invoice['AMOUNT_CENTS'], 'adjustment_cents': adjustment,
                     'net_cents': net, 'paid_cents': paid, 'outstanding_cents': net - paid})
    return rows


def sum_blank(rows, field):
    return sum(row[field] for row in rows) if rows else None


def ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 60
        return Decimal(numerator) / Decimal(denominator)


def calculate(raw, adjustments, params=None):
    """Return full gold invoices plus three report arrays (KPI always one row).

    Contexts are direct business predicates, independent of DAX/SQL translation.
    Reports sort by month then segment. Ratio values are Decimal or None.
    """
    p = parameters(params)
    invoices = build_invoices(raw, adjustments)
    # Security/date restrictions remain fixed when ordinary measure context changes.
    secure_date = [row for row in invoices if row['tenant_id'] == p['tenant']
                   and p['start_date'] <= row['invoice_date'] < p['end_date']]
    status_context = [row for row in secure_date if row['status'] == p['status']]
    selected = [row for row in status_context if p['segment'] == 'ALL' or row['segment'] == p['segment']]
    posted_replacement = [row for row in secure_date if row['status'] == 'posted'
                          and (p['segment'] == 'ALL' or row['segment'] == p['segment'])]
    posted_intersection = [row for row in selected if row['status'] == 'posted']
    scalar = p['multipliers'][0] if len(p['multipliers']) == 1 else 1
    marks = {}
    for row in selected:
        marks.setdefault((row['invoice_month'], row['segment']), []).append(row)
    revenue_trend, segment_share = [], []
    for (month, segment), visible in sorted(marks.items()):
        net, paid, outstanding = (sum_blank(visible, field) for field in ('net_cents', 'paid_cents', 'outstanding_cents'))
        # REMOVEFILTERS clears only segment, preserving this mark's month context.
        denominator = sum_blank([row for row in status_context if row['invoice_month'] == month], 'net_cents')
        revenue_trend.append({'month': month, 'segment': segment, 'revenue_cents': net,
                              'paid_cents': paid, 'outstanding_cents': outstanding,
                              'payment_rate': ratio(paid, net), 'scenario_revenue_cents': net * scalar})
        segment_share.append({'month': month, 'segment': segment, 'revenue_cents': net,
                              'all_segment_revenue_cents': denominator, 'share_all_segments': ratio(net, denominator)})
    # Totals have their own context; they are never summed from repeated mark LODs.
    total_net, total_paid, total_outstanding = (sum_blank(selected, field) for field in ('net_cents', 'paid_cents', 'outstanding_cents'))
    all_segment_net = sum_blank(status_context, 'net_cents')
    kpi = {'revenue_cents': total_net, 'paid_cents': total_paid, 'outstanding_cents': total_outstanding,
           'payment_rate': ratio(total_paid, total_net), 'all_segment_revenue_cents': all_segment_net,
           'share_all_segments': ratio(total_net, all_segment_net),
           'posted_revenue_cents': sum_blank(posted_replacement, 'net_cents'),
           'posted_intersection_cents': sum_blank(posted_intersection, 'net_cents'),
           'scenario_revenue_cents': None if total_net is None else total_net * scalar}
    return {'invoices': invoices, 'revenue_trend': revenue_trend, 'segment_share': segment_share, 'kpi_totals': [kpi]}


SCENARIOS = [
    ('default_a', {}), ('tenant_b', {'tenant': 'B'}),
    ('january_a', {'end_date': '2026-02-01'}), ('february_a', {'start_date': '2026-02-01'}),
    ('february_boundary_a', {'start_date': '2026-02-01', 'end_date': '2026-02-02'}),
    ('segment_smb_a', {'segment': 'SMB'}), ('segment_enterprise_a', {'segment': 'Enterprise'}),
    ('segment_smb_b', {'tenant': 'B', 'segment': 'SMB'}), ('segment_enterprise_b', {'tenant': 'B', 'segment': 'Enterprise'}),
    ('empty_equal_bounds', {'end_date': '2026-01-01'}),
    ('empty_after_snapshot', {'start_date': '2026-04-01', 'end_date': '2026-05-01'}),
    ('zero_revenue_a', {'start_date': '2026-02-20', 'end_date': '2026-02-21'}),
    ('multiplier_two', {'multipliers': [2]}), ('multipliers_multiple', {'multipliers': [1, 2]}),
    ('multipliers_none', {'multipliers': []}), ('draft_a', {'status': 'draft'}),
    ('draft_smb_a', {'status': 'draft', 'segment': 'SMB'}), ('draft_b', {'status': 'draft', 'tenant': 'B'}),
    ('unknown_segment_empty', {'segment': 'Unrepresented'}),
    ('january_smb_a', {'end_date': '2026-02-01', 'segment': 'SMB'}),
    ('draft_january_a', {'status': 'draft', 'end_date': '2026-02-01'}),
    ('draft_enterprise_february_a', {'status': 'draft', 'segment': 'Enterprise', 'start_date': '2026-02-01'}),
]
INVALID_SCENARIOS = [
    ('unknown_tenant', {'tenant': 'C'}, 'unknown_tenant'),
    ('missing_tenant', {'tenant': None}, 'unknown_tenant'),
    ('unknown_role', {'role': 'Administrator'}, 'unknown_role'),
    ('missing_role', {'role': None}, 'unknown_role'),
    ('role_mismatch', {'tenant': 'B', 'role': 'TenantA'}, 'role_mismatch'),
    ('persona_mismatch', {'persona_tenant': 'B'}, 'persona_mismatch'),
    ('missing_persona', {'persona_tenant': None}, 'persona_mismatch'),
    ('unauthorized', {'authorized': False}, 'unauthorized'),
    ('invalid_date', {'start_date': '2026-02-30'}, 'invalid_date'),
    ('reversed_dates', {'start_date': '2026-03-01', 'end_date': '2026-01-01'}, 'reversed_dates'),
    ('unknown_status', {'status': 'void'}, 'unknown_status'),
    ('duplicate_multipliers', {'multipliers': [1, 1]}, 'invalid_multipliers'),
    ('unknown_multiplier', {'multipliers': [3]}, 'invalid_multipliers'),
    ('noninteger_multiplier', {'multipliers': [1.0]}, 'invalid_multipliers'),
    ('boolean_multiplier', {'multipliers': [True]}, 'invalid_multipliers'),
    ('missing_multiplier_selection', {'multipliers': None}, 'invalid_multipliers'),
]


def generate():
    case = Path(__file__).resolve().parent.parent
    names = ['input/scenario.md', 'input/raw-data.json', 'input/repo/adjustments.csv']
    hashes = {name: hashlib.sha256((case / name).read_bytes()).hexdigest() for name in names}
    raw = json.loads((case / names[1]).read_text())
    adjustments = (case / names[2]).read_text()
    metadata = {'schema_version': 1, 'origin': 'synthetic_independent_oracle',
                'platform_instance': 'DMA_POWERBI_SYNTHETIC', 'catalogue': 'DMA_POWERBI', 'input_sha256': hashes}
    rows = dict(metadata, invoices=calculate(raw, adjustments)['invoices'])
    reports = dict(metadata, ratio_absolute_tolerance='1e-12', scenarios=[], invalid_scenarios=[])
    for name, params in SCENARIOS:
        outputs = calculate(raw, adjustments, params)
        outputs.pop('invoices')
        reports['scenarios'].append({'name': name, 'parameters': params, 'outputs': outputs})
    for name, params, code in INVALID_SCENARIOS:
        try:
            calculate(raw, adjustments, params)
        except OracleContractError as error:
            if error.code != code:
                raise AssertionError((name, error.code, code))
        else:
            raise AssertionError('Invalid context accepted: ' + name)
        reports['invalid_scenarios'].append({'name': name, 'parameters': params, 'expected_error_code': code})
    for name, content in [('expected_rows.json', rows), ('expected_reports.json', reports)]:
        (case / 'expected' / name).write_text(json.dumps(content, indent=2, default=str, allow_nan=False) + '\n')
    print(json.dumps({'invoices': len(rows['invoices']), 'valid_scenarios': len(reports['scenarios']),
                      'invalid_scenarios': len(reports['invalid_scenarios']),
                      'report_rows': sum(len(rows) for scenario in reports['scenarios'] for rows in scenario['outputs'].values())}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true', help='Write expected fixtures before freeze only')
    arguments = parser.parse_args()
    if arguments.generate:
        generate()
    else:
        parser.print_help()
