# Public-release security and regression review

Checked October 2, 2026. This public snapshot starts from source commit
`762960b9afe2ad60bd75fa739300981837b6aef5`, with the corrections below. The private
repository's Git history, credentials and ignored working files are not imported.

## Results

| Check | Evidence |
| --- | --- |
| Dependency advisories | pip-audit 2.10.1: 77 resolved framework packages and 86 bundled-example packages; no known vulnerabilities after remediation. [Framework](dependency-audit.json), [example](example-dependency-audit.json). |
| Secret scan | Gitleaks 8.30.1 scanned source and nested archives to depth 5. No confirmed secrets. The initial 24 matches were three exact SQL-file checksum values; `.gitleaks.toml` excepts only those exact filename/value assignments. A different value under the same filename was detected. [Final report](gitleaks.json). |
| Python security analysis | Bandit 1.9.4: 65 raw findings, zero high-severity findings, zero scanner errors. Each finding was manually reviewed against the actual code boundary. No blanket rule suppression. [Raw report](bandit.json), [dispositions](bandit-disposition.json). |
| Full regression | 1,118 tests passed, zero skips. [Receipt](regression.json). |
| Dependency-free regression | Python 3.9 without site packages: 1,118 tests, 462 explicitly optional skips, no failures. |
| Public content | All eight source archives inspected; synthetic examples and external-seed provenance retained. See [evidence handling](../PUBLICATION.md) and [third-party notices](../../NOTICE.md). |

The counts for framework and example dependencies overlap and must not be added
as unique packages. Local package resolution was on Python 3.12/macOS; GitHub's
Linux resolution is separately checked by the Security checks workflow.

## Corrections made before publication

- Upgraded `lxml` from 6.0.2 to 6.1.0 for CVE-2026-41066. The advisory service
  returned two records for the same advisory; the recorded issue is one affected
  package. Existing XML paths already set restrictive parser options, but the
  dependency is now on the patched version.
- Fixed a manually reproduced Tableau credential disclosure: connection password
  attributes previously entered generated inventory output. Credential-bearing
  XML is now rejected before schema diagnostics or graph generation. Regression
  tests cover native files, packages, mixed-case fields and nested properties;
  safe lineage and empty credential fields remain supported.
- Removed the Hex schema from redistributed files. Optional setup explicitly
  downloads a checksum-pinned publisher copy, or verifies an offline local copy;
  source analysis never downloads it. The October 2 publisher schema was
  requalified against the Hex and full regression tests.
- Added the selected MIT license, retained third-party licenses, generalized a
  customer-specific plan reference and documented historical local evidence.
- Added public CI dependency and secret checks using pinned actions, a
  checksum-verified Gitleaks binary and read-only repository tokens.

The optional-schema test initially exposed an import-order issue in the
dependency-free lane. The missing-schema check now precedes optional imports;
the complete dependency-free suite and Hex tests were rerun successfully.

## Reproduce

Use the isolated environment and explicit Hex setup described in the root README.
Then run:

```sh
python -m pip check
python -m unittest discover -s tests -q
python -m pip_audit -r requirements-dev.txt --progress-spinner off
gitleaks dir . --config .gitleaks.toml --redact --ignore-gitleaks-allow --max-archive-depth 5
bandit -r skills/data-model-accelerator/scripts -f json -o /absolute/audit/bandit.json
```

Install the scanner versions named above in a separate environment. Bandit
returns a nonzero result for its retained findings; review them against the
recorded dispositions. A new or changed finding requires a fresh review.
Obtain the bundled example's three `requirements-*.txt` files by reading the
curated ZIP and audit their combined dependency set separately.

## Scope of assurance

No additional exploitable defect was confirmed in the reviewed code paths after
the fixes. This is bounded source review, synthetic testing and advisory evidence;
it is not a guarantee of zero vulnerabilities or production certification. Real
warehouse permissions, live-provider behavior, customer data, business acceptance
and operational execution remain separately qualified. Reviewed dbt macros and
SQL are executable code and require an isolated, least-privilege environment.

[Machine-readable summary](summary.json) · [Security policy](../../SECURITY.md)
