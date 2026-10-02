"""Independent Tableau fixture oracle; standard library only, no SQL or targets.

Inputs used to author this oracle: input/scenario.md, input/raw-data.json and
input/repo/adjustments.csv only. calculate() is reusable for focused mutations.
Run this file to regenerate the two expected JSON artifacts before their freeze.
"""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path


class OracleContractError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ': ' + message)


def fail(code, message):
    raise OracleContractError(code, message)


DEFAULTS = {'tenant': 'A', 'start_date': '2026-01-01', 'end_date': '2026-03-01',
            'segment': 'ALL', 'multiplier': 1}
TABLE_FIELDS = {
    'INVOICE_CDC': {'TENANT_ID', 'INVOICE_ID', 'CUSTOMER_ID', 'INVOICE_DATE', 'AMOUNT_CENTS', 'STATUS', 'IS_DELETED', 'SEQUENCE'},
    'PAYMENT_CDC': {'TENANT_ID', 'PAYMENT_ID', 'INVOICE_ID', 'PAID_CENTS', 'IS_DELETED', 'SEQUENCE'},
    'CUSTOMER_HISTORY': {'TENANT_ID', 'CUSTOMER_ID', 'SEGMENT', 'VALID_FROM', 'VALID_TO'},
    'ADJUSTMENTS': {'TENANT_ID', 'INVOICE_ID', 'ADJUSTMENT_CENTS', 'REASON'},
}


def iso_date(value):
    if not isinstance(value, str):
        fail('invalid_date', 'Date must be YYYY-MM-DD text')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        fail('invalid_date', 'Date must be valid YYYY-MM-DD text')
    if result.isoformat() != value:
        fail('invalid_date', 'Date must be canonical YYYY-MM-DD text')
    return result


def parameters(params=None):
    if params is not None and not isinstance(params, dict):
        fail('invalid_parameters', 'Expected a parameter mapping')
    supplied = {} if params is None else params
    if set(supplied) - set(DEFAULTS) - {'authorized', 'persona_tenant'}:
        fail('invalid_parameters', 'Unknown parameter')
    result = dict(DEFAULTS)
    result.update(supplied)
    if result['tenant'] not in ('A', 'B'):
        fail('unknown_tenant', 'Known synthetic tenant is required')
    if result.get('authorized', True) is not True:
        fail('unauthorized', 'Synthetic persona is denied')
    # Choosing a fixture tenant selects that tenant's invented persona. Explicit
    # persona overrides must agree; this does not implement production security.
    if result.get('persona_tenant', result['tenant']) != result['tenant']:
        fail('persona_mismatch', 'Requested tenant differs from supplied persona')
    start, end = iso_date(result['start_date']), iso_date(result['end_date'])
    if start > end:
        fail('reversed_dates', 'Inclusive start must not exceed exclusive end')
    if not isinstance(result['segment'], str) or not result['segment'] or len(result['segment']) > 200:
        fail('invalid_segment', 'A bounded nonempty segment string is required')
    multiplier = result['multiplier']
    if type(multiplier) not in (str, int, float, Decimal):
        fail('invalid_multiplier', 'A finite numeric multiplier is required')
    try:
        multiplier = Decimal(str(multiplier))
    except InvalidOperation:
        fail('invalid_multiplier', 'A finite numeric multiplier is required')
    if not multiplier.is_finite():
        fail('invalid_multiplier', 'Nonfinite multiplier is not permitted')
    result['multiplier'] = multiplier
    return result


def require_record(row, fields):
    if not isinstance(row, dict) or set(row) != fields:
        fail('source_schema', 'Source fields differ from the declared fixture schema')
    for key, value in row.items():
        if key.endswith('_ID'):
            if not isinstance(value, str) or not value or '|' in value:
                fail('invalid_identity', 'Nonempty identity without pipe is required')
        elif key.endswith('_CENTS') or key == 'SEQUENCE':
            if type(value) is not int:
                fail('invalid_integer', 'Cents and source sequence must be exact integers')
            if key == 'SEQUENCE' and value < 1:
                fail('invalid_sequence', 'Sequence must be positive')
        elif key == 'IS_DELETED':
            if type(value) is not bool:
                fail('invalid_tombstone', 'Tombstone must be boolean')
        elif key in ('INVOICE_DATE', 'VALID_FROM', 'VALID_TO'):
            if key != 'VALID_TO' or value is not None:
                iso_date(value)
        elif not isinstance(value, str) or not value:
            fail('invalid_text', 'Source text must be nonempty')


def adjustment_rows(adjustments):
    if isinstance(adjustments, str):
        reader = csv.DictReader(io.StringIO(adjustments))
        if reader.fieldnames is None or len(reader.fieldnames) != 4 or set(reader.fieldnames) != TABLE_FIELDS['ADJUSTMENTS']:
            fail('missing_adjustments', 'Present CSV with exact declared header is required')
        result = []
        for row in reader:
            if set(row) != TABLE_FIELDS['ADJUSTMENTS']:
                fail('source_schema', 'Adjustment CSV row width differs from header')
            value = row['ADJUSTMENT_CENTS']
            try:
                integer = int(value)
            except (TypeError, ValueError):
                fail('invalid_integer', 'Adjustment CSV requires integer cents')
            if str(integer) != value:
                fail('invalid_integer', 'Adjustment CSV requires canonical integer cents')
            result.append(dict(row, ADJUSTMENT_CENTS=integer))
        return result
    if not isinstance(adjustments, list):
        fail('missing_adjustments', 'Adjustment records or complete CSV content is required')
    return adjustments


def current_records(records, table, identity):
    if not isinstance(records, list):
        fail('missing_source', 'Declared source must be an array')
    versions, newest = {}, {}
    for row in records:
        require_record(row, TABLE_FIELDS[table])
        key = (row['TENANT_ID'], row[identity])
        version = (*key, row['SEQUENCE'])
        if version in versions and versions[version] != row:
            fail('cdc_conflict', 'Same source identity and sequence have different payloads')
        versions[version] = row
        if key not in newest or row['SEQUENCE'] > newest[key]['SEQUENCE']:
            newest[key] = row
    return {key: row for key, row in newest.items() if not row['IS_DELETED']}


def invoices_from_sources(raw, adjustments):
    if not isinstance(raw, dict) or set(raw) != {'origin', 'snapshot_at', 'INVOICE_CDC', 'PAYMENT_CDC', 'CUSTOMER_HISTORY'} or raw['origin'] != 'synthetic':
        fail('source_schema', 'This oracle accepts the declared synthetic source contract')
    current = current_records(raw['INVOICE_CDC'], 'INVOICE_CDC', 'INVOICE_ID')
    payments = current_records(raw['PAYMENT_CDC'], 'PAYMENT_CDC', 'PAYMENT_ID')
    paid = {}
    for payment in payments.values():
        key = (payment['TENANT_ID'], payment['INVOICE_ID'])
        if key not in current:
            fail('payment_orphan', 'Current payment has no current invoice')
        paid[key] = paid.get(key, 0) + payment['PAID_CENTS']
    manual = {}
    for row in adjustment_rows(adjustments):
        require_record(row, TABLE_FIELDS['ADJUSTMENTS'])
        key = (row['TENANT_ID'], row['INVOICE_ID'])
        if key in manual:
            fail('duplicate_adjustment', 'Only one manual row per tenant/invoice is permitted')
        if key not in current:
            fail('adjustment_orphan', 'Manual adjustment has no current invoice')
        manual[key] = row['ADJUSTMENT_CENTS']
    if not isinstance(raw['CUSTOMER_HISTORY'], list):
        fail('missing_source', 'Customer history array is required')
    histories, history_versions = {}, set()
    for history in raw['CUSTOMER_HISTORY']:
        require_record(history, TABLE_FIELDS['CUSTOMER_HISTORY'])
        exact = tuple(history[key] for key in sorted(history))
        if exact in history_versions:
            continue
        history_versions.add(exact)
        start = iso_date(history['VALID_FROM'])
        end = None if history['VALID_TO'] is None else iso_date(history['VALID_TO'])
        if end is not None and start >= end:
            fail('invalid_history', 'History interval must have positive width')
        key = (history['TENANT_ID'], history['CUSTOMER_ID'])
        histories.setdefault(key, []).append((start, end, history))
    for intervals in histories.values():
        intervals.sort(key=lambda interval: interval[0])
        for previous, following in zip(intervals, intervals[1:]):
            if previous[1] is None or following[0] < previous[1]:
                fail('history_overlap', 'Customer history intervals overlap')
    result = []
    for key in sorted(current):
        invoice = current[key]
        effective = iso_date(invoice['INVOICE_DATE'])
        matches = [record for start, end, record in histories.get((key[0], invoice['CUSTOMER_ID']), [])
                   if start <= effective and (end is None or effective < end)]
        if len(matches) != 1:
            fail('history_orphan', 'Invoice requires exactly one effective customer record')
        customer = matches[0]
        net = invoice['AMOUNT_CENTS'] + manual.get(key, 0)
        result.append({
            'tenant_id': key[0], 'invoice_id': key[1], 'invoice_key': '|'.join(key),
            'customer_id': invoice['CUSTOMER_ID'],
            'customer_key': '|'.join((key[0], invoice['CUSTOMER_ID'], customer['VALID_FROM'])),
            'invoice_date': effective.isoformat(), 'invoice_month': effective.replace(day=1).isoformat(),
            'status': invoice['STATUS'], 'segment': customer['SEGMENT'],
            'amount_cents': invoice['AMOUNT_CENTS'], 'adjustment_cents': manual.get(key, 0),
            'net_cents': net, 'paid_cents': paid.get(key, 0), 'outstanding_cents': net - paid.get(key, 0),
        })
    return result


def divide(numerator, denominator):
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return Decimal(numerator) / Decimal(denominator)


def calculate(raw, adjustments, params=None):
    """Return complete invoices and the three selected Tableau sheets.

    adjustments: uppercase-key list or complete CSV text, never a filesystem path.
    Reports use canonical ascending month/segment or customer/segment ordering.
    The invoice list is not reduced by report parameters. Ratios are Decimal/None.
    """
    p = parameters(params)
    invoices = invoices_from_sources(raw, adjustments)
    population = [row for row in invoices if row['tenant_id'] == p['tenant'] and row['status'] == 'posted'
                  and p['start_date'] <= row['invoice_date'] < p['end_date']]
    fixed_customer = {}
    for row in population:
        key = (row['tenant_id'], row['customer_id'])
        fixed_customer[key] = fixed_customer.get(key, 0) + row['net_cents']
    selected = [row for row in population if p['segment'] == 'ALL' or row['segment'] == p['segment']]
    monthly, customer_marks = {}, {}
    for row in selected:
        mark = (row['invoice_month'], row['segment'])
        amounts = monthly.setdefault(mark, {'net': 0, 'paid': 0, 'outstanding': 0})
        amounts['net'] += row['net_cents']
        amounts['paid'] += row['paid_cents']
        amounts['outstanding'] += row['outstanding_cents']
        customer_mark = (row['customer_id'], row['segment'])
        customer_marks[customer_mark] = customer_marks.get(customer_mark, 0) + row['net_cents']
    partition_totals = {}
    for (month, _), amounts in monthly.items():
        partition_totals[month] = partition_totals.get(month, 0) + amounts['net']
    revenue, share = [], []
    for (month, segment), amounts in sorted(monthly.items()):
        with localcontext() as context:
            context.prec = max(50, len(str(abs(amounts['net']))) + len(p['multiplier'].as_tuple().digits) + 10)
            scenario = Decimal(amounts['net']) * p['multiplier']
        if scenario == scenario.to_integral_value():
            scenario = int(scenario)
        revenue.append({'month': month, 'segment': segment, 'revenue_cents': amounts['net'],
                        'paid_cents': amounts['paid'], 'outstanding_cents': amounts['outstanding'],
                        'payment_rate': divide(amounts['paid'], amounts['net']), 'scenario_revenue_cents': scenario})
        share.append({'month': month, 'segment': segment, 'revenue_cents': amounts['net'],
                      'share_of_month': divide(amounts['net'], partition_totals[month])})
    customer = [{'customer_id': customer_id, 'segment': segment, 'selected_revenue_cents': selected_net,
                 'fixed_customer_revenue_cents': fixed_customer[(p['tenant'], customer_id)]}
                for (customer_id, segment), selected_net in sorted(customer_marks.items())]
    return {'invoices': invoices, 'revenue_trend': revenue, 'customer_value': customer, 'revenue_share': share}


SCENARIOS = [
    ('default_a', {}), ('tenant_b', {'tenant': 'B'}),
    ('january_a', {'end_date': '2026-02-01'}), ('february_a', {'start_date': '2026-02-01'}),
    ('february_boundary_a', {'start_date': '2026-02-01', 'end_date': '2026-02-02'}),
    ('segment_smb_a', {'segment': 'SMB'}), ('segment_enterprise_a', {'segment': 'Enterprise'}),
    ('segment_smb_b', {'tenant': 'B', 'segment': 'SMB'}), ('segment_enterprise_b', {'tenant': 'B', 'segment': 'Enterprise'}),
    ('empty_equal_bounds', {'end_date': '2026-01-01'}),
    ('empty_after_snapshot', {'start_date': '2026-04-01', 'end_date': '2026-05-01'}),
    ('zero_revenue_a', {'start_date': '2026-02-20', 'end_date': '2026-02-21'}),
    ('multiplier_double', {'multiplier': 2}),
    ('context_january_smb', {'end_date': '2026-02-01', 'segment': 'SMB'}),
    ('context_february_enterprise', {'start_date': '2026-02-01', 'segment': 'Enterprise'}),
    ('unknown_segment_empty', {'segment': 'Unrepresented'}),
]
ERROR_SCENARIOS = [
    ('unknown_tenant', {'tenant': 'C'}, 'unknown_tenant'),
    ('missing_tenant', {'tenant': None}, 'unknown_tenant'),
    ('unauthorized_persona', {'authorized': False}, 'unauthorized'),
    ('persona_mismatch', {'tenant': 'A', 'persona_tenant': 'B'}, 'persona_mismatch'),
    ('reversed_dates', {'start_date': '2026-03-01', 'end_date': '2026-01-01'}, 'reversed_dates'),
    ('invalid_date', {'start_date': '2026-02-30'}, 'invalid_date'),
    ('nonfinite_multiplier_nan', {'multiplier': 'NaN'}, 'invalid_multiplier'),
    ('nonfinite_multiplier_infinity', {'multiplier': 'Infinity'}, 'invalid_multiplier'),
]


def generate():
    root = Path(__file__).resolve().parent.parent
    files = ['input/scenario.md', 'input/raw-data.json', 'input/repo/adjustments.csv']
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    raw = json.loads((root / files[1]).read_text())
    adjustments = (root / files[2]).read_text()
    common = {'schema_version': 1, 'origin': 'synthetic_independent_oracle',
              'platform_instance': 'DMA_TABLEAU_SYNTHETIC', 'catalogue': 'DMA_TABLEAU', 'input_sha256': hashes}
    rows = dict(common, invoices=calculate(raw, adjustments)['invoices'])
    reports = dict(common, ratio_absolute_tolerance='1e-12', scenarios=[], error_scenarios=[])
    for name, params in SCENARIOS:
        result = calculate(raw, adjustments, params)
        reports['scenarios'].append({'scenario_id': name, 'parameters': params,
                                     'outputs': {key: value for key, value in result.items() if key != 'invoices'}})
    for name, params, expected_code in ERROR_SCENARIOS:
        try:
            calculate(raw, adjustments, params)
        except OracleContractError as error:
            if error.code != expected_code:
                raise AssertionError((name, error.code, expected_code))
        else:
            raise AssertionError('Invalid context was accepted: ' + name)
        reports['error_scenarios'].append({'scenario_id': name, 'parameters': params, 'expected_error_code': expected_code})
    for filename, document in [('expected_rows.json', rows), ('expected_reports.json', reports)]:
        (root / 'expected' / filename).write_text(json.dumps(document, indent=2, default=str, allow_nan=False) + '\n')
    print(json.dumps({'invoices': len(rows['invoices']), 'report_scenarios': len(reports['scenarios']),
                      'invalid_contexts': len(reports['error_scenarios']),
                      'report_marks': sum(len(rows) for scenario in reports['scenarios'] for rows in scenario['outputs'].values())}))


if __name__ == '__main__':
    generate()
