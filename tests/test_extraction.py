import json

import pytest
from vc_clone_graph.providers.base import GenerationResult, Usage

from vclogic_onboarding.extraction import extract_episode, enrich_machine


class Provider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return GenerationResult(parsed=response, content=json.dumps(response), usage=Usage(),
                                elapsed_seconds=0, raw_metadata={})


def episode():
    return {'slug': '1-example', 'panel': [{'slug': 'test-investor', 'name': 'Test Investor'}],
            'transcript': 'Founder: We build software.\nTest: How many customers?\nFounder: Ten.\nTest: I am out because the market is too small.'}


def proposal():
    return {'status': 'Out', 'context': 'initial_panel', 'evidence_turn_index': 3,
            'evidence_quote': 'I am out because the market is too small.',
            'condition': None, 'reason': 'Explicit rejection during the pitch.'}


def verification():
    return {**proposal(), 'verified': True}


def test_extract_binds_exact_investor_quote_and_requires_verification():
    provider = Provider(proposal(), verification())
    row, receipt = extract_episode(episode(), ['Test Investor', 'Test'], provider)
    assert row['pitch_window_decision'] == 'Out'
    assert row['evidence_turn_index'] == 3
    assert row['evaluation_eligible'] is False
    assert receipt['status'] == 'verified_machine'
    assert len(provider.requests) == 2
    assert 'Founder' in provider.requests[1].prompt
    assert receipt['calls'][0]['usage']['cost_usd'] == 0


@pytest.mark.parametrize('change', [
    {'evidence_turn_index': 2, 'evidence_quote': 'Ten.'},
    {'evidence_quote': 'I would never invest.'},
    {'evidence_turn_index': 99},
    {'context': 'later_diligence'},
    {'status': 'Unobserved', 'evidence_turn_index': None, 'evidence_quote': None},
])
def test_invalid_or_non_pitch_evidence_stays_unobserved(change):
    candidate = {**proposal(), **change}
    row, receipt = extract_episode(episode(), ['Test'], Provider(candidate, verification()))
    assert row['pitch_window_decision'] == 'Unobserved'
    assert 'evidence_quote' not in row


@pytest.mark.parametrize('change', [{'verified': False}, {'status': 'In'}, {'evidence_turn_index': 1}, {'context': 'same_session_reversal'}, {'condition': 'Subject to revenue verification'}])
def test_verifier_disagreement_stays_unobserved(change):
    row, _ = extract_episode(episode(), ['Test'], Provider(proposal(), {**verification(), **change}))
    assert row['pitch_window_decision'] == 'Unobserved'


def test_malformed_response_stays_unobserved_and_retains_receipt():
    row, receipt = extract_episode(episode(), ['Test'], Provider({'status': 'Out'}))
    assert row['pitch_window_decision'] == 'Unobserved'
    assert receipt['calls'][0]['parsed'] == {'status': 'Out'}


def test_provider_failure_is_not_silently_converted_to_unknown():
    with pytest.raises(RuntimeError, match='provider failed'):
        extract_episode(episode(), ['Test'], Provider(RuntimeError('provider down')))


def test_oversized_transcript_is_preserved_without_partial_extraction(monkeypatch):
    import vclogic_onboarding.extraction as module
    monkeypatch.setattr(module, 'MAX_TRANSCRIPT_CHARS', 10)
    provider = Provider()
    row, receipt = extract_episode(episode(), ['Test'], provider)
    assert row['pitch_window_decision'] == 'Unobserved'
    assert receipt['status'] == 'oversized'
    assert not provider.requests


def test_machine_corpus_has_portable_provenance_without_evaluation_labels(tmp_path):
    episodes = tmp_path / 'source/pitch-show/episodes'
    episodes.mkdir(parents=True)
    (episodes / '1-example.json').write_text(json.dumps(episode()))
    missing = {**episode(), 'slug': '2-missing', 'transcript': None}
    (episodes / '2-missing.json').write_text(json.dumps(missing))
    result = enrich_machine(tmp_path, 'test-investor', ['Test'], Provider(proposal(), verification()), 'test-model', explanations=False)
    assert result['precedent_records'] == 1
    assert result['observed_machine_decisions'] == 1
    assert result['missing_transcripts'] == ['2-missing']
    assert not (tmp_path / 'evaluation').exists()
    record = json.loads((tmp_path / 'inputs/data/investors/test-investor/precedents/records/1-example.json').read_text())
    assert record['decision']['audit_source'] == 'inputs/data/investors/test-investor/machine-decisions.json'
    assert 'machine' in record['decision']['audit_notes'].lower()
    receipt = json.loads((tmp_path / 'source/pitch-show/extraction/1-example.json').read_text())
    assert receipt['model'] == 'test-model'
    assert receipt['source_sha256']


def test_provider_value_error_aborts_instead_of_publishing_unknown():
    with pytest.raises(RuntimeError, match='provider failed'):
        extract_episode(episode(), ['Test'], Provider(ValueError('blank response')))


def test_human_rows_override_machine_and_other_episodes_remain_searchable(tmp_path):
    episodes = tmp_path/'source/pitch-show/episodes'; episodes.mkdir(parents=True)
    first = episode()
    second = {**episode(), 'slug': '2-example'}
    for ep in [first, second]:
        (episodes/f"{ep['slug']}.json").write_text(json.dumps(ep))
    labels = tmp_path/'evaluation/labels/test-investor.json'; labels.parent.mkdir(parents=True)
    human = {'episode_slug': '1-example', 'pitch_window_decision': 'Out',
             'decision_context': 'initial_panel', 'evidence_quote': proposal()['evidence_quote'],
             'evidence_turn_index': 3, 'audit_notes': 'Human reviewed exact transcript.'}
    labels.write_text(json.dumps([human]))
    before = labels.read_bytes()
    provider = Provider(proposal(), verification())
    result = enrich_machine(tmp_path, 'test-investor', ['Test'], provider, 'test-model', explanations=False)
    assert result['precedent_records'] == 2
    assert result['human_rows'] == 1
    assert result['machine_rows'] == 1
    assert len(provider.requests) == 2
    assert labels.read_bytes() == before
    records = tmp_path/'inputs/data/investors/test-investor/precedents/records'
    assert json.loads((records/'1-example.json').read_text())['decision']['audit_source'] == 'evaluation/labels/test-investor.json'
    assert json.loads((records/'2-example.json').read_text())['decision']['audit_source'].endswith('machine-decisions.json')
    assert not (tmp_path/'source/pitch-show/extraction/1-example.json').exists()


def test_abstention_still_builds_searchable_transcript(tmp_path):
    episodes = tmp_path/'source/pitch-show/episodes'; episodes.mkdir(parents=True)
    (episodes/'1-example.json').write_text(json.dumps(episode()))
    result = enrich_machine(tmp_path, 'test-investor', ['Test'], Provider({**proposal(), 'context': 'later_diligence'}), 'test-model', explanations=False)
    assert result['precedent_records'] == 1
    assert result['observed_machine_decisions'] == 0
    record = json.loads((tmp_path/'inputs/data/investors/test-investor/precedents/records/1-example.json').read_text())
    assert record['decision']['status'] == 'unobserved'
    assert len(record['turns']) == 4
