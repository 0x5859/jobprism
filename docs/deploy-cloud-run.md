# Cloud Run deployment notes

This repository does not ship a production Cloud Run deployment, but the expected shape is:

1. package `apps/pipeline/` into a container
2. run a scheduled job that:
   - fetches raw data
   - normalizes
   - enriches
   - builds graph exports
3. publish artifacts to either:
   - a Git branch
   - object storage
   - a front-end build job

Suggested next steps for Codex:

- add a Dockerfile for the pipeline
- add environment-based source registry
- add provider-backed enrichment
- add artifact publishing target selection
