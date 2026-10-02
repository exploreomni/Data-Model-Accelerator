# Trial-driven engineering and handoff improvements

## Evidence and scope

The guided, context-assisted and missing-SME exercises exposed reusable gaps:
CSV-only inputs were not classified; completed handoffs retained preparation
prompts; native Omni filenames and portable links needed export handling; dense
relationships needed clearer roles; lazy views concealed unqueried cast errors.
The comparison also showed that matching model structure is not a business
accuracy score. Keep all trial data, ZIPs and machine-specific evidence outside
this repository. Preserve the existing guided-delivery changes in plan 10.

## Implementation sequence and ownership

1. **Raw discovery specialist:** add bounded, metadata-only CSV recognition and
   tests. Keep dbt seed ownership, source immutability and explicit coverage gaps.
   Do not imply warehouse types or invent an existing dbt project.
2. **Delivery specialist:** support explicitly registered native Omni files,
   validate portable Markdown dependencies, improve relationship diagrams, and
   bind exports to the current context. Test selection, integrity and geometry.
3. **Workflow integrator:** record a selected handoff only after validating the
   review contract and actual artifact bytes. Invalidate it on input, selection,
   review or file drift. Advance the next action without claiming native tests,
   business correctness, human approval or deployment.
4. **Engineering guidance:** document a provisional raw-only/missing-SME route,
   separate retained data from published fields, require explicit projection
   checks, and report comparison denominators. Preserve the existing eight-gate
   refactor qualification; do not manufacture missing prerequisites to pass it.
5. **Integration and release:** run focused adversarial checks, the complete
   regression suite, the synthetic guided demo, skill validation and a fresh
   independent review. Review the staged diff for generated/private artifacts;
   update against main and publish a PR. Merging and deployment are separate.

## Acceptance

- A seed directory is discoverable without opening non-CSV source context;
  malformed/truncated input remains a coverage gap.
- The engineer can retain known interview answers and export only requested
  formats through the offline guide, including native Omni model text.
- Completed handoff state has verifiable file integrity, survives a clean resume
  and becomes stale when bound inputs or selected files change.
- Generated documentation distinguishes observed structure, proposed business
  meaning, local execution, native execution and human approval.
- Regressions and release evidence describe the actual scope tested. Existing
  fixture results are never reused as customer acceptance evidence.
