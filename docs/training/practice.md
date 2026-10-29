# Practice: review a small commerce model

[← Learning guide](README.md)

**Your job:** decide whether a proposed model is understandable, identify an unanswered question, and return useful feedback. You do not need to read SQL.

This lesson uses the repository's maintained **synthetic commerce review demo**. It contains three event tables and two reused descriptive tables. It demonstrates review and packaging; it does not query Snowflake or validate customer data. Only the gold layer is in scope. Prepared inputs are simulated prerequisites, so this is not a complete raw-to-gold pipeline example and it contains no Omni topics.

## Try it here, with no setup

These are the five tables and their declared purposes in the demo:

| Table | What one row represents | Proposed action |
| --- | --- | --- |
| `GOLD.DIM_CUSTOMER` | One customer | Reuse |
| `GOLD.DIM_PRODUCT` | One product | Reuse |
| `GOLD.FACT_SALES` | One sale record | Create |
| `GOLD.FACT_RETURNS` | One return record | Create |
| `GOLD.FACT_PAYMENTS` | One product-attributed payment record | Create |

[Open the actual exported ERD](assets/commerce-export.svg) to inspect all five tables and their declared joins. This is a synthetic product export, not a screenshot or a brand-redrawn diagram.

In `GOLD.FACT_SALES`, the demo declares `sales_id` as the primary key, `customer_id` and `product_id` as foreign keys, and `amount` as a recorded amount in the source currency. Currency alignment and netting remain unresolved. Those labels describe the candidate; they do not prove the actual data obeys them.

### Exercise 1 — explain a table

Describe `FACT_SALES` to a colleague in one sentence. Can you also explain what `amount` means well enough to call it “net revenue”?

<details>
<summary>Compare your answer</summary>

“The proposal contains one row per sale record, with references to customer and product.” You cannot yet call the amount net revenue: the demo does not establish currency alignment, taxes, refunds or netting. Ask the business owner for the intended definition and a trusted comparison result.

</details>

### Exercise 2 — catch a risky assumption

Someone suggests adding sales amounts and payment amounts together to report total revenue. What should you do?

<details>
<summary>Compare your answer</summary>

Flag it for review. Sales and payments represent different events and could count the same commercial activity twice. The supplied design explicitly says not to sum them together. Product attribution for payments also needs confirmation. A shared customer key does not make two measures safe to add.

</details>

### Exercise 3 — return a useful correction

Write feedback that names the table, identifies the uncertainty and asks for the evidence needed to resolve it.

<details>
<summary>Example feedback</summary>

“For `GOLD.FACT_SALES`, clarify whether `amount` includes tax, how refunds are treated, and which currency it uses. Keep a net-revenue measure provisional until our business owner confirms the definition and our engineer compares it with an approved baseline. Show which warehouse and semantic outputs would change.”

</details>

### Exercise 4 — choose what you can approve

The package integrity check passed, and all five tables appear in the exported ERD. Is this sufficient to authorize production deployment?

<details>
<summary>Compare your answer</summary>

No. It establishes package integrity and declared diagram coverage. The demo has not verified physical Snowflake columns, executed its dbt models, reconciled real results, tested access or obtained business approval. You can finish the learning exercise without declaring the model production-ready.

</details>

## Try the actual offline review page

If you already have a configured coding assistant with this repository, paste:

```text
Use this checkout's maintained run_model_review_demo.py to create its synthetic
commerce review package in a new local output folder outside the repository.
Check package integrity and the page's JavaScript when Node is available.
Give me the exact ZIP and extracted START_HERE.html paths so I can open them.
Keep this a training exercise: do not connect to a warehouse, deploy anything,
invent extra models, or treat the sample as an end-to-end migration.
Tell me which checks you performed and which were unavailable.
```

If you do not have that setup, send this request to your engineer or ask them to share the generated synthetic ZIP. **You only need the extracted package and a browser to review it.**

1. Open the extracted `START_HERE.html`. In **Data model**, find all five tables. This demo uses the classic ERD layout; normal simple deliveries lead with a gold-table pipeline picker.
2. Select `GOLD.FACT_SALES` in the table inspector. Find its grain, key labels, column descriptions and linked implementation file. Compare its declared meaning with Exercise 1.
3. Open **Code & files**. Find `dbt_project.yml` (project setup), `fact_sales.sql` (one model's code), `sources.yml` (input definitions), `properties.yml` (model descriptions and test declarations), and `IMPLEMENTATION.md` (engineering instructions). Finding the files is the task; running or understanding the code is not required.
4. Open **Validation**. Find the pending physical-input check. Explain why it remains pending even though the ZIP passed its integrity check.
5. Open **Prepare review feedback**. Select the sales table, enter your question and choose **Download feedback**. Return the downloaded file to the agent in the same engagement, or to the person who sent you the ZIP. The page does not submit it automatically.

**Expected outcome:** you can locate a table, explain its meaning, find the selected files, identify a missing check and return a correction. You have practiced reviewing a candidate; you have not approved or deployed a warehouse.

If your environment blocks opening the HTML, use the files directly: `01_Model/design.md`, `01_Model/Dictionary/data-dictionary.md`, `01_Model/ERD/model-001.svg`, `02_Implementation/dbt/IMPLEMENTATION.md` and `03_Validation/remaining-checks.md`. Return your feedback in chat.

<details>
<summary>For the engineer: reproduce the practice package</summary>

From the accelerator repository root, use the maintained Python 3.12 environment. Replace the example output path with a **new** folder outside the checkout:

```sh
python3 skills/data-model-accelerator/scripts/run_model_review_demo.py \
  --output /absolute/new-training-demo
python3 skills/data-model-accelerator/scripts/delivery_portal.py verify \
  /absolute/new-training-demo/commerce-model-review.zip
python3 skills/data-model-accelerator/scripts/delivery_portal.py check-page \
  /absolute/new-training-demo/commerce-model-review.zip --javascript
```

The last command requires Node. Report missing tooling as an unperformed check. Open `handoff/START_HERE.html`, or share `commerce-model-review.zip`. Do not share `technical-evidence/` as an additional learner deliverable. These checks do not visually test the page in a browser.

The [demo source](../../skills/data-model-accelerator/scripts/run_model_review_demo.py) owns the sample definitions. Its `fact_` names are fixture names, not a naming recommendation. Real projects retain their explicitly selected naming policy.

</details>

<details>
<summary>About the visuals in this lesson</summary>

`commerce-export.svg` is the unmodified ERD produced by the maintained demo at revision `fcec34f`. The lesson was checked against the generated package and source definitions. Local-file browser access was blocked during authoring, so these are not UI screenshots and interactive browser behavior was not visually verified. Repeat the five page actions above when qualifying your team's environment.

</details>

## Take it into your own work

Return to [Launch your migration](06-launch.md) with the full migration scope, approved inputs and review responsibilities. Select a complete domain for the first implementation wave. Keep the same review habits: **find the evidence, ask about ambiguity, and distinguish a candidate from a verified outcome**.
