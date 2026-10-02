"""Independent synthetic source arithmetic; never imports or queries candidate SQL.

Run only while authoring the unfrozen fixture. A frozen receipt must not be
regenerated to accommodate candidate behavior. Python standard library only.
"""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT.parent / 'input'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def current(name, entity):
    """Choose the latest full entity history, then apply its deletion flag."""
    with (INPUT / 'repo' / 'seeds' / (name + '.csv')).open(newline='') as stream:
        history = list(csv.DictReader(stream))
    latest = {}
    for raw in history:
        row = dict(raw)
        row['cdc_sequence'] = int(row['cdc_sequence'])
        key = row['tenant_id'], row[entity]
        prior = latest.get(key)
        order = row['cdc_sequence'], row['updated_at']
        if prior is None or order > (prior['cdc_sequence'], prior['updated_at']):
            latest[key] = row
        elif order == (prior['cdc_sequence'], prior['updated_at']):
            assert row == prior, 'Conflicting replicated source version'
    return [{k: v for k, v in row.items() if k != 'is_deleted'}
            for key, row in sorted(latest.items()) if row['is_deleted'] == 'false']


rentals = current('raw_rentals', 'rental_id')
charges = current('raw_charges', 'charge_id')
locations = current('raw_locations', 'location_id')
rental_index = {(r['tenant_id'], r['rental_id']): r for r in rentals}
location_index = {(r['tenant_id'], r['location_id']): r for r in locations}
eligible = []
for charge in charges:
    parent = rental_index.get((charge['tenant_id'], charge['rental_id']))
    if not parent or parent['rental_status'] != 'completed':
        continue
    if charge['charge_type'] not in ('rental_fee', 'damage_fee', 'refund'):
        continue
    assert charge['currency'] == parent['currency']
    value = Decimal(charge['amount'])
    signed = -value if charge['charge_type'] == 'refund' else value
    eligible.append({key: charge[key] for key in
                     ('tenant_id', 'charge_id', 'rental_id', 'charge_type', 'currency')} |
                    {'source_amount': format(value, '.2f'), 'signed_amount': format(signed, '.2f')})

gold = []
for rental in rentals:
    if rental['rental_status'] != 'completed':
        continue
    key = rental['tenant_id'], rental['rental_id']
    matching = [r for r in eligible if (r['tenant_id'], r['rental_id']) == key]
    fees = sum((Decimal(r['signed_amount']) for r in matching
                if r['charge_type'] != 'refund'), Decimal('0'))
    refunds = sum((Decimal(r['signed_amount']) for r in matching
                   if r['charge_type'] == 'refund'), Decimal('0'))
    row = {k: rental[k] for k in ('tenant_id', 'rental_id', 'location_id',
                                 'rental_status', 'rental_date', 'currency')}
    row['location_name'] = location_index[(rental['tenant_id'], rental['location_id'])]['location_name']
    row.update(fee_amount=format(fees, '.2f'), refund_amount=format(refunds, '.2f'),
               net_revenue=format(fees + refunds, '.2f'), eligible_charge_count=len(matching))
    gold.append(row)

# Independent hand arithmetic cross-checks, pinned before candidate authoring.
assert (len(rentals), len(charges), len(locations), len(eligible), len(gold)) == (5, 8, 3, 5, 4)
assert {(r['tenant_id'], r['rental_id']): r['net_revenue'] for r in gold} == {
    ('A', 'R1'): '100.00', ('A', 'R2'): '0.00', ('B', 'R1'): '65.00', ('C', 'R9'): '42.00'}
assert sum(Decimal(r['net_revenue']) for r in gold) == Decimal('207.00')

gold_columns = ['tenant_id', 'rental_id', 'location_id', 'location_name', 'rental_status',
                'rental_date', 'currency', 'fee_amount', 'refund_amount', 'net_revenue', 'eligible_charge_count']
compat_columns = gold_columns[:7] + ['net_revenue']
case_data = [
    ('gold_all', gold, gold_columns, ['tenant_id', 'rental_id'], 'fct_rental_revenue', '',
     'correctness', {'tenant_id': ['A', 'B', 'C'], 'rental_status': 'completed'}, 'synthetic:finance_all'),
    ('tenant_A', [r for r in gold if r['tenant_id'] == 'A'], gold_columns,
     ['tenant_id', 'rental_id'], 'fct_rental_revenue', " where tenant_id = 'A'",
     'correctness', {'tenant_id': 'A', 'rental_status': 'completed'}, 'synthetic:rental_viewer_A'),
    ('eligible_charges', eligible,
     ['tenant_id', 'charge_id', 'rental_id', 'charge_type', 'currency', 'source_amount', 'signed_amount'],
     ['tenant_id', 'charge_id'], 'int_eligible_charges', '', 'correctness',
     {'tenant_id': ['A', 'B', 'C'], 'rental_status': 'completed', 'charge_type': ['rental_fee', 'damage_fee', 'refund']},
     'synthetic:validation_analyst'),
    ('staging_rentals', rentals, list(rentals[0]), ['tenant_id', 'rental_id'], 'stg_rentals', '',
     'correctness', {'is_deleted': False, 'latest_version': True}, 'synthetic:validation_analyst'),
    ('staging_charges', charges, list(charges[0]), ['tenant_id', 'charge_id'], 'stg_charges', '',
     'correctness', {'is_deleted': False, 'latest_version': True}, 'synthetic:validation_analyst'),
    ('staging_locations', locations, list(locations[0]), ['tenant_id', 'location_id'], 'stg_locations', '',
     'correctness', {'is_deleted': False, 'latest_version': True}, 'synthetic:validation_analyst'),
    ('clean_compatibility', [{k: r[k] for k in compat_columns} for r in gold if r['tenant_id'] == 'C'],
     compat_columns, ['tenant_id', 'rental_id'], 'fct_rental_revenue', " where tenant_id = 'C' and rental_id = 'R9'",
     'compatibility', {'tenant_id': 'C', 'rental_id': 'R9', 'rental_status': 'completed'}, 'synthetic:rental_viewer_C'),
    ('denied_persona', [], gold_columns, ['tenant_id', 'rental_id'], 'fct_rental_revenue',
     " where tenant_id = '__DENIED__'", 'correctness',
     {'tenant_id': [], 'effective_tenant_filter': '__DENIED__'}, 'synthetic:denied_no_tenant_grants'),
]
decimals = {'amount', 'source_amount', 'signed_amount', 'fee_amount', 'refund_amount', 'net_revenue'}
integers = {'cdc_sequence', 'eligible_charge_count'}
cases, queries = [], {}
for case_id, rows, columns, keys, model, predicate, category, filters, principal in case_data:
    export = ROOT / 'exports' / (case_id + '.json')
    write(export, {'rows': rows})
    case = {
        'id': case_id, 'category': category,
        'context': {'timezone': 'UTC', 'watermark': '2026-08-16T00:00:00Z',
                    'principal': principal, 'currency': 'USD', 'filters': filters},
        'keys': keys,
        'columns': {col: {'type': 'decimal' if col in decimals else 'integer' if col in integers else 'string',
                          'nullable': False} for col in columns},
        'expected': {'path': 'exports/' + case_id + '.json', 'sha256': digest(export),
                     'query_id': 'synthetic-oracle:' + case_id},
    }
    if category == 'correctness':
        case['decision'] = {
            'id': 'SYNTHETIC-RENTAL-DECISION-001',
            'approved_by': 'synthetic-exercise-authority:/root/rental_analyst',
            'reason': 'Fabricated accepted definitions in input/requirements.md; synthetic test authority only, not human or production approval.'}
    cases.append(case)
    queries[case_id] = 'select ' + ', '.join(columns) + ' from ' + model + predicate + ' order by ' + ', '.join(keys)

write(ROOT / 'contract-template.json', {
    'schema_version': 1, 'analyst_id': '/root/rental_analyst',
    'source_revision': 'REPLACE_WITH_PLAN_SOURCE_SNAPSHOT_SHA256',
    'catalogue_sha256': digest(INPUT / 'catalogue.json'), 'cases': cases})
write(ROOT / 'queries.json', queries)
write(ROOT / 'source-receipts.json', {
    'evidence_class': 'independent_synthetic_source_calculation',
    'candidate_read': False, 'native_source_query_executed': False,
    'method': 'Standard-library CSV latest-version selection plus exact Decimal arithmetic and manual total checks.',
    'files': [{'path': str(path.relative_to(INPUT)), 'sha256': digest(path)}
              for path in sorted(INPUT.rglob('*')) if path.is_file()]})
print('Authored 8 independent synthetic oracle exports; no baseline frozen.')
