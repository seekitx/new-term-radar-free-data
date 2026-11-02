"""Per-sitemap snapshots and traceable page-level candidate phrases.

The first run of a newly configured competitor records a baseline only. Existing
upstream per-site snapshots are used as a conservative migration baseline. All
shards of a source must finish before any of its snapshots are replaced.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import snap, sitemaps
from .terms import by_source, surges

MAX_SHARDS = 150
MAX_PAGES = 2500000
KEEP_DAYS = 30
MAX_HISTORY = 5000
EXCLUDE_PATH = re.compile(r'/(?:category|categories|tag|tags|author|authors|archive|archives|feed|search)(?:/|$)', re.I)
INDEX_INCLUDE = re.compile(r'(?:post|article|product|tools?|games?|pages?)', re.I)
INDEX_EXCLUDE = re.compile(r'(?:category|categories|tags?|authors?|archive|taxonomy|attachment)', re.I)
YEAR = re.compile(r'^(?:19|20)\d\d$')
LOCALE = re.compile(r'^(?:[a-z]{2})(?:[-_][a-z]{2})?$', re.I)


def _name(tag):
    return tag.rsplit('}', 1)[-1].lower()


def _child(el, key):
    return next(((child.text or '').strip() for child in el if _name(child.tag) == key), '')


def _parse(text):
    root = ET.fromstring(text)
    typ = _name(root.tag)
    if typ not in ('urlset', 'sitemapindex'):
        raise ValueError('不支持的 Sitemap 格式')
    entries = []
    for child in root:
        if _name(child.tag) in ('url', 'sitemap'):
            loc = _child(child, 'loc')
            if loc:
                entries.append((loc, _child(child, 'lastmod')))
    return typ, entries


def _same_host(url, index):
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(index)
    def host(v): return (v.hostname or '').lower().removeprefix('www.')
    return a.scheme in ('http', 'https') and host(a) == host(b) and not a.username and not a.password


def _candidate(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    parts = [x for x in path.split('/') if x]
    if not parts:
        return ''
    slug = parts[-1]
    slug = re.sub(r'\.(?:html?|php|aspx?)$', '', slug, flags=re.I)
    slug = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', slug)
    words = re.split(r'[-_\s]+', slug)
    words = [w for w in words if w and not YEAR.fullmatch(w) and not re.fullmatch(r'\d{4,}', w)
             and not re.fullmatch(r'[0-9a-f]{12,}', w, re.I)]
    if not words or (len(words) == 1 and LOCALE.fullmatch(words[0])):
        return ''
    return ' '.join(words)[:180]


def _key(site, shard):
    return hashlib.sha256((site + '\n' + shard).encode()).hexdigest()[:24]


def _normal(url, strip_locale):
    return re.sub(sitemaps._LOCALE, r'\1', url) if strip_locale else url


def _shards(index, entry, fetch):
    text = fetch(index)
    typ, entries = _parse(text)
    if typ == 'urlset':
        return [(index, entries)], typ
    pattern = entry.get('shards')
    chosen = [loc for loc, _ in entries if (re.search(pattern, loc) if pattern else
              INDEX_INCLUDE.search(urllib.parse.urlsplit(loc).path) and not INDEX_EXCLUDE.search(urllib.parse.urlsplit(loc).path))]
    chosen = list(dict.fromkeys(chosen))
    if not chosen:
        raise ValueError('目录索引中没有匹配的内容子 Sitemap，请检查选择规则')
    if len(chosen) > MAX_SHARDS:
        raise ValueError(f'匹配到 {len(chosen)} 个子 Sitemap，超过 {MAX_SHARDS} 个上限；请缩小范围')
    outputs=[]
    for child in chosen:
        if not _same_host(child, index):
            raise ValueError('子 Sitemap 跨域，已跳过并保留旧记录')
        time.sleep(max(float(entry.get('pause', sitemaps.DEFAULT_PAUSE)), 0))
        child_type, pages = _parse(fetch(child))
        if child_type != 'urlset':
            raise ValueError('检测到嵌套索引，请指定更具体的内容 Sitemap')
        outputs.append((child,pages))
    return outputs, typ


def collect(cfg, state: Path, fetch):
    now = datetime.now(timezone.utc)
    snapshots = state / 'sitemap_shards'
    old_history = snap.load(state / 'sitemap_history.json.gz') or []
    source_versions = snap.load(state / 'sitemap_sources.json.gz') or {}
    pages_new, reports, recent, baseline = [], {}, [], []
    history = {(r['site'], r.get('canonical_url', r['url'])): r for r in old_history if r.get('site') and r.get('url')}
    for site, entry in cfg['sitemaps'].items():
        if entry.get('enabled', True) is False:
            reports[site] = {'skipped': True, 'new': 0, 'urls': 0}
            continue
        index = entry.get('index', '')
        site_slug = re.sub(r'[^A-Za-z0-9._-]', '_', site)
        legacy_data = snap.load(state / 'sitemaps' / f'{site_slug}.json.gz')
        legacy = set(legacy_data) if legacy_data is not None else None
        try:
            time.sleep(max(float(entry.get('pause', sitemaps.DEFAULT_PAUSE)), 0))
            shards, root_type = _shards(index, entry, fetch)
            version = hashlib.sha256(json.dumps([index, entry.get('shards'), bool(entry.get('strip_locale'))], ensure_ascii=False).encode()).hexdigest()
            previous_version = source_versions.get(site)
            changed = previous_version is not None and previous_version != version
            # The old collector treated an index without a shard selector as a list
            # of page URLs; it cannot serve as a baseline for the actual pages.
            if previous_version is not None or changed or (root_type == 'sitemapindex' and not entry.get('shards')):
                legacy = None
            if sum(len(pages) for _, pages in shards) > MAX_PAGES:
                raise ValueError('网址数量超过安全上限，请缩小监控范围')
            pending, local_new, local_recent, local_baseline = [], [], [], []
            baseline_shards, seen_urls = 0, set()
            old_sets = {}
            old_union = set(legacy or ())
            for shard, _ in shards:
                path = snapshots / (_key(site + version, shard) + '.json.gz')
                stored = snap.load(path)
                old = set(stored) if stored is not None else legacy
                old_sets[shard] = old
                if stored is not None:
                    old_union.update(stored)
            local_baseline = [(u, sitemaps.slug_text(u)) for u in old_union]
            for shard, raw_pages in shards:
                path = snapshots / (_key(site + version, shard) + '.json.gz')
                old = old_sets[shard]
                if old is None:
                    baseline_shards += 1
                now_urls = set()
                items=[]
                for url, lastmod in raw_pages:
                    if not _same_host(url,index) or EXCLUDE_PATH.search(urllib.parse.urlsplit(url).path):
                        continue
                    normalized = _normal(url, bool(entry.get('strip_locale')))
                    now_urls.add(normalized)
                    if normalized in seen_urls:
                        continue
                    seen_urls.add(normalized)
                    items.append((normalized, url, lastmod))
                if not now_urls:
                    raise ValueError('内容 Sitemap 没有可用网址，保留旧记录')
                if old is not None:
                    for normalized, original_url, lastmod in items:
                        if normalized in old_union:
                            continue
                        item={'site':site,'url':original_url,'canonical_url':normalized,'sitemap':shard,'candidate':_candidate(original_url),
                              'first_seen':now.isoformat(),'lastmod':lastmod or None,
                              'note':'候选词由网址提取，尚未验证搜索需求'}
                        local_new.append(item)
                        local_recent.append((normalized,sitemaps.slug_text(normalized)))
                pending.append((path,sorted(now_urls)))
            for path, data in pending:
                snap.save(path, data)
            source_versions[site] = version
            snap.save(state / 'sitemap_sources.json.gz', source_versions)
            for item in local_new:
                key=(item['site'],item['canonical_url'])
                if key not in history:
                    history[key]=item
                    pages_new.append(item)
            recent.extend(local_recent)
            baseline.extend(local_baseline)
            reports[site]={'urls':len(seen_urls),'new':len(local_new),'first_run':baseline_shards == len(shards),
                           'baseline_shards':baseline_shards,'shards':len(shards),'sample':[x['url'] for x in local_new[:8]]}
        except Exception as exc:
            reports[site]={'error':f'{type(exc).__name__}: {str(exc)[:180]}','new':0}
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    stored_history=sorted((r for r in history.values() if r.get('first_seen','') >= cutoff), key=lambda r:r.get('first_seen',''),reverse=True)
    truncated = len(stored_history) > MAX_HISTORY
    stored_history = stored_history[:MAX_HISTORY]
    snap.save(state / 'sitemap_history.json.gz', stored_history)
    ratio=len(recent)/max(len(baseline),1)
    return {'sites':reports,'terms':surges(by_source(recent),by_source(baseline),ratio,sitemaps.MIN_URLS,sitemaps.TOP),
            'pages':stored_history,'pages_new':len(pages_new),'history_days':KEEP_DAYS,'history_limit':MAX_HISTORY,'truncated':truncated}
