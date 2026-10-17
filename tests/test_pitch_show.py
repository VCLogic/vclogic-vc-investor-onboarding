import json
from pathlib import Path

import httpx
import pytest

from vclogic_onboarding.pitch_show import collect

BASE = 'https://www.thepitch.show'
SLUG = 'alex-example'


def profile():
    return '<script type="application/ld+json">' + json.dumps({'@type': 'Person', 'name': 'Alex Example'}) + '</script><section><h2>Investments on The Pitch</h2><div><a href="/special-company"><h3>Company</h3></a><p>$50K</p><p>SAFE</p></div></section>'


def episode(investor=SLUG, transcript=True):
    data = {'@type': 'PodcastEpisode', 'name': 'Company', 'actor': [{'name': 'Founder'}, {'name': 'Alex Example', 'description': 'Investor', 'url': BASE + '/investors/' + investor}]}
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>' + ('<div id="transcript">Founder: Hello\nAlex: Interesting</div>' if transcript else '')


def fetcher(pages):
    def fetch(url):
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        return httpx.Response(200, text=value, request=httpx.Request('GET', url))
    return fetch


def pages():
    return {BASE + '/investors/' + SLUG: profile(), BASE + '/sitemap.xml': '<sitemapindex><sitemap><loc>' + BASE + '/episodes.xml</loc></sitemap></sitemapindex>', BASE + '/episodes.xml': '<urlset>' + ''.join('<url><loc>' + BASE + '/' + s + '</loc></url>' for s in ['1-company', '2-other']) + '</urlset>', BASE + '/1-company': episode(), BASE + '/2-other': episode('other-investor'), BASE + '/special-company': episode('other-investor')}


def read(path):
    return json.loads(path.read_text())


def test_collect_keeps_panel_and_investments_without_inventing_out(tmp_path):
    report = collect(SLUG, tmp_path / 'out', fetch=fetcher(pages()))
    out = tmp_path / 'out'
    assert report['complete'] is True
    assert {p.stem for p in (out / 'episodes').glob('*.json')} == {'1-company', 'special-company'}
    decisions = {r['episode_slug']: r for r in read(out / 'decisions.json')}
    assert decisions['1-company']['reported_decision'] == 'Unknown'
    assert decisions['special-company']['reported_decision'] == 'In'
    assert decisions['special-company']['check_size'] == '$50K'
    assert all(r['pitch_window_decision'] == 'Unobserved' for r in decisions.values())
    assert all(r['decision_context'] in {'unclear', 'off_panel'} for r in read(out / 'review-template.json'))
    assert list((out / 'sources').glob('*'))


def test_failures_missing_transcripts_and_cap_are_incomplete(tmp_path):
    p = pages()
    p[BASE + '/1-company'] = episode(transcript=False)
    p[BASE + '/2-other'] = RuntimeError('download failed')
    report = collect(SLUG, tmp_path / 'out', fetch=fetcher(p))
    assert not report['complete']
    assert any(r['url'] == BASE + '/2-other' for r in report['failures'])
    assert report['missing_transcripts'] == ['1-company']
    capped = collect(SLUG, tmp_path / 'capped', max_episodes=1, fetch=fetcher(pages()))
    assert not capped['complete']
    assert capped['capped']


@pytest.mark.parametrize('slug', ['../outside', 'UPPER', '', 'a/b', 'a%2fb'])
def test_unsafe_slug_rejected(tmp_path, slug):
    with pytest.raises(ValueError, match='slug'):
        collect(slug, tmp_path / 'out', fetch=lambda _: pytest.fail('network'))


def test_invalid_profile_rejected(tmp_path):
    with pytest.raises(ValueError, match='identity'):
        collect(SLUG, tmp_path / 'out', fetch=fetcher({BASE + '/investors/' + SLUG: '<h1>Not found</h1>'}))


def test_cache_original_and_collected_are_offline(tmp_path):
    cache = tmp_path / 'cache' / 'data'
    (cache / 'investors').mkdir(parents=True)
    (cache / 'episodes').mkdir()
    (cache / 'investors' / (SLUG + '.json')).write_text(json.dumps({'id': SLUG, 'name': 'Alex Example', 'investments': []}))
    (cache / 'episodes' / '1-company.json').write_text(json.dumps({'slug': '1-company', 'panel': [{'slug': SLUG}], 'founders': [], 'transcript': 'Founder: Hello'}))
    report = collect(SLUG, tmp_path / 'out', cache=cache.parent, fetch=lambda _: pytest.fail('network'))
    assert report['mode'] == 'cache'
    assert not report['complete']  # original cache has no proof of crawl coverage
    second = collect(SLUG, tmp_path / 'second', cache=tmp_path / 'out', fetch=lambda _: pytest.fail('network'))
    assert second['episode_count'] == 1


def test_cache_symlink_rejected(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'profile.json').symlink_to(tmp_path / 'outside.json')
    with pytest.raises(ValueError, match='symlink'):
        collect(SLUG, tmp_path / 'out', cache=cache)


def test_external_redirect_rejected(tmp_path):
    def fetch(url):
        return httpx.Response(302, headers={'location': 'http://169.254.169.254/latest'}, request=httpx.Request('GET', url))
    with pytest.raises(ValueError, match='official'):
        collect(SLUG, tmp_path / 'out', fetch=fetch)


def test_jsonld_graph_and_single_actor_are_supported(tmp_path):
    p = pages()
    p[BASE + '/investors/' + SLUG] = '<script type="application/ld+json">' + json.dumps({'@graph': [{'@type': 'Person', 'name': 'Alex Example'}]}) + '</script>'
    p[BASE + '/1-company'] = '<script type="application/ld+json">' + json.dumps({'@graph': [{'@type': 'PodcastEpisode', 'actor': {'name': 'Alex Example', 'description': 'Investor', 'url': BASE + '/investors/' + SLUG}}]}) + '</script><div id="transcript">Alex: Still considering it</div>'
    report = collect(SLUG, tmp_path / 'out', fetch=fetcher(p))
    assert report['episode_count'] == 1
    assert read(tmp_path / 'out' / 'decisions.json')[0]['reported_decision'] == 'Unknown'


def test_official_redirect_and_external_sitemap_are_bounded(tmp_path):
    p = pages()
    p[BASE + '/episodes.xml'] = '<urlset><url><loc>https://evil.example/1-test</loc></url></urlset>'
    seen = []
    def fetch(url):
        seen.append(url)
        assert url.startswith(BASE)
        if url == BASE + '/investors/' + SLUG:
            return httpx.Response(301, headers={'location': '/investors/' + SLUG + '/'}, request=httpx.Request('GET', url))
        return fetcher(p)(url.rstrip('/') if '/investors/' in url else url)
    result = collect(SLUG, tmp_path / 'out', fetch=fetch)
    assert not result['complete']
    assert any('official' in f['error'] for f in result['failures'])


def test_size_limit_rejected(tmp_path, monkeypatch):
    import vclogic_onboarding.pitch_show as module
    monkeypatch.setattr(module, 'MAX_BYTES', 10)
    with pytest.raises(ValueError, match='size limit'):
        collect(SLUG, tmp_path / 'out', fetch=fetcher(pages()))


def test_absolute_investment_link_preserves_reported_outcome(tmp_path):
    p = pages()
    p[BASE + '/investors/' + SLUG] = profile().replace('href="/special-company"', 'href="' + BASE + '/special-company"')
    collect(SLUG, tmp_path / 'out', fetch=fetcher(p))
    decisions = read(tmp_path / 'out' / 'decisions.json')
    assert any(row['episode_slug'] == 'special-company' and row['reported_decision'] == 'In' for row in decisions)


@pytest.mark.parametrize('mode', ['live', 'cache'])
def test_episode_cap_counts_matching_investor_episodes(tmp_path, mode):
    p = pages()
    p[BASE + '/investors/' + SLUG] = '<script type="application/ld+json">' + json.dumps({'@type': 'Person', 'name': 'Alex Example'}) + '</script>'
    p[BASE + '/1-company'] = episode('other-investor')
    p[BASE + '/2-other'] = episode()
    kwargs = {'fetch': fetcher(p)}
    if mode == 'cache':
        cache = tmp_path / 'cache'
        (cache / 'episodes').mkdir(parents=True)
        (cache / 'profile.json').write_text(json.dumps({'id': SLUG, 'name': 'Alex Example'}))
        for name, investor in [('1-company', 'other-investor'), ('2-other', SLUG)]:
            (cache / 'episodes' / (name + '.json')).write_text(json.dumps({'slug': name, 'panel': [{'slug': investor}], 'transcript': 'Hello'}))
        kwargs = {'cache': cache}
    report = collect(SLUG, tmp_path / 'out', max_episodes=1, **kwargs)
    assert report['episode_count'] == 1
    assert (tmp_path / 'out' / 'episodes' / '2-other.json').is_file()
    assert report['examined_count'] == 2
    assert not report['capped']  # All candidates were examined.


def test_live_client_respects_environment_proxy(tmp_path, monkeypatch):
    original_client = httpx.Client
    options = {}
    def client(**kwargs):
        options.update(kwargs)
        return original_client(transport=httpx.MockTransport(lambda request: fetcher(pages())(str(request.url))), **kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    assert collect(SLUG, tmp_path / 'out')['complete']
    assert options.get('trust_env', True) is True


def test_live_jsonld_actor_ids_match_investor_panel(tmp_path):
    p = pages()
    p[BASE + '/1-company'] = '<script type="application/ld+json">' + json.dumps({'@graph': [{'@type': 'PodcastEpisode', 'actor': [
        {'@type': 'Person', '@id': BASE + '/founders/example#person', 'name': 'Founder'},
        {'@type': 'Person', '@id': BASE + '/investors/' + SLUG + '#person', 'name': 'Alex Example'},
    ], 'transcript': 'Founder: Hello\nAlex: Still considering it'}]}) + '</script>'
    report = collect(SLUG, tmp_path / 'out', fetch=fetcher(p))
    assert report['episode_count'] == 2
    ep = read(tmp_path / 'out' / 'episodes' / '1-company.json')
    assert ep['panel'][0]['slug'] == SLUG
    assert [f['name'] for f in ep['founders']] == ['Founder']
    assert ep['transcript'] == 'Founder: Hello\nAlex: Still considering it'
    assert not report['missing_transcripts']


def test_failed_candidate_does_not_consume_matching_episode_limit(tmp_path):
    p = pages()
    p[BASE + '/special-company'] = RuntimeError('temporary failure')
    report = collect(SLUG, tmp_path / 'out', fetch=fetcher(p), max_episodes=1)
    assert report['episode_count'] == 1
    assert (tmp_path / 'out' / 'episodes' / '1-company.json').is_file()
    assert report['examined_count'] == 2
    assert report['capped']
    assert not report['complete']


def test_matching_episode_limit_stops_further_downloads(tmp_path):
    seen = []
    def fetch(url):
        seen.append(url)
        return fetcher(pages())(url)
    report = collect(SLUG, tmp_path / 'out', fetch=fetch, max_episodes=1)
    assert report['episode_count'] == 1
    assert report['examined_count'] == 1
    assert BASE + '/1-company' not in seen
    assert BASE + '/2-other' not in seen


def test_official_investor_slug_can_contain_consecutive_hyphens(tmp_path):
    site_slug = 'rohit-gupta--future-communities-capital'
    p = {url.replace(SLUG, site_slug): body.replace(SLUG, site_slug)
         for url, body in pages().items()}
    report = collect(site_slug, tmp_path/'out', fetch=fetcher(p))
    assert report['complete']
    assert report['episode_count'] == 2
