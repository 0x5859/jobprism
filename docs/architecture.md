# Architecture

## Core idea

A public recruitment graph system has three layers:

1. **Acquisition**
   - ATS adapters
   - JSON-LD extraction
   - HTML fallback

2. **Truth layer**
   - raw records
   - normalized jobs
   - companies
   - skills
   - enrichment artifacts
   - graph edges

3. **Read layer**
   - public static JSON
   - list pages
   - graph views
   - search index

## Pipeline flow

```text
[ATS/API/JSON-LD/HTML]
        ↓
   collectors
        ↓
 normalize + dedupe
        ↓
   enrichment
        ↓
  graph builder
        ↓
 SQLite (truth) + public JSON exports
```

## Design constraints

- Public site must not hold secrets.
- Raw data should be preserved for replay.
- The database should remain replaceable.
- The graph is the truth, not the UI tree.

## Why SQLite first

SQLite is enough for:

- local development
- batch normalization
- demo deployments
- exporting public JSON

If the project later needs concurrency, APIs, or multi-tenant behavior, the same schema can move to Postgres.
