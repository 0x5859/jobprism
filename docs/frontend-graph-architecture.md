# Frontend Graph Architecture

## Product shape

The site stays list-first. Graph visuals support exploration, but they do not replace the main browse flow.

- `/jobs`, `/companies/:id`, and `/skills/:id` remain the primary entry points.
- `/graph` is the secondary discovery surface for focused graph inspection.
- The right-hand detail pane is where local graph neighborhoods are rendered.

## Runtime split

### Global overview

The overview graph uses Sigma.js for the broader node/edge surface. It is intended for stable orientation across a larger graph and should favor readable structure over exhaustive detail.

### Local neighborhoods

Cytoscape.js powers small neighborhood graphs in the detail pane. These views stay compact, use preset coordinates when available, and degrade to a static SVG fallback if the library fails to load.

## Browser modules

The graph runtime is organized so the browser can load it from static files without a bundler:

- `graph-renderers.js`
  - mounts Sigma or Cytoscape into DOM containers
  - loads Graphology, Sigma.js, and Cytoscape from CDN at runtime
  - handles graceful fallback rendering when a graph library is unavailable
  - is safe for GitHub Pages because it relies only on browser ESM and runtime CDN scripts

## Data contract

The renderer expects the existing public JSON exports that back the site views:

- `graph.full.json`
- `job_neighbors.json`
- `company_jobs.json`
- `skill_jobs.json`
- `job_skills.json`
- `company_skill_stats.json`
- `jobs.json`
- `companies.json`
- `skills.json`
- `search-index.json`

No backend changes are required for the renderer itself.

## Deployment policy

The renderer remains compatible with a static GitHub Pages deployment:

- no Node-side runtime is required in the browser path
- graph libraries are loaded on demand from CDN
- SVG fallback rendering keeps the page usable if a library blocks or fails to load
- the static site shell can continue to be copied as-is into the Pages output directory
