# Maintenance synthetic candidate

Generated five dbt views for snowflake plus one native Omni view/topic. Physical namespaces and types are planned synthetic bindings, not native catalogue observations. Definitions are proposed.

- [dbt project](implementation/dbt/dbt_project.yml) and [setup](implementation/SETUP.md)
- [Omni files](implementation/omni/GENERATION_MANIFEST.json), [static check](omni-generation-check.json)
- [Connected ERD](ERD.svg), [editable source](ERD.mmd), [dictionary](DICTIONARY.md) and [canonical v2 dictionary](dictionary-v2.json)
- [Bronze](BRONZE.md), [silver](SILVER.md), [gold](GOLD.md) documentation
- [Dashboard worklist](DASHBOARD.md), [complete canonical source](looker-canonical.json), [manual target mapping](dashboard-worklist.json)
- [Cautious private AI notes](AI_REVIEW_NOTES.md) and [withheld context](ai-context/AI_CONTEXT.md)
- [Local observations](local-results.json), [dbt documentation preview](dbt-doc-after-helper-fix.json), [static lint summary](lint-summary.json), [lint scope](LINT_SCOPE.md)

Source snapshots remain untouched. Dashboard mapping, physical destination, metadata/privacy review, adapter compilation, native query/access behavior and business acceptance all remain pending. The generator's required approved enum is bound only to [synthetic review](synthetic-review.json), never a human approval.
