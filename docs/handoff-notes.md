# Handoff notes for Codex

## What is intentionally complete enough to keep

- CLI command surface
- SQLite truth schema
- public JSON export contract
- adapter interfaces
- enrichment pipeline shape
- graph build shape
- minimal site assembly script

## What is intentionally heuristic and should be upgraded

- company alias config
- skill taxonomy config
- remote mode inference
- role family inference
- seniority inference
- similarity scoring
- evidence extraction
- HTML fallback extraction
- demo site UI

## Recommended next implementation passes

### Pass 1

- Add unit tests.
- Add JSON Schema validation in all write paths.

### Pass 2

- Add embeddings-backed job similarity.
- Add config-driven source registry.
- Add response caching / retries for remote enrichment providers.

### Pass 3

- Add direct path routing or 404 redirect handling for GitHub Pages.
- Add Cytoscape or Sigma integration.
- Add richer filters, sorting, and search ranking.

### Pass 4

- Add production deploy:
  - GitHub Actions for MVP
  - Cloud Run Jobs + Scheduler for heavier workloads
