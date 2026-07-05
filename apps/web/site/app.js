import { createSiteStore, loadSiteData } from "./data-store.js";
import { createGraphAdapter } from "./graph-adapter.js";
import { destroyGraphRenderers, renderLocalCytoscape, renderSigmaOverview } from "./graph-renderers.js";
import { renderSafeRichText } from "./rich-text.js";

const state = {
  data: null,
  indices: null,
  graphAdapter: null,
  renderToken: 0,
  overviewTimer: null,
  hierarchyPaths: {
    jobs: [],
    companies: [],
    skills: [],
    graph: [],
  },
  queries: {
    jobs: "",
    companies: "",
    skills: "",
    graph: "",
  },
};

const root = {
  searchRail: document.getElementById("searchRail"),
  detailRail: document.getElementById("detailRail"),
  lensNav: document.getElementById("lensNav"),
  searchInput: document.getElementById("searchInput"),
  searchClear: document.getElementById("searchClear"),
  searchResults: document.getElementById("searchResults"),
  searchLensLabel: document.getElementById("searchLensLabel"),
  searchLensMeta: document.getElementById("searchLensMeta"),
  searchSummary: document.getElementById("searchSummary"),
  graphStage: document.getElementById("graphStage"),
  sceneKicker: document.getElementById("sceneKicker"),
  sceneTitle: document.getElementById("sceneTitle"),
  sceneSubtitle: document.getElementById("sceneSubtitle"),
  sceneStats: document.getElementById("sceneStats"),
  drawerKicker: document.getElementById("drawerKicker"),
  drawerTitle: document.getElementById("drawerTitle"),
  drawerClose: document.getElementById("drawerClose"),
  detailContent: document.getElementById("detailContent"),
};

function lensConfig(view) {
  const map = {
    jobs: {
      navLabel: "Jobs",
      searchLabel: "Jobs",
      searchMeta: "Browse discrete roles. Click a role to reveal its company and required skills.",
      title: "Jobs Lens",
      subtitle: "Click a job node to reveal its company and skills. Drag any node to rearrange the graph.",
      placeholder: "Search jobs, titles, or teams",
      allowedTypes: new Set(["job"]),
      emptyTitle: "Explore jobs",
      emptyCopy: "Click any role to reveal the company behind it and the skills it demands. Drag nodes to rearrange.",
    },
    companies: {
      navLabel: "Companies",
      searchLabel: "Companies",
      searchMeta: "Browse discrete companies. Click one to reveal its open roles and recurring skills.",
      title: "Companies Lens",
      subtitle: "Click a company to reveal its open roles and recurring skills. Drag any node to rearrange.",
      placeholder: "Search companies",
      allowedTypes: new Set(["company"]),
      emptyTitle: "Explore companies",
      emptyCopy: "Click any company to reveal its open roles and the skills it hires for most often.",
    },
    skills: {
      navLabel: "Skills",
      searchLabel: "Skills",
      searchMeta: "Start from a skill you have. Expand it to find companies that value it, then drill into matching roles.",
      title: "Skills Lens",
      subtitle: "Most job boards go job → skill. Here you start from the skill and find the job. Click any skill node to expand.",
      placeholder: "Search skills or aliases",
      allowedTypes: new Set(["skill"]),
      emptyTitle: "Start from a skill, find the job",
      emptyCopy: "Unlike typical job boards, this graph begins with skills. Click any skill node to reveal companies that value it, then drill into matching roles.",
    },
    graph: {
      navLabel: "Graph",
      searchLabel: "Graph",
      searchMeta: "All node types in one canvas. Click any node to expand its neighborhood.",
      title: "Graph Lens",
      subtitle: "All nodes in one canvas — skills, companies, jobs. Click any node to expand. Drag to rearrange.",
      placeholder: "Search the full graph",
      allowedTypes: null,
      emptyTitle: "Explore the full graph",
      emptyCopy: "All nodes — skills, companies, jobs — in one canvas. Click any node to expand its neighborhood.",
    },
  };
  return map[view] || map.jobs;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function truncate(value, length = 120) {
  const text = String(value ?? "").trim();
  if (text.length <= length) return text;
  return `${text.slice(0, length - 1).trimEnd()}…`;
}

function humanize(value) {
  if (!value) return "Unknown";
  return String(value)
    .replaceAll(/[_-]+/g, " ")
    .replaceAll(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatSourceHost(value) {
  if (!value) return "External link";
  try {
    return new URL(String(value)).hostname.replace(/^www\./, "") || "External link";
  } catch (_error) {
    return "External link";
  }
}

function uniq(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function routeHref(view, id = "") {
  return id ? `#/${view}/${encodeURIComponent(id)}` : `#/${view}`;
}

function routeForNode(nodeId) {
  if (!nodeId) return routeHref("graph");
  if (nodeId.startsWith("job:")) return routeHref("jobs", nodeId);
  if (nodeId.startsWith("company:")) return routeHref("companies", nodeId);
  if (nodeId.startsWith("skill:")) return routeHref("skills", nodeId);
  return routeHref("graph", nodeId);
}

function canonicalViewForNode(nodeId) {
  if (!nodeId) return null;
  if (nodeId.startsWith("job:")) return "jobs";
  if (nodeId.startsWith("company:")) return "companies";
  if (nodeId.startsWith("skill:")) return "skills";
  return "graph";
}

function nodeTypeForView(view) {
  if (view === "jobs") return "job";
  if (view === "companies") return "company";
  if (view === "skills") return "skill";
  return "skill";
}

function getHierarchyPath(view) {
  state.hierarchyPaths[view] ||= [];
  return state.hierarchyPaths[view];
}

function setHierarchyPath(view, path) {
  state.hierarchyPaths[view] = [...(path || [])];
}

function syncHierarchyPathFromRoute(route) {
  if (!route.id) return;
  const current = getHierarchyPath(route.view);
  if (!current.length && route.id.startsWith(`${nodeTypeForView(route.view)}:`)) {
    setHierarchyPath(route.view, [route.id]);
  }
}

function getActiveNodeId(route) {
  const path = getHierarchyPath(route.view);
  return path[path.length - 1] || route.id || null;
}

function toggleNodeSelection(nodeId) {
  const route = parseRoute();
  if (!nodeId) return;
  const currentPath = getHierarchyPath(route.view);
  const nextPath = state.graphAdapter.toggleHierarchyNode({
    type: nodeTypeForView(route.view),
    path: currentPath,
    nodeId,
  }).path;

  const changed = JSON.stringify(nextPath) !== JSON.stringify(currentPath);
  if (changed) {
    setHierarchyPath(route.view, nextPath);
    if (route.id) {
      window.location.hash = routeHref(route.view);
      return;
    }
    renderApp();
    return;
  }

  window.location.hash = routeForNode(nodeId);
}

function normalizeExternalRoute(rawRoute) {
  if (!rawRoute) return null;
  const route = String(rawRoute).trim();
  if (!route || route === "/" || route === "/index.html") return "#/skills";
  if (route.startsWith("#/")) return route;

  const url = new URL(route, window.location.origin);
  const path = url.pathname.replace(/\/index\.html$/, "");
  const segments = path.split("/").filter(Boolean);
  if (!segments.length) return "#/skills";
  const [view, ...rest] = segments;
  if (!["jobs", "companies", "skills", "graph"].includes(view)) return null;
  return rest.length ? routeHref(view, decodeURIComponent(rest.join("/"))) : routeHref(view);
}

function bootstrapRoute() {
  const params = new URLSearchParams(window.location.search);
  const redirect = params.get("redirect");
  if (redirect && !window.location.hash) {
    const normalized = normalizeExternalRoute(redirect);
    if (normalized) {
      window.history.replaceState({}, "", window.location.pathname);
      window.location.hash = normalized;
      return;
    }
  }

  if (!window.location.hash) {
    const normalized = normalizeExternalRoute(window.location.pathname);
    window.location.hash = normalized || "#/skills";
  }
}

function parseRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [view = "jobs", ...rest] = raw.split("/").filter(Boolean);
  const allowed = new Set(["jobs", "companies", "skills", "graph"]);
  return {
    view: allowed.has(view) ? view : "jobs",
    id: rest.length ? decodeURIComponent(rest.join("/")) : null,
  };
}

function canonicalizeRoute(route) {
  if (!route.id) return false;
  const canonicalView = canonicalViewForNode(route.id);
  if (canonicalView && route.view !== "graph" && route.view !== canonicalView) {
    window.location.hash = routeHref(canonicalView, route.id);
    return true;
  }
  return false;
}

function getCurrentQuery(view) {
  return state.queries[view] || "";
}

function setCurrentQuery(view, value) {
  state.queries[view] = value;
}

function getJobSkills(jobId) {
  return [...(state.data.jobSkills[jobId] || [])].sort((left, right) => {
    if (left.edge_type !== right.edge_type) return left.edge_type === "REQUIRES" ? -1 : 1;
    return String(left.label).localeCompare(String(right.label));
  });
}

function getCompanyJobs(companyId) {
  const jobIds = state.data.companyJobs[companyId] || [];
  return sortJobs(jobIds.map((jobId) => state.indices.jobsById[jobId]).filter(Boolean));
}

function getSkillJobs(skillId) {
  const jobIds = state.data.skillJobs[skillId] || [];
  return sortJobs(jobIds.map((jobId) => state.indices.jobsById[jobId]).filter(Boolean));
}

function getSkillCompanies(skillId) {
  const companyIds = state.indices.skillCompanies[skillId] || [];
  return companyIds.map((companyId) => state.indices.companiesById[companyId]).filter(Boolean);
}

function getTopSkillsForCompany(companyId, limit = 6) {
  const stats = state.data.companySkillStats[companyId] || {};
  return Object.entries(stats)
    .map(([skillId, count]) => ({ skill: state.indices.skillsById[skillId], count }))
    .filter((item) => item.skill)
    .sort((left, right) => {
      if (left.count !== right.count) return right.count - left.count;
      return String(left.skill.label).localeCompare(String(right.skill.label));
    })
    .slice(0, limit);
}

function sortJobs(jobs) {
  return [...jobs].sort((left, right) => {
    const leftDate = left?.posted_at || "";
    const rightDate = right?.posted_at || "";
    if (leftDate !== rightDate) return rightDate.localeCompare(leftDate);
    return String(left?.title || "").localeCompare(String(right?.title || ""));
  });
}

function getSelectedDescriptor(route) {
  const selectedId = getActiveNodeId(route);
  if (!selectedId) return { entity: null, missingId: null };
  if (selectedId.startsWith("job:")) {
    const job = state.indices.jobsById[selectedId];
    return job ? { entity: { kind: "job", id: job.id, data: job }, missingId: null } : { entity: null, missingId: selectedId };
  }
  if (selectedId.startsWith("company:")) {
    const company = state.indices.companiesById[selectedId];
    return company ? { entity: { kind: "company", id: company.id, data: company }, missingId: null } : { entity: null, missingId: selectedId };
  }
  if (selectedId.startsWith("skill:")) {
    const skill = state.indices.skillsById[selectedId];
    return skill ? { entity: { kind: "skill", id: skill.id, data: skill }, missingId: null } : { entity: null, missingId: selectedId };
  }
  const node = state.indices.nodeById[selectedId];
  return node ? { entity: { kind: "graph", id: node.id, data: node }, missingId: null } : { entity: null, missingId: selectedId };
}

function renderNav(activeView) {
  const items = ["jobs", "companies", "skills", "graph"];
  root.lensNav.innerHTML = items
    .map((view) => {
      const meta = lensConfig(view);
      const current = activeView === view ? ' aria-current="page"' : "";
      return `<a class="lens-link ${activeView === view ? "active" : ""}" href="${routeHref(view)}"${current}>${escapeHtml(meta.navLabel)}</a>`;
    })
    .join("");
}

function resultSummary(item) {
  if (item.type === "job") return item.subtitle || "Job";
  if (item.type === "company") return item.subtitle || "Company";
  if (item.type === "skill") return item.subtitle || "Skill";
  return item.subtitle || item.text || item.id;
}

function resultMeta(item) {
  return [`${humanize(item.type)}`, item.degree ? `${formatNumber(item.degree)} links` : null].filter(Boolean).join(" · ");
}

function typeBadge(type, label = null) {
  const text = label || humanize(type || "node");
  return `<span class="type-pill type-${escapeHtml(String(type || "node").replaceAll(/\s+/g, "-").toLowerCase())}">${escapeHtml(text)}</span>`;
}

function metaCard(label, value) {
  return `<div class="meta-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function linkChip({ href, title, subtitle = "", badge = "", external = false }) {
  return `
    <a class="chip-link" href="${escapeHtml(href)}" ${external ? 'target="_blank" rel="noreferrer"' : ""}>
      <span class="chip-link-label">
        <strong>${escapeHtml(title)}</strong>
        ${subtitle ? `<span>${escapeHtml(subtitle)}</span>` : ""}
      </span>
      ${badge ? `<span class="detail-pill">${escapeHtml(badge)}</span>` : ""}
    </a>
  `;
}

function inlineChip(title, subtitle = "", badge = "") {
  return `
    <div class="inline-chip">
      <span class="chip-link-label">
        <strong>${escapeHtml(title)}</strong>
        ${subtitle ? `<span>${escapeHtml(subtitle)}</span>` : ""}
      </span>
      ${badge ? `<span class="detail-pill">${escapeHtml(badge)}</span>` : ""}
    </div>
  `;
}

function actionLink({ href, label, external = false }) {
  return `
    <a class="detail-action" href="${escapeHtml(href)}" ${external ? 'target="_blank" rel="noreferrer"' : ""}>
      ${escapeHtml(label)}
    </a>
  `;
}

function detailSection(title, copy, content) {
  return `
    <section class="detail-section">
      <div class="detail-group-head">
        <h3>${escapeHtml(title)}</h3>
        ${copy ? `<p>${escapeHtml(copy)}</p>` : ""}
      </div>
      ${content}
    </section>
  `;
}

function renderSearchCard(item, activeId) {
  return `
    <button class="result-card ${item.id === activeId ? "active" : ""}" type="button" data-select-node="${escapeHtml(item.id)}">
      <div class="result-head">
        <p class="result-title">${escapeHtml(item.label || item.title || item.id)}</p>
        ${typeBadge(item.type)}
      </div>
      <div class="result-summary">${escapeHtml(truncate(resultSummary(item), 110))}</div>
      <div class="result-meta">${escapeHtml(resultMeta(item))}</div>
    </button>
  `;
}

function buildSearchBundle(route, selectedEntity) {
  const lens = lensConfig(route.view);
  const query = getCurrentQuery(route.view).trim();
  const selectedId = selectedEntity?.id || getActiveNodeId(route);
  const { snapshot, results } = state.graphAdapter.listGraphResults({
    search: query,
    type: nodeTypeForView(route.view),
    selectedId,
  });

  const primaryResults = lens.allowedTypes ? results.filter((item) => lens.allowedTypes.has(item.type)) : results;
  const relatedResults = lens.allowedTypes ? results.filter((item) => !lens.allowedTypes.has(item.type)) : [];

  return {
    query,
    snapshot,
    primaryResults: primaryResults.slice(0, query ? 14 : 10),
    relatedResults: relatedResults.slice(0, query ? 5 : 0),
  };
}

function buildLensStageSnapshot(route, selectedEntity) {
  const query = getCurrentQuery(route.view).trim();
  const hierarchyPath = getHierarchyPath(route.view);
  return state.graphAdapter.buildHierarchyOverview({
    mode: "hierarchy",
    search: query,
    type: nodeTypeForView(route.view),
    path: hierarchyPath,
  });
}

function renderSearchRail(route, selectedEntity) {
  const lens = lensConfig(route.view);
  const bundle = buildSearchBundle(route, selectedEntity);
  const { query, primaryResults, relatedResults } = bundle;
  const hasPrimary = primaryResults.length > 0;
  const brandMark = root.searchRail.querySelector(".brand-mark");
  const resultsBlock = root.searchResults.closest(".results-block");

  if (brandMark) {
    brandMark.textContent = "Search graph";
  }

  root.searchLensLabel.textContent = lens.searchLabel;
  root.searchLensMeta.textContent = lens.searchMeta;
  root.searchSummary.textContent = query
    ? `${primaryResults.length} primary matches${relatedResults.length ? ` · ${relatedResults.length} related nodes` : ""}`
    : "Search, then click a node to expand its neighborhood.";

  root.searchInput.placeholder = lens.placeholder;
  if (root.searchInput.value !== getCurrentQuery(route.view)) {
    root.searchInput.value = getCurrentQuery(route.view);
  }
  root.searchClear.hidden = !query;
  if (resultsBlock) {
    resultsBlock.hidden = !query;
  }

  root.searchResults.innerHTML = query
    ? [
        `<p class="result-section-title">Matches</p>`,
        hasPrimary
          ? primaryResults.map((item) => renderSearchCard(item, selectedEntity?.id || route.id)).join("")
          : `<div class="detail-empty"><p class="drawer-copy">No direct matches in this lens.</p></div>`,
        relatedResults.length
          ? `<p class="result-section-title">Related</p>${relatedResults.map((item) => renderSearchCard(item, selectedEntity?.id || route.id)).join("")}`
          : "",
      ].join("")
    : "";

  return bundle;
}

function renderScene(route, selectedEntity, overviewSnapshot, searchBundle) {
  const lens = lensConfig(route.view);
  const activeLabel = selectedEntity?.data?.label || selectedEntity?.data?.title || selectedEntity?.data?.name || null;
  const isExpanded = Boolean(getHierarchyPath(route.view).length);

  if (root.sceneKicker) {
    root.sceneKicker.textContent = isExpanded ? `${humanize(selectedEntity.kind)} focus` : lens.searchLabel;
  }
  if (root.sceneTitle) {
    root.sceneTitle.textContent = activeLabel || lens.title;
  }
  if (root.sceneSubtitle) {
    root.sceneSubtitle.textContent = isExpanded
      ? overviewSnapshot?.caption || `Showing the neighborhood of ${activeLabel || selectedEntity?.id || "the selected node"}. Click the same node to collapse. Drag any node to rearrange.`
      : searchBundle.query
        ? `Search focus: ${searchBundle.query}. Click a node to expand its immediate sublayer.`
        : lens.subtitle;
  }
  if (root.sceneStats) {
    root.sceneStats.hidden = true;
    root.sceneStats.innerHTML = "";
  }
  if (root.graphStage) {
    root.graphStage.setAttribute(
      "aria-label",
      isExpanded
        ? `${lens.navLabel} lens expanded around ${activeLabel || selectedEntity.id}`
        : `${lens.navLabel} lens with discrete nodes`
    );
  }
}

function renderWelcomeDetail(route, suggestions, missingId = null) {
  const lens = lensConfig(route.view);
  const counts = state.data.summary?.counts || {};
  root.drawerKicker.textContent = lens.searchLabel;
  root.drawerTitle.textContent = missingId ? "Selection unavailable" : lens.emptyTitle;

  const callout = missingId
    ? `<p class="drawer-copy">The deep link <strong>${escapeHtml(missingId)}</strong> is not in the current export. Pick another node or use the search bar to continue.</p>`
    : `<p class="drawer-copy">${escapeHtml(lens.emptyCopy)}</p>`;

  const suggestionMarkup = suggestions.length
    ? suggestions
        .slice(0, 6)
        .map((item) => linkChip({ href: routeForNode(item.id), title: item.label || item.title || item.id, subtitle: resultSummary(item), badge: humanize(item.type) }))
        .join("")
    : `<p class="drawer-copy">No suggested routes are available yet.</p>`;

  root.detailContent.innerHTML = `
    <section class="detail-empty">
      ${callout}
      <div class="detail-meta-grid">
        ${metaCard("Jobs", formatNumber(counts.jobs || 0))}
        ${metaCard("Companies", formatNumber(counts.companies || 0))}
        ${metaCard("Skills", formatNumber(counts.skills || 0))}
        ${metaCard("Nodes", formatNumber(counts.nodes || 0))}
      </div>
      ${detailSection("Suggested routes", "Click a node to expand its chain in this reading pane.", `<div class="detail-link-list">${suggestionMarkup}</div>`)}
    </section>
  `;
  return null;
}

function renderJobDetail(job) {
  root.drawerKicker.textContent = "Job";
  root.drawerTitle.textContent = job.title;

  const skills = getJobSkills(job.id);
  const requiredSkills = skills.filter((skill) => skill.edge_type === "REQUIRES");
  const preferredSkills = skills.filter((skill) => skill.edge_type === "PREFERS");
  const similarJobs = (state.data.jobNeighbors[job.id]?.similar_jobs || [])
    .map((item) => ({ ...item, job: state.indices.jobsById[item.job_id] }))
    .filter((item) => item.job)
    .slice(0, 5);

  root.detailContent.innerHTML = `
    <section class="detail-hero">
      <div class="detail-title-row">
        <div>
          ${typeBadge("job")}
        </div>
      </div>
      <div class="detail-copy">${renderSafeRichText(job.enrichment?.summary || "No generated summary is available for this role yet.")}</div>
      <div class="detail-meta-grid">
        ${metaCard("Company", job.company_name || job.company_id)}
        ${metaCard("Location", job.location_text || "Unknown")}
        ${metaCard("Posted", formatDate(job.posted_at))}
        ${metaCard("Seniority", job.enrichment?.seniority ? humanize(job.enrichment.seniority) : "Unknown")}
      </div>
      <div class="detail-actions">
        ${job.source_url ? actionLink({ href: job.source_url, label: "Source posting", external: true }) : ""}
      </div>
    </section>
    ${detailSection(
      "Links",
      "Direct connections from the selected job.",
      `<div class="detail-chip-grid">
        ${job.company_id ? linkChip({ href: routeForNode(job.company_id), title: job.company_name || job.company_id, subtitle: "Company", badge: "Company" }) : ""}
        ${requiredSkills.slice(0, 4).map((skill) => linkChip({ href: routeForNode(skill.skill_id), title: skill.label, subtitle: "Required skill", badge: "Required" })).join("")}
        ${preferredSkills.slice(0, 2).map((skill) => linkChip({ href: routeForNode(skill.skill_id), title: skill.label, subtitle: "Preferred skill", badge: "Preferred" })).join("")}
      </div>`
    )}
    ${job.source_url ? detailSection(
      "Original posting",
      "Open the source page for this role.",
      `<div class="detail-link-list">
        ${linkChip({
          href: job.source_url,
          title: "Open original posting",
          subtitle: formatSourceHost(job.source_url),
          badge: "External",
          external: true,
        })}
      </div>`
    ) : ""}
    ${detailSection(
      "Details",
      "High-overlap roles from the current graph export.",
      `<div class="detail-link-list">
        ${similarJobs.length ? similarJobs.map(({ job: similar, score }) => linkChip({ href: routeForNode(similar.id), title: similar.title, subtitle: `${similar.company_name} · ${similar.location_text || "Unknown"}`, badge: formatPercent(score) })).join("") : `<p class="drawer-copy">No similar roles are available yet.</p>`}
      </div>`
    )}
    ${job.enrichment?.responsibilities?.length ? detailSection(
      "Responsibilities",
      "Extracted from the posting.",
      `<div class="detail-note-list">
        ${job.enrichment.responsibilities.slice(0, 4).map((item) => `<div class="inline-chip"><div class="note-copy">${renderSafeRichText(item)}</div></div>`).join("")}
      </div>`
    ) : ""}
  `;

  return state.graphAdapter.buildNeighborhoodForJob(job);
}

function renderCompanyDetail(company) {
  root.drawerKicker.textContent = "Company";
  root.drawerTitle.textContent = company.name;

  const jobs = getCompanyJobs(company.id);
  const topSkills = getTopSkillsForCompany(company.id, 8);
  const locations = uniq(jobs.map((job) => job.location_text || "Unknown"));

  root.detailContent.innerHTML = `
    <section class="detail-hero">
      <div class="detail-title-row">
        <div>${typeBadge("company")}</div>
      </div>
      <p class="detail-copy">${escapeHtml(`${company.name} currently links to ${jobs.length} roles and ${topSkills.length} recurrent skill signals in the graph.`)}</p>
      <div class="detail-meta-grid">
        ${metaCard("Open roles", formatNumber(jobs.length))}
        ${metaCard("Top skills", formatNumber(topSkills.length))}
        ${metaCard("Locations", formatNumber(locations.length))}
        ${metaCard("Industry", company.industry || "Unknown")}
      </div>
      <div class="detail-actions">
        ${actionLink({ href: routeHref("graph", company.id), label: "Graph context" })}
        ${company.website ? actionLink({ href: company.website, label: "Website", external: true }) : ""}
      </div>
    </section>
    ${detailSection(
      "Skills",
      "The most recurrent skills across this company's visible jobs.",
      `<div class="detail-link-list">
        ${topSkills.length ? topSkills.map((item) => linkChip({ href: routeForNode(item.skill.id), title: item.skill.label, subtitle: `${item.count} linked job${item.count === 1 ? "" : "s"}`, badge: "Skill" })).join("") : `<p class="drawer-copy">No skill aggregation is available yet.</p>`}
      </div>`
    )}
    ${detailSection(
      "Roles",
      "Roles connected to this company in the current export.",
      `<div class="detail-link-list">
        ${jobs.length ? jobs.slice(0, 10).map((job) => linkChip({ href: routeForNode(job.id), title: job.title, subtitle: `${job.location_text || "Unknown"} · ${formatDate(job.posted_at)}`, badge: job.remote_mode ? humanize(job.remote_mode) : "Job" })).join("") : `<p class="drawer-copy">No jobs are linked to this company.</p>`}
      </div>`
    )}
  `;

  return state.graphAdapter.buildNeighborhoodForCompany(company);
}

function renderSkillDetail(skill) {
  root.drawerKicker.textContent = "Skill";
  root.drawerTitle.textContent = skill.label;

  const jobs = getSkillJobs(skill.id);
  const companies = getSkillCompanies(skill.id);
  const requiredJobs = jobs.filter((job) => getJobSkills(job.id).some((item) => item.skill_id === skill.id && item.edge_type === "REQUIRES"));
  const preferredJobs = jobs.filter((job) => getJobSkills(job.id).some((item) => item.skill_id === skill.id && item.edge_type === "PREFERS"));

  root.detailContent.innerHTML = `
    <section class="detail-hero">
      <div class="detail-title-row">
        <div>${typeBadge("skill")}</div>
      </div>
      <p class="detail-copy">${escapeHtml(`${skill.label} appears across ${jobs.length} jobs and ${companies.length} companies in the current graph.`)}</p>
      <div class="detail-meta-grid">
        ${metaCard("Jobs", formatNumber(jobs.length))}
        ${metaCard("Companies", formatNumber(companies.length))}
        ${metaCard("Category", skill.category || "Unknown")}
        ${metaCard("Parent", skill.parent_id || "None")}
      </div>
      <div class="detail-actions">
        ${actionLink({ href: routeHref("graph", skill.id), label: "Graph context" })}
      </div>
    </section>
    ${detailSection(
      "Companies",
      "The companies most directly connected in the current export.",
      `<div class="detail-link-list">
        ${companies.length ? companies.slice(0, 8).map((company) => linkChip({ href: routeForNode(company.id), title: company.name, subtitle: `${getCompanyJobs(company.id).length} linked roles`, badge: "Company" })).join("") : `<p class="drawer-copy">No companies are linked to this skill.</p>`}
      </div>`
    )}
    ${detailSection(
      "Roles",
      "Primary demand signal.",
      `<div class="detail-link-list">
        ${requiredJobs.length ? requiredJobs.slice(0, 10).map((job) => linkChip({ href: routeForNode(job.id), title: job.title, subtitle: `${job.company_name} · ${job.location_text || "Unknown"}`, badge: "Required" })).join("") : `<p class="drawer-copy">No required roles are linked to this skill.</p>`}
      </div>`
    )}
    ${preferredJobs.length ? detailSection(
      "Preferred roles",
      "Secondary demand signal.",
      `<div class="detail-link-list">
        ${preferredJobs.slice(0, 8).map((job) => linkChip({ href: routeForNode(job.id), title: job.title, subtitle: `${job.company_name} · ${job.location_text || "Unknown"}`, badge: "Preferred" })).join("")}
      </div>`
    ) : ""}
  `;

  return state.graphAdapter.buildNeighborhoodForSkill(skill);
}

function renderGenericNodeDetail(node) {
  root.drawerKicker.textContent = humanize(node.type || "node");
  root.drawerTitle.textContent = node.label || node.id;
  const neighbors = (state.indices.adjacency[node.id] || []).slice(0, 8);
  const referenceFields = Object.entries(node.data || {}).slice(0, 6);

  root.detailContent.innerHTML = `
    <section class="detail-hero">
      <div class="detail-title-row">
        <div>${typeBadge(node.type || "node")}</div>
      </div>
      <p class="detail-copy">This node belongs to the graph layer but is not one of the primary public entities.</p>
      <div class="detail-actions">
        ${actionLink({ href: routeHref("graph", node.id), label: "Keep in graph" })}
      </div>
    </section>
    ${detailSection(
      "Connected nodes",
      "Direct links from the current graph export.",
      `<div class="detail-link-list">
        ${neighbors.length ? neighbors.map(({ nodeId, edge }) => {
          const neighbor = state.indices.nodeById[nodeId];
          return linkChip({ href: routeForNode(nodeId), title: neighbor?.label || nodeId, subtitle: humanize(neighbor?.type || "node"), badge: edge.type });
        }).join("") : `<p class="drawer-copy">No neighbors are linked to this node.</p>`}
      </div>`
    )}
    ${referenceFields.length ? detailSection(
      "Reference data",
      "Raw fields carried through to the graph.",
      `<div class="detail-meta-grid">${referenceFields.map(([key, value]) => metaCard(humanize(key), Array.isArray(value) ? value.join(", ") : String(value ?? "n/a"))).join("")}</div>`
    ) : ""}
  `;

  return state.graphAdapter.buildNeighborhoodForNode(node.id);
}

function renderGraphPanel(title, copy) {
  return `
    <section class="graph-panel">
      <div class="detail-group-head">
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(copy)}</p>
      </div>
      <div class="graph-runtime-stage" data-local-graph-host></div>
    </section>
  `;
}

function renderDetail(route, selectedDescriptor, suggestions) {
  // The detail rail only exists when something is selected — at rest the
  // universe owns the whole viewport (CSS slides the rail away on
  // data-state="welcome").
  if (root.detailRail) {
    root.detailRail.dataset.state = selectedDescriptor.entity ? "detail" : "welcome";
  }
  if (!selectedDescriptor.entity) {
    return renderWelcomeDetail(route, suggestions, selectedDescriptor.missingId);
  }

  const selectedEntity = selectedDescriptor.entity;
  if (selectedEntity.kind === "job") return renderJobDetail(selectedEntity.data);
  if (selectedEntity.kind === "company") return renderCompanyDetail(selectedEntity.data);
  if (selectedEntity.kind === "skill") return renderSkillDetail(selectedEntity.data);
  return renderGenericNodeDetail(selectedEntity.data);
}

async function hydrateGraphs(route, overviewSnapshot, localSnapshot) {
  // Camera key = lens only. Search, selection and hierarchy expansion all
  // morph inside the same renderer (position-preserving + camera animation);
  // tearing down the canvas on every selection was the source of the flash.
  const cameraKey = route.view;

  const tasks = [
    renderSigmaOverview(root.graphStage, overviewSnapshot, {
      cameraKey,
      // No render-token gating here: a user click is always valid — the
      // handler reads current route/path state at click time. Gating by
      // render generation silently swallowed clicks after renderer reuse.
      onNodeSelect(nodeId) {
        toggleNodeSelection(nodeId);
      },
      onStageReset() {},
    }),
  ];

  const localHost = root.detailContent.querySelector("[data-local-graph-host]");
  if (localHost && localSnapshot) {
    tasks.push(
      renderLocalCytoscape(localHost, localSnapshot, {
        onNodeSelect(nodeId) {
          toggleNodeSelection(nodeId);
        },
      })
    );
  }

  await Promise.all(tasks);
}


function closeSelectionToBaseRoute() {
  const route = parseRoute();
  setHierarchyPath(route.view, []);
  state.graphAdapter.collapseHierarchy();
  window.location.hash = routeHref(route.view);
}

function scheduleRender() {
  window.clearTimeout(state.overviewTimer);
  state.overviewTimer = window.setTimeout(() => renderApp(), 110);
}

function renderApp() {
  const route = parseRoute();
  if (canonicalizeRoute(route)) return;

  syncHierarchyPathFromRoute(route);
  state.graphAdapter.setHierarchyType(nodeTypeForView(route.view));
  renderNav(route.view);
  const selectedDescriptor = getSelectedDescriptor(route);
  const searchBundle = renderSearchRail(route, selectedDescriptor.entity);
  const stageSnapshot = buildLensStageSnapshot(route, selectedDescriptor.entity);
  renderScene(route, selectedDescriptor.entity, stageSnapshot, searchBundle);
  const localSnapshot = renderDetail(route, selectedDescriptor, searchBundle.primaryResults.length ? searchBundle.primaryResults : searchBundle.relatedResults);
  hydrateGraphs(route, stageSnapshot, localSnapshot);
}

function bindEvents() {
  window.addEventListener("hashchange", () => renderApp());

  root.searchInput.addEventListener("input", (event) => {
    const route = parseRoute();
    setCurrentQuery(route.view, event.target.value);
    root.searchClear.hidden = !String(event.target.value).trim();
    scheduleRender();
  });

  root.searchInput.addEventListener("keydown", (event) => {
    const route = parseRoute();
    const descriptor = getSelectedDescriptor(route);
    const bundle = buildSearchBundle(route, descriptor.entity);
    const topResult = bundle.primaryResults[0] || bundle.relatedResults[0];

    if (event.key === "Enter" && topResult) {
      event.preventDefault();
      toggleNodeSelection(topResult.id);
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      if (root.searchInput.value) {
        root.searchInput.value = "";
        setCurrentQuery(route.view, "");
        renderApp();
      } else if (route.id || getHierarchyPath(route.view).length) {
        closeSelectionToBaseRoute();
      }
    }
  });

  root.searchClear.addEventListener("click", () => {
    const route = parseRoute();
    root.searchInput.value = "";
    setCurrentQuery(route.view, "");
    root.searchInput.focus();
    renderApp();
  });

  root.drawerClose.addEventListener("click", closeSelectionToBaseRoute);

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-select-node]");
    if (target) {
      event.preventDefault();
      toggleNodeSelection(target.dataset.selectNode);
    }
  });

  document.addEventListener("keydown", (event) => {
    const isEditable = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName || "");
    if (event.key === "/" && document.activeElement !== root.searchInput && !isEditable) {
      event.preventDefault();
      root.searchInput.focus();
      root.searchInput.select();
    }
  });
}

async function main() {
  try {
    bootstrapRoute();
    const store = createSiteStore(await loadSiteData());
    state.data = store.data;
    state.indices = store.indices;
    state.graphAdapter = createGraphAdapter(state.data, state.indices);
    bindEvents();
    renderApp();
  } catch (error) {
    console.error(error);
    if (root.sceneKicker) {
      root.sceneKicker.textContent = "Load error";
    }
    if (root.sceneTitle) {
      root.sceneTitle.textContent = "Failed to load graph data";
    }
    if (root.sceneSubtitle) {
      root.sceneSubtitle.textContent = error.message;
    }
    root.searchResults.innerHTML = `<div class="detail-empty"><p class="drawer-copy">${escapeHtml(error.message)}</p></div>`;
    root.detailContent.innerHTML = `<section class="detail-empty"><p class="drawer-copy">${escapeHtml(error.message)}</p></section>`;
  }
}

main();
