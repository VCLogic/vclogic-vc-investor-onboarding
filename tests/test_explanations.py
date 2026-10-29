import copy
import json
from pathlib import Path

import pytest

from test_extraction import Provider, proposal, verification
from vclogic_onboarding.explanations import explain, Draft, Review, stable_id
from vclogic_onboarding.explanation_bundle import build_explanations, validate_explanations, retrieve_cases
from vclogic_onboarding.policy_links import load_policies, Link, guard_link, link_case
from vclogic_onboarding.files import write_json, read_json, digest


def episode():
    return read_json(Path(__file__).parent/'fixtures/explanation-case.json')


def row():
    p = proposal()
    return {'episode_slug': '1-example', 'pitch_window_decision': p['status'],
        'decision_context': p['context'], 'evidence_turn_index': p['evidence_turn_index'],
        'evidence_quote': p['evidence_quote'], 'condition': None, 'evaluation_eligible': False,
        'audit_notes': 'Machine reviewed, not human audited.'}


def evidence(index=3, speaker='Test', quote=None):
    return {'speaker': speaker, 'turn_index': index, 'quote': quote or proposal()['evidence_quote']}


def draft():
    return {'window_start': 0, 'window_end': 3, 'timing_explanation': 'Original pitch.',
        'reasons': [{'key': 'market', 'statement': 'Market size explains rejection.',
            'taxonomy_labels': [], 'direction': 'negative', 'role': 'controlling',
            'interpretation': 'explicit', 'timing': 'original', 'disposition': 'reason',
            'evidence': [evidence()], 'decision_connection': [evidence()]}],
        'context': [], 'missing_information': ['Vehicle and case date unknown.']}


def review():
    return {'window_verified': True, 'context_keys': [], 'explanation': 'Checked original pitch.',
        'items': [{'key': 'market', 'accepted': True, 'explanation': 'Explicit because statement.',
            **{k: True for k in ('speaker', 'quotation', 'decision_relevance', 'direction', 'importance', 'disposition', 'timing', 'conditions')},
            'revised_role': 'controlling', 'revised_interpretation': 'explicit'}]}


def run(ep=None, decision=None, d=None, v=None):
    return explain(ep or episode(), decision or row(), 'test-investor', ['Test', 'Test Investor'],
        Provider(d or draft(), v or review()), 'cached-test-model')


def test_cached_transcript_smoke_and_policy_free_prompt():
    cached = read_json(Path(__file__).parent/'fixtures/explanation-responses.json')
    p = Provider(cached['proposal'], cached['verification'])
    case, receipt = explain(episode(), row(), 'test-investor', ['Test'], p, 'fixture')
    assert case['status'] == 'supported'
    assert case['reasons'][0]['role'] == 'controlling'
    assert len(receipt['calls']) == 2
    assert case['verification_basis'] == 'model_review_not_independent_ground_truth'
    assert all('"policies"' not in r.prompt for r in p.requests)


@pytest.mark.parametrize('ref', [evidence(2, 'Founder', 'Ten.'), evidence(999), evidence(3, 'Test', 'Not verbatim')])
def test_reject_other_panelist_and_invalid_evidence(ref):
    d = draft(); d['reasons'][0]['evidence'] = [ref]
    c, receipt = run(d=d)
    assert not c['reasons'] and c['rejected'] and receipt['calls'][0]['parsed'] == d


def test_later_explanation_is_not_original_reason():
    ep = episode(); ep['transcript'] += '\nTest: After diligence I learned the market was small.'
    d = draft(); d['reasons'][0]['evidence'] = [evidence(4, 'Test', 'After diligence I learned the market was small.')]
    c, _ = run(ep=ep, d=d)
    assert not c['reasons']
    d['reasons'][0]['timing'] = 'later_diligence'
    c, _ = run(ep=ep, d=d)
    assert c['separate_timing'] and not c['reasons']


def test_conditional_commitment_preserved():
    ep = episode(); ep['transcript'] = 'Test: I am in if you secure the patent, because of the technology.'
    r = {**row(), 'pitch_window_decision': 'In', 'condition': 'if you secure the patent',
         'evidence_turn_index': 0, 'evidence_quote': ep['transcript'][6:]}
    d = draft(); d.update(window_end=0)
    d['reasons'][0].update(direction='positive', evidence=[evidence(0, 'Test', r['evidence_quote'])], decision_connection=[evidence(0, 'Test', r['evidence_quote'])])
    c, _ = run(ep=ep, decision=r, d=d)
    assert c['decision'] == r and c['decision']['condition']


def test_in_does_not_make_negative_mention_tolerated():
    d = draft(); d['reasons'][0].update(disposition='tolerated_concern', decision_connection=[])
    c, _ = run(decision={**row(), 'pitch_window_decision': 'In'}, d=d)
    assert not c['reasons'] and 'contrast' in c['rejected'][0]['rejection']


def test_out_acknowledged_positive_needs_explicit_insufficiency():
    ep = episode(); ep['transcript'] = 'Test: Great team, but that is not enough; I am out because the market is too small.'
    d = draft(); d['window_end'] = 0
    ref = evidence(0, 'Test', ep['transcript'][6:])
    d['reasons'][0].update(direction='positive', disposition='insufficient_strength', evidence=[ref], decision_connection=[ref])
    r = {**row(), 'evidence_turn_index': 0, 'evidence_quote': ref['quote']}
    c, _ = run(ep=ep, decision=r, d=d)
    assert c['reasons'][0]['disposition'] == 'insufficient_strength'
    d['reasons'][0]['decision_connection'] = []
    c, _ = run(ep=ep, decision=r, d=d)
    assert not c['reasons']


def test_unestablished_controlling_reason_downgraded_without_losing_evidence():
    v = review(); v['items'][0]['revised_role'] = 'unresolved'
    c, _ = run(v=v)
    assert c['reasons'][0]['role'] == 'unresolved'
    assert c['reasons'][0]['evidence'] == draft()['reasons'][0]['evidence']


def test_invalid_window_and_unobserved_fail_closed():
    v = review(); v['window_verified'] = False
    c, receipt = run(v=v)
    assert c['verification_failures'] and not c['reasons'] and receipt['calls']
    c, receipt = explain(episode(), {**row(), 'pitch_window_decision': 'Unobserved'}, 'test-investor', ['Test'], Provider(), 'fixture')
    assert c['unavailable_reason'] == 'decision_unobserved' and not receipt['calls']


def policy():
    fields = {'investor': 'test-investor', 'vehicle': 'fund', 'period': '2020-2025', 'stage': 'seed',
              'sector': 'software', 'geography': 'US', 'decision_setting': 'panel'}
    return {'id': 'pol-test', 'type': 'hard_requirement',
        'applicability': {k: {'status': 'stated', 'value': v} for k, v in fields.items()}, 'preconditions': []}


def comparison_case():
    c, _ = run()
    values = {'date': '2024-01-01', 'vehicle': 'fund', 'stage': 'seed', 'sector': 'software', 'geography': 'US', 'decision_setting': 'panel'}
    c['context'] = [{'key': k, 'field': k, 'value': v, 'evidence': [evidence()]} for k, v in values.items()]
    return c


def link(c, relation='supports'):
    return Link(policy_id='pol-test', rationale_ids=[c['reasons'][0]['rationale_id']], relationship=relation,
        comparisons=[{'dimension': k, 'status': 'matches', 'context_keys': [] if k == 'investor' else ['date' if k == 'period' else k],
                      'explanation': 'Proposed matching context.'} for k in policy()['applicability']],
        material_differences=[], uncertainty='Model interpretation requires human review.')


@pytest.mark.parametrize('field,value', [('vehicle', 'personal'), ('date', '2019-01-01')])
def test_personal_fund_and_dated_policy_mismatches(field, value):
    c = comparison_case()
    next(f for f in c['context'] if f['field'] == field)['value'] = value
    result = guard_link(link(c, 'potentially_conflicts'), policy(), c)
    assert result['relationship'] == 'not_applicable' and not result['applicability_established']


@pytest.mark.parametrize('relation', ['illustrates_an_exception', 'potentially_conflicts'])
def test_unknown_scope_prevents_exception_or_conflict(relation):
    c = comparison_case(); c['context'] = []
    proposal = link(c, relation)
    for comp in proposal.comparisons: comp.context_keys = []
    result = guard_link(proposal, policy(), c)
    assert result['relationship'] == 'unresolved'


def test_exception_requires_explicit_contrast_and_conflicts_are_inferences():
    c = comparison_case()
    assert guard_link(link(c, 'illustrates_an_exception'), policy(), c)['relationship'] == 'unresolved'
    c['reasons'][0]['interpretation'] = 'inferred'
    assert guard_link(link(c, 'potentially_conflicts'), policy(), c)['relationship'] == 'unresolved'


def test_missing_policies_and_incompatible_versions(tmp_path):
    assert load_policies(tmp_path, 'test-investor') is None
    c, _ = run()
    assert link_case(c, None, Provider(), {'calls': []})['status'] == 'unavailable'
    write_json(tmp_path/'policies.json', {'schema_version': '99'})
    with pytest.raises(ValueError, match='incompatible'):
        load_policies(tmp_path, 'test-investor')


def test_unknown_rationale_context_and_missing_preconditions_rejected():
    c = comparison_case(); p = policy()
    l = link(c); l.rationale_ids = ['other-case-rationale']
    with pytest.raises(ValueError, match='rationale'):
        guard_link(l, p, c)
    l = link(c); l.comparisons[1].context_keys = ['invented']
    with pytest.raises(ValueError, match='context'):
        guard_link(l, p, c)
    p['preconditions'] = [{'condition': 'revenue'}]
    with pytest.raises(ValueError, match='preconditions'):
        guard_link(link(c), p, c)


def test_complete_local_bundle_sidecars_coverage_and_leakage(tmp_path):
    from vclogic_onboarding.extraction import enrich_machine
    eps = tmp_path/'source/pitch-show/episodes'
    write_json(eps/'1-example.json', episode())
    write_json(eps/'2-target-followup.json', {**episode(), 'slug': '2-target-followup'})
    write_json(eps/'3-missing.json', {**episode(), 'slug': '3-missing', 'transcript': None})
    # Decision extraction precedes explanation extraction for all cases.
    p = Provider(proposal(), verification(), proposal(), verification(), draft(), review(), draft(), review())
    s = enrich_machine(tmp_path, 'test-investor', ['Test'], p, 'fixture')
    cov = validate_explanations(tmp_path, 'test-investor')
    assert cov == s['semantic_coverage']
    assert cov['supported_explanations'] == 2 and cov['missing_transcripts'] == 1
    assert cov['policy_linking_unavailable'] == 3
    kwargs = dict(allowed_episode_slugs=['1-example', '2-target-followup'],
        company_episodes={'target': ['1-example'], 'target-alias': ['1-example', '2-target-followup']}, held_out_company='target')
    assert retrieve_cases(tmp_path, 'test-investor', **kwargs) == []
    with pytest.raises(ValueError, match='resolved'):
        retrieve_cases(tmp_path, 'test-investor', **{**kwargs, 'held_out_company': 'unknown'})
    kwargs['company_episodes'] = {'target': ['2-target-followup']}
    hits = retrieve_cases(tmp_path, 'test-investor', **kwargs)
    assert len(hits) == 1 and hits[0]['case']['episode_slug'] == '1-example'
    assert 'rejected' not in hits[0]['explanation']


def test_actual_investment_memory_policy_contract_and_bad_refs(tmp_path):
    from wiki_build.policies import finalize, SCOPE_FIELDS
    ev = {'id': 'one', 'source': 'interview', 'quote': 'I prefer reliable founders.',
          'label': 'founder_qualities', 'support': 'explicit'}
    p = {'key': 'reliability', 'statement': 'Prefer reliable founders.',
        'taxonomy_labels': ['founder_qualities'], 'type': 'preference',
        'decision_effect': 'supports_investment', 'support': 'explicit', 'evidence_refs': ['ev:one'],
        'applicability': {f: {'status': 'unknown', 'value': 'unknown'} for f in SCOPE_FIELDS},
        'preconditions': [], 'applicability_evidence_needed': 'Establish scope from investor evidence.',
        'missing_information_effect': 'unresolved', 'exceptions_status': 'not_stated', 'exceptions': [],
        'uncertainty': 'Scope is unknown.', 'conflicting_evidence_refs': [], 'unresolved_applicability': list(SCOPE_FIELDS)}
    artifact, _ = finalize({'schema_version': '1.0', 'policies': [p], 'relationships': [],
                          'limitations': 'Fixture policy only.'}, [ev], [], 'test-investor')
    write_json(tmp_path/'policies.json', artifact); write_json(tmp_path/'evidence.json', [ev])
    loaded = load_policies(tmp_path, 'test-investor')
    assert loaded['sha256'] == digest(tmp_path/'policies.json')
    c = comparison_case(); l = link(c).model_dump(); l['policy_id'] = artifact['policies'][0]['id']
    linked = link_case(c, loaded, Provider({'links': [l]}, {'judgments': [{'policy_id': l['policy_id'], 'accepted': True, 'explanation': 'Scope unknown.'}]}), {'calls': []})
    assert linked['links'][0]['relationship'] == 'unresolved'
    assert linked['policy_artifact']['schema_version'] == '1.0'
    artifact['policies'][0]['evidence_refs'] = ['ev:missing']
    write_json(tmp_path/'policies.json', artifact)
    with pytest.raises(ValueError, match='unknown evidence reference'):
        load_policies(tmp_path, 'test-investor')


def test_link_reviewer_rejects_proposal_and_retains_receipt():
    c = comparison_case(); p = policy(); proposed = link(c, 'potentially_conflicts').model_dump()
    receipt = {'calls': []}
    artifact = link_case(c, {'schema_version': '1.0', 'sha256': 'x', 'data': {'policies': [p]}},
        Provider({'links': [proposed]}, {'judgments': [{'policy_id': p['id'], 'accepted': False, 'explanation': 'Topic alone is insufficient.'}]}), receipt)
    assert not artifact['links'] and artifact['rejected'][0]['proposal'] == proposed
    assert len(receipt['calls']) == 2


def test_resealed_invalid_reference_and_policy_hash_rejected(tmp_path):
    from vclogic_onboarding.extraction import enrich_machine
    write_json(tmp_path/'source/pitch-show/episodes/1-example.json', episode())
    enrich_machine(tmp_path, 'test-investor', ['Test'], Provider(proposal(), verification(), draft(), review()), 'fixture')
    base = tmp_path/'inputs/data/investors/test-investor/explanations'
    manifest = read_json(base/'manifest.json')
    path = base/manifest['cases'][0]['explanation']['path']
    original = read_json(path); bad = copy.deepcopy(original)
    bad['reasons'][0]['evidence'][0]['turn_index'] = 999
    write_json(path, bad)
    manifest['cases'][0]['explanation']['sha256'] = digest(path)
    write_json(base/'manifest.json', manifest)
    with pytest.raises(ValueError, match='identity|outside'):
        validate_explanations(tmp_path, 'test-investor')
    write_json(path, original); manifest['cases'][0]['explanation']['sha256'] = digest(path)
    manifest['policy_artifact'] = {'schema_version': '1.0', 'sha256': '0'*64}
    write_json(base/'manifest.json', manifest)
    with pytest.raises(ValueError, match='policy version/hash'):
        validate_explanations(tmp_path, 'test-investor')


def test_installed_sidecars_retrieve_with_relocated_sources(wiki, tmp_path, monkeypatch):
    from vclogic_onboarding import extraction, pitch_show
    from vclogic_onboarding.bundle import prepare, install_bundle
    def collect(slug, output, **kwargs):
        write_json(output/'episodes/1-example.json', episode())
        return {'episode_count': 1, 'complete': True}
    monkeypatch.setattr(pitch_show, 'collect', collect)
    monkeypatch.setattr(extraction, 'make_provider', lambda model=None: (Provider(proposal(), verification(), draft(), review()), 'fixture'))
    bundle = tmp_path/'bundle'; workspace = tmp_path/'workspace'; workspace.mkdir()
    prepare(wiki, bundle, from_pitch_show=True, skip_indexes=True)
    install_bundle(bundle, workspace)
    hits = retrieve_cases(workspace, 'test-investor', allowed_episode_slugs=['1-example'],
                          company_episodes={'held-out': []}, held_out_company='held-out')
    assert len(hits) == 1
    assert hits[0]['explanation']['status'] == 'supported'


def test_audit_notes_cannot_seed_historical_reasons_with_policy_text():
    p = Provider(draft(), review())
    explain(episode(), {**row(), 'audit_notes': 'POLICY_TEXT_MUST_NOT_LEAK'}, 'test-investor', ['Test'], p, 'fixture')
    assert all('POLICY_TEXT_MUST_NOT_LEAK' not in request.prompt for request in p.requests)


def test_neutral_direction_must_be_explicit():
    d = draft(); d['reasons'][0].update(direction='neutral', interpretation='inferred')
    v = review(); v['items'][0]['revised_interpretation'] = 'inferred'
    c, _ = run(d=d, v=v)
    assert not c['reasons'] and 'neutral' in c['rejected'][0]['rejection']


def test_documented_schemas_and_examples_match_models():
    from vclogic_onboarding.explanations import ExplanationArtifact
    from vclogic_onboarding.policy_links import LinkArtifact
    root = Path(__file__).parents[1]/'docs'
    for name, model in [('historical-explanations-v1', ExplanationArtifact), ('policy-case-links-v1', LinkArtifact),
                        ('explanation-proposal-v1', Draft), ('explanation-review-v1', Review)]:
        assert read_json(root/f'schemas/{name}.schema.json') == model.model_json_schema()
    ExplanationArtifact.model_validate(read_json(root/'examples/historical-explanation.json'))
    for name in ('policy-links-unavailable', 'policy-links-unresolved'):
        LinkArtifact.model_validate(read_json(root/f'examples/{name}.json'))


def test_duplicate_rationale_proposal_rejected_without_losing_first():
    d = draft(); d['reasons'].append({**copy.deepcopy(d['reasons'][0]), 'key': 'duplicate'})
    v = review(); v['items'].append({**v['items'][0], 'key': 'duplicate'})
    c, _ = run(d=d, v=v)
    assert len(c['reasons']) == 1
    assert c['status'] == 'supported' and 'duplicate' in c['rejected'][0]['rejection']


def test_resealed_role_cannot_exceed_verifier_downgrade(tmp_path):
    from vclogic_onboarding.extraction import enrich_machine
    write_json(tmp_path/'source/pitch-show/episodes/1-example.json', episode())
    v = review(); v['items'][0]['revised_role'] = 'unresolved'
    enrich_machine(tmp_path, 'test-investor', ['Test'], Provider(proposal(), verification(), draft(), v), 'fixture')
    base = tmp_path/'inputs/data/investors/test-investor/explanations'
    manifest = read_json(base/'manifest.json'); path = base/manifest['cases'][0]['explanation']['path']
    case = read_json(path); case['reasons'][0]['role'] = 'controlling'; write_json(path, case)
    manifest['cases'][0]['explanation']['sha256'] = digest(path)
    manifest['coverage']['explicit_controlling_reasons'] = 1
    write_json(base/'manifest.json', manifest)
    with pytest.raises(ValueError, match='reviewed interpretation'):
        validate_explanations(tmp_path, 'test-investor')
