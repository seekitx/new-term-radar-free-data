"""Read recent Stack Exchange questions without the upstream paid classification flow."""
from __future__ import annotations

import gzip
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import UA

API = "https://api.stackexchange.com/2.3/"
WINDOW_DAYS = 7
PAGE_SIZE = 50
MAX_PAGES = 3


def candidate(title: str) -> str:
    """Conservatively clean the question title; this is not a search-volume claim."""
    text = re.sub(r"\s+", " ", html.unescape(title)).strip(" ?!.:;–—-")
    text = re.sub(
        r"^(?:is there (?:a|an|any) |can (?:the |i |we )?|(?:looking|searching) for (?:a|an|any) |"
        r"(?:recommend|recommendation for|suggestions? for) (?:a|an|any)?\s*|"
        r"(?:how (?:can|do) (?:i|we)|how to)\s+)", "", text, flags=re.I,
    ).strip(" ?!.:;–—-")
    words = text.split()
    return " ".join(words[:18]).strip(" ,;:–—-") if len(words) >= 2 else ""


def _fetch(path: str, params: dict) -> dict:
    url = API + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    if data.get("error_id"):
        raise RuntimeError(str(data.get("error_message") or data["error_id"]))
    return data


def collect(cfg: dict) -> dict:
    """Fetch each source independently; preserve failures and API pagination limits."""
    now = datetime.now(timezone.utc)
    since = int((now - timedelta(days=WINDOW_DAYS)).timestamp())
    settings = cfg["asks"]
    requests = [("questions", site, {}) for site in settings["stack_all"]]
    requests += [("search", site, {"intitle": query})
                 for site in settings["stack_sites"] for query in settings["stack_titles"]]
    rows, errors, seen, backoff, trace = [], [], set(), {}, []
    incomplete = False
    successful = 0
    for path, site, extra in requests:
        detail = {"site": site, "title_contains": extra.get("intitle"), "received": 0, "kept": 0, "duplicates_or_missing_id": 0}
        trace.append(detail)
        try:
            for page in range(1, MAX_PAGES + 1):
                wait = backoff.get(path, 0) - time.monotonic()
                if wait > 60:
                    raise RuntimeError("来源要求较长等待时间，本次跳过")
                if wait > 0:
                    time.sleep(wait)
                data = _fetch(path, {"site": site, "order": "desc", "sort": "creation", "fromdate": since,
                                     "pagesize": PAGE_SIZE, "page": page, **extra})
                if page == 1:
                    successful += 1
                backoff[path] = time.monotonic() + max(0, int(data.get("backoff") or 0))
                for question in data.get("items", []):
                    detail["received"] += 1
                    key = (site, question.get("question_id"))
                    if not key[1] or key in seen:
                        detail["duplicates_or_missing_id"] += 1
                        continue
                    seen.add(key)
                    detail["kept"] += 1
                    owner = question.get("owner") or {}
                    title = html.unescape(question.get("title") or "")
                    rows.append({"id": f"{site}:{key[1]}", "site": site, "title": title,
                                 "candidate": candidate(title), "url": question.get("link") or "",
                                 "created_at": datetime.fromtimestamp(question.get("creation_date", 0), timezone.utc).isoformat(),
                                 "score": int(question.get("score") or 0),
                                 "author": html.unescape(owner.get("display_name") or "已注销用户"),
                                 "author_url": owner.get("link") or "",
                                 "license": question.get("content_license") or "CC BY-SA"})
                if not data.get("has_more"):
                    break
                if page == MAX_PAGES:
                    incomplete = True
        except Exception as exc:
            detail["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
            errors.append(f"{site}: {type(exc).__name__}: {str(exc)[:100]}")
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return {"questions": rows, "window_days": WINDOW_DAYS, "errors": errors,
            "successful": successful, "total_sources": len(requests), "truncated": incomplete, "trace": trace}
