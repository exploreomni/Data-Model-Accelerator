# Public evidence handling

The public snapshot retains the authored synthetic fixtures and their recorded qualification artifacts. They document specific local exercises, including unsuccessful iterations; they do not establish production deployment, customer acceptance, or independent authentication of the original execution.

The publication review opened all eight tracked ZIP, Tableau-package and compressed TAR files in the source snapshot. The two Tableau packages contain authored synthetic workbook/data-source/adjustment fixtures. The rental, retail and native-build archives contain local synthetic execution outputs. The source-only delivery contains generated documentation/code and source metadata; it does not bundle raw seed rows or a working database.

Some historical JSON receipts, specialist prompts, error traces and archive members retain the original developer's absolute filesystem paths. Those paths describe where an exercise ran, are not credentials, and are not installation instructions. In particular, `candidate-delivery.zip` retains the original dbt verification receipt. Its HTML includes packaged artifact previews. Preserve its recorded bytes and manifest hashes when checking integrity; rewriting a path in a frozen record would invalidate the recorded association. No historical receipt or successful-check count has been rewritten to suggest a new run.

A customer-specific preference in an implementation plan was generalized for the public copy. Source manifests, scoped synthetic data, public vendor references and third-party attribution remain explicit. The original private repository and its Git history are separate from this new public snapshot.

To reproduce, create a fresh output directory using the documented runner for that fixture and retain the new evidence with its actual runtime and target. New public checks should use neutral workspace paths and separately identify any unavailable optional engines or native-provider acceptance. The release's security report describes the tools, scope and results of the publication checks; historical validation results are not security guarantees.
