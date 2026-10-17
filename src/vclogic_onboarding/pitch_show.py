"""Collect official Pitch Show evidence without inferring audited decisions."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .pitch_parsers.episode import parse_episode
from .pitch_parsers.investor import parse_investor

BASE = 'https://www.thepitch.show'
MAX_BYTES = 12 * 1024 * 1024
_SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def _slug(value):
    if not isinstance(value, str) or len(value) > 200 or not _SLUG.fullmatch(value):
        raise ValueError(f'invalid slug: {value!r}')
    return value


def validate_investor_slug(value):
    # Official profile identifiers may contain consecutive hyphens.
    if not isinstance(value, str) or len(value) > 200 or not re.fullmatch(r'[a-z0-9]+(?:-+[a-z0-9]+)*', value):
        raise ValueError(f'invalid investor slug: {value!r}')
    return value


def _official(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'www.thepitch.show', 'thepitch.show'} or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f'URL must use the official HTTPS host: {url}')
    return url


def _write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _safe_cache(root):
    root = root.absolute()
    for part in [root, *root.parents]:
        if part.is_symlink():
            raise ValueError(f'cache symlink is not allowed: {part}')
    if not root.is_dir():
        raise ValueError(f'cache directory does not exist: {root}')
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'cache symlink is not allowed: {path}')
    return root


def collect(slug: str, output: Path, *, cache: Path | None = None,
            max_episodes: int | None = None, fetch=None) -> dict:
    """Write canonical evidence files; fetch, if supplied, is callable(url)->Response.

    Cache mode never calls fetch. Completeness describes source collection, never
    human label audit. An original scraper cache cannot prove crawl coverage.
    """
    validate_investor_slug(slug)
    if max_episodes is not None and (isinstance(max_episodes, bool) or not isinstance(max_episodes, int) or max_episodes < 1):
        raise ValueError('max_episodes must be a positive integer')
    output = Path(output).absolute()
    if any(p.is_symlink() for p in [output, *output.parents]):
        raise ValueError('output symlink is not allowed')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('output must be a new or empty directory')
    cache_root = _safe_cache(Path(cache)) if cache is not None else None
    output.mkdir(parents=True, exist_ok=True)
    (output / 'episodes').mkdir()
    (output / 'sources').mkdir()
    profile_url = BASE + '/investors/' + slug
    report = {'schema_version': 1, 'investor_slug': slug, 'mode': 'cache' if cache_root else 'live',
              'complete': False, 'capped': False, 'failures': [], 'missing_transcripts': [],
              'episode_count': 0, 'examined_count': 0, 'sources': [], 'coverage_notes': []}
    client = httpx.Client(timeout=30, follow_redirects=False, trust_env=True) if cache_root is None and fetch is None else None

    def download(url):
        original = _official(url)
        for _ in range(6):
            _official(url)
            if client is not None:
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        url = _official(urljoin(url, response.headers['location']))
                        continue
                    response.raise_for_status()
                    chunks, length = [], 0
                    for chunk in response.iter_bytes():
                        length += len(chunk)
                        if length > MAX_BYTES:
                            raise ValueError('response exceeds size limit')
                        chunks.append(chunk)
                    body = b''.join(chunks)
                    final_url = str(response.url)
            else:
                response = fetch(url)
                if isinstance(response, str):
                    body, final_url = response.encode(), url
                else:
                    _official(str(response.url))
                    for previous in response.history:
                        _official(str(previous.url))
                    if response.is_redirect:
                        url = _official(urljoin(url, response.headers['location']))
                        continue
                    response.raise_for_status()
                    body, final_url = response.content, str(response.url)
            if len(body) > MAX_BYTES:
                raise ValueError('response exceeds size limit')
            _official(final_url)
            digest = hashlib.sha256(body).hexdigest()
            name = hashlib.sha256(original.encode()).hexdigest()[:20] + '.txt'
            (output / 'sources' / name).write_bytes(body)
            report['sources'].append({'url': original, 'final_url': final_url, 'path': 'sources/' + name, 'sha256': digest})
            return body.decode('utf-8', errors='replace')
        raise ValueError('too many redirects')

    def failure(url, exc):
        report['failures'].append({'url': url, 'error': f'{type(exc).__name__}: {exc}'})

    try:
        previous_report = None
        if cache_root:
            source = cache_root / 'profile.json'
            episode_root = cache_root / 'episodes'
            if not source.exists():
                data_root = cache_root / 'data' if (cache_root / 'data').is_dir() else cache_root
                source = data_root / 'investors' / (slug + '.json')
                episode_root = data_root / 'episodes'
            profile = json.loads(source.read_text())
            report['sources'].append({'cache_path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
            if (cache_root / 'collection.json').exists():
                previous_report = json.loads((cache_root / 'collection.json').read_text())
            else:
                report['coverage_notes'].append('Original cache has no verifiable crawl completeness record.')
        else:
            profile = parse_investor(BeautifulSoup(download(profile_url), 'html.parser'), profile_url)
        if not isinstance(profile, dict) or not isinstance(profile.get('name'), str) or not profile['name'].strip() or profile.get('id', slug) != slug:
            raise ValueError('investor profile lacks valid matching identity')
        profile['id'] = slug
        profile.setdefault('profile_url', profile_url)
        _write(output / 'profile.json', profile)
        investments = {}
        for investment in profile.get('investments') or []:
            ep_slug = _slug(investment.get('episode_slug'))
            investments[ep_slug] = investment
        episodes = []
        matched = set()

        def retain_candidate(ep):
            ep_slug = _slug(ep.get('slug'))
            if ep_slug not in matched and (ep_slug in investments or any(
                    p.get('slug') == slug for p in ep.get('panel') or [])):
                matched.add(ep_slug)
                episodes.append(ep)

        def limit_reached():
            if max_episodes is not None and len(matched) >= max_episodes:
                report['capped'] = True
                return True
            return False
        if cache_root:
            if not episode_root.is_dir():
                failure(str(episode_root), ValueError('episode cache missing'))
            paths = sorted(episode_root.glob('*.json'))
            report['candidate_count'] = len(paths)
            for path in paths:
                if limit_reached():
                    break
                report['examined_count'] += 1
                try:
                    ep = json.loads(path.read_text())
                    _slug(ep.get('slug'))
                    if path.stem != ep['slug']:
                        raise ValueError('cache episode slug does not match filename')
                    retain_candidate(ep)
                    report['sources'].append({'cache_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
                except Exception as exc:
                    failure(str(path), exc)
        else:
            urls = { _official(inv.get('episode_url') or BASE + '/' + key) for key, inv in investments.items() }
            pending, visited = [BASE + '/sitemap.xml'], set()
            while pending:
                url = pending.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                if len(visited) > 100:
                    failure(url, ValueError('sitemap count limit exceeded'))
                    break
                try:
                    xml = ElementTree.fromstring(download(url))
                    index = xml.tag.split('}')[-1] == 'sitemapindex'
                    for node in xml.iter():
                        if node.tag.split('}')[-1] != 'loc' or not node.text:
                            continue
                        loc = _official(node.text.strip())
                        if index:
                            pending.append(loc)
                        else:
                            path = urlsplit(loc).path.strip('/')
                            # Crawl every root content slug, including nonnumeric episodes.
                            if _SLUG.fullmatch(path):
                                urls.add(loc)
                except Exception as exc:
                    failure(url, exc)
            ordered = sorted(urls, key=lambda u: (u not in {i.get('episode_url') for i in investments.values()}, u))
            report['candidate_count'] = len(ordered)
            for url in ordered:
                if limit_reached():
                    break
                report['examined_count'] += 1
                try:
                    ep_slug = _slug(urlsplit(url).path.strip('/'))
                    retain_candidate(parse_episode(BeautifulSoup(download(url), 'html.parser'), ep_slug, url))
                except Exception as exc:
                    failure(url, exc)
        decisions, review, retained = [], [], set()
        for ep in episodes:
            ep_slug = _slug(ep.get('slug'))
            on_panel = any(p.get('slug') == slug for p in ep.get('panel') or [])
            if not on_panel and ep_slug not in investments:
                continue
            if ep_slug in retained:
                continue
            retained.add(ep_slug)
            _write(output / 'episodes' / (ep_slug + '.json'), ep)
            if not isinstance(ep.get('transcript'), str) or not ep['transcript'].strip():
                report['missing_transcripts'].append(ep_slug)
            inv = investments.get(ep_slug)
            reported = 'In' if inv is not None else 'Unknown'
            decisions.append({'episode_slug': ep_slug, 'investor_slug': slug, 'on_panel': on_panel,
                              'reported_decision': reported, 'pitch_window_decision': 'Unobserved',
                              'source_urls': [profile_url, ep.get('url') or BASE + '/' + ep_slug],
                              'check_size': inv.get('check_size') if inv else None,
                              'deal_terms': inv.get('deal_terms') if inv else None})
            review.append({'episode_slug': ep_slug, 'final_decision': reported, 'pitch_window_decision': 'Unobserved',
                           'initial_response': 'Unobserved', 'decision_context': 'unclear' if on_panel else 'off_panel',
                           'label_basis': 'Profile-reported investment; timing unaudited.' if inv else 'No audited decision evidence.',
                           'audit_notes': 'Human transcript review required; no pitch-window label inferred.',
                           'founder_aliases': [p['name'] for p in ep.get('founders') or [] if p.get('name')], 'on_panel': on_panel})
        for ep_slug in sorted(set(investments) - retained):
            failure(investments[ep_slug].get('episode_url') or BASE + '/' + ep_slug, ValueError('reported investment episode unavailable'))
        report['episode_count'] = len(retained)
        report['complete'] = not (report['capped'] or report['failures'] or report['missing_transcripts'])
        if cache_root:
            report['complete'] = report['complete'] and bool(previous_report and previous_report.get('complete'))
            if previous_report:
                report['coverage_notes'].append('Cache completeness inherited from collection.json; no network revalidation.')
                report['failures'].extend(previous_report.get('failures', []))
        _write(output / 'decisions.json', decisions)
        _write(output / 'review-template.json', review)
        _write(output / 'sources' / 'receipts.json', report['sources'])
        _write(output / 'collection.json', report)
        return report
    finally:
        if client:
            client.close()
