import json
import pytest

from vc_clone_graph.firewall import verify_package, validate_precedent_corpus
from vc_clone_graph.config import load_config
from vclogic_onboarding.bundle import prepare, check_bundle


@pytest.mark.parametrize('collect_only', [True, False])
def test_reviewed_pitch_collection_produces_audited_engine_inputs(wiki,tmp_path,monkeypatch,collect_only):
    from vclogic_onboarding import extraction
    from test_extraction import Provider
    from test_explanations import draft, review as explanation_review
    explanation = draft()
    for ref in explanation['reasons'][0]['evidence'] + explanation['reasons'][0]['decision_connection']:
        ref['speaker'] = 'Test Investor'
    provider = Provider(explanation, explanation_review())
    monkeypatch.setattr(extraction, 'make_provider', lambda model=None: (provider, 'test-model'))
    cache=tmp_path/'cache';(cache/'episodes').mkdir(parents=True)
    (cache/'profile.json').write_text(json.dumps({'id':'test-investor','name':'Test Investor','investments':[]}))
    (cache/'episodes/1-example.json').write_text(json.dumps({
        'slug':'1-example','episode_type':'pitch','url':'https://www.thepitch.show/1-example',
        'founders':[{'name':'Founder'}],'panel':[{'name':'Test Investor','slug':'test-investor'}],
        'transcript':"Founder: We build scheduling software for small businesses.\nTest Investor: How many customers pay today?\nFounder: Ten businesses pay monthly.\nTest Investor: I am out because the market is too small."
    }))
    review=tmp_path/'review.json';review.write_text(json.dumps([{
        'episode_slug':'1-example','final_decision':'Out','pitch_window_decision':'Out',
        'initial_response':'Out','decision_context':'initial_panel',
        'label_basis':'explicit investor statement','audit_notes':'Exact quote inspected.',
        'evidence_contains':'I am out because the market is too small.',
    }]))
    out=tmp_path/'bundle'
    prepare(wiki,out,skip_indexes=True,from_pitch_show=True,pitch_show_cache=cache,review=review,collect_only=collect_only)
    config=load_config(out/'configs/investors/test-investor/canonical.toml')
    assert config.precedents.enabled
    package=verify_package(out/'inputs','test-investor','1-example')
    text=package.pitch.read_text()
    assert 'Ten businesses pay monthly.' in text
    assert 'I am out' not in text
    assert check_bundle(out)['valid']
    corpus=out/'inputs/data/investors/test-investor/precedents'
    assert validate_precedent_corpus(corpus)
    assert json.loads((corpus/'records/1-example.json').read_text())['decision']['audit_source']=='evaluation/labels/test-investor.json'

    ledger=json.loads((out/'evaluation/labels/test-investor.json').read_text())
    assert ledger[0]['evidence_source']=='source/pitch-show/episodes/1-example.json transcript'
