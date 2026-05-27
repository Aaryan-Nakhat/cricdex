# Shipping CricDex for free

Every option below costs $0. They're not mutually exclusive — the
recommended ship is **PyPI + GHCR + (optional) HF Spaces**, which
covers install-and-run, Docker, and a clickable browser demo at no
cost.

CricDex is **terminal-first**, so the natural distribution is a
package people install — not a server you pay to keep running. The
hosted options exist for people who'd rather click a URL than
`pip install`.

---

## The dependency map (what actually needs to run)

Before picking a host, know what each component requires:

| Component | Runtime need | Free-ship friendliness |
|---|---|---|
| DuckDB (analytics) | none — a file | trivial, ships in the package |
| Qdrant (rule vectors) | embedded on-disk mode, no server | trivial — `QDRANT_URL` unset → on-disk |
| Cricsheet data (~600 MB) | persistent disk OR rebuild on boot | the main sizing constraint |
| **Neo4j (scout graph)** | a running server | **the only hard dependency** |
| Gemini (rules answer, match reports, translate) | API key / proxy | optional; features degrade without it |
| Snowflake-arctic-embed model (~2 GB) | downloaded once, or pre-baked | pre-baked in the Docker image |

**Key fact:** everything except Neo4j runs serverless (file/embedded).
The scout-graph features (Twins, find-replacement, war-room advisor's
graph cohort) need Neo4j. They already **soft-fail** with a clear
message when the `neo4j` extra isn't installed — so a Neo4j-less ship
still works for the other 9 surfaces.

Neo4j options when you want graph features hosted:
- **Neo4j Aura Free** — cloud, 200k nodes / 400k relationships. The
  IPL graph (~600 players + edges) fits comfortably. Set `NEO4J_URI`
  / `NEO4J_USER` / `NEO4J_PASSWORD` to the Aura instance.
- Run Neo4j as a second container locally (the dev compose does this).

---

## Option 1 — PyPI publish (recommended; the actual product)

Make `pip install cricdex` work for anyone. This is the truest ship
for a terminal-first tool — the user runs it locally, owns their own
`~/.cricdex/data/`, and there's no server to keep alive.

**What's already in place:** `pyproject.toml` declares the
`[project.scripts] cricdex = "cricdex.cli:main"` entry point and the
optional extras (`[cli,graph,ui]`).

**Steps:**

```bash
# 1. Build the wheel + sdist
uv build                       # → dist/cricdex-0.1.0-py3-none-any.whl + .tar.gz

# 2. Dry-run on TestPyPI first (separate account + token)
uv publish --index testpypi    # or: twine upload --repository testpypi dist/*
#    verify: pip install -i https://test.pypi.org/simple/ cricdex

# 3. Publish for real
uv publish                     # uses PYPI_TOKEN env / ~/.pypirc
```

**Cost:** free forever. PyPI hosts the package; users pull it.

**Caveat:** the heavy deps (torch, jax, numpyro, xgboost,
sentence-transformers) make `pip install cricdex` a large download.
Mitigate by keeping the base install lean and gating the heavy bits
behind extras: base `cricdex` = CLI + DuckDB metrics; `cricdex[graph]`
= +neo4j; `cricdex[ml]` = +numpyro/xgboost/torch; `cricdex[ui]` =
+streamlit/textual. Most users want `cricdex[cli,ui]`.

**One-line install for a user after publish:**

```bash
uvx --from 'cricdex[cli,ui]' cricdex     # zero-install try
pip install 'cricdex[cli,ui]'            # permanent
cricdex init                             # first-run wizard
```

---

## Option 2 — GHCR Docker image (already automated)

`docker-push.yml` already builds `ghcr.io/aaryan-nakhat/cricdex` on
every push to main and tags it `:latest` + `:sha-<short>` +
`:vX.Y.Z` on a git tag. GHCR hosts public images free.

**User pulls it:**

```bash
make docker-up-prod    # composes the prebuilt image + Qdrant
```

**Cost:** free (public GHCR). **Caveat:** the image is ~9.8 GB (torch
+ jax + xgboost + transformers + pre-baked embed model). The pull is
heavy but skips the ~10-min local build.

**To ship a release image:** tag the repo —

```bash
git tag -a v0.1.0 -m "CricDex v0.1.0"
git push origin v0.1.0          # fires docker-push.yml for :v0.1.0
```

---

## Option 3 — HuggingFace Spaces (clickable browser demo)

A public URL running the Streamlit dashboard, free. HF Spaces gives
16 GB Docker, 2 vCPU, but **ephemeral disk** — anything not in the
image is wiped on restart.

**Strategy for the data problem:**
- Pre-bake the small artifacts (rules Qdrant index ~57 MB, metrics
  JSONs ~few MB, Bayes ratings JSON) into the image at build time.
- Skip the 600 MB raw Cricsheet DuckDB — the dashboard reads the
  pre-computed metric JSONs, not the raw balls, for most pages. Only
  Venues + Records + Profile-career hit DuckDB; ship a trimmed
  `balls_ipl` Parquet (~80 MB) or disable those pages in the demo.
- Neo4j via **Aura Free** (env vars in the Space's secrets) or
  disable Twins/advisor in the demo.

**Files needed:**
- `Dockerfile` for the Space (HF reads a `Dockerfile` at repo root or
  a `space` branch) with `CMD ["streamlit", "run",
  "src/cricdex/dashboard/app.py", "--server.port=7860"]` (HF expects
  port 7860).
- `README.md` front-matter with `sdk: docker` + `app_port: 7860`.
- `GEMINI_API_KEY` + Neo4j creds in Space secrets.

**Cost:** free. **Caveat:** cold-start rebuild on every restart; demo
data only.

---

## Option 4 — Oracle Cloud Always Free (full stack, 24/7)

The only free option that runs the **entire** stack persistently —
DuckDB + Qdrant + Neo4j + the API + the dashboard — with real disk.

**What you get free forever:** an ARM Ampere A1 VM up to 4 vCPU /
24 GB RAM / 200 GB block storage. Enough for the 600 MB data + 9.8 GB
image + Neo4j.

**Steps (high level):**
1. Create an Always-Free ARM VM (Ubuntu 22.04).
2. Install Docker + Compose.
3. `git clone` + `make docker-up-prod` (the compose pulls the GHCR
   image; note ARM — the CI image is amd64, so either build on the VM
   or add an arm64 build to `docker-push.yml` via buildx
   `--platform linux/amd64,linux/arm64`).
4. Open the firewall for the dashboard / API port.
5. Point a free domain (DuckDNS / a Cloudflare-proxied subdomain) at
   the VM IP.

**Cost:** free. **Caveat:** ARM build needed; some setup + ongoing
patching is on you.

---

## Option 5 — Streamlit Community Cloud (dashboard only) — NOT recommended

Free, dead-simple (`point at the GitHub repo`), but the **1 GB
resource cap** can't hold the 600 MB DuckDB + Qdrant index +
embed-model download. Workable only for a heavily-trimmed demo
reading pre-computed JSONs and with the model pulled at runtime
(slow cold start). Use HF Spaces (Option 3) instead — same idea, 16×
the disk.

---

## Recommended ship sequence

1. **Tag `v0.1.0`** → fires the GHCR release image (Option 2). Free,
   already wired.
2. **Publish to PyPI** (Option 1) → `pip install cricdex` works. This
   is the headline ship for a terminal tool.
3. **(Optional) HF Spaces demo** (Option 3) → a clickable dashboard
   URL for people who won't install. Pre-bake the small artifacts,
   point Neo4j at Aura Free.

All three are $0. Steps 1–2 are an afternoon; step 3 is a half-day of
Dockerfile + data-trimming work.

### Pre-publish checklist

- [ ] `pyproject.toml` — version, description, authors, license,
      `classifiers`, `project.urls` (Homepage/Repository/Issues).
- [ ] `README.md` renders cleanly as the PyPI long-description.
- [ ] Extras split so base install is lean (see Option 1 caveat).
- [ ] `LICENSE` present (MIT).
- [ ] `uv build` produces a clean wheel; `uvx --from
      ./dist/cricdex-*.whl cricdex --help` works in a fresh venv.
- [ ] TestPyPI dry-run succeeds before the real `uv publish`.
- [ ] Secrets scrubbed — no `GEMINI_TMP_URL`, HF tokens, or work
      proxy URLs baked into the package or image.
