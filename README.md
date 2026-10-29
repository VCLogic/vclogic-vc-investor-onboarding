# VCLogic Investor Onboarding

Turn an investor knowledge wiki into a validated, portable bundle for the VCLogic assessment pipeline. For investors on **The Pitch**, collect their historical pitches, extract evidence-linked decisions, and build retrieval over those transcripts and decisions.

```text
vclogic-vc-investment-memory
          │ investor wiki
          ▼
vclogic-vc-investor-onboarding  ◄── The Pitch profiles and transcripts
          │ validated bundle: identity, wiki, historical records, indexes, configs
          ▼
vclogic-vc-agentic-assessment
```

Onboarding generates the investor registration and assessment configurations for you. The assessment engine owns the retrieval formats, validators, and assessment logic. The web application and API live separately in `vclogic-web-application`.

## Choose what to prepare

| Workflow | Wiki retrieval | Historical pitch/decision retrieval | Paid extraction calls |
| --- | --- | --- | --- |
| `prepare` | Yes | No | No |
| `prepare --from-pitch-show` | Yes | Yes, when usable transcripts exist | Yes |
| `prepare --from-pitch-show --collect-only` | Yes | No automatic historical corpus | No |

**Use `--from-pitch-show` if you want the assessment to retrieve the investor's past pitches and decisions.** Human `--review` rows can also create historical records and audited evaluation assets, including in `--collect-only` mode.

## Dependencies on Other VCLogic Repositories

This project directly depends on two repositories in the [VCLogic organization](https://github.com/VCLogic). A third repository provides the web interface that consumes prepared investor assets.

| Repository | Relationship to onboarding | What it provides or consumes |
| --- | --- | --- |
| [vclogic-vc-investment-memory](https://github.com/VCLogic/vclogic-vc-investment-memory) | **Required Python dependency and source-data producer** | Generates the investor wiki supplied to `prepare --wiki`. Onboarding imports its `wiki_build` validator to check the source wiki and its archived snapshot. |
| [vclogic-vc-agentic-assessment](https://github.com/VCLogic/vclogic-vc-agentic-assessment) | **Required Python dependency and bundle consumer** | Provides the `vc_clone_graph` config schemas, validators, historical corpus and pitch-package builders, retrieval indexes, and model/embedding adapters. Onboarding generates assets in these formats; the engine uses them for assessments and rehearsal. |
| [vclogic-web-application](https://github.com/VCLogic/vclogic-web-application) | **Optional downstream application** | Provides the React interface and FastAPI API. It depends on the assessment engine and can discover prepared onboarding bundles or installed investor assets. It is not needed to run this CLI and does not build missing onboarding indexes through the browser. |

### Package and Checkout Dependencies

The required packages are declared in [`pyproject.toml`](pyproject.toml):

| Python package | Required version | Editable checkout path |
| --- | --- | --- |
| `vc-investment-memory` | `>=0.2,<0.3` | `../vclogic-vc-investment-memory` |
| `vclogic-vc-agentic-assessment` | `>=0.1,<0.2` | `../vclogic-vc-agentic-assessment` |

Both sibling checkouts must exist before running `uv sync`, including for wiki-only onboarding. The `embeddings` extra also enables the assessment package's optional embedding dependencies. Because these dependencies are editable, changes in a sibling checkout affect this CLI immediately; use compatible revisions and rerun validation after updating them.

If the required sibling repositories are not yet checked out:

```bash
cd /home/dpasch01
git clone https://github.com/VCLogic/vclogic-vc-investment-memory.git
git clone https://github.com/VCLogic/vclogic-vc-agentic-assessment.git
```

### Data Handoff and Repository Ownership

1. **Investment-memory** produces the wiki. Onboarding reads and snapshots it without modifying the original.
2. **Onboarding** prepares and validates the bundle in this repository. `prepare` does not install it into another project; `install --pipeline-workspace PATH` performs that explicit handoff.
3. **Assessment** runs the investor-specific assessment or rehearsal using the prepared identity, wiki, historical records, indexes, and configs.
4. **Web application**, when used, runs against an assessment workspace and discovers available investor assets. Its [README](https://github.com/VCLogic/vclogic-web-application#readme) documents bundle discovery and workspace configuration.

Source collection and bundle preparation belong here; assessment logic belongs in the assessment repository; browser and API changes belong in the web repository. Credentials and downloaded model caches are configured separately from bundle installation.

## Requirements

- Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).
- A generated, valid investor wiki from the investment-memory project.
- These three repositories checked out as siblings; `pyproject.toml` uses editable local dependencies:

```text
/home/dpasch01/
├── vclogic-vc-investment-memory/
├── vclogic-vc-investor-onboarding/
└── vclogic-vc-agentic-assessment/
```

```bash
cd /home/dpasch01/vclogic-vc-investor-onboarding
uv sync --extra embeddings
uv run investor-onboarding --help
```

The first indexing run downloads the pinned local embedding model. Automatic Pitch Show extraction requires `OPENROUTER_API_KEY` in your environment or this repository's `.env` file:

```dotenv
OPENROUTER_API_KEY=your-key-here
```

`.env` and generated bundles are ignored by Git. Supplying `--from-pitch-show` without `--collect-only` authorizes paid model calls. `--decision-model MODEL` overrides the extraction model from the shipped canonical config; it does not change the assessment models.

## Quick start: Example Investor with historical retrieval

The names below are synthetic placeholders; substitute your local wiki slug, actual Pitch Show profile slug, and transcript speaker alias. Run steps 1–3 from the onboarding repository. Step 4 runs from the assessment repository.

### 1. Prepare the bundle

```bash
uv run --extra embeddings investor-onboarding prepare \
  --wiki ../vclogic-vc-investment-memory/wiki/example-investor \
  --output bundles/example-investor-example-ventures-v2 \
  --from-pitch-show \
  --pitch-show-slug example-investor-example-ventures \
  --alias Example
```

This collects matching episodes, extracts and verifies decisions, builds both retrieval indexes, and writes canonical and rehearsal configs. `prepare` requires a **new output directory**. If this version already exists, check it or choose a new version; preparation never overwrites it.

The three names serve different purposes:

| Name | Meaning |
| --- | --- |
| `example-investor` | Investor ID from the wiki; use it as the assessment's `--vc` value |
| `example-investor-example-ventures` | Investor profile slug on The Pitch |
| `bundles/example-investor-example-ventures-v2` | Your chosen bundle directory; naming it does not change the investor ID |

`--alias Example` binds the transcript speaker `Example` to this investor. For other investors, supply their actual transcript speaker names with repeatable `--alias` flags.

### 2. Check readiness

```bash
uv run investor-onboarding check \
  --bundle bundles/example-investor-example-ventures-v2
```

Before installation for historical assessment, look for:

- `valid: true`: file hashes and engine compatibility checks pass.
- `ready_for_assessment: true`: the required indexes are built and loadable.
- `capabilities.precedents: true`: historical retrieval is enabled.
- `extraction`: counts of historical records and observed machine decisions.

Inspect `pitch_show.complete`, failures, and missing transcripts separately. A bundle can have complete indexes while covering only a subset of the investor's history. A wiki-only bundle can also be assessment-ready with `precedents: false`.

### 3. Install into the assessment workspace

```bash
uv run investor-onboarding install \
  --bundle bundles/example-investor-example-ventures-v2 \
  --pipeline-workspace ../vclogic-vc-agentic-assessment
```

The target workspace must already exist. Installation checks all conflicts before writing, skips identical files, and refuses differing existing files. There is no force-overwrite flag. Resolve version conflicts explicitly before installing a replacement.

### 4. Assess a founder pitch

Replace the pitch path and company name below. This creates a canonical assessment and starts a rehearsal session; it makes paid model calls.

```bash
cd /home/dpasch01/vclogic-vc-agentic-assessment
uv sync --extra embeddings

# Make OPENROUTER_API_KEY available in this shell or this repository's .env.
uv run --extra embeddings vc-clone-rehearsal start \
  --config configs/investors/example-investor/rehearsal.toml \
  --vc example-investor \
  --pitch /absolute/path/to/founder-pitch.txt \
  --company "Your Company Name" \
  --build-canonical-baseline
```

The generated rehearsal config already points to the investor's canonical config. The onboarding `.env` is not installed into the assessment workspace. See the [assessment README](https://github.com/VCLogic/vclogic-vc-agentic-assessment/blob/main/README.md) for the downstream workflow.

## Historical Explanations And Policy Links

New automatic Pitch Show bundles include versioned explanations of the investor’s
original decision: stated reasons, importance, conditions, explicitly tolerated
concerns, insufficient strengths, context, and exact transcript evidence. A separate
model review can reject or downgrade individual interpretations. These remain
machine-reviewed interpretations, separate from human-audited labels.

When the source wiki contains valid investment-memory `policies.json` v1.0, a later
step links verified reasons to policies with applicability checks and uncertainty.
Older wikis still work and report policy linking as unavailable. `check` reports
semantic coverage separately from technical/index readiness. Explanation and policy
review add model calls to automatic preparation, including explanations for supplied
human-reviewed decisions; `--collect-only` still makes no automatic extraction calls.

Existing bundles and assessment indexes remain compatible. Assessment agents need
an explicit downstream integration to consume the new artifacts. See the
[schemas, examples, coverage definitions, and assessment handoff](docs/historical-explanations.md),
including required held-out-company filtering. No prediction-accuracy improvement
has been established.

## Collection and indexing options

| Option | Effect |
| --- | --- |
| `--max-episodes 10` | Retain at most ten matching investor episodes. Unrelated pages and failed requests do not consume the limit, so more than ten pages may be examined. |
| `--pitch-show-cache PATH` | Reuse collected evidence without downloading it again. Automatic extraction still calls the model. |
| `--collect-only` | Skip automatic extraction. Requires `--from-pitch-show`. |
| `--skip-indexes` | Skip embedding generation, **not** extraction. The bundle is marked not ready. |
| `--decision-model MODEL` | Choose an OpenRouter model for extraction and verification. Cannot be combined with `--collect-only`. |
| `--review PATH` | Apply evidence-linked human review rows; these override automatic extraction for their episodes. |

To collect a small sample without model calls or embedding downloads:

```bash
uv run investor-onboarding prepare \
  --wiki ../vclogic-vc-investment-memory/wiki/example-investor \
  --output bundles/example-investor-collected-v1 \
  --from-pitch-show \
  --pitch-show-slug example-investor-example-ventures \
  --max-episodes 2 \
  --collect-only \
  --skip-indexes
```

Then prepare an enriched version from that cache:

```bash
uv run --extra embeddings investor-onboarding prepare \
  --wiki ../vclogic-vc-investment-memory/wiki/example-investor \
  --output bundles/example-investor-sample-ready-v1 \
  --from-pitch-show \
  --pitch-show-slug example-investor-example-ventures \
  --pitch-show-cache bundles/example-investor-collected-v1/source/pitch-show \
  --alias Example
```

A two-episode cache remains a two-episode sample; using a cache does not expand collection coverage. Supported caches include this tool's `source/pitch-show` directory and the original scraper's `data` directory containing `investors/` and `episodes/`.

To finish indexes for any bundle prepared with `--skip-indexes`:

```bash
uv run --extra embeddings investor-onboarding index --bundle /path/to/bundle
```

`index` builds indexes for the assets already in the bundle. It does not collect episodes or extract decisions. To add historical retrieval to an existing wiki-only bundle, run `prepare --from-pitch-show` into a new directory.

For wiki-only onboarding, omit the Pitch Show options from `prepare`. Optional identity overrides are `--slug`, `--display-name`, `--firm`, `--role`, and repeatable `--alias`. The importer does not infer current employment from historical mentions.

## How historical decisions are handled

Collection records profile-reported investments separately from transcript decisions. **Absence from an investment list never means Out.**

Automatic extraction reads each usable transcript and proposes a pitch-window decision. A separate model pass verifies the proposal. Local checks bind the evidence to the exact investor speaker, transcript turn, quote, and any condition. Accepted decisions become machine In/Out records; ambiguous or unsupported decisions remain unobserved. Timing and decision meaning rely on model judgment and are not human-audited facts.

Unobserved transcripts remain searchable. Missing transcripts are reported and excluded from the historical corpus. Transcripts above 180,000 characters remain searchable with an unobserved decision; they are not silently truncated. API failures abort preparation instead of publishing a successful extraction result.

Machine extraction produces historical retrieval assets, **not evaluation ground truth**. It does not generate audited evaluation labels or historical evaluation pitch packages. Structured portfolio memory and trained classifiers are also not generated; their unsupported paths remain disabled in the generated configs. Portfolio prose remains available through wiki retrieval.

### Add human-reviewed evaluation data

Copy `source/pitch-show/review-template.json` outside the bundle and review the transcript. Supply a nonempty JSON list using actual episode identifiers and exact evidence:

```json
[
  {
    "episode_slug": "1-example",
    "final_decision": "Out",
    "pitch_window_decision": "Out",
    "initial_response": "Out",
    "decision_context": "initial_panel",
    "label_basis": "explicit investor statement",
    "audit_notes": "Checked the speaker and decision timing against the transcript.",
    "evidence_contains": "I am out because the market is too small."
  }
]
```

Add `--review /absolute/path/to/review.json` when preparing a new Pitch Show bundle. Reviewed rows override machine extraction for their episodes; other episodes still receive automatic extraction. Combine `--collect-only --review ...` to use only human-reviewed decisions without automatic model extraction.

The assessment engine compiles reviewed rows into an audited ledger, historical precedents, and eligible pitch packages with decision evidence removed from the assessment input. Missing or ambiguous review evidence fails validation.

## Bundle contents and provenance

| Path | Contents |
| --- | --- |
| `bundle.json` | File hashes, capabilities, readiness, collection and extraction summaries |
| `inputs/investors/<slug>.toml` | Investor registration and speaker aliases |
| `inputs/wiki/<slug>/` | Curated wiki for retrieval |
| `configs/investors/<slug>/` | Generated canonical and rehearsal configs |
| `inputs/indexes/` | Wiki and, when available, historical semantic indexes |
| `inputs/data/investors/<slug>/` | Historical corpus, machine decisions, and any human-reviewed pitch packages |
| `source/wiki/` | Original validated wiki snapshot |
| `source/pitch-show/` | Downloaded evidence, profile-reported decisions, receipts and review template |
| `source/pitch-show/extraction/` | Model identity, prompts, responses, usage, source hashes and abstention reasons |
| `evaluation/labels/<slug>.json` | Human-reviewed labels only, when supplied |

Installation archives source evidence under `onboarding/<slug>/source/` in the target workspace. Source locators beginning with `source/` resolve there after installation. Machine decision ledgers stay under `inputs/data/investors/<slug>/`.

The source wiki is validated by investment-memory; generated configs, corpora, packages and indexes are validated by the assessment engine. Pinned config and taxonomy resource hashes are recorded in [`resources/provenance.json`](src/vclogic_onboarding/resources/provenance.json). Live downloads respect standard HTTP proxy and certificate environment settings.

## Development and validation

```bash
uv sync --extra dev
uv run --extra dev pytest -q
uv build
```

The test suite uses offline HTTP responses, model doubles and deterministic embedding doubles. It does not require credentials, paid inference or model downloads.

Investor-specific live validation notes are kept locally outside version control.

## Repository Data Policy

This repository publishes pipeline code, generic taxonomy definitions, schemas,
and synthetic examples only. Keep investor wikis, policies, profiles, transcripts,
decisions, indexes, bundles, model receipts, credentials, and live validation reports
in ignored local directories. Never force-add them. Quick-start investor names are
placeholders, not real profiles. Tests and documentation fixtures must be synthetic.

`.gitignore` does not remove files already committed or erase older Git history.
Review the staged diff before publishing; historical data removal requires a
separate history cleanup.
