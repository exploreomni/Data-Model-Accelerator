-- Synthetic assessment fixture. No target connection or compilation evidence.
select
    tenant_id,
    invoice_id,
    status,
    gross_cents,
    paid_cents,
    gross_cents - coalesce(credit_cents, 0) as net_cents
from {{ source('billing', 'invoice_current') }}
