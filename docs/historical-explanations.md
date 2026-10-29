# Historical Decision Explanations And Policy Links

New automatic `prepare --from-pitch-show` runs produce additive explanation and
policy-link artifacts. Existing bundles remain valid. This change does not migrate
existing bundles or install them. It does not change the assessment engine's strict
historical records, embeddings, audited labels, or configuration schemas.

## Processing And Verification

1. Extract and verify the original In/Out/Unobserved decision using the existing
   rules. Human review rows still take precedence over machine decision labels.
2. For each observed decision with a usable transcript, extract explanations from
   that transcript and decision only. **No policy or wiki text enters this call.**
3. Re-read the transcript in a separate verification call. Review each proposal for
   speaker, exact quotation, decision relevance, direction, importance, disposition,
   timing, and conditions. The verifier can reject one reason or lower its role
   without losing the other reasons. Rejected interpretations and their evidence
   remain in the audit artifacts and raw call receipts.
4. Only then compare accepted original-window reasons with validated policies.
   A separate link review checks every proposed relationship. Mechanical guards
   downgrade unsupported applicability to unresolved or not applicable.

These are separate model calls, normally to the **same configured OpenRouter
model**. They are not independent ground truth or human verification. A human-audited
decision does not make its machine explanation human-audited. Explanation generation
may call the model for human-reviewed decisions, without modifying their labels.

Original reasons are bounded by a model-proposed, model-reviewed inclusive pitch
window and cannot cite turns after the final decision evidence turn. Later diligence,
retrospective, and unclear-timing explanations remain in `separate_timing`; they do
not contribute to original explanations, coverage, policy links, or retrieval helper
results. A model can still misidentify a window; mechanical checks cannot establish
semantic timing by themselves.

A controlling reason requires an explicit interpretation and a decision-connection
quote. An unsupported controlling role becomes unresolved. Tolerance requires an In,
negative concern, explicit interpretation, and evidence of acknowledging the concern
and nevertheless committing. Insufficiency requires an Out, acknowledged positive,
and explicit contrast. These semantic claims must also pass model review: the
presence of two quotes alone is not proof. Conditional commitments are copied
unchanged in `decision.condition`, never converted into unconditional investments.

Transport failures abort preparation as before. Malformed output or unverifiable
windows produce explicit unavailable artifacts with receipts. Unsupported individual
interpretations are rejected. Unobserved decisions and missing/oversized transcripts
produce unavailable explanations without explanation model calls. Unknown facts
are absent, not fabricated. Conflicting context values are removed from accepted
context and retained as rejected proposals.

## Artifact Contract

All files below are included in the bundle's SHA-256 inventory and installed by the
existing scoped installer. Paths are relative to the bundle/workspace unless noted.

| File | Version and purpose |
| --- | --- |
| `inputs/data/investors/<vc>/explanations/manifest.json` | `historical-explanation-manifest-v1`: case IDs, episode joins, relative sidecar paths/hashes, original historical-record paths/hashes, schema versions, policy identity, and coverage |
| `…/explanations/cases/<episode>.json` | `historical-explanations-v1`: immutable original decision, original window, reasons, context, separate later evidence, rejected proposals, and unavailable/failure state |
| `…/explanations/links/<episode>.json` | `policy-case-links-v1`: policy version/hash, accepted comparisons, rejected proposals, and unavailable state |
| `source/pitch-show/explanations/<episode>.json` | Prompt version, model, exact source hash, prompts, raw and parsed responses, verification receipts, usage, and provider metadata; installed under `onboarding/<vc>/source/…` |

Case IDs hash investor ID and episode slug. Rationale IDs hash case ID, proposed
statement, and exact evidence references; downgrading importance preserves the ID.
Link IDs hash case ID, policy artifact SHA-256, and policy ID. These IDs are stable
for unchanged content, not a claim that differently worded interpretations are equal.

Each reason has `direction` (positive/negative/neutral), `role`
(controlling/supporting/secondary/unresolved), `interpretation` (explicit/inferred),
`timing`, `disposition` (reason/tolerated_concern/insufficient_strength/unresolved_question),
existing `taxonomy_labels` when supported, `evidence`, and `decision_connection`.
Evidence carries the exact speaker string, zero-based turn index, and quotation.
Accepted context facts cover date, vehicle, role, stage, sector, financing terms,
geography and decision setting, with quotations. Vehicle/role evidence must be from
the target investor. Other context can be stated by a founder or host if the verifier
establishes that it concerns this case. A publication date is not silently a pitch date.
Unresolved questions may have evidence-backed reason entries; `missing_information`
is a model-generated list of gaps, not a statement of investor rationale.

Machine-readable schemas and complete synthetic examples:

- [Explanation schema](schemas/historical-explanations-v1.schema.json)
- [Policy-link schema](schemas/policy-case-links-v1.schema.json)
- [Proposal schema](schemas/explanation-proposal-v1.schema.json)
- [Review schema](schemas/explanation-review-v1.schema.json)
- [Explanation example](examples/historical-explanation.json)
- [Unavailable-policy example](examples/policy-links-unavailable.json)
- [Unresolved-policy example](examples/policy-links-unresolved.json)

## Investment-Memory Coordination

The adapter was implemented against the actual `wiki_build/policies.py` contract
`VERSION = '1.0'`, inspected on 2026-10-21. Its
[contract snapshot](schemas/investment-memory-policies-1.0.schema.json) documents the
interface; the adapter uses investment-memory's `validate_policies` at runtime to
validate evidence references, scope, content-derived IDs, and investor identity.
The source `policies.json`, `evidence.json`, and `context.json` are read from the
archived source wiki. The source files are never rewritten to match outcomes.
No sibling repository changes are required or made by this implementation.

Policy IDs are the producer's `id` values. Each link artifact pins both
`schema_version: "1.0"` and the exact policies.json SHA-256. Missing policies means
`status: "unavailable", unavailable_reason: "missing_policies"`; explanations still
work with old wikis. An incompatible version, invalid reference, or missing validator
for a present policy artifact is an error, not silent best-effort interpretation.

Relationships are `supports`, `illustrates_an_exception`, `potentially_conflicts`,
`not_applicable`, and `unresolved`. These are **model-inferred comparisons**. Each
proposal compares all seven producer applicability dimensions (investor, vehicle,
period, stage, sector, geography, decision_setting) and every precondition, keyed as
`precondition:0`, etc. Comparison evidence refers only to accepted case context keys.
Missing scope or comparison evidence prevents established applicability. Unknown
preconditions remain unresolved; established mismatches become not applicable.
This conservative v1 does not assume that an unstated scope means unrestricted scope.

Mechanical checks detect explicit personal/fund mismatches and out-of-range years
for a policy period formatted `YYYY` or `YYYY-YYYY`. Other natural-language period
and scope interpretations depend on the model review and are recorded as such.
Exceptions need explicit decision contrast; descriptive context cannot establish
an exception/conflict. Topic similarity or an opposite final verdict alone is
insufficient. Material differences and uncertainty are retained. Potential conflict
is not a resolved contradiction and creates no precedence over stated policy.

## Assessment Retrieval Handoff

Existing assessment retrieval still reads its unchanged precedent records and
indexes. **Assessment agents do not yet consume these explanation artifacts.**
Their integration, prompt changes, and evaluation require downstream work.

The new local `retrieve_cases` helper joins an original historical record to its
explanation and policy links. It works on a bundle or an installed workspace; it
validates sidecar hashes, source/record joins, accepted evidence, policy versions,
and coverage before returning data. There is no new embedding model or vector
index for sidecars: reuse the existing historical retrieval's episode hits, then
join and filter the sidecars.

```python
from pathlib import Path
from vclogic_onboarding.explanation_bundle import retrieve_cases

hits = retrieve_cases(
    Path('/path/to/bundle-or-workspace'), 'investor-slug',
    allowed_episode_slugs=firewall_approved_historical_episode_ids,
    company_episodes=resolved_company_to_all_episode_ids,
    held_out_company=canonical_target_company_id,
    excluded_episode_slugs=additional_linked_target_episode_ids,
    taxonomy_label='business_model_assessment',  # optional
)
```

The caller must first apply assessment's existing information firewall and resolve
the held-out company's identity, aliases, and **all linked episodes**, including
follow-ups and later appearances. An unknown target mapping raises an error. An
explicit empty group is allowed only when the caller established no historical
appearance. The helper expands exclusion transitively across overlapping company
groups before returning any case or link. It never infers company identity from
similar titles. Policy links are local to a case and cannot reference another case's
rationale. Rejected proposals, later explanations, and raw policy text are excluded
from retrieval output. Consumers must not bypass filtering by opening the complete
manifest, raw receipts, or policy source and placing them in an assessment prompt.

Use `taxonomy_label` to find cases mentioning the same concern, then compare their
original decisions. Inspect `role`, `disposition`, exact evidence and conditions;
compare context and link `material_differences` before drawing conclusions. Shared
taxonomy labels do not establish identical concerns or comparable circumstances.
`status: unavailable` means no usable explanation extraction; `no_supported_explanation`
means the attempted review established no supported original reason, not that the
investor had no reasons. Older bundles without the capability have no explanation
data, not zero rationales.

## Coverage And Limits

`check` returns `semantic_coverage` separately from `valid` and
`ready_for_assessment`. Old bundles return null. New bundles declare
`capabilities.historical_explanations` for artifact availability and
`capabilities.policy_case_links` for a present valid source policy artifact; neither
flag promises supported reasons or usable links. Coverage reports counts of cases:
observed decisions, supported explanations, explicit controlling reasons,
established vehicle-and-date context, usable policy links, missing transcripts,
ambiguous decisions, failed verification, and unavailable policy linking. Rejected
interpretations are counted separately. A usable policy link has established
applicability and a relationship other than unresolved/not applicable.

A loadable index is a technical property, not evidence of adequate judgment coverage.
No quality cutoffs, numeric policy weights, calibrated probabilities, classifiers,
or accuracy improvement claims are introduced. Exact quote/index checks are
mechanical; relevance, importance, temporal boundaries and policy comparisons are
model interpretations. Human verification and downstream evaluation remain needed.

## Local Verification

`uv run --no-sync pytest -q` exercises saved transcript and response fixtures without
network/model calls, including wrong-speaker evidence, later rationale, conditional
commitment, unjustified tolerance, insufficient positive, downgraded controlling
reason, scope mismatches, invalid policy references/versions, missing policies,
resealed invalid evidence, and transitive company exclusion. A temporary-workspace
installation test verifies that relocated explanation joins remain usable. These
fixtures test mechanics and boundaries, not model accuracy. The test suite does not
reprocess installed investors or run assessments.
