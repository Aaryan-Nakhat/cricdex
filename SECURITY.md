# Security

## Reporting a problem

Please report a security issue privately, not in a public issue. Use GitHub's
**Report a vulnerability** button on the repository's Security tab (private
vulnerability reporting). Say what you found, how to reproduce it and what it
affects. You should get a reply within a week. Please give a fix time to ship
before you talk about it in public.

## What is hardened

**GitHub Actions**

- Every third-party action is pinned to a full commit SHA (the version is in
  a comment next to it), so a moved tag can't change what runs.
- Every workflow's token is read-only by default. Only the refresh job may
  write (it commits the re-cooked data), and only the Pages deploy job gets the
  Pages and OIDC permissions.
- Checkouts keep no credential on disk. The refresh job hands its token to
  the one `git push` that needs it, so the ingest, model and LLM steps never
  see it.
- Manual inputs reach the shell through environment variables, never pasted
  into the script. The refresh's collection list must be league keys from
  `config/leagues.toml`; anything else stops the run.
- Python installs use the lock file (`uv sync --locked`, `UV_LOCKED=1`), so a
  run can't pick up an unreviewed package version.
- The LLM settings and key are given only to the two steps that call the LLM.

**LLM answers**

The player taxonomy and the display-name check come from an LLM, so their
answers are treated as untrusted input. `cricdex.scout.identity.taxonomy`
checks every field against a fixed list (roles, bowling styles, batting
slots, hands, confidence, country codes) or a bounded plain-text name, both
when an answer is saved and when a cached file is read. A bad value is dropped
with a logged warning.

**Website**

The site sets a Content-Security-Policy in `site/index.html` (GitHub Pages
can't send headers). Scripts, styles, fonts and data load only from the site
itself; the one inline script is allowed by its hash, computed at build time
(`site/vite.config.ts`). Images may also come from Wikimedia (player photos).
`object-src` is `none`.

**Docker**

The image runs as an unprivileged user, not root. Compose publishes the API
and dashboard on `127.0.0.1` only. Set `CRICDEX_BIND=0.0.0.0` to expose them,
and put a proxy with auth in front first: the API has no login.

## Known gaps

- The Pages deploy runs on a push to `main` without waiting for CI to pass.
- Some locked dependencies have published advisories (`uv audit`,
  `pnpm audit`); most are in development tools. Upgrades are tracked
  separately.
