```
     ██╗ ██████╗ ██████╗     ██████╗ ██████╗ ██╗███████╗███╗   ███╗
     ██║██╔═══██╗██╔══██╗    ██╔══██╗██╔══██╗██║██╔════╝████╗ ████║
     ██║██║   ██║██████╔╝    ██████╔╝██████╔╝██║███████╗██╔████╔██║
██   ██║██║   ██║██╔══██╗    ██╔═══╝ ██╔══██╗██║╚════██║██║╚██╔╝██║
╚█████╔╝╚██████╔╝██████╔╝    ██║     ██║  ██║██║███████║██║ ╚═╝ ██║
 ╚════╝  ╚═════╝ ╚═════╝     ╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚═╝     ╚═╝
```

# Job Prism

An interactive recruitment graph that you explore like a night sky — jobs,
companies, and skills as one living, drifting web. One prism, many angles on
the same market.

## Start from a skill, find the job

Ordinary job boards run one direction: **company → job → skill**. You browse
openings, click in, and only then discover what they demand.

Job Prism adds the reverse. Start from a skill you already have — say
`Python` or `大模型` — and the graph fans out to the companies that value it
and the roles you could actually fill. **Skill → company → job.** You pick
work by what you can do, instead of scrolling listings hoping to match.

Both directions live in the same graph, so you can walk it either way and
pivot at any node.

## Highlights

- **Skill-first browsing** — reverse the usual flow and hunt for jobs by capability.
- **Obsidian-style force graph** — nodes scatter organically, drift with a
  continuous simulation, and are fully draggable; expanding a node unfolds its
  neighborhood with a fluid camera glide.
- **Depth-of-field + particle encoding** — each node type has its own color,
  size, and particle signature (amber-sun skills, ringed-planet companies,
  satellite jobs); deeper layers dim so multi-level expansions stay readable.
- **Bilingual (中 / EN)** — Chinese and English postings coexist in one graph.
- **Fresh data, daily** — a GitHub Actions cron re-fetches live job boards and
  redeploys automatically.
- **Static & free to host** — plain HTML + ES modules, no backend, publishes to
  GitHub Pages.

## How it works

A small Python ETL pipeline (fetch → normalize → dedupe → enrich → build graph
→ export JSON) feeds a static front end. Data arrives on two channels:

1. **Live public APIs** — Greenhouse, Lever, and Ashby job boards
   (`source-config.ci.json`). Standard-library `urllib` only; no scraping, no
   anti-bot risk. Re-fetched on every push and on a daily schedule.
2. **Committed snapshots** — Chinese company career sites (e.g. Tencent /
   ByteDance campus) are crawled locally with the optional Playwright bundle and
   committed as JSONL under `data/snapshots/`.

The pipeline itself is intentionally simple: Python standard library, SQLite as
the truth store, validated JSON exports for the site.

## Quick start

```bash
# Offline demo on bundled fixtures (no network):
bash scripts/run_demo.sh

# Production build — live APIs + committed snapshots (same as CI):
bash scripts/build_site.sh

# Serve the result:
python3 -m http.server 8765 --directory dist
```

## Deploy to GitHub Pages

Push to `main`, then set **Settings → Pages → Source** to **GitHub Actions**.
The workflow builds `dist/` and deploys it; a daily cron keeps the data fresh.
See [docs/deploy-github-pages.md](docs/deploy-github-pages.md).

## Refreshing Chinese company data

Chinese career sites need a headless browser, so they can't run in CI. Refresh
them locally:

```bash
cd includes/company_site_crawler_bundle
pip install -r requirements.txt && playwright install chromium
# crawl, then copy the JSONL into data/snapshots/, commit, and push
```

See [includes/company_site_crawler_bundle/README.md](includes/company_site_crawler_bundle/README.md).

## Open-source components

This project stands on open-source work, gratefully acknowledged:

**Front-end libraries** (loaded from cdnjs at runtime, MIT-licensed):

| Library | Version | License |
|---|---|---|
| [Sigma.js](https://www.sigmajs.org/) | 3.0.2 | MIT |
| [Graphology](https://graphology.github.io/) | 0.26.0 | MIT |
| [Cytoscape.js](https://js.cytoscape.org/) | 3.33.1 | MIT |

**Fonts** (via Google Fonts, SIL Open Font License 1.1):
[Instrument Sans](https://fonts.google.com/specimen/Instrument+Sans),
[IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono),
[Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC).

**Python** — the pipeline uses the standard library only. The optional crawler
bundle uses [Playwright](https://playwright.dev/) (Apache-2.0),
[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) (MIT), and
[lxml](https://lxml.de/) (BSD-3-Clause).

**Data** comes from the public Greenhouse, Lever, and Ashby job-board APIs. Job
content belongs to the respective companies; please respect their terms of use.

## License

[MIT](LICENSE) © 2026 0x5859
