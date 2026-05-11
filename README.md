# CricDex

Open cricket intelligence platform.

## Modules

| Module | Status | What |
|---|---|---|
| `scout` | planned P0 | Player graph + opposition-bridged ratings spanning pro → semi-pro → grassroots (Cricsheet + Cricinfo + Cricbuzz + BCCI Domestic + CricHeroes). |
| `metrics` | planned P0 | Novel context-adjusted ratings (Pressure Runs, Intent Curve, Recoverability, Sticky Dot Pressure, Wicket Quality, NGI/WAR-cricket, etc). |
| `rules` | planned P0 | Natural-language Q&A over all cricket rulebooks (MCC Laws + ICC Playing Conditions Test/ODI/T20I + IPL + Hundred + BBL + SA20 + ILT20 + MLC + CPL + LPL + WPL + Domestic). |
| `pulse` | planned P1 | Social trend analysis across Reddit + Bluesky + YouTube + Telegram + Twitter (paid spot scrape). Sentiment, rumor detection, hype-reality gap. |
| `auction` | planned P1 | Multi-agent RL auction simulator with per-franchise personality priors. |
| `drs` | planned P1 | DRS scenario simulator + umpire/scorer practice gamification. |
| `records` | planned P1 | Searchable records DB + On-This-Day digest. |
| `reports` | planned P1 | Auto-generated post-match reports from ball-by-ball + social pulse. |
| `predict` | planned P1 | Daily prediction game with leaderboard (no money). |
| `live` | planned P1 | Live match insights surfacer (WP, novel stat tags). |
| `venues` | planned P1 | Pitch + conditions archive per venue. |
| `profiles` | planned P1 | Public claimable player profiles. |
| `comparator` | planned P1 | Visual career side-by-side. |
| `newsletter` | planned P1 | Per-user/team digest engine. |
| `commentary_translate` | planned P1 + voice-clone P3 | Live commentary translation into Hindi/Tamil/Bengali/Urdu/Sinhala. Final feature: voice-cloned target-language TTS in original commentator's voice. |
| `api` | planned P1 | Public REST/GraphQL API. |

Deferred year-2: OpenBoundary (Hawk-Eye OSS), ChuckCheck (elbow flex), Voice analyst, ScoutVLM (video → ball-by-ball), Highlight CV, Tournament B2B.

## Setup

```bash
uv sync --group dev
cp .env.example .env
```

## Layout

```
src/cricdex/        Python package, one subfolder per module
data/               raw + processed datasets (gitignored)
notebooks/          exploration
scripts/            one-off + maintenance
tests/              pytest
docs/               architecture, roadmap, decisions
```

## License

MIT.
