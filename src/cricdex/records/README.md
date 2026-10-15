# records

Searchable cricket records + On-This-Day digest, straight from the Cricsheet
ball-by-ball in DuckDB (`queries.py`).

- 9 record queries in `RECORDS`: highest individual innings, fastest fifty,
  fastest hundred, most sixes in an innings, career run leaders, best bowling
  in an innings, career wicket leaders, highest team totals, most runs in an
  over. Records are per innings; super overs are excluded.
- `on_this_day(month, day)` — notable 50+ innings and 4+ wicket spells from
  the same calendar date.

Used by the CLI `cricdex records`, the REST API (`/v1/records…`) and
`scripts/export_site.py`, which cooks `records.json` into the site snapshot
that the web, Streamlit and TUI Records pages read.
