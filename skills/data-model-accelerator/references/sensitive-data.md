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

Personal data the user lists or the accelerator identifies must not appear in any gold model, gold implementation file or Omni view/topic. This applies to columns that already exist in the target, and it overrides any instruction to keep existing columns. Keep such columns in staging or integration only where a transformation needs them. Expose a hashed key to a dimension instead. Hiding a field in Omni does not count as removing it.

1. At intake, build the register and record it as the `personal_data` answer:
   ```sh
   python scripts/personal_data.py import-csv --csv inventory.csv --output register.json \
     --attribute CONTACT_EMAIL --attribute NAME_FIRST --attribute NAME_LAST
   python scripts/personal_data.py from-dictionary --dictionary dictionary.json --merge register.json --output register-all.json
   ```
   Use `--attribute` when an inventory lists broader attributes (such as country) than the engagement must exclude; the user decides which attributes count. `from-dictionary` adds columns whose privacy classification includes PII, PCI or PHI.
2. Build gold and Omni without registered columns. A changed register invalidates earlier reviews.
3. `omni_handoff.build_handoff` and `delivery_portal` (status page and package) refuse output when a gold column, an identifier in a gold model's linked implementation file or an Omni field matches the register. Matching is by name: an exact match, or a name ending in `_<entry>` for multi-word entries and unambiguous identifier words (email, phone, iban and similar).
4. A match that is not personal data (for example `n_msgs_from_email`) is recorded in `not_personal_data` as `{identifier, scope, reason, reference}`, with the model ID or file path (or `*`) as scope. This records a false positive. It never keeps real personal data in the output.

Name matching cannot follow a rename the register never sees, and it does not replace warehouse access controls or a privacy review.

