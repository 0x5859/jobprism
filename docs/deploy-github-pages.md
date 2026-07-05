# GitHub Pages deployment notes

The site is pure static HTML + ES-module JS — no bundler, no framework. CI
builds `dist/` with real data and publishes it to GitHub Pages.

## How the production build works

`.github/workflows/pages.yml` runs on three triggers:

| Trigger | Purpose |
|---|---|
| `push` to `main` | Deploy code changes |
| `schedule` (daily, 00:00 UTC = 08:00 Beijing) | Refresh job data even without pushes |
| `workflow_dispatch` | Manual re-run from the Actions tab |

Each run executes `scripts/build_site.sh`, which feeds two data channels
into the pipeline:

1. **Live fetch** — the public job-board APIs in `source-config.ci.json`
   (greenhouse / lever / ashby; stdlib `urllib` only, no Playwright).
   A failing board is logged in the source-registry report and skipped
   (`--continue-on-error`); it never fails the deploy.
2. **Committed snapshots** — `data/snapshots/*.jsonl`, produced locally by
   the Playwright crawler for Chinese company sites (tencent/bytedance).
   Refresh flow: run the crawler per
   `includes/company_site_crawler_bundle/README.md`, copy the JSONL into
   `data/snapshots/`, commit, push — the next Pages run picks it up.

## First-time setup (one-off, after pushing to GitHub)

1. Repository **Settings → Pages → Build and deployment → Source**:
   select **GitHub Actions** (not "Deploy from a branch").
2. Push to `main` (or trigger the workflow manually). The `deploy` job
   prints the site URL.

## Local equivalents

```bash
# Production build (live APIs + snapshots) — same as CI:
bash scripts/build_site.sh

# Fixture-only demo (offline, no network):
bash scripts/run_demo.sh

# Serve the result:
python3 -m http.server 8765 --directory dist
```

## Notes

- The site uses relative asset/data paths (`./data/...`), so it works under
  a project-page base path (`https://<user>.github.io/<repo>/`) without a
  bundler `base` option.
- `dist/` is disposable: every CI run rebuilds it from scratch. Do not edit
  files in `dist/` directly — change `apps/web/site/` (shell) or the
  pipeline (data) instead.
