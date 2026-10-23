# Synthetic native topic tree

The sales topic joins orders to two aliases of customers. Only the buyer path
continues to regions. The aliases keep distinct occurrence IDs while sharing the
explicit reviewed gold.customers dependency. All data and labels are synthetic.

From the repository root, use an existing environment with the pinned YAML/SQL
dependencies:

```sh
PYTHONPATH=skills/data-model-accelerator/scripts python - <<'PY'
import json
from pathlib import Path
from omni_topic_trees import build_topic_trees
p = Path('skills/data-model-accelerator/examples/omni-topic-trees')
files = {f.name: f.read_text() for f in sorted((p / 'model').iterdir())}
context = json.loads((p / 'model-context.json').read_text())
review = json.loads((p / 'review-bindings.json').read_text())
result = build_topic_trees(files, context, review['omni_warehouse_bindings'], review['models'])
assert result['coverage']['status'] == 'complete'
assert result['topics'][0]['binding_status'] == 'complete'
assert len(result['topics'][0]['nodes']) == 4
assert result['native_status'] == 'pending'
print(json.dumps(result, sort_keys=True, indent=2))
PY
```

Remove the regions warehouse binding to expose the unresolved delivery coverage
without deleting its node or changing the topic's structural result. Change an
alias's table_name to expose the source-override binding boundary. These local
observations do not prove native behavior or business acceptance.
