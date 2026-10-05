# Maintenance dictionary
All physical namespaces/types are synthetic plans. Definitions are proposed; approvals, ownership, source NULL semantics, CDC/history, retention and currency remain unresolved.

## source:work_orders
Grain: One row per work_order_id is a synthetic contract; original platform grain unknown

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| WORK_ORDER_ID | TEXT (CSV lexical contract) | Work order identifier in the synthetic snapshot. | Identity retention of lexical CSV value |
| TENANT_ID | TEXT (CSV lexical contract) | Tenant identifier retained for downstream filtering; no security policy is established. | Identity retention of lexical CSV value |
| OPENED_ON | TEXT (CSV lexical contract) | Work order opening date; dashboard date interpretation is UTC. | Identity retention of lexical CSV value |
| LABOR_COST | TEXT (CSV lexical contract) | Labor contribution to work cost; currency is unspecified. | Identity retention of lexical CSV value |
| STATUS | TEXT (CSV lexical contract) | Work order status retained without upstream filtering. | Identity retention of lexical CSV value |

## source:parts
Grain: One row per part_line_id is a synthetic contract; original platform grain unknown

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| PART_LINE_ID | TEXT (CSV lexical contract) | Part line identifier in the supplied snapshot. | Identity retention of lexical CSV value |
| WORK_ORDER_ID | TEXT (CSV lexical contract) | Work order identifier in the synthetic snapshot. | Identity retention of lexical CSV value |
| QUANTITY | TEXT (CSV lexical contract) | Quantity of the part on this line. | Identity retention of lexical CSV value |
| UNIT_COST | TEXT (CSV lexical contract) | Cost per part unit; currency is unspecified. | Identity retention of lexical CSV value |

## bronze_work_orders
Grain: One row per work_order_id in the supplied snapshot; no historical uniqueness asserted

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| WORK_ORDER_ID | TEXT (CSV lexical contract) | Work order identifier in the synthetic snapshot. | Identity retention of lexical CSV value |
| TENANT_ID | TEXT (CSV lexical contract) | Tenant identifier retained for downstream filtering; no security policy is established. | Identity retention of lexical CSV value |
| OPENED_ON | TEXT (CSV lexical contract) | Work order opening date; dashboard date interpretation is UTC. | Identity retention of lexical CSV value |
| LABOR_COST | TEXT (CSV lexical contract) | Labor contribution to work cost; currency is unspecified. | Identity retention of lexical CSV value |
| STATUS | TEXT (CSV lexical contract) | Work order status retained without upstream filtering. | Identity retention of lexical CSV value |

## bronze_parts
Grain: One row per part_line_id in the supplied snapshot; no historical uniqueness asserted

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| PART_LINE_ID | TEXT (CSV lexical contract) | Part line identifier in the supplied snapshot. | Identity retention of lexical CSV value |
| WORK_ORDER_ID | TEXT (CSV lexical contract) | Work order identifier in the synthetic snapshot. | Identity retention of lexical CSV value |
| QUANTITY | TEXT (CSV lexical contract) | Quantity of the part on this line. | Identity retention of lexical CSV value |
| UNIT_COST | TEXT (CSV lexical contract) | Cost per part unit; currency is unspecified. | Identity retention of lexical CSV value |

## silver_work_orders
Grain: One row per work_order_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| WORK_ORDER_ID | NUMBER(38, 0) | Work order identifier in the synthetic snapshot. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| TENANT_ID | NUMBER(38, 0) | Tenant identifier retained for downstream filtering; no security policy is established. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| OPENED_ON | DATE | Work order opening date; dashboard date interpretation is UTC. | Explicit cast to date; invalid values fail rather than silently null. |
| LABOR_COST | NUMBER(18, 4) | Labor contribution to work cost; currency is unspecified. | Explicit cast to number(18, 4); invalid values fail rather than silently null. |
| STATUS | VARCHAR | Work order status retained without upstream filtering. | Explicit cast to varchar; invalid values fail rather than silently null. |

## silver_parts
Grain: One row per part_line_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| PART_LINE_ID | NUMBER(38, 0) | Part line identifier in the supplied snapshot. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| WORK_ORDER_ID | NUMBER(38, 0) | Work order identifier in the synthetic snapshot. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| QUANTITY | NUMBER(18, 4) | Quantity of the part on this line. | Explicit cast to number(18, 4); invalid values fail rather than silently null. |
| UNIT_COST | NUMBER(18, 4) | Cost per part unit; currency is unspecified. | Explicit cast to number(18, 4); invalid values fail rather than silently null. |

## gold_work_orders
Grain: One row per work_order_id

| Column | Planned type | Meaning | Transformation |
|---|---|---|---|
| WORK_ORDER_ID | NUMBER(38, 0) | Work order identifier in the synthetic snapshot. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| TENANT_ID | NUMBER(38, 0) | Tenant identifier retained for downstream filtering; no security policy is established. | Explicit cast to number(38, 0); invalid values fail rather than silently null. |
| OPENED_ON | DATE | Work order opening date; dashboard date interpretation is UTC. | Explicit cast to date; invalid values fail rather than silently null. |
| LABOR_COST | NUMBER(18, 4) | Labor contribution to work cost; currency is unspecified. | Explicit cast to number(18, 4); invalid values fail rather than silently null. |
| STATUS | VARCHAR | Work order status retained without upstream filtering. | Explicit cast to varchar; invalid values fail rather than silently null. |
| PARTS_COST | NUMBER(18, 4) | Sum of quantity times unit_cost by work_order_id; zero when no part rows exist. | Sum of quantity times unit_cost by work_order_id; zero when no part rows exist. |
| WORK_COST | NUMBER(18, 4) | Labor cost plus parts cost at work order grain. | Labor cost plus parts cost at work order grain. |
