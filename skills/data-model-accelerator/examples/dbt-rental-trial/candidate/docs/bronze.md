# Bronze: immutable synthetic CDC seeds

Authority: `SYNTHETIC-RENTAL-DECISION-001`, fabricated for this trial. The source catalogue is supplied input, not live warehouse discovery. The three CSV files and source README are copied byte-for-byte from `../input/repo/`; the original files remain unchanged. All data is USD and UTC at or before `2026-08-16T00:00:00Z`.

| Seed binding | Entity key | Source grain | Logical relationship |
|---|---|---|---|
| `ref('raw_rentals')` | tenant_id + rental_id | Replicated rental CDC event | tenant_id + location_id to raw_locations |
| `ref('raw_charges')` | tenant_id + charge_id | Replicated charge CDC event | tenant_id + rental_id to raw_rentals |
| `ref('raw_locations')` | tenant_id + location_id | Replicated location CDC event | No parent |

The catalogue's `synthetic.raw` labels describe fabricated provenance. Execution binds dbt seeds through `ref`, using the isolated host's configured database and `main` schema. They are not hard-coded warehouse source names.

Entity keys are non-null but not unique in bronze: multiple versions and exact replay duplicates are legitimate. `cdc_sequence` is BIGINT, `is_deleted` BOOLEAN, `amount` DECIMAL(18,2), and every other column VARCHAR. Timestamps are canonical sortable UTC text; dates are UTC text, not session-timezone timestamps. All columns are non-null under the fixture contract. See [the dictionary](data-dictionary.md) for every column and its lineage.

Bronze preserves source statuses, obsolete labels, tombstones and unsigned refund magnitudes. No report filter, authorization predicate or business eligibility rule belongs here. A charge can reference a rental whose latest version is deleted. Source guarantees nonnegative amounts, supported categories, same-tenant currency equality and live locations for live rentals.

Staging consumes complete source history, ordering each composite entity key by `cdc_sequence DESC, updated_at DESC`; it chooses the latest version before removing a tombstone. Exact tied replicas have equivalent payloads. Conflicting payloads at the same sequence/timestamp are outside this fixture and require investigation rather than an invented tie-break rule.

Recovery is a full rebuild: restore source CSV bytes from `../input/repo/seeds/`, verify their SHA-256 against `../input/catalogue.json`, reseed, and rebuild downstream tables. No incremental state, production retention policy, ingestion SLA or credential setup is supplied. No raw file or source README is edited. The catalogue-verified source history is the recovery basis; gold cannot reconstruct discarded versions.
