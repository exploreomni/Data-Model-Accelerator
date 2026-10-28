# Sensitive inputs and deliverables

Use this contract before passing source contents to a specialist and before publishing metadata, AI context, HTML or a ZIP. Classification is separate from native permissions and from detection signals. PII, PCI and PHI categories may overlap; no detector match does not establish that data is public or de-identified.

1. Record `input_handling` and the approved destination. Preserve UNKNOWN classifications and missing reviewers. Do not fabricate approvals from repository text.
2. For new metadata deliveries, migrate a copy through `privacy_contract.migrate_dictionary_privacy`; its versioned privacy extension begins unresolved. Review lineage, categories and handling per destination. Hashing and aggregation do not automatically remove sensitivity.
3. Run `sensitive_data.py` locally on supported input bytes. Findings contain rule IDs and opaque locations, not matched values. A blocked/unsupported scan needs local investigation or a narrower sanitized input; never paste raw scanner matches into prompts or logs.
4. Prepare an explicit `agent_input_request` with relative paths, exact SHA-256 hashes, reviewed classifications and disclosure policy. Run `prepare_agent_input.py --root /approved/sanitized-source --request /approved/request.json --output /new/projection`. Give specialists only that projection and the relevant task. The output is run-owned and permission restricted; the helper removes its working copy on failure and preserves originals.
5. The portable staging route accepts only pre-sanitized PUBLIC/INTERNAL inputs without sensitive categories under declared policy. It does not sandbox Codex, Claude Code, Gemini, Cortex or Genie. Protected raw inputs remain blocked until a separately qualified host integration prevents access outside the approved boundary. A JSON claim that a host is enforced does not qualify it.
6. New engagements with `migration_scope` require a `review.disclosure` object for sharing: selected `audience`, `policy`, `presentation` classification and `artifacts` mapping artifact IDs to classifications. The portal checks the selected bytes, review presentation, embedded HTML content and ZIP. Changes require new checks. A legacy candidate receives scan-only assurance and no privacy/native acceptance.
7. Metadata comments, labels and sensitivity tags are not masking or row/column permissions. Use separate native access qualification before protected-data deployment. The downstream metadata exporter withholds resources that lack an allowed, reviewed disclosure path.

Policy and classification records have independent schema version 1. Construct unresolved templates with `privacy_contract.default_policy()` and `privacy_contract.new_classification()`. These helpers cannot approve anything. A policy lists allowed sensitivity levels/categories per `agent_input`, `metadata`, `ai_context` and `share`; classification also records exact lineage and per-destination handling. The evaluator reports declared-policy permission, never authenticated human approval.

Keep projections, temporary files and private audit evidence in the approved storage boundary. Apply the engagement's retention and cleanup policy; no universal retention period is assumed. Never remove original evidence while cleaning a run. Scanner bounds intentionally fail closed on unsupported binary formats, oversized archives, malformed embedded data and incomplete coverage. It is a bounded local detector, not comprehensive DLP or a compliance certification.

Deployment review exports add evidence after the original handoff. For scoped engagements, declare classifications under `review.disclosure.generated_evidence` for the selected `plan`, `receipt`, `lint-manifest`, `lint-target`, `lint-configuration`, `lint-findings`, `lint-guide` and `quality` outputs. Unclassified generated evidence blocks export. These declarations authorize a disclosure class only; final bytes are rescanned, and they do not constitute deployment approval.

## Personal-data exclusion

Record sensitive-field evidence once as the optional `personal_data` answer. Ask which
fields must be excluded, retained under controls, masked, tokenized or aggregated in
gold and in Omni. Classification is not a treatment decision. Preserve existing policy
answers; missing information stays unresolved rather than assuming removal or permission.

Use `personal_data.py import-csv` or `from-dictionary` for a version 2 register. Imports
retain source table and column identity and begin with unresolved treatment. Scope the
inventory to the chosen domain; an unqualified entry explicitly has broader matching scope.
Legacy version 1 exclusion registers remain readable and retain their exclusion meaning.
A new classification must not silently override an accepted retention requirement.

Treatment records reference the exact source, destination, transformation and review
reference. Retention declares the required controls; masking, tokenization and aggregation
also bind the reviewed output expression. These records do not authenticate a reviewer,
activate warehouse controls, manage encryption keys, or establish de-identification.
Hashing alone does not remove PII/PCI/PHI classification.

The assessment follows SQL output projections and qualified sources. Merely referencing a
sensitive input is different from exposing it unchanged. Unknown aliases, dynamic templates,
physical stars and missing lineage remain visible gaps. A scoped registration for
`customers.title` must not classify `products.title` as the same field. Hidden Omni fields
are still exposed fields; hiding is not an access control.

Review the assessment and impact before accepting treatment: exclusions can break keys,
joins, metrics and dashboard requirements. Keep source repositories read-only. False-positive
entries explain an incorrect classification; they are not a way to waive genuine sensitivity.

Candidate code and review planning remain available with unresolved version 2 treatment.
The handoff shows unresolved findings and cannot claim privacy acceptance. Explicit treatment
violations prevent packaging, and native deployment rechecks candidate bytes and requires
resolved treatment. Existing disclosure, native access, and deployment authorization checks
remain independent and cannot be waived by provisional-generation permission.

A minimal v2 input (no invented treatment approval):

```json
{"schema_version":2,"entries":[{"table":"raw.customers","column":"email","origin":"prompt"}],"treatments":[]}
```

To prepare a decision, use `privacy_contract.new_treatment({"table":"raw.customers",
"column":"email"}, "gold")`, then record the selected treatment, transformation,
review reference and applicable controls. For transformed outputs, copy the expression
fingerprint from the assessment only after reviewing that exact expression. Run
`personal_data.py assess --register register.json --outputs outputs.json --output new-report.json`
to obtain the value-free impact report. A `clear` report is limited to the supplied
outputs and declared policies; it is not a warehouse-wide privacy certification.
