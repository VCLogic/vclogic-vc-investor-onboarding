"""Portable sidecar manifest, semantic coverage and filtered retrieval handoff."""
from __future__ import annotations

from pathlib import Path

from vc_clone_graph.precedent_builder import parse_speaker_turns
from vc_clone_graph.firewall import safe_slug

from .explanations import (VERSION, LINK_VERSION, Reason, ContextFact, ReviewItem,
                           explain, evidence_valid, stable_id, ExplanationArtifact)
from .policy_links import Link, LinkArtifact, guard_link, link_case, load_policies
from .files import digest, read_json, write_json, safe_relative

MANIFEST_VERSION = 'historical-explanation-manifest-v1'


def build_explanations(root, slug, aliases, rows, provider, model):
    safe_slug(slug, 'vc_slug')
    root = Path(root)
    policies = load_policies(root/'source/wiki', slug)
    by_episode = {r['episode_slug']: r for r in rows}
    base = root/f'inputs/data/investors/{slug}/explanations'
    entries = []
    for path in sorted((root/'source/pitch-show/episodes').glob('*.json')):
        episode = read_json(path)
        row = by_episode.get(episode['slug'], {'episode_slug': episode['slug'],
            'pitch_window_decision': 'Unobserved', 'decision_context': 'unclear',
            'evaluation_eligible': False, 'audit_notes': 'No usable transcript.'})
        case, receipt = explain(episode, row, slug, aliases, provider, model)
        source_rel = path.relative_to(root).as_posix()
        case['source'] = {'path': source_rel, 'sha256': digest(path)}
        case['investor_aliases'] = aliases
        links = link_case(case, policies, provider, receipt)
        ep = episode['slug']
        safe_relative(ep)
        if '/' in ep:
            raise ValueError('invalid episode slug')
        files = {'explanation': f'cases/{ep}.json', 'policy_links': f'links/{ep}.json'}
        write_json(base/files['explanation'], case)
        write_json(base/files['policy_links'], links)
        receipt.update(source=case['source'], case_id=case['case_id'])
        write_json(root/f'source/pitch-show/explanations/{ep}.json', receipt)
        record = root/f'inputs/data/investors/{slug}/precedents/records/{ep}.json'
        entries.append({'case_id': case['case_id'], 'episode_slug': ep,
            **{k: {'path': v, 'sha256': digest(base/v)} for k, v in files.items()},
            'record': {'path': record.relative_to(root).as_posix(), 'sha256': digest(record)} if record.exists() else None})
    manifest = {'schema_version': MANIFEST_VERSION, 'explanation_schema': VERSION,
        'policy_link_schema': LINK_VERSION, 'investor_slug': slug, 'cases': entries,
        'policy_artifact': {k: policies[k] for k in ('schema_version', 'sha256')} if policies else None}
    manifest['coverage'] = coverage([read_json(base/e['explanation']['path']) for e in entries],
                                    [read_json(base/e['policy_links']['path']) for e in entries])
    write_json(base/'manifest.json', manifest)
    return manifest['coverage']


def coverage(cases, links):
    return {'cases': len(cases),
        'observed_decisions': sum(c['decision']['pitch_window_decision'] in {'In', 'Out'} for c in cases),
        'supported_explanations': sum(c['status'] == 'supported' for c in cases),
        'explicit_controlling_reasons': sum(any(r['role'] == 'controlling' and r['interpretation'] == 'explicit' for r in c['reasons']) for c in cases),
        'established_vehicle_and_date': sum({'vehicle', 'date'} <= {f['field'] for f in c['context']} for c in cases),
        'usable_policy_links': sum(any(l['applicability_established'] and l['relationship'] not in {'unresolved', 'not_applicable'} for l in p['links']) for p in links),
        'missing_transcripts': sum(c.get('unavailable_reason') == 'missing_transcript' for c in cases),
        'ambiguous_cases': sum(c['decision']['pitch_window_decision'] == 'Unobserved' for c in cases),
        'verification_failed_cases': sum(bool(c['verification_failures']) or p['status'] == 'verification_failed' for c, p in zip(cases, links)),
        'rejected_interpretations': sum(len(c['rejected']) + len(p['rejected']) for c, p in zip(cases, links)),
        'policy_linking_unavailable': sum(p['status'] == 'unavailable' for p in links)}


def validate_explanations(root, slug):
    safe_slug(slug, 'vc_slug')
    root = Path(root)
    base = root/f'inputs/data/investors/{slug}/explanations'
    manifest = read_json(base/'manifest.json')
    if (manifest['schema_version'], manifest['explanation_schema'], manifest['policy_link_schema'], manifest['investor_slug']) != (MANIFEST_VERSION, VERSION, LINK_VERSION, slug):
        raise ValueError('incompatible explanation manifest')
    source_root = root/'source' if (root/'source/pitch-show').is_dir() else root/f'onboarding/{slug}/source'
    policies = load_policies(source_root/'wiki', slug)
    policy_ref = {k: policies[k] for k in ('schema_version', 'sha256')} if policies else None
    if manifest['policy_artifact'] != policy_ref:
        raise ValueError('policy version/hash mismatch')
    policy_ids = {p['id']: p for p in policies['data']['policies']} if policies else {}
    cases, links, seen = [], [], set()
    ledger_path = source_root/'pitch-show/extraction/corpus-ledger.json'
    ledger = {r['episode_slug']: r for r in read_json(ledger_path)}
    for entry in manifest['cases']:
        ep = entry['episode_slug']
        if ep in seen or '/' in ep or safe_relative(ep) != ep:
            raise ValueError('duplicate/invalid case episode')
        seen.add(ep)
        for key in ('explanation', 'policy_links'):
            location = entry[key]
            safe_relative(location['path'])
            if digest(base/location['path']) != location['sha256']:
                raise ValueError('explanation artifact hash mismatch')
        case = read_json(base/entry['explanation']['path'])
        link = read_json(base/entry['policy_links']['path'])
        ExplanationArtifact.model_validate(case)
        LinkArtifact.model_validate(link)
        expected_id = stable_id('case-', [slug, ep])
        if case['schema_version'] != VERSION or link['schema_version'] != LINK_VERSION or case['case_id'] != expected_id or link['case_id'] != expected_id or entry['case_id'] != expected_id or case['episode_slug'] != ep or link['episode_slug'] != ep or case['investor_slug'] != slug:
            raise ValueError('case identity/schema mismatch')
        if ep not in ledger and case['decision']['pitch_window_decision'] != 'Unobserved':
            raise ValueError('decision absent from source ledger')
        if ep in ledger and case['decision'] != ledger[ep]:
            raise ValueError('explanation changed original decision')
        source = case['source']
        if source['path'] != f'source/pitch-show/episodes/{ep}.json' or digest(source_root/'pitch-show/episodes'/f'{ep}.json') != source['sha256']:
            raise ValueError('explanation source mismatch')
        episode = read_json(source_root/'pitch-show/episodes'/f'{ep}.json')
        turns = parse_speaker_turns(episode.get('transcript') or '')
        record = entry['record']
        if record is not None:
            if record['path'] != f'inputs/data/investors/{slug}/precedents/records/{ep}.json' or digest(root/record['path']) != record['sha256']:
                raise ValueError('historical record mismatch')
        w = case['window']
        window = (w['start'], w['decision_turn']) if w else None
        if w and (not 0 <= w['start'] <= w['decision_turn'] <= w['end'] < len(turns) or w['decision_turn'] != case['decision'].get('evidence_turn_index')):
            raise ValueError('invalid original decision window')
        if any(r['timing'] != 'original' for r in case['reasons']) or any(r['timing'] == 'original' for r in case['separate_timing']):
            raise ValueError('mixed original and later explanations')
        ids = set()
        for reason in case['reasons'] + case['separate_timing']:
            raw = {k: v for k, v in reason.items() if k not in {'rationale_id', 'verification'}}
            r = Reason.model_validate(raw)
            if reason['rationale_id'] in ids:
                raise ValueError('duplicate rationale ID')
            ids.add(reason['rationale_id'])
            review = ReviewItem.model_validate(reason['verification'])
            if not review.accepted or not all(getattr(review, field) for field in ('speaker', 'quotation', 'decision_relevance', 'direction', 'importance', 'disposition', 'timing', 'conditions')):
                raise ValueError('unverified rationale in accepted evidence')
            ranks = {'unresolved': 0, 'secondary': 1, 'supporting': 2, 'controlling': 3}
            if review.key != r.key or ranks[r.role] > ranks[review.revised_role] or (review.revised_interpretation == 'inferred' and r.interpretation == 'explicit'):
                raise ValueError('stored reason exceeds reviewed interpretation')
            if reason['rationale_id'] != stable_id('rationale-', [expected_id, r.statement, [e.model_dump() for e in r.evidence]]):
                raise ValueError('rationale identity mismatch')
            if r.direction == 'neutral' and r.interpretation != 'explicit':
                raise ValueError('neutral direction must be explicit')
            if r.role == 'controlling' and (r.interpretation != 'explicit' or not r.decision_connection):
                raise ValueError('unsupported controlling rationale')
            if r.disposition in {'tolerated_concern', 'insufficient_strength'}:
                expected = ('In', 'negative') if r.disposition == 'tolerated_concern' else ('Out', 'positive')
                if (case['decision']['pitch_window_decision'], r.direction) != expected or r.interpretation != 'explicit' or not r.decision_connection:
                    raise ValueError('unsupported contrast')
            if r.timing == 'original' and not window:
                raise ValueError('missing decision window')
            for ref in r.evidence + r.decision_connection:
                evidence_valid(ref, turns, case['investor_aliases'], window if r.timing == 'original' else None)
        for fact in case['context']:
            f = ContextFact.model_validate(fact)
            for ref in f.evidence:
                evidence_valid(ref, turns, case['investor_aliases'] if f.field in {'vehicle', 'role'} else None, window)
        if link['policy_artifact'] != policy_ref:
            raise ValueError('linked policy hash/version mismatch')
        for item in link['links']:
            if not item['verification']['accepted'] or item['verification']['policy_id'] != item['policy_id'] or item['link_id'] != stable_id('link-', [expected_id, policy_ref['sha256'], item['policy_id']]):
                raise ValueError('invalid policy link verification/identity')
            if item['policy_id'] not in policy_ids:
                raise ValueError('unknown linked policy')
            proposed = Link.model_validate({k: item[k] for k in Link.model_fields})
            guarded = guard_link(proposed, policy_ids[item['policy_id']], case)
            if guarded['relationship'] != item['relationship'] or guarded['applicability_established'] != item['applicability_established'] or guarded['comparison_statuses'] != item['comparison_statuses']:
                raise ValueError('unsupported policy relationship/applicability')
        cases.append(case); links.append(link)
    expected = {p.stem for p in (source_root/'pitch-show/episodes').glob('*.json')}
    if seen != expected:
        raise ValueError('explanation coverage inventory mismatch')
    computed = coverage(cases, links)
    if computed != manifest['coverage']:
        raise ValueError('semantic coverage mismatch')
    return computed


def retrieve_cases(root, slug, *, allowed_episode_slugs, company_episodes,
                   held_out_company, excluded_episode_slugs=(), taxonomy_label=None):
    """Join after the caller's assessment firewall and company identity resolution.

    company_episodes is a trusted caller mapping of canonical company IDs to ALL
    linked episodes. Unknown held-out identity is an error, never permission.
    No cross-case backlinks, raw proposals, or unfiltered policy text are returned.
    """
    for company, episodes in company_episodes.items():
        if not isinstance(company, str) or not company.strip() or not isinstance(episodes, (list, tuple, set)):
            raise ValueError('company mapping must contain explicit episode collections')
        for episode in episodes:
            safe_slug(episode, 'episode_slug')
    if held_out_company not in company_episodes:
        raise ValueError('held-out company must be resolved to its linked episodes')
    excluded = set(excluded_episode_slugs) | set(company_episodes[held_out_company])
    # Expand aliases/overlapping company groups to a fixed point.
    changed = True
    while changed:
        before = len(excluded)
        for episodes in company_episodes.values():
            if excluded.intersection(episodes):
                excluded.update(episodes)
        changed = len(excluded) != before
    allowed = set(allowed_episode_slugs) - excluded
    validate_explanations(root, slug)
    base = Path(root)/f'inputs/data/investors/{slug}/explanations'
    manifest = read_json(base/'manifest.json')
    if manifest['schema_version'] != MANIFEST_VERSION or manifest['investor_slug'] != slug:
        raise ValueError('incompatible retrieval manifest')
    output = []
    for entry in manifest['cases']:
        if entry['episode_slug'] not in allowed:
            continue
        for kind in ('explanation', 'policy_links'):
            safe_relative(entry[kind]['path'])
            if digest(base/entry[kind]['path']) != entry[kind]['sha256']:
                raise ValueError('retrieval artifact hash mismatch')
        case = read_json(base/entry['explanation']['path'])
        links = read_json(base/entry['policy_links']['path'])
        if taxonomy_label and not any(taxonomy_label in r['taxonomy_labels'] for r in case['reasons']):
            continue
        record = entry['record']
        if record is None:
            continue
        safe_relative(record['path'])
        if digest(Path(root)/record['path']) != record['sha256']:
            raise ValueError('retrieval record hash mismatch')
        clean = {k: v for k, v in case.items() if k not in {'rejected', 'separate_timing'}}
        output.append({'case': read_json(Path(root)/record['path']), 'explanation': clean,
                       'policy_links': {k: v for k, v in links.items() if k != 'rejected'}})
    return output
