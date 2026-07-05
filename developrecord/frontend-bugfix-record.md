# Frontend Bugfix Record

This file records the recent frontend bugfix work using commits as anchors.

## Commit Marker: `bb7e9a9` `Fix Sigma renderer field collisions in the overview graph`

### Scope

This commit finalized the Sigma runtime hotfix that followed the redesign5 frontend adoption.

Changed file:

- [apps/web/site/graph-renderers.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/graph-renderers.js)

### Problem

The overview graph mounted Sigma canvases, but the graph still failed at runtime because business graph fields were colliding with Sigma's reserved renderer fields.

Observed browser errors:

- `Sigma: could not find a suitable program for node type "job"!`
- `Sigma: could not find a suitable program for edge type "POSTS"!`

### Fix

Inside `createSigmaData(snapshot)`:

- changed node payload field from `type` to `nodeType`
- changed edge payload field from `type` to `edgeType`

This kept the app's business semantics while avoiding Sigma renderer field collisions.

### Validation

1. Syntax checks:

   ```bash
   node --check apps/web/site/graph-renderers.js
   ```

2. Rebuilt the demo site:

   ```bash
   bash scripts/run_demo.sh
   ```

3. Browser-level verification:

   - confirmed the page loaded
   - confirmed the default job state opened
   - confirmed search suggestions were visible
   - confirmed Sigma canvases were mounted in `#graphStage`
   - confirmed the prior Sigma `node type` / `edge type` errors were gone

### Result

After this commit:

- the page no longer failed with `Failed to load graph data`
- the overview stage rendered without the prior Sigma type-collision errors
- the redesign5 shell remained intact
- the default job preview and search interaction remained usable

## Commit Marker: `0c70918` `Adopt redesign5 frontend experience`

### Context

This commit switched the frontend to the redesign5 UI model:

- left rail search and route tabs
- center graph overview
- right detail reading pane
- Sigma.js for the overview
- Cytoscape.js for local graphs

After this switch, the page shell rendered, but the center radar / overview graph did not visibly show nodes.

### Observed symptom

- The page loaded.
- Search suggestions were visible.
- The graph stage existed and Sigma canvas layers were mounted.
- Users reported that the radar view appeared empty.

### Reproduction path

1. Rebuild the site with:

   ```bash
   bash scripts/run_demo.sh
   ```

2. Serve the site locally:

   ```bash
   python -m http.server 8001 -d dist
   ```

3. Open `http://localhost:8001`.

### Diagnostic steps

1. Verified static assets and JSON endpoints:

   - `dist/index.html`
   - `dist/app.js`
   - `dist/data/*.json`

   All were present and returned `200`.

2. Verified that Sigma was mounting canvases into `#graphStage`.

3. Ran a temporary Playwright-based browser inspection from a throwaway local environment under `/tmp/jobviz-pw`.

4. Captured the real runtime error from the browser:

   - `Sigma: could not find a suitable program for node type "job"!`
   - later also confirmed the same class of issue for edge type handling

### Root cause

The data passed into Sigma used the field name `type` for business semantics:

- node business type such as `job`, `company`, `skill`
- edge business type such as `POSTS`, `REQUIRES`, `SIMILAR_TO`

Sigma also treats `type` as an internal renderer selection field.
That caused Sigma to look for renderer programs named after business values like `job` and `POSTS`, which do not exist.

### Follow-up note

The Sigma runtime bug introduced by this redesign was fixed in the later commit:

- `bb7e9a9` `Fix Sigma renderer field collisions in the overview graph`

## Notes

- Future key frontend bugfixes should be appended as new `Commit Marker` sections in this same file.

## Commit Marker: `working tree after 36b4aab` `Preserve Sigma overview camera across node expansion`

### Scope

This hotfix keeps the radar / overview camera stable when users click nodes to expand or collapse hierarchy layers.

Changed files:

- [apps/web/site/graph-renderers.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/graph-renderers.js)
- [apps/web/site/app.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/app.js)

### Problem

Each node click re-rendered the Sigma overview and reapplied `computeCameraState(...)`, which recentred and re-zoomed the graph.

Observed behavior:

- clicking a node expanded the hierarchy correctly
- but the radar view jumped to a new zoom/focus state
- repeated expand/collapse operations felt inconsistent because the user lost their current viewport

### Fix

Inside `renderSigmaOverview(container, snapshot, options)`:

- added a per-lens `cameraKey`
- stored camera state in an in-memory `sigmaCameraMemory` map
- restored the last camera state for that lens before falling back to `computeCameraState(...)`

Inside `destroySigmaOverview()`:

- captured the current Sigma camera state before killing the renderer

Inside `hydrateGraphs(...)` in `app.js`:

- passed `cameraKey: route.view` so each lens keeps its own stable overview camera

### Validation

1. Syntax checks:

   ```bash
   node --check apps/web/site/app.js
   node --check apps/web/site/graph-renderers.js
   ```

2. Rebuilt the static site:

   ```bash
   python apps/web/build_site.py --data-dir data/public --out dist
   ```

3. Interaction verification:

   - click-to-expand still works
   - click-the-same-node-to-collapse still works
   - the overview camera no longer resets on each node toggle within the same lens

### Result

After this hotfix:

- expanding or collapsing nodes no longer forces the radar graph to jump
- the current zoom/focus is preserved per lens
- interaction is more stable and visually consistent during repeated exploration

### Status Update

This attempt only partially held up in real interaction.

Confirmed current state before the next commit:

- clicking blank stage space no longer resets the overview camera
- clicking a node still causes the radar view to jump in zoom/focus

So the remaining issue is specifically:

- preserve the current Sigma camera when node expansion changes the hierarchy snapshot

## Commit Marker: `working tree after 169b687` `Sanitize escaped job detail HTML and wrap long detail content`

### Scope

This patch fixes two right-rail detail-pane issues:

- escaped HTML fragments like `&lt;/p&gt;` appearing literally in job summaries and responsibilities
- long responsibility text failing to wrap cleanly inside the detail chips

Changed files:

- [apps/web/site/app.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/app.js)
- [apps/web/site/rich-text.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/rich-text.js)
- [apps/web/site/styles.css](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/styles.css)
- [tests/test_web_rich_text.py](/Volumes/meowhub/agents/jobvisualizer/tests/test_web_rich_text.py)

### Problem

Job enrichment text in `data/public/jobs.json` often arrives as plain strings containing entity-encoded HTML or partial tag fragments.

Observed failures:

- summaries displayed literal fragments like `&lt;/div&gt;`, `&lt;/p&gt;`, and `&amp;nbsp;`
- responsibilities could render as long, malformed blocks
- long detail text inside the right-side chips did not reliably wrap, so the visible content could start mid-line or appear clipped

### Fix

For rich text handling:

- moved the browser-side decoding/sanitization logic into a shared helper module at [rich-text.js](/Volumes/meowhub/agents/jobvisualizer/apps/web/site/rich-text.js)
- decode HTML entities
- parse in a detached template
- rebuild only a strict allowlist of safe structural tags
- strip attributes and drop blocked tags entirely
- render job summary and responsibility items through that safe rich-text path

For layout/wrapping:

- updated the right-side detail styles so long content uses block layout and wraps inside the card instead of behaving like a short inline chip
- added wrapping and overflow rules for `.detail-copy`, `.note-copy`, and detail-note card content
- ensured nested paragraphs/lists inside sanitized markup have sane spacing

### Validation

1. Syntax checks:

   ```bash
   node --check apps/web/site/app.js
   node --check apps/web/site/rich-text.js
   ```

2. Frontend build:

   ```bash
   python apps/web/build_site.py --data-dir data/public --out dist
   ```

3. Regression coverage:

   ```bash
   python -m unittest discover -s tests
   ```

4. Data inspection:

   - confirmed the public export contains hundreds of affected summaries and responsibilities, so the fix targets a real high-frequency failure mode rather than an isolated bad row

### Result

After this patch:

- job summaries and responsibilities no longer show raw encoded HTML fragments in the right rail
- allowed structural markup renders as readable text blocks
- long responsibility content wraps inside the display component instead of visually clipping or losing the leading text
