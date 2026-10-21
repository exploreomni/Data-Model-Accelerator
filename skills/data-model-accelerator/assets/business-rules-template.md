# Business rules intake

Answer in ordinary language. Leave unknown items as **Unknown**. Existing documents
and conversation answers can be reused; the agent prepares structured records.
Do not include credentials or sensitive example rows.

Repeat this block for each definition affecting the selected reports or models:

- Rule name and original wording:
- Reports, metrics, entities or business domain it applies to:
- Business owner and source of the definition:
- Meaning and formula:
- Grain: what does one row represent?
- Included population and exclusions:
- Timezone, reporting window and treatment of the current day:
- Currency and conversion rule:
- Historical changes, cancellations and late-arriving records:
- Security: who may see which records?
- Missing values: when are NULL, zero or unknown different?
- A normal example and its expected answer:
- An edge case and its expected answer:
- Effective date, if known:
- Does this describe today's behavior or an intentional correction?
- Outstanding decision or conflicting definition:

Imported wording starts as **proposed**. Tell the agent which rules you accept,
reject or defer and why. Rule acceptance does not approve a model, establish test
success or authorize deployment.
