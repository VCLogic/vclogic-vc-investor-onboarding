# Investor onboarding CLI

The automatic precedent extension in [2026-09-23-automatic-precedents.md](2026-09-23-automatic-precedents.md) supersedes the original human-review-only retrieval restriction below. Machine extraction remains separate from audited evaluation labels.

## Approved scope
The user requested a separate sibling repository and CLI that turns investment-memory wikis into assessment-pipeline inputs, with a `--from-pitch-show` flag to download the investor's pitches and decision evidence.

## Design
Use a versioned bundle between source wiki and assessment workspace. This makes the result inspectable and portable before installation. Direct mutation of the source wiki is excluded; embedding the importer inside either existing project would violate the requested separate repository boundary.

`investor-onboarding prepare --wiki PATH --output PATH [--from-pitch-show --pitch-show-slug SLUG]` copies a curated, validated wiki snapshot, writes investor TOML, copies the common assessment taxonomy, and generates a canonical and a grounded rehearsal config. Identity comes from the wiki manifest and prepared identity, with CLI overrides for display metadata. Default preparation builds local semantic indexes; `--skip-indexes` prepares an explicitly not-ready bundle without embedding downloads. `index` completes that bundle. `check` verifies hashes and package/config compatibility. `install --bundle PATH --pipeline-workspace PATH` installs only this investor's assets after checking for conflicts, with rollback on failure.

Pitch Show enrichment archives source pages, discovers episodes from the site sitemap and profile investment links, and saves episode/transcript data and reported investment outcomes. Missing investments are unknown, never inferred Out. Download failures and missing transcripts are reported, not silently claimed complete. `--pitch-show-cache` makes existing collected data reusable offline. `--review PATH` accepts evidence-linked pitch-window review rows in the assessment engine's format; only reviewed observed rows generate evaluation pitch packages and decision labels. Precedents are generated from reviewed transcript data. Without reviewed data the bundle remains wiki-only and clearly reports pending enrichment.

Structured portfolio memory and learned classifiers are not fabricated from prose. They remain disabled/fallback until compatible data exists. Preserve portfolio prose as wiki evidence. Generated canonical/rehearsal configs agree about available capabilities.

Use the assessment package's builders/validators/index formats as a dependency, not copies of its engine. Ship config templates and taxonomy as versioned package resources copied from the engine with provenance. Source hashes and generated-file hashes make bundles reproducible and checkable; reject unsafe paths, symlinks, stale wiki validation, and target conflicts. No model-generation calls are required.

## Validation
Unit tests cover wiki validation and import boundaries, config capability matching, cache/HTTP Pitch Show collection, unknown decisions, reviewed dataset generation, bundle tampering, and install conflict/rollback. Integration tests use the actual assessment validators and deterministic embedding doubles. Local private wiki validation is kept outside version control. Package/CLI build and isolated wheel import are checked.
