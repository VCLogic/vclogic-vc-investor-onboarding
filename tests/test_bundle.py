import json
from pathlib import Path

import pytest
from vc_clone_graph.config import load_config
from vc_clone_graph.rehearsal_config import load_rehearsal_config
from vc_clone_graph.rehearsal_bootstrap import prepare_live_package
from vc_clone_graph.firewall import verify_package

from vclogic_onboarding.bundle import prepare, check_bundle, install_bundle, index_bundle


def test_wiki_only_bundle_uses_pipeline_contract(wiki, tmp_path):
    output=tmp_path/'bundle'
    report=prepare(wiki, output, skip_indexes=True)
    assert report['vc_slug']=='test-investor'
    assert not report['ready_for_assessment']
    assert check_bundle(output)['valid']
    canonical=load_config(output/'configs/investors/test-investor/canonical.toml')
    rehearsal=load_rehearsal_config(output/'configs/investors/test-investor/rehearsal.toml')
    assert not canonical.precedents.enabled and not rehearsal.precedents.enabled
    assert not canonical.portfolio_memory.enabled and not rehearsal.portfolio_memory.enabled
    assert rehearsal.classification.mode=='v41_grounded'
    assert rehearsal.classification.canonical_config_path=='configs/investors/test-investor/canonical.toml'
    assert not (output/'inputs/wiki/test-investor/BUILD_REPORT.md').exists()
    live=prepare_live_package(source_root=output/'inputs',destination_root=tmp_path/'live',vc_slug='test-investor',
        episode_slug='new-pitch',pitch='We build scheduling software.',target_company_aliases=['NewCo'])
    assert verify_package(live,'test-investor','new-pitch').pitch.is_file()


def test_source_is_revalidated_not_trusted_by_stale_receipt(wiki,tmp_path):
    (wiki/'validation.json').write_text('{"valid":true}')
    with (wiki/'persona.md').open('a') as f: f.write('\n- In: Fabricated policy [ev:missing]\n')
    with pytest.raises(ValueError,match='wiki validation'):
        prepare(wiki,tmp_path/'bundle',skip_indexes=True)
    assert not (tmp_path/'bundle').exists()


def test_source_symlink_and_unsafe_slug_rejected(wiki,tmp_path):
    (wiki/'evil.md').symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='symlink'):
        prepare(wiki,tmp_path/'bundle',skip_indexes=True)
    (wiki/'evil.md').unlink()
    with pytest.raises(ValueError):
        prepare(wiki,tmp_path/'bundle',slug='../outside',skip_indexes=True)


def test_tampered_file_and_unlisted_file_rejected(wiki,tmp_path):
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    (out/'inputs/wiki/test-investor/persona.md').write_text('tampered')
    with pytest.raises(ValueError,match='hash'):
        check_bundle(out)
    with pytest.raises(ValueError):
        install_bundle(out,tmp_path/'pipeline')


def test_install_is_scoped_idempotent_and_checks_all_conflicts_first(wiki,tmp_path):
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    target=tmp_path/'pipeline'; target.mkdir()
    conflict=target/'inputs/taxonomy/codebook_v_final.json'; conflict.parent.mkdir(parents=True);conflict.write_text('different')
    with pytest.raises(ValueError,match='conflict'):
        install_bundle(out,target)
    assert not (target/'inputs/investors/test-investor.toml').exists()
    conflict.unlink()
    install_bundle(out,target)
    assert (target/'inputs/investors/test-investor.toml').exists()
    assert not (target/'source').exists()
    assert (target/'onboarding/test-investor/source/wiki/prepared.json').exists()
    assert install_bundle(out,target)['installed_files']==0


def test_install_rejects_symlink_parent(wiki,tmp_path):
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    target=tmp_path/'pipeline'; target.mkdir()
    elsewhere=tmp_path/'elsewhere';elsewhere.mkdir();(target/'inputs').symlink_to(elsewhere,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):
        install_bundle(out,target)
    assert list(elsewhere.iterdir())==[]


def test_index_completion_and_source_hashes(wiki,tmp_path):
    from vclogic_onboarding.bundle import embedding_settings
    class Embedder:
        metadata=embedding_settings()
        def embed(self,texts): return [[1.,float(len(t)),.2] for t in texts]
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    index_bundle(out,embedder=Embedder())
    assert check_bundle(out)['ready_for_assessment']
    assert (out/'inputs/indexes/test-investor.json').exists()


def test_unreviewed_pitch_show_collection_keeps_retrievers_disabled(wiki,tmp_path,monkeypatch):
    from vclogic_onboarding import pitch_show
    def collect(slug,output,**kwargs):
        output.mkdir(parents=True)
        (output/'decisions.json').write_text('[{"reported_decision":"In","pitch_window_decision":"Unobserved"}]')
        return {'complete':True,'episode_count':1}
    monkeypatch.setattr(pitch_show,'collect',collect)
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True,from_pitch_show=True,collect_only=True)
    assert not load_config(out/'configs/investors/test-investor/canonical.toml').precedents.enabled
    assert (out/'source/pitch-show/decisions.json').exists()


def test_existing_output_is_never_overwritten(wiki,tmp_path):
    out=tmp_path/'bundle';out.mkdir();(out/'keep').write_text('keep')
    with pytest.raises(ValueError,match='exists'):
        prepare(wiki,out,skip_indexes=True)
    assert (out/'keep').read_text()=='keep'


def test_failed_index_build_preserves_bundle(wiki,tmp_path):
    from vclogic_onboarding.files import inventory
    class Broken:
        def embed(self,texts): raise RuntimeError('model unavailable')
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    before=inventory(out)
    with pytest.raises(RuntimeError,match='complete wiki embedding'):
        index_bundle(out,embedder=Broken())
    assert inventory(out)==before
    assert not check_bundle(out)['ready_for_assessment']


def test_install_rejects_bundle_symlink(wiki,tmp_path):
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    link=tmp_path/'link';link.symlink_to(out,target_is_directory=True)
    target=tmp_path/'pipeline';target.mkdir()
    with pytest.raises(ValueError,match='symlink'):
        install_bundle(link,target)


def test_unlisted_file_is_rejected(wiki,tmp_path):
    out=tmp_path/'bundle';prepare(wiki,out,skip_indexes=True)
    (out/'unexpected.txt').write_text('unexpected')
    with pytest.raises(ValueError,match='inventory'):
        check_bundle(out)


def test_pitch_show_builds_machine_precedents_by_default(wiki, tmp_path, monkeypatch):
    import json
    from vclogic_onboarding import pitch_show, extraction
    from vc_clone_graph.precedents import PrecedentCorpus
    from vclogic_onboarding.configuration import embedding_settings
    from test_extraction import Provider, episode, proposal, verification
    def collect(slug, output, **kwargs):
        (output/'episodes').mkdir(parents=True)
        (output/'episodes/1-example.json').write_text(json.dumps(episode()))
        return {'episode_count': 1, 'complete': True}
    monkeypatch.setattr(pitch_show, 'collect', collect)
    monkeypatch.setattr(extraction, 'make_provider', lambda model=None: (Provider(proposal(), verification()), 'test-model'))
    class Embedder:
        metadata = embedding_settings()
        def embed(self, texts): return [[1., float(len(t)), .2] for t in texts]
    bundle = tmp_path/'machine-bundle'
    prepare(wiki, bundle, from_pitch_show=True, embedder=Embedder())
    assert check_bundle(bundle)['capabilities']['precedents']
    assert not (bundle/'evaluation').exists()
    assert (bundle/'inputs/indexes/test-investor.precedents.json').exists()
    workspace = tmp_path/'workspace'; workspace.mkdir()
    install_bundle(bundle, workspace)
    corpus = PrecedentCorpus.load(workspace/'inputs/indexes/test-investor.precedents.json',
        workspace/'inputs/data/investors/test-investor/precedents', Embedder(), require_complete_embeddings=True)
    assert corpus is not None
    record = json.loads((workspace/'inputs/data/investors/test-investor/precedents/records/1-example.json').read_text())
    assert record['decision']['status'] == 'Out'
    assert (workspace/record['decision']['audit_source']).is_file()


def test_collect_only_does_not_initialize_model(wiki, tmp_path, monkeypatch):
    from vclogic_onboarding import pitch_show, extraction
    def collect(slug, output, **kwargs):
        output.mkdir(parents=True)
        return {'episode_count': 0, 'complete': False}
    monkeypatch.setattr(pitch_show, 'collect', collect)
    monkeypatch.setattr(extraction, 'make_provider', lambda *a: pytest.fail('model initialization'))
    prepare(wiki, tmp_path/'collected', from_pitch_show=True, collect_only=True, skip_indexes=True)
    assert not check_bundle(tmp_path/'collected')['capabilities']['precedents']


def test_pitch_site_slug_can_differ_from_engine_slug(wiki,tmp_path,monkeypatch):
    from vclogic_onboarding import pitch_show
    site_slug='rohit-gupta--future-communities-capital'
    def collect(slug,output,**kwargs):
        assert slug==site_slug
        output.mkdir(parents=True)
        return {'episode_count':0,'complete':False}
    monkeypatch.setattr(pitch_show,'collect',collect)
    prepare(wiki,tmp_path/'bundle',from_pitch_show=True,pitch_show_slug=site_slug,
            collect_only=True,skip_indexes=True)
    assert check_bundle(tmp_path/'bundle')['vc_slug']=='test-investor'
