# Investor Onboarding Implementation Plan

**Goal:** Deliver the approved standalone import CLI in `/home/dpasch01/vclogic-vc-investor-onboarding`.
**Architecture:** The importer builds versioned bundles; the Pitch Show collector is independent; the assessment engine owns schemas, indexing, and leakage validation.
**Tech stack:** Python 3.11+, argparse, httpx, BeautifulSoup, pytest, existing assessment package.

- [x] Write failing tests for `bundle.prepare`, `check_bundle`, and `install_bundle` with synthetic wiki input and engine validators.
- [x] Implement curated wiki import, version/hash receipts, investor registry, and compatible config templates in `src/vclogic_onboarding/bundle.py` and `resources/`.
- [x] Worker: implement `pitch_show.collect` and cache reader plus tests, with source receipts and explicit unknown outcomes.
- [x] Implement reviewed Pitch Show dataset enrichment through assessment builders in `dataset.py`.
- [x] Add local semantic index completion and CLI subcommands in `cli.py`, package metadata, and documentation.
- [x] Run offline tests, prepare/check an actual generated wiki, check install in a temporary workspace, and build a wheel.
- [x] Perform independent spec/code review, fix findings, and commit the verified project locally.

## Verification

- 31 offline tests pass, including real source validation, engine configuration schemas, reviewed pitch conversion, index completion/failure preservation, and conflict-safe installation.
- Wheel and source distribution build successfully.
- Independent read-only review found no major issues and confirmed reviewed dataset indexes load after relocation. Its minor ledger source-locator finding was fixed and regression-tested.
- Real embedding model downloads and a live full-site Pitch Show crawl were not run. Collection tests use recorded-shaped offline responses and embedding tests use deterministic doubles.
