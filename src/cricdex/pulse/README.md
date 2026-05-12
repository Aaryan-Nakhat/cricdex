# pulse

Social-pulse analysis — player sentiment / themes / "buzz" extracted from
public cricket-community posts.

## What it does (v1)

1. `sources/reddit_public.py` pulls top-of-week posts from r/Cricket
   + r/ipl + r/IndiaCricket + r/PakCricket + r/CricketShitpost via
   the public `<sub>/top.json` endpoint (no OAuth needed in theory).
2. `sentiment.extract_mentions` sends each post (title + selftext) to
   Gemini Flash with a strict prompt asking for an array of
   `{player, sentiment, theme}` triples. Posts without a named
   cricketer are skipped.
3. `sentiment.aggregate` rolls the mention list into a per-player
   tally with positive / neutral / negative counts and a
   `weighted_score` weighted by post score + comment count.
4. Output:
    * `data/pulse/posts_<date>.jsonl` — raw fetched posts
    * `data/pulse/mentions_<date>.jsonl` — per-mention rows
    * `data/pulse/player_sentiment_<date>.json` — aggregated leaderboard

## Run

```bash
make docker-pulse-run PERIOD=week LIMIT=50
# or separately:
make docker-pulse-fetch PERIOD=week LIMIT=50
docker compose run --rm cricdex uv run python scripts/pulse.py extract data/pulse/posts_<date>.jsonl
```

## Known caveat — datacenter-IP blocking

Reddit blocks the public JSON endpoint from cloud datacenter IPs (we
get HTTP 403 from GCP). The pipeline is correct end to end; populate
from a non-datacenter network (laptop / home VPN), or wire OAuth via
the `praw` extra (`uv sync --extra bots`) and set `REDDIT_CLIENT_ID`
+ `REDDIT_CLIENT_SECRET` in `.env`. OAuth path is the next bolt-on
when actual data collection becomes the bottleneck.

Same pattern as the Wikidata module — code ships, data fetch is
deferred to a friendlier IP.
