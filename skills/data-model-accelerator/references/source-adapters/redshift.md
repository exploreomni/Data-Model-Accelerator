# Redshift supplied-source adapter

Research reviewed: 2026-10-15. Implementation:
[`redshift.py`](../../scripts/source_adapters/redshift.py). Independent tests:
[`test_source_redshift.py`](../../../../tests/test_source_redshift.py).

## Supported export contract

This is bounded static extraction from supplied UTF-8 snapshots. It does not
connect to Redshift, execute SQL, invoke AWS CLI, load credentials or import a
database client. Nested repository-relative paths retain exact file hashes and
locators. The shared SQLGlot 30.18.0 parser uses its `redshift` dialect; parser
success is not warehouse validation. Redshift is a managed service; these shapes
refer to the current documented Data API, not a claimed fixed engine release.

| Input | Evidence preserved | Boundary |
| --- | --- | --- |
| `.sql` | Exact SQL, supported DDL columns/types and declared keys, distribution/sort properties, projections, clauses and unresolved reads | No native syntax validation, effective security or observed key integrity |
| Data API `DescribeTable` JSON | `ColumnList` names/types, namespace components, numeric nullable code, defaults and original column metadata | Database is absent from the response; identity starts with an explicit null database component. Array position is not declared ordinal position |
| Data API `ListTables` JSON | `Tables` name/schema/type and original metadata | Database, columns and view definitions are absent; no filename inference |
| Data API `GetStatementResult` JSON | `ColumnMetadata` as result columns, row count, original JSON and typed `Records` validation | No physical columns, catalogue-row conversion or statement identity inferred from SELECT outputs |
| `SVV_COLUMNS` JSON row array | Catalog/schema/table/column identity, ordinal, type, nullability, remarks, defaults and other documented fields | Includes tables and views, local and external; does not establish object kind, view SQL or effective access |

The response schemas are documented in
[`DescribeTable`](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_DescribeTable.html),
[`ListTables`](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_ListTables.html),
[`GetStatementResult`](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_GetStatementResult.html)
and [`ColumnMetadata`](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_ColumnMetadata.html).
Column names/types are required by this bounded extraction subset even though
the API marks individual metadata fields optional; missing values produce gaps.
The API documents `nullable` as an integer without defining its value mapping
on that shape, so the adapter preserves the code without guessing a boolean.
Result [`Field`](https://docs.aws.amazon.com/redshift-data/latest/APIReference/API_Field.html)
values are tagged unions. JSON snapshots must use the documented field names and
types; SDK byte objects are not JSON and must be serialized appropriately upstream.

`SVV_COLUMNS` inputs are row arrays whose keys are the documented lower-case
column names. A row must include complete namespace, column name, type, positive
integer ordinal and `YES`/`NO` nullability. The
[view documentation](https://docs.aws.amazon.com/redshift/latest/dg/r_SVV_COLUMNS.html)
describes metadata visibility and external-table permission differences; absence
from an export is not proof that an object does not exist. AWS currently recommends
SHOW COLUMNS for discovery, and
[driver metadata APIs](https://docs.aws.amazon.com/redshift/latest/mgmt/discovering-metadata-driver-api.html)
for applications. Their export shapes are not silently treated as SVV_COLUMNS.

## Operator acquisition handoff

1. Outside this parser, record the cluster/workgroup, AWS Region, database,
   principal, filters, snapshot time and exporting operation/query. Supply only
   authorized, sanitized metadata; retain request context separately from secrets.
2. Authorize the Data API and database authentication method. AWS documents
   Secrets Manager, temporary credentials and IAM Identity Center in the
   [Data API guide](https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html).
   Temporary credentials require the applicable `redshift-serverless:GetCredentials`,
   `redshift:GetClusterCredentialsWithIAM` or `redshift:GetClusterCredentials`
   permission. API authorization does not establish access to every database object.
3. Enumerate schema/table patterns deliberately, follow each `NextToken`, then
   retrieve the required column descriptions. DescribeTable and ListTables
   responses omit the database request context. Keep different databases/snapshots
   in separate runs until independently bound; the parser does not merge pages
   or resolve two-part names against an assumed database.
4. If supplying query results, retain the statement ID, SQL, database and completion
   receipt outside the response. GetStatementResult retrieves JSON results;
   GetStatementResultV2 CSV chunks are unsupported. The guide states result retention
   is 24 hours, compressed result limit is 500 MB, statement limit is 200 KB and
   calls have operation-specific throttling quotas. Acquire within these limits;
   parser byte/structure limits are separately enforced and much smaller.

Non-empty page tokens, empty inventories, malformed tagged fields, row-count
differences, unknown fields, conflicting identities and unsupported files remain
explicit gaps. Absence of a final token cannot authenticate preceding pages,
principal visibility or request filters. Original valid JSON is retained;
unknown fields also remain in parsed object raw metadata where available.
Duplicate identities are flagged and retained separately, never silently merged.
Every run keeps `export_completeness: not_established`, `native_validation: not_run`
and `execution_performed: false`.

## Reuse and primary research

| Candidate/source | License/authority | Decision |
| --- | --- | --- |
| [SQLGlot](https://github.com/tobymao/sqlglot), [license](https://raw.githubusercontent.com/tobymao/sqlglot/main/LICENSE) | MIT | Reuse the pinned shared parser and preserve notices on redistribution; no copied grammar or new dependency |
| [Amazon Redshift Python driver](https://github.com/aws/amazon-redshift-python-driver), [license](https://raw.githubusercontent.com/aws/amazon-redshift-python-driver/master/LICENSE) | Apache-2.0 | Useful future acquisition candidate; not imported or vendored in an offline parser. Any later redistribution must preserve applicable license/notice obligations |
| [AWS Data API technical article](https://aws.amazon.com/blogs/big-data/using-the-amazon-redshift-data-api-to-interact-with-amazon-redshift-clusters/) | AWS, 2020-09-16, updated 2023-06 | Explains asynchronous query/result acquisition and result metadata. Supports keeping query-output columns separate from table definitions; no sample code copied |
| [Get started with the Data API](https://aws.amazon.com/blogs/big-data/get-started-with-the-amazon-redshift-data-api/) | AWS, 2021-08-31, updated 2023-06 | SDK and batch/parameter examples inform the external acquisition handoff, not automatic execution or export completeness |

## Unsupported behavior and validation

Procedures, functions, dynamic `EXECUTE`, templates and procedural bodies remain
original source with gaps. External DDL, COPY, UNLOAD and library statements remain
uninterpreted; Spectrum/Lake Formation/catalogue permissions and file movement
need separate evidence. Conservative text markers can also flag words in comments
or literals. SQL COMMENT statements remain exact source with a structural gap;
catalogue remarks are extracted when supplied. Grants and policy syntax remain
source evidence with effective security unverified. Unknown security metadata is
retained without converting it into an access-control claim.

Redshift [primary, foreign and unique keys are informational, while NOT NULL is
enforced](https://docs.aws.amazon.com/redshift/latest/dg/t_Defining_constraints.html).
The adapter preserves declared keys without claiming actual uniqueness,
referential integrity or native enforcement validation. Late-binding views,
materialized-view refresh behavior, UDF invocation lineage, SUPER/PartiQL expansion,
row-level security, masking bindings and full column lineage require separate
review. Result contents are never used as physical schema definitions.

Independent synthetic tests cover identifiers, nested paths, namespace omissions,
lossless source evidence, comments/defaults/types, Redshift distribution/keys,
CTE lineage, result/catalogue separation, malformed/duplicate-key JSON, bad tagged
fields, unknown fields, incomplete pagination and the missing optional SQL parser.
Passing tests proves this bounded local extractor, not native compatibility,
deployment, complete security coverage or customer acceptance.
