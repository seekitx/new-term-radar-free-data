#!/usr/bin/env python3
"""Collect only the upstream project's free public signals and publish a compact report."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

# Paid integrations must not inherit any credentials or enable the model judge.
for name in ('AISA_API_KEY','GOANYAPI_API_KEY','TRUSTMRR_API_KEY','RESEND_API_KEY'):
    os.environ.pop(name, None)
from radar import config, sources, breakout, sitemaps, sitemap_detail, feeds, report

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
state = ROOT / 'state'
state.mkdir(exist_ok=True)
cfg = config.load(ROOT / 'free-config.json')

# Check robots.txt for every sitemap and shard. If the policy cannot be checked, skip it.
robot_cache = {}
last_fetch = {}
original_fetch = sitemaps.fetch

def checked_fetch(url):
    parsed = urllib.parse.urlsplit(url.replace('&amp;', '&'))
    origin = f'{parsed.scheme}://{parsed.netloc}'
    if origin not in robot_cache:
        robots_url = origin + '/robots.txt'
        try:
            request = urllib.request.Request(robots_url, headers={'User-Agent': 'new-term-radar/0.2'})
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(500000).decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raw = ''
            else:
                raise RuntimeError(f'robots.txt unavailable (HTTP {exc.code})') from exc
        except Exception as exc:
            raise RuntimeError(f'robots.txt unavailable ({type(exc).__name__})') from exc
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(raw.splitlines())
        robot_cache[origin] = parser
    parser = robot_cache[origin]
    if not parser.can_fetch('new-term-radar', url):
        raise RuntimeError('robots.txt disallows this sitemap')
    delay = max(float(parser.crawl_delay('new-term-radar') or parser.crawl_delay('*') or 0), 0)
    remaining = delay - (time.monotonic() - last_fetch.get(origin, 0))
    if remaining > 0:
        time.sleep(remaining)
    last_fetch[origin] = time.monotonic()
    return original_fetch(url)
sitemaps.fetch = checked_fetch

def collect(fn):
    try:
        return fn()
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {str(exc)[:150]}', 'terms': []}

blocks = {
    'hf': collect(lambda: sources.hf_new(cfg, state)),
    'breakout': collect(lambda: breakout.breakouts(cfg, state)),
    'sitemap': collect(lambda: sitemap_detail.collect(cfg, state, checked_fetch)),
    'feed': collect(lambda: feeds.feeds(cfg, state)),
}
leads, judge = report.leads(cfg, blocks)
rows = []
for item in leads:
    about = item.get('about')
    url = about[0] if isinstance(about, (list, tuple)) and about else ''
    if item.get('repo'):
        url = 'https://github.com/' + item['repo']
    if not url and 'hf' in item.get('kinds', []):
        for example in item.get('examples', []):
            identifier = example.split(' (', 1)[0]
            if '/' in identifier and ' ' not in identifier:
                url = 'https://huggingface.co/' + identifier
                break
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        url = ''
    rows.append({'term':item.get('term', ''),'kinds':item.get('kinds', []),'signals':item.get('signals', []),
                 'examples':item.get('examples', [])[:2],'url':url})
statuses = []
for key, label in [('hf','Hugging Face 热门'),('breakout','GitHub 新项目')]:
    block = blocks[key]
    statuses.append({'id':key,'label':label,'status':'error' if block.get('error') else ('baseline' if block.get('first_run') else 'ok'),
                     'count':len(block.get('terms', [])), 'message':str(block.get('error',''))[:150]})
siteblock = blocks['sitemap']
for name in cfg['sitemaps']:
    item = siteblock.get('sites',{}).get(name,{})
    statuses.append({'id':'sitemap:'+name,'label':'网站目录 · '+name,'status':'disabled' if item.get('skipped') else ('error' if item.get('error') or siteblock.get('error') else ('baseline' if item.get('first_run') else ('partial' if item.get('baseline_shards') else 'ok'))),
                     'count':item.get('new',0),'message':str(item.get('error') or siteblock.get('error') or (f"其中 {item.get('baseline_shards')} 个内容清单首次建立对照。" if item.get('baseline_shards') and not item.get('first_run') else ''))[:150], 'shards':item.get('shards',0), 'baseline_shards':item.get('baseline_shards',0)})
fb = blocks['feed']
errors = fb.get('errors', [])
labels={'producthunt':'Product Hunt','hn':'Show HN','openrouter':'OpenRouter','civitai':'Civitai','appstore':'App Store','awesome':'GitHub 精选列表'}
for name in cfg['feeds']['enabled']:
    error = next((x for x in errors if x.startswith(name+':')), fb.get('error',''))
    statuses.append({'id':'feed:'+name,'label':labels.get(name,name),'status':'error' if error else ('baseline' if name in fb.get('first_run',[]) else 'ok'),
                     'count':len(fb.get('new',{}).get(name,[])),'message':str(error)[:150]})
now = datetime.now(timezone.utc).isoformat()
result = {'generated_at':now,'leads':rows,'sources':statuses,'mode':'free','version':2,
          'sitemap_pages':siteblock.get('pages', []), 'sitemap_new_count':siteblock.get('pages_new', 0),
          'sitemap_history_days':siteblock.get('history_days', 30), 'sitemap_truncated':siteblock.get('truncated', False),
          'competitors':[{'id':name,'index':site.get('index',''),'enabled':site.get('enabled',True),
                          'shards':site.get('shards','')} for name,site in cfg['sitemaps'].items()]}
out = ROOT / 'public' / 'latest.json'
out.parent.mkdir(exist_ok=True)
tmp = out.with_suffix('.tmp')
tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
tmp.replace(out)
print(json.dumps({'generated_at':now,'leads':len(rows),'ok':sum(s['status']=='ok' for s in statuses),
                  'baseline':sum(s['status']=='baseline' for s in statuses),'errors':sum(s['status']=='error' for s in statuses)},ensure_ascii=False))
