"""Validated, versioned investor bundles and conflict-checked installation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
import tempfile
import tomllib

from vc_clone_graph.config import load_config
from vc_clone_graph.firewall import safe_slug, verify_package, validate_precedent_corpus
from vc_clone_graph.precedents import PrecedentCorpus
from vc_clone_graph.rehearsal_config import load_rehearsal_config
from vc_clone_graph.retrieval import HybridWikiIndex
from wiki_build.check_wiki import validate as validate_wiki

from .configuration import embedding_settings, resource, write_configs, write_toml
from .files import digest, inventory, read_json, reject_symlinks, safe_relative, write_json

SCHEMA='vclogic-investor-bundle-v1'


class _IndexIdentity:
    """Inspect saved index metadata without loading a model or making calls."""
    metadata=embedding_settings()


def _embedder():
    from vc_clone_graph.providers.sentence_transformers import SentenceTransformerEmbeddingProvider
    from .configuration import template
    cfg=template('canonical.toml')['embedding']
    cfg={k:v for k,v in cfg.items() if k not in {'kind','require_complete_index'}}
    return SentenceTransformerEmbeddingProvider(**cfg)


def _wiki_valid(path: Path) -> None:
    errors=validate_wiki(path)
    if errors:
        raise ValueError('wiki validation failed: '+'; '.join(errors[:8]))


def _seal(root: Path,metadata: dict) -> dict:
    metadata={**metadata,'files':inventory(root)}
    write_json(root/'bundle.json',metadata)
    return metadata


def _build_indexes(root: Path,metadata: dict,embedder=None) -> None:
    embedder=embedder if embedder is not None else _embedder()
    slug=metadata['vc_slug']; inputs=root/'inputs'
    target=inputs/f'indexes/{slug}.json';target.parent.mkdir(parents=True,exist_ok=True)
    HybridWikiIndex.build(inputs/f'wiki/{slug}',embedder,require_complete_embeddings=True).save(target)
    if metadata['capabilities']['precedents']:
        PrecedentCorpus.build(inputs/f'data/investors/{slug}/precedents',embedder,
            require_complete_embeddings=True).save(inputs/f'indexes/{slug}.precedents.json')
    metadata['ready_for_assessment']=True


def prepare(wiki: Path,output: Path,*,slug=None,display_name=None,firm=None,role=None,aliases=(),
            from_pitch_show=False,pitch_show_slug=None,pitch_show_cache=None,review=None,
            skip_indexes=False,embedder=None,max_episodes=None,collect_only=False,decision_model=None) -> dict:
    wiki=Path(wiki);output=Path(output)
    reject_symlinks(wiki,recursive=True);reject_symlinks(output)
    wiki=wiki.resolve(strict=True);output=output.absolute()
    if output.exists():
        raise ValueError(f'output already exists: {output}; choose a new bundle version')
    if output.is_relative_to(wiki):
        raise ValueError('output must not be inside the source wiki')
    if (review or pitch_show_cache or pitch_show_slug or max_episodes is not None or collect_only or decision_model) and not from_pitch_show:
        raise ValueError('Pitch Show options require --from-pitch-show')
    if collect_only and decision_model:
        raise ValueError('--decision-model cannot be used with --collect-only')
    decision_provider = None
    if from_pitch_show and not collect_only:
        from .extraction import make_provider
        decision_provider, decision_model = make_provider(decision_model)
    _wiki_valid(wiki)
    manifest=read_json(wiki/'_manifest.json');prepared=read_json(wiki/'prepared.json')
    if manifest['vc_slug']!=prepared['vc_slug']:
        raise ValueError('source wiki identities disagree')
    slug=safe_slug(slug or manifest['vc_slug'],'vc_slug')
    identity=prepared.get('identity') or {}
    name=display_name or identity.get('canonical_name')
    if not isinstance(name,str) or not name.strip():
        raise ValueError('investor display name is missing; supply --display-name')
    investor_aliases=list(dict.fromkeys([name,*identity.get('aliases',[]),*aliases]))
    if not all(isinstance(a,str) and a.strip() for a in investor_aliases):
        raise ValueError('investor aliases must be nonempty strings')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.onboarding-',dir=output.parent) as tmp:
        root=Path(tmp)/'bundle';root.mkdir()
        source=root/'source/wiki';shutil.copytree(wiki,source)
        _wiki_valid(source)
        target=root/f'inputs/wiki/{slug}';target.mkdir(parents=True)
        selected=['persona.md','theses.md','portfolio_and_constraints.md','sources.md','context.md']
        selected += [p.relative_to(source).as_posix() for p in sorted((source/'evidence').glob('*.md'))]
        for relative in selected:
            original=source/relative
            if original.is_file():
                dst=target/relative;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,dst)
        write_toml(root/f'inputs/investors/{slug}.toml',{
            'vc_slug':slug,'display_name':name,'firm':firm or '', 'role':role or 'Investor',
            'wiki_path':f'wiki/{slug}','speaker_names':investor_aliases,
            'check_tiers':['no_check_tier','small_exploratory','standard_initial','larger_conviction']})
        taxonomy=root/'inputs/taxonomy/codebook_v_final.json';taxonomy.parent.mkdir(parents=True);taxonomy.write_bytes(resource('taxonomy.json'))
        metadata={'schema':SCHEMA,'vc_slug':slug,'display_name':name,'created_at':datetime.now(timezone.utc).isoformat(),
            'source_wiki_slug':manifest['vc_slug'],'source_generated_at':manifest.get('generated_at'),
            'source_warnings':manifest.get('warnings',[]),'ready_for_assessment':False,
            'capabilities':{'wiki':True,'precedents':False,'portfolio_memory':False,'classifier':False},
            'eligible_pitches':[],'pitch_show':None}
        if from_pitch_show:
            from .pitch_show import collect, validate_investor_slug
            site_slug=validate_investor_slug(pitch_show_slug or slug)
            metadata['pitch_show']=collect(site_slug,root/'source/pitch-show',
                cache=Path(pitch_show_cache) if pitch_show_cache else None,max_episodes=max_episodes)
            if review:
                from .dataset import enrich
                review=Path(review);reject_symlinks(review)
                shutil.copy2(review,root/'source/pitch-show/review.json')
                enrichment=enrich(root,slug,root/'source/pitch-show/review.json',investor_aliases,site_slug)
                metadata['capabilities']['precedents']=enrichment['precedent_records']>0
                metadata['eligible_pitches']=enrichment['eligible_pitches']
                metadata['dataset']=enrichment
            if not collect_only:
                from .extraction import enrich_machine
                extraction=enrich_machine(root,slug,investor_aliases,decision_provider,decision_model)
                metadata['extraction']=extraction
                metadata['capabilities']['historical_explanations']=True
                metadata['capabilities']['policy_case_links']=(root/'source/wiki/policies.json').exists()
                metadata['semantic_coverage']=extraction['semantic_coverage']
                metadata['capabilities']['precedents']=extraction['precedent_records']>0
        write_configs(root,slug,precedents=metadata['capabilities']['precedents'])
        if not skip_indexes:
            _build_indexes(root,metadata,embedder)
        _seal(root,metadata);check_bundle(root)
        os.rename(root,output)
    return read_json(output/'bundle.json')


def check_bundle(bundle: Path) -> dict:
    root=Path(bundle);reject_symlinks(root,recursive=True)
    metadata=read_json(root/'bundle.json')
    if metadata.get('schema')!=SCHEMA:
        raise ValueError('unsupported bundle schema')
    slug=safe_slug(metadata['vc_slug'],'vc_slug')
    declared=metadata.get('files')
    if not isinstance(declared,dict):
        raise ValueError('bundle file manifest is missing')
    for relative in declared:
        safe_relative(relative)
        _install_path(relative,slug)  # Also enforces the allowed bundle layout.
    actual=inventory(root)
    if set(actual)!=set(declared):
        raise ValueError('bundle file inventory mismatch')
    if actual!=declared:
        raise ValueError('bundle file hash mismatch')
    _wiki_valid(root/'source/wiki')
    registry=tomllib.loads((root/f'inputs/investors/{slug}.toml').read_text())
    if registry.get('vc_slug')!=slug or registry.get('wiki_path')!=f'wiki/{slug}':
        raise ValueError('investor registration does not match bundle')
    canonical=load_config(root/f'configs/investors/{slug}/canonical.toml')
    rehearsal=load_rehearsal_config(root/f'configs/investors/{slug}/rehearsal.toml')
    capabilities=metadata['capabilities']
    if (canonical.run.vc_slug!=slug or canonical.precedents.enabled!=capabilities['precedents']
        or rehearsal.precedents.enabled!=capabilities['precedents']
        or canonical.portfolio_memory.enabled or rehearsal.portfolio_memory.enabled
        or rehearsal.classification.canonical_config_path!=f'configs/investors/{slug}/canonical.toml'):
        raise ValueError('bundle configuration capabilities disagree')
    for episode in metadata['eligible_pitches']:
        verify_package(root/'inputs',slug,safe_slug(episode,'episode_slug'))
    if capabilities['precedents']:
        validate_precedent_corpus(root/f'inputs/data/investors/{slug}/precedents')
    if metadata['ready_for_assessment']:
        HybridWikiIndex.load(root/f'inputs/indexes/{slug}.json',root/f'inputs/wiki/{slug}',
            _IndexIdentity(),require_complete_embeddings=True)
        if capabilities['precedents']:
            PrecedentCorpus.load(root/f'inputs/indexes/{slug}.precedents.json',root/f'inputs/data/investors/{slug}/precedents',
                _IndexIdentity(),require_complete_embeddings=True)
    semantic_coverage=None
    if capabilities.get('historical_explanations'):
        from .explanation_bundle import validate_explanations
        semantic_coverage=validate_explanations(root,slug)
        if semantic_coverage != metadata.get('semantic_coverage'):
            raise ValueError('bundle semantic coverage mismatch')
        if capabilities.get('policy_case_links') != (root/'source/wiki/policies.json').exists():
            raise ValueError('policy capability mismatch')
    return {'semantic_coverage':semantic_coverage,'valid':True,'vc_slug':slug,'ready_for_assessment':metadata['ready_for_assessment'],
            'capabilities':capabilities,'files':len(actual),'pitch_show':metadata['pitch_show'],
            'extraction':metadata.get('extraction')}


def index_bundle(bundle: Path,*,embedder=None) -> dict:
    root=Path(bundle).absolute();check_bundle(root)
    # Build off to the side. A failed model download or index build leaves the
    # previously valid bundle intact; indexes and the receipt publish last.
    with tempfile.TemporaryDirectory(prefix='.onboarding-index-',dir=root.parent) as tmp:
        staged=Path(tmp)/'bundle';shutil.copytree(root,staged)
        metadata=read_json(staged/'bundle.json');_build_indexes(staged,metadata,embedder)
        _seal(staged,metadata);check_bundle(staged)
        backup=Path(tmp)/'previous';os.rename(root,backup)
        try: os.rename(staged,root)
        except BaseException:
            os.rename(backup,root);raise
    return check_bundle(root)


def _install_path(relative: str,slug: str) -> str:
    safe_relative(relative)
    if relative.startswith('source/'):
        return f'onboarding/{slug}/{relative}'
    exact={f'inputs/investors/{slug}.toml','inputs/taxonomy/codebook_v_final.json',
           f'inputs/indexes/{slug}.json',f'inputs/indexes/{slug}.precedents.json',f'evaluation/labels/{slug}.json'}
    prefixes=(f'inputs/wiki/{slug}/',f'inputs/data/investors/{slug}/',f'configs/investors/{slug}/')
    if relative not in exact and not relative.startswith(prefixes):
        raise ValueError(f'file is outside investor bundle scope: {relative}')
    return relative


def install_bundle(bundle: Path,workspace: Path) -> dict:
    root=Path(bundle);check_bundle(root);root=root.resolve()
    target=Path(workspace).absolute();reject_symlinks(target)
    if not target.is_dir():
        raise ValueError('pipeline workspace must be an existing directory')
    if target==root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('bundle and pipeline workspace must be separate')
    metadata=read_json(root/'bundle.json');slug=metadata['vc_slug']
    planned=[(root/rel,target/_install_path(rel,slug)) for rel in metadata['files']]
    planned.append((root/'bundle.json',target/f'onboarding/{slug}/bundle.json'))
    pending=[]
    for source,destination in planned:
        reject_symlinks(destination)
        for ancestor in destination.parents:
            if ancestor==target: break
            if ancestor.exists() and not ancestor.is_dir():
                raise ValueError(f'install conflict: {ancestor}')
        if destination.exists():
            if not destination.is_file() or digest(source)!=digest(destination):
                raise ValueError(f'install conflict: {destination}; existing versions are never overwritten')
        else: pending.append((source,destination))
    created=[];directories=[]
    try:
        for source,destination in pending:
            missing=[];parent=destination.parent
            while not parent.exists(): missing.append(parent);parent=parent.parent
            for directory in reversed(missing): directory.mkdir();directories.append(directory)
            # Exclusive create protects against another installer appearing after preflight.
            with destination.open('xb') as stream:
                created.append(destination)
                with source.open('rb') as original: shutil.copyfileobj(original,stream)
            if digest(destination)!=digest(source): raise ValueError('installed file hash mismatch')
    except BaseException:
        for path in reversed(created): path.unlink(missing_ok=True)
        for directory in reversed(directories):
            try: directory.rmdir()
            except OSError: pass
        raise
    return {'vc_slug':slug,'workspace':str(target),'installed_files':len(created),
            'ready_for_assessment':metadata['ready_for_assessment']}
