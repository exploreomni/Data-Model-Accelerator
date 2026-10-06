# Scopes and inherited models

Identify connection, model, schema/shared/workbook layer, branch, parent and environment before designing changes. Keep authored files separate from resolved effective state. Never write a combined snapshot as authored overrides. Preserve inherited defaults, source identifiers, unrelated settings and server-owned properties. Omission is not deletion.

Current implementation supports a bounded physical/inherited subset; a full layer-aware inventory and round trip are later work. Constants, routing, calendars, SQL preambles and extension behavior need individual contracts. Shared extensions can override security; full extension Git support is described as work in progress. Review policy changes explicitly.

Sources: [layers](https://docs.omni.co/modeling), [model settings](https://docs.omni.co/modeling/models), [extensions](https://docs.omni.co/guides/deployment/scaled-deployments-shared-model-extensions). Release labels and reviewed dates live in the manifest.
