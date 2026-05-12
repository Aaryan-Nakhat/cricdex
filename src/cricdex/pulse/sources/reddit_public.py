"""Reddit fetcher via the public JSON endpoint (no auth).

Reddit serves a JSON view of any listing at `<url>.json` with the same
data the web UI uses. Requires only a clear `User-Agent` per Reddit's
rules; works without OAuth for read-only top/hot pulls. Rate limits
are softer than the OAuth API but exist — keep batches small.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

import httpx
from loguru import logger

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = "cricdex/0.1 (https://github.com/Aaryan-Nakhat/cricdex)"
DEFAULT_SUBS = ["Cricket", "ipl", "IndiaCricket", "PakCricket", "CricketShitpost"]


def fetch_subreddit_top(
    subreddit: str,
    period: str = "week",
    limit: int = 100,
    timeout: float = 30.0,
) -> list[dict]:
    """Return Reddit's top posts for the period (hour/day/week/month/year/all)."""
    url = f"{REDDIT_BASE}/r/{subreddit}/top.json"
    params = {"t": period, "limit": min(limit, 100)}
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=timeout, headers=headers) as cx:
        r = cx.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    children = data.get("data", {}).get("children", [])
    posts: list[dict] = []
    for c in children:
        d = c.get("data", {})
        posts.append(
            {
                "subreddit": subreddit,
                "id": d.get("id"),
                "title": d.get("title"),
                "selftext": (d.get("selftext") or "")[:2000],
                "url": d.get("url"),
                "permalink": f"https://reddit.com{d.get('permalink', '')}",
                "score": d.get("score"),
                "num_comments": d.get("num_comments"),
                "created_utc": d.get("created_utc"),
                "author": d.get("author"),
                "is_self": d.get("is_self"),
                "domain": d.get("domain"),
            }
        )
    return posts


def fetch_many(
    subs: Iterable[str] = DEFAULT_SUBS,
    period: str = "week",
    limit_per_sub: int = 100,
    sleep_between: float = 1.5,
) -> list[dict]:
    out: list[dict] = []
    for s in subs:
        try:
            posts = fetch_subreddit_top(s, period=period, limit=limit_per_sub)
            logger.info(f"r/{s}: pulled {len(posts)} top-{period} posts")
            out.extend(posts)
        except httpx.HTTPError as e:
            logger.warning(f"r/{s} failed: {e}")
        time.sleep(sleep_between)
    return out
