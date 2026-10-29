# Maintain the learning guide

The six numbered Markdown lessons are the editable source of truth. The PDF reads those files directly; do not edit its text separately. Keep the course a static reading guide. This directory does not add an agent, runtime stage, installer or telemetry.

## Rebuild

From this directory, use an isolated maintainer environment (Python 3.12 recommended):

```sh
python3 -m venv /absolute/path/to/training-build-env
/absolute/path/to/training-build-env/bin/python -m pip install -r requirements-build.txt
/absolute/path/to/training-build-env/bin/python build_guide.py
/absolute/path/to/training-build-env/bin/python build_guide.py --check
```

The helper draws `assets/workflow.png` and `assets/review-route.png`, retains the reviewed `assets/billing-pipeline.png` as an input, and writes `data-model-accelerator-guide.pdf`. It embeds local fonts and preserves links, selectable lesson text and bookmarks. It makes no network requests and runs no accelerator code. `--check` rebuilds in memory and fails if the rebuilt outputs differ. Any change to the Billing illustration also requires rebuilding and reviewing the PDF.

The deliberately small Markdown renderer supports headings, paragraphs, lists, inline links/emphasis/code, tables, blockquotes, fenced text and the three registered illustrations. Keep unsupported HTML and nested structures out of the six lessons. The separate optional practice page uses GitHub details elements and is not included in the PDF. A font/license or compiler change requires a rebuild and visual review.

## Verify before updating the draft

1. Check every local file link and lesson navigation. Confirm example claims against the maintained fixture, including the current invoice grain and the two active-customer meanings.
2. Open the official host documentation before changing installation paths. Record the date and distinguish documented discovery from actual host execution. Preserve full skill folders and explicit environment qualification.
3. Run the builder and `--check` with the pinned build dependencies. Render and inspect **every PDF page** at reading size: headings, tables, diagrams, code, page breaks, footers and links. Confirm fonts are embedded and text can be selected.
4. Ask a new reader to find a first-domain choice, a warehouse file, an Omni file, an unresolved definition, installation guidance and the kickoff prompt. Correct ambiguous instructions rather than adding another guide.
5. Keep the SE/AE draft-review label until explicit approval for customer use. Passing documentation checks is not that approval.

PDF references to maintained examples use workflow revision `fcec34fb8e83bf7b663ab5ed0e1e945224dd03fd`. Update `REVISION` in the builder when requalifying against a newer baseline. Companion training links use the review branch while this work is a draft; change that branch reference to `main` when publishing the approved guide. Do not claim live or native-host testing from source inspection.

## Assets and provenance

- The workflow and review-route PNGs are original teaching illustrations drawn by `build_guide.py`. The Billing illustration was revised with the built-in image-generation tool on October 28, 2026, using the prior diagram as its reference. Its brief was to preserve source/preparation lineage, show `FCT_INVOICES` and `DIM_CUSTOMERS` binding to their separate Omni views, and join both in `billing.topic`. The invoice-date history lookup is retained; the actual topic’s additional customer-month join is explicitly omitted for clarity. The revised labels and edges were checked against the maintained synthetic SQL, views, topic and relationships. These are teaching illustrations, not UI screenshots or evidence of native validation. The Billing raster approximates the brand typography; the PDF lesson text embeds the licensed fonts below.
- Reviewed Billing image SHA-256: `1d14e27854905730d03dff0493c1e46c72c355173babe32e4d02209b91d62c49`. Rebuilds reuse its checked-in bytes; they do not call an image service. Its text can be corrected through an explicitly reviewed asset revision, followed by PDF visual QA.
- `commerce-export.svg` is the unchanged output of the maintained synthetic commerce review demo at workflow revision `fcec34f`. It retains its own product styling. It supports optional practice, not the Billing example.
- `omni-wordmark.png` is the supplied Rich Black raster wordmark, used unchanged on Warm White/Omni Pink. Its native dimensions are 539 × 223; the PDF places it at 106 points wide. The corporate artifact guidance permits this fallback. Complete original vector-export provenance was not supplied. Do not redraw, recolor, upscale or imply new trademark rights or formal Brand approval.
- The four locally embedded fonts are Cal Sans 400, IBM Plex Sans 400/500 and IBM Plex Mono 500. Their SIL Open Font License notices, conversion hashes and source provenance are in [assets/fonts](assets/fonts/). They are build assets; the helper does not install system fonts. See [the repository notice](../../NOTICE.md) for license boundaries.

The October 28, 2026 authoring review checked official installation documentation and rendered the PDF. Local-file browser access was unavailable; no interactive screenshot or native assistant installation is claimed. Use the optional practice actions to qualify review-page behavior in the learner's own environment.
