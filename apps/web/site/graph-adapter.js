const TYPE_LAYOUT = {
  company: { x: -0.3, y: -0.1, rank: 0, spread: 0.3 },
  job: { x: 0.0, y: 0.12, rank: 1, spread: 0.32 },
  skill: { x: 0.3, y: -0.1, rank: 2, spread: 0.3 },
  location: { x: -0.18, y: 0.38, rank: 3, spread: 0.2 },
  role_family: { x: 0.18, y: 0.38, rank: 4, spread: 0.2 },
  source: { x: 0.0, y: -0.38, rank: 5, spread: 0.16 },
  node: { x: 0.0, y: 0.0, rank: 6, spread: 0.24 },
};

const TYPE_THEME = {
  company: { color: "#245790", border: "#1d4672" },
  job: { color: "#0d7a73", border: "#085852" },
  skill: { color: "#cc5f2f", border: "#9a451f" },
  location: { color: "#6f63d9", border: "#564db1" },
  role_family: { color: "#8b5cf6", border: "#6d28d9" },
  source: { color: "#64748b", border: "#475569" },
  node: { color: "#5b6470", border: "#364152" },
};

const OVERVIEW_DEFAULT_LIMITS = {
  defaultNodes: 2600,
  focusedNodes: 600,
  focusedMatches: 72,
};

const HIERARCHY_DEFAULT_LIMITS = {
  rootNodes: 120,
  expandedNeighbors: 10,
};

const FORCE_LAYOUT_LIMITS = {
  hierarchy: 120,
  overview: 180,
};

export function createGraphAdapter(data, indices) {
  const coreTypes = new Set(["company", "job", "skill"]);
  const hierarchyState = {
    type: null,
    path: [],
  };

  const buildOverview = (filters = {}) => {
    if (filters.mode === "hierarchy") {
      return buildHierarchyOverview(filters);
    }

    const search = String(filters.search || "").trim().toLowerCase();
    const type = normalizeHierarchyType(filters.type || "all", coreTypes);
    const selectedId = filters.selectedId || null;
    const hasFocus = Boolean(search || type !== "all" || selectedId);
    const limit = hasFocus ? OVERVIEW_DEFAULT_LIMITS.focusedNodes : OVERVIEW_DEFAULT_LIMITS.defaultNodes;
    const defaultTypes = hasFocus && type !== "all" ? new Set([type]) : coreTypes;

    let nodeIds = hasFocus
      ? buildFocusedOverviewNodeIds({
          data,
          indices,
          search,
          type,
          selectedId,
          maxMatches: OVERVIEW_DEFAULT_LIMITS.focusedMatches,
          maxNodes: limit,
        })
      : buildDefaultOverviewNodeIds({
          data,
          indices,
          allowedTypes: defaultTypes,
          maxNodes: limit,
        });

    if (!nodeIds.size) {
      nodeIds = buildDefaultOverviewNodeIds({ data, indices, allowedTypes: coreTypes, maxNodes: Math.min(limit, 220) });
    }

    if (selectedId && indices.nodeById[selectedId]) {
      nodeIds.add(selectedId);
      addNeighborIds(nodeIds, indices, selectedId, 1, limit);
    }

    const snapshot = materializeSubgraph({ data, indices, nodeIds, selectedId });
    const nodes = computeOverviewLayout(snapshot.nodes, snapshot.edges, selectedId);

    return {
      ...snapshot,
      nodes,
      caption: hasFocus
        ? "Focused graph view: current search matches with immediate context, capped for performance."
        : "Ambient overview of jobs, companies, and skills arranged as a stable graph field.",
      limits: OVERVIEW_DEFAULT_LIMITS,
      hasFocus,
      selectedId,
    };
  };

  const buildHierarchyOverview = (filters = {}) => buildHierarchyOverviewSnapshot({
    data,
    indices,
    coreTypes,
    hierarchyState,
    search: String(filters.search || "").trim().toLowerCase(),
    type: filters.type ?? hierarchyState.type,
    path: filters.path ?? hierarchyState.path,
    maxNodes: filters.maxNodes || HIERARCHY_DEFAULT_LIMITS.rootNodes,
  });

  const setHierarchyType = (type = null) => {
    hierarchyState.type = normalizeHierarchyType(type, coreTypes);
    const rootType = hierarchyState.type === "all" ? null : hierarchyState.type;
    if (rootType && hierarchyState.path.length) {
      const rootNode = indices.nodeById[hierarchyState.path[0]];
      if (!rootNode || rootNode.type !== rootType) {
        hierarchyState.path = [];
      }
    }
    return { ...hierarchyState };
  };

  const toggleHierarchyNode = ({ nodeId = null, path = hierarchyState.path, type = hierarchyState.type } = {}) => {
    const normalizedType = normalizeHierarchyType(type, coreTypes);
    const cleanPath = (path || []).filter((id) => indices.nodeById[id]);
    if (!nodeId || !indices.nodeById[nodeId]) {
      hierarchyState.type = normalizedType;
      hierarchyState.path = [];
      return { ...hierarchyState };
    }

    let nextPath = computeNextHierarchyPath({
      data,
      indices,
      rootType: normalizedType === "all" ? inferHierarchyTypeForNode(indices, nodeId) || "skill" : normalizedType,
      path: cleanPath,
      nodeId,
    });

    hierarchyState.type = normalizedType === "all" ? inferHierarchyTypeForNode(indices, nextPath[0]) || "all" : normalizedType;
    if (!nextPath.length && normalizedType !== "all") {
      hierarchyState.type = normalizedType;
    }
    hierarchyState.path = nextPath;

    return { ...hierarchyState };
  };

  const collapseHierarchy = ({ nodeId = null, path = hierarchyState.path } = {}) => {
    const cleanPath = (path || []).filter((id) => indices.nodeById[id]);
    if (!nodeId) {
      hierarchyState.path = [];
      return { ...hierarchyState };
    }
    const index = cleanPath.indexOf(nodeId);
    hierarchyState.path = index >= 0 ? cleanPath.slice(0, index) : cleanPath;
    return { ...hierarchyState };
  };

  const getHierarchyState = () => ({ ...hierarchyState });

  const listGraphResults = ({ search = "", type = "all", selectedId = null } = {}) => {
    const snapshot = buildOverview({ search, type, selectedId });
    const results = [...snapshot.nodes]
      .sort((left, right) => {
        const leftSelected = left.id === snapshot.selectedId ? 1 : 0;
        const rightSelected = right.id === snapshot.selectedId ? 1 : 0;
        if (leftSelected !== rightSelected) return rightSelected - leftSelected;
        if (left.type !== right.type) return (TYPE_LAYOUT[left.type]?.rank || 99) - (TYPE_LAYOUT[right.type]?.rank || 99);
        if ((right.degree || 0) !== (left.degree || 0)) return (right.degree || 0) - (left.degree || 0);
        return String(left.label).localeCompare(String(right.label));
      })
      .slice(0, 120);

    return { snapshot, results };
  };

  return {
    getTheme(type) {
      return TYPE_THEME[type] || TYPE_THEME.node;
    },
    buildOverview,
    buildHierarchyOverview,
    setHierarchyType,
    toggleHierarchyNode,
    collapseHierarchy,
    getHierarchyState,

    buildNeighborhoodForJob(job) {
      const skills = getJobSkills(data, job.id).slice(0, 6);
      const similarJobs = (data.jobNeighbors[job.id]?.similar_jobs || [])
        .map((item) => indices.jobsById[item.job_id])
        .filter(Boolean)
        .slice(0, 4);
      const nodes = [baseNode(job.id, job.title, job.company_name, "job", 470, 150)];
      const edges = [];

      if (job.company_id && indices.companiesById[job.company_id]) {
        nodes.push(baseNode(job.company_id, indices.companiesById[job.company_id].name, "Company", "company", 160, 150));
        edges.push(baseEdge(job.company_id, job.id, "POSTS"));
      }

      stackPositions(skills.length, 150, 74).forEach((y, index) => {
        const skill = skills[index];
        nodes.push(baseNode(skill.skill_id, skill.label, skill.edge_type, "skill", 790, y));
        edges.push(baseEdge(job.id, skill.skill_id, skill.edge_type, skill.weight, skill.confidence));
      });

      spreadPositions(similarJobs.length, 470, 210).forEach((x, index) => {
        const similar = similarJobs[index];
        nodes.push(baseNode(similar.id, truncate(similar.title, 28), similar.company_name, "job", x, 338));
        edges.push(baseEdge(job.id, similar.id, "SIMILAR_TO", 0.7, 0.7));
      });

      return {
        title: "Job neighborhood",
        caption: "The selected role stays centered. Company sits on the left, related skills on the right, and similar jobs below.",
        layout: "preset",
        nodes,
        edges,
        selectedId: job.id,
      };
    },

    buildNeighborhoodForCompany(company) {
      const jobs = getCompanyJobs(data, indices, company.id).slice(0, 7);
      const topSkills = getTopSkillsForCompany(data, indices, company.id, 8);
      const nodes = [baseNode(company.id, company.name, "Company", "company", 150, 210)];
      const edges = [];

      stackPositions(jobs.length, 210, 72).forEach((y, index) => {
        const job = jobs[index];
        nodes.push(baseNode(job.id, truncate(job.title, 28), job.location_text || "Job", "job", 470, y));
        edges.push(baseEdge(company.id, job.id, "POSTS"));
      });

      stackPositions(topSkills.length, 210, 72).forEach((y, index) => {
        const item = topSkills[index];
        nodes.push(baseNode(item.skill.id, item.skill.label, `${item.count} linked jobs`, "skill", 790, y));
      });

      const visibleSkillIds = new Set(topSkills.map((item) => item.skill.id));
      for (const job of jobs) {
        for (const skill of getJobSkills(data, job.id)) {
          if (!visibleSkillIds.has(skill.skill_id)) continue;
          edges.push(baseEdge(job.id, skill.skill_id, skill.edge_type, skill.weight, skill.confidence));
        }
      }

      return {
        title: "Company neighborhood",
        caption: "Company on the left, live roles in the middle, and strongest recurring skills on the right.",
        layout: "preset",
        nodes,
        edges,
        selectedId: company.id,
      };
    },

    buildNeighborhoodForSkill(skill) {
      const jobs = getSkillJobs(data, indices, skill.id).slice(0, 7);
      const companies = getSkillCompanies(indices, skill.id).slice(0, 4);
      const nodes = [baseNode(skill.id, skill.label, "Skill", "skill", 810, 210)];
      const edges = [];

      stackPositions(companies.length, 210, 84).forEach((y, index) => {
        const company = companies[index];
        nodes.push(baseNode(company.id, company.name, "Company", "company", 150, y));
      });

      stackPositions(jobs.length, 210, 72).forEach((y, index) => {
        const job = jobs[index];
        const link = getJobSkills(data, job.id).find((item) => item.skill_id === skill.id);
        nodes.push(baseNode(job.id, truncate(job.title, 28), job.company_name, "job", 470, y));
        edges.push(baseEdge(job.id, skill.id, link?.edge_type || "REQUIRES", link?.weight || 1, link?.confidence || 0.7));
        if (companies.some((company) => company.id === job.company_id)) {
          edges.push(baseEdge(job.company_id, job.id, "POSTS"));
        }
      });

      return {
        title: "Skill neighborhood",
        caption: "Selected skill on the right, linked roles in the center, and related companies on the left.",
        layout: "preset",
        nodes,
        edges,
        selectedId: skill.id,
      };
    },

    buildNeighborhoodForNode(nodeId) {
      const node = indices.nodeById[nodeId];
      if (!node) {
        return {
          title: "Neighborhood unavailable",
          caption: "Node not present in current graph export.",
          layout: "preset",
          nodes: [],
          edges: [],
          selectedId: nodeId,
        };
      }

      const neighbors = (indices.adjacency[nodeId] || []).slice(0, 10);
      const nodes = [baseNode(nodeId, node.label || nodeId, node.type, node.type || "node", 470, 180)];
      const edges = [];
      const radiusX = 290;
      const radiusY = 130;

      neighbors.forEach(({ nodeId: neighborId, edge }, index) => {
        const angle = -Math.PI / 2 + (index * (2 * Math.PI)) / Math.max(neighbors.length, 1);
        const neighbor = indices.nodeById[neighborId];
        nodes.push(
          baseNode(
            neighborId,
            truncate(neighbor?.label || neighborId, 28),
            neighbor ? humanize(neighbor.type) : edge.type,
            neighbor?.type || "node",
            470 + radiusX * Math.cos(angle),
            180 + radiusY * Math.sin(angle),
          ),
        );
        edges.push(baseEdge(nodeId, neighborId, edge.type, edge.weight, edge.confidence));
      });

      return {
        title: "Graph neighborhood",
        caption: "Fallback radial neighborhood for non-primary graph nodes.",
        layout: "preset",
        nodes,
        edges,
        selectedId: nodeId,
      };
    },

    listGraphResults,
  };
}

function buildHierarchyOverviewSnapshot({ data, indices, coreTypes, hierarchyState, search = "", type = "all", path = [], maxNodes = HIERARCHY_DEFAULT_LIMITS.rootNodes }) {
  const normalizedType = normalizeHierarchyType(type, coreTypes);
  const rootType = normalizedType === "all" ? hierarchyState.type || "skill" : normalizedType;
  const cleanPath = normalizeHierarchyPath(indices, rootType, path);
  const rootItems = buildHierarchyRootItems({ data, indices, rootType, search, maxNodes, path: cleanPath });
  const { nodes: rootNodes, links: rootLinks } = computeHierarchyRootLayout(rootItems, cleanPath[0] || null, { data, indices, rootType });
  const rootNodeMap = new Map(rootNodes.map((node) => [node.id, node]));
  const nodes = [...rootNodes];
  const edges = [];
  const seenIds = new Set(rootNodes.map((node) => node.id));

  // The similarity links that shaped the layout are also rendered, so the
  // resting view reads as an interwoven web instead of disconnected dots.
  for (const link of rootLinks) {
    edges.push(baseEdge(link.source, link.target, "WOVEN", link.weight, link.weight));
  }

  let parentPath = [];
  for (const nodeId of cleanPath) {
    const anchor = rootNodeMap.get(nodeId) || nodes.find((node) => node.id === nodeId);
    const node = indices.nodeById[nodeId];
    if (!node || !anchor) break;
    const children = getHierarchyChildren({ data, indices, rootType, path: [...parentPath, nodeId], nodeId, maxNeighbors: HIERARCHY_DEFAULT_LIMITS.expandedNeighbors });
    const positionedChildren = positionHierarchyChildren(children, anchor, parentPath.length + 1, rootType);

    for (const child of positionedChildren) {
      if (!seenIds.has(child.id)) {
        nodes.push(child);
        seenIds.add(child.id);
      }
      // Tag hierarchy edges with their depth so the renderer can grade
      // brightness by level (depth-of-field encoding).
      edges.push({ ...baseEdge(nodeId, child.id, child.edgeType || "RELATED", child.weight || 1, child.confidence || 1), level: parentPath.length + 1 });
    }

    parentPath.push(nodeId);
  }

  const selectedId = cleanPath.at(-1) || null;
  return {
    title: hierarchyTitle(rootType),
    caption: selectedId ? hierarchyExpandedCaption(rootType, indices.nodeById[selectedId]) : hierarchyCollapsedCaption(rootType),
    layout: "preset",
    mode: "hierarchy",
    type: rootType,
    nodes,
    edges,
    selectedId,
    expandedPath: cleanPath,
    hasFocus: Boolean(search || cleanPath.length),
  };
}

export function toCytoscapeElements(snapshot) {
  return {
    nodes: (snapshot.nodes || []).map((node) => {
      const theme = TYPE_THEME[node.type] || TYPE_THEME.node;
      return {
        data: {
          id: node.id,
          label: node.label,
          subtitle: node.subtitle || "",
          type: node.type || "node",
          degree: node.degree || 0,
          selected: node.id === snapshot.selectedId,
          color: theme.color,
          borderColor: theme.border,
        },
        position: typeof node.x === "number" && typeof node.y === "number" ? { x: node.x, y: node.y } : undefined,
        selectable: true,
        grabbable: true,
      };
    }),
    edges: (snapshot.edges || []).map((edge) => ({
      data: {
        id: edge.id || `${edge.source}::${edge.type}::${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: edge.type,
        weight: edge.weight || 1,
        confidence: edge.confidence || 1,
      },
    })),
  };
}

export function createSigmaData(snapshot) {
  return {
    nodes: (snapshot.nodes || []).map((node) => {
      const theme = TYPE_THEME[node.type] || TYPE_THEME.node;
      return {
        id: node.id,
        label: node.label,
        type: node.type,
        x: node.x,
        y: node.y,
        size: node.size || 4,
        color: theme.color,
        borderColor: theme.border,
        degree: node.degree || 0,
      };
    }),
    edges: (snapshot.edges || []).map((edge) => ({
      id: edge.id || `${edge.source}::${edge.type}::${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      size: edge.type === "SIMILAR_TO" ? 1.3 : 1,
      color: edge.type === "SIMILAR_TO" ? "rgba(13,122,115,0.24)" : "rgba(42,42,40,0.08)",
    })),
  };
}

function buildDefaultOverviewNodeIds({ data, indices, allowedTypes, maxNodes }) {
  const nodes = (data.graph.nodes || [])
    .filter((node) => allowedTypes.has(node.type))
    .sort((left, right) => {
      const leftDegree = indices.degreeById[left.id] || 0;
      const rightDegree = indices.degreeById[right.id] || 0;
      if (leftDegree !== rightDegree) return rightDegree - leftDegree;
      if (left.type !== right.type) return (TYPE_LAYOUT[left.type]?.rank || 99) - (TYPE_LAYOUT[right.type]?.rank || 99);
      return String(left.label).localeCompare(String(right.label));
    });

  return new Set(nodes.slice(0, maxNodes).map((node) => node.id));
}

function inferHierarchyTypeForNode(indices, nodeId) {
  if (!nodeId) return null;
  return indices.nodeById[nodeId]?.type || null;
}

function normalizeHierarchyType(type, coreTypes) {
  const value = String(type || "").trim().toLowerCase();
  if (!value || value === "all" || value === "graph") return "all";
  if (value === "jobs") return "job";
  if (value === "companies") return "company";
  if (value === "skills") return "skill";
  if (coreTypes.has(value)) return value;
  return value;
}

function hierarchyTitle(type) {
  if (type === "all") return "Expandable graph";
  return `${humanize(type)} lens`;
}

function hierarchyCollapsedCaption(type) {
  if (type === "all") {
    return "Top-level nodes are grouped by type. Select a node to reveal its immediate context.";
  }
  return `Top-level ${humanize(type)} nodes are shown without edges. Click one node to expand its immediate sublayer.`;
}

function hierarchyExpandedCaption(_type, node) {
  const label = node?.label || node?.id || "the selection";
  return `${label} is expanded with its immediate context. Click it again to collapse. Drag any node to rearrange the graph.`;
}

function normalizeHierarchyPath(indices, rootType, path) {
  const clean = (path || []).filter((id) => indices.nodeById[id]);
  if (!clean.length) return [];
  if (rootType && indices.nodeById[clean[0]]?.type !== rootType) return [];
  return clean;
}

function buildHierarchyRootItems({ data, indices, rootType, search = "", maxNodes, path = [] }) {
  const query = String(search || "").trim().toLowerCase();
  let items = [];

  if (rootType === "skill") {
    items = (data.skills || []).map((skill) => ({
      id: skill.id,
      label: skill.label,
      subtitle: skill.category || "Skill",
      type: "skill",
      degree: getSkillJobs(data, indices, skill.id).length,
    }));
  } else if (rootType === "company") {
    items = (data.companies || []).map((company) => ({
      id: company.id,
      label: company.name,
      subtitle: company.industry || "Company",
      type: "company",
      degree: getCompanyJobs(data, indices, company.id).length,
    }));
  } else {
    items = (data.jobs || []).map((job) => ({
      id: job.id,
      label: job.title,
      subtitle: job.company_name || "Job",
      type: "job",
      degree: getJobSkills(data, job.id).length,
      sortDate: job.posted_at || "",
    }));
  }

  if (query) {
    items = items.filter((item) => [item.label, item.subtitle, item.id].filter(Boolean).join(" ").toLowerCase().includes(query));
  }

  items.sort((left, right) => {
    if (rootType === "job" && left.sortDate !== right.sortDate) {
      return String(right.sortDate || "").localeCompare(String(left.sortDate || ""));
    }
    if ((right.degree || 0) !== (left.degree || 0)) return (right.degree || 0) - (left.degree || 0);
    return String(left.label).localeCompare(String(right.label));
  });

  const rootPathId = path[0];
  if (rootPathId && !items.some((item) => item.id === rootPathId) && indices.nodeById[rootPathId]) {
    const node = indices.nodeById[rootPathId];
    items.unshift({
      id: node.id,
      label: node.label || node.id,
      subtitle: buildNodeSubtitle(node, indices),
      type: node.type,
      degree: indices.degreeById[node.id] || 0,
    });
  }

  return items.slice(0, maxNodes);
}

function computeHierarchyRootLayout(items, selectedId = null, context = {}) {
  const { positions, links } = runHierarchyForceLayout(items, { ...context, selectedId });

  const nodes = items.map((item) => {
    const point = positions.get(item.id) || { x: 0, y: 0 };
    const emphasis = item.id === selectedId ? 1.35 : 1;
    return {
      id: item.id,
      label: truncate(item.label, 30),
      subtitle: item.subtitle,
      type: item.type,
      degree: item.degree || 0,
      selected: item.id === selectedId,
      level: 0,
      x: point.x,
      y: point.y,
      size: Math.max(3.4, Math.min(9.6, (3 + Math.log2((item.degree || 1) + 1) * 0.9) * emphasis)),
    };
  });

  return { nodes, links };
}

function runHierarchyForceLayout(items, context = {}) {
  const count = items.length;
  if (!count) return { positions: new Map(), links: [] };
  if (count === 1) return { positions: new Map([[items[0].id, { x: 0, y: 0 }]]), links: [] };

  const nodes = items.map((item, index) => seedForceNode({
    id: item.id,
    degree: item.degree || 0,
    type: item.type,
    selected: item.id === context.selectedId,
    anchorX: 0,
    anchorY: 0,
  }, index, {
    spreadX: 0.95,
    spreadY: 0.85,
  }));

  const links = buildHierarchySimilarityLinks(items, context);
  // Light relaxation only: resolve collisions and let similarity springs
  // pull related nodes into loose constellations. Anchors OFF so the seeded
  // scatter survives instead of collapsing into a centered disc.
  runForcePass(nodes, links, {
    iterations: count > 84 ? 60 : 90,
    repulsion: count > 84 ? 0.012 : 0.016,
    centerStrength: 0.005,
    anchorStrength: 0,
    springStrength: 0.05,
    damping: 0.88,
    maxVelocity: 0.028,
    collisionPadding: 0.08,
    idealDistance: 0.24,
    selectedId: context.selectedId,
  });

  return { positions: normalizeHierarchyPositions(nodes, context.selectedId), links };
}

function buildHierarchySimilarityLinks(items, context = {}) {
  const featureMap = new Map(items.map((item) => [item.id, collectHierarchyFeatures(item.id, context)]));
  const pairs = [];

  for (let leftIndex = 0; leftIndex < items.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < items.length; rightIndex += 1) {
      const left = items[leftIndex];
      const right = items[rightIndex];
      const weight = computeWeightedSimilarity(featureMap.get(left.id), featureMap.get(right.id));
      if (weight <= 0.12) continue;
      pairs.push({ source: left.id, target: right.id, weight });
    }
  }

  return mergeWeightedLinks([...pairs, ...collectDirectHierarchyLinks(items, context)], 4);
}

function collectHierarchyFeatures(nodeId, context = {}) {
  const { data, indices, rootType } = context;
  const features = new Map();
  if (!data || !indices || !nodeId) return features;

  if (rootType === "skill") {
    const companies = indices.skillCompanies[nodeId] || [];
    const jobs = data.skillJobs[nodeId] || [];
    const skill = indices.skillsById[nodeId];
    for (const companyId of companies) addWeightedFeature(features, `company:${companyId}`, 1.1);
    for (const jobId of jobs) addWeightedFeature(features, `job:${jobId}`, 0.72);
    if (skill?.parent_id) addWeightedFeature(features, `parent:${skill.parent_id}`, 0.85);
    if (skill?.category) addWeightedFeature(features, `category:${skill.category}`, 0.2);
    return features;
  }

  if (rootType === "company") {
    const stats = data.companySkillStats[nodeId] || {};
    const company = indices.companiesById[nodeId];
    const maxCount = Math.max(1, ...Object.values(stats));
    for (const [skillId, count] of Object.entries(stats)) {
      addWeightedFeature(features, `skill:${skillId}`, 0.45 + (Number(count) / maxCount) * 0.75);
    }
    if (company?.industry) addWeightedFeature(features, `industry:${company.industry}`, 0.22);
    return features;
  }

  const job = indices.jobsById[nodeId];
  for (const skill of getJobSkills(data, nodeId)) {
    addWeightedFeature(features, `skill:${skill.skill_id}`, skill.edge_type === "REQUIRES" ? 1.0 : 0.66);
  }
  if (job?.company_id) addWeightedFeature(features, `company:${job.company_id}`, 0.3);
  if (job?.enrichment?.role_family) addWeightedFeature(features, `family:${job.enrichment.role_family}`, 0.55);
  return features;
}

function collectDirectHierarchyLinks(items, context = {}) {
  const { data, rootType } = context;
  if (rootType !== "job" || !data) return [];
  const allowed = new Set(items.map((item) => item.id));
  const direct = [];
  const seen = new Set();

  for (const item of items) {
    for (const similar of data.jobNeighbors[item.id]?.similar_jobs || []) {
      if (!allowed.has(similar.job_id)) continue;
      const key = [item.id, similar.job_id].sort().join("::");
      if (seen.has(key)) continue;
      seen.add(key);
      direct.push({
        source: item.id,
        target: similar.job_id,
        weight: clamp(0.22 + Number(similar.score || 0) * 0.78, 0.22, 1),
      });
    }
  }

  return direct;
}

function addWeightedFeature(map, key, weight) {
  if (!key || !Number.isFinite(weight) || weight <= 0) return;
  map.set(key, Math.max(map.get(key) || 0, weight));
}

function computeWeightedSimilarity(leftFeatures, rightFeatures) {
  if (!leftFeatures?.size || !rightFeatures?.size) return 0;
  let intersection = 0;
  let union = 0;
  const keys = new Set([...leftFeatures.keys(), ...rightFeatures.keys()]);
  for (const key of keys) {
    const left = leftFeatures.get(key) || 0;
    const right = rightFeatures.get(key) || 0;
    intersection += Math.min(left, right);
    union += Math.max(left, right);
  }
  if (!union || !intersection) return 0;
  return intersection / union;
}

function mergeWeightedLinks(links, maxLinksPerNode = 4) {
  const merged = new Map();
  for (const link of links) {
    const key = [link.source, link.target].sort().join("::");
    const existing = merged.get(key);
    if (!existing || link.weight > existing.weight) merged.set(key, { ...link });
  }

  const ordered = [...merged.values()].sort((left, right) => right.weight - left.weight);
  const perNode = new Map();
  const selected = [];

  for (const link of ordered) {
    const sourceCount = perNode.get(link.source) || 0;
    const targetCount = perNode.get(link.target) || 0;
    if (sourceCount >= maxLinksPerNode || targetCount >= maxLinksPerNode) continue;
    perNode.set(link.source, sourceCount + 1);
    perNode.set(link.target, targetCount + 1);
    selected.push(link);
  }

  return selected;
}

function seedForceNode(node, index, options = {}) {
  // Organic scatter: two independent id-seeded hashes give a stable but
  // pattern-free position for every node (the old golden-angle spiral packed
  // into a visibly regular lattice). The force pass afterwards only resolves
  // collisions and pulls related nodes together — it never regularizes.
  const jitter = seededJitter(node.id);
  const jitterAlt = seededJitter(`${node.id}::scatter`);
  const spreadX = options.spreadX ?? 0.95;
  const spreadY = options.spreadY ?? 0.85;
  const anchorX = node.anchorX || 0;
  const anchorY = node.anchorY || 0;
  return {
    ...node,
    x: anchorX + jitter.x * 2 * spreadX + jitterAlt.x * 0.22,
    y: anchorY + jitter.y * 2 * spreadY + jitterAlt.y * 0.22,
    vx: 0,
    vy: 0,
  };
}

function runForcePass(nodes, links, options = {}) {
  const iterations = options.iterations || 120;
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const cooling = 1 - (iteration / iterations) * 0.55;
    runForceStep(nodes, links, { ...options, alpha: cooling });
  }
}

export function runForceStep(nodes, links, options = {}) {
  const alpha = options.alpha ?? 1;
  // Stronger short-range repulsion → nodes naturally space out instead of
  // piling at the origin when one is dragged far away.
  const repulsion = options.repulsion ?? 0.022;
  // Center strength is tiny: just enough to prevent infinite drift, not enough
  // to "yank" nodes back when a peer wanders.
  const centerStrength = options.centerStrength ?? 0.0014;
  // Anchor force defaults to ZERO in continuous mode — anchors snap things
  // back rigidly, which is the opposite of "celestial".
  const anchorStrength = options.anchorStrength ?? 0;
  const springStrength = options.springStrength ?? 0.07;
  // Lower damping = more inertia. Real stars and electrons keep coasting.
  const damping = options.damping ?? 0.93;
  const maxVelocity = options.maxVelocity ?? 0.032;
  // Bigger personal-space padding prevents the "pileup" failure mode.
  const collisionPadding = options.collisionPadding ?? 0.085;
  const idealDistance = options.idealDistance ?? 0.2;
  const selectedId = options.selectedId || null;
  // Far larger play-pen so dragged nodes can wander without smashing the rest
  // against an invisible wall.
  const clampBound = options.clampBound ?? 5.0;
  // Per-frame Brownian noise — what makes the field feel alive (the twinkle).
  const noise = options.noise ?? 0;

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const forces = new Map(nodes.map((node) => {
    const selectedBoost = node.id === selectedId ? 2.8 : 1;
    let fx = -node.x * centerStrength;
    let fy = -node.y * centerStrength;
    if (anchorStrength > 0) {
      fx += ((node.anchorX || 0) - node.x) * anchorStrength * selectedBoost;
      fy += ((node.anchorY || 0) - node.y) * anchorStrength * selectedBoost;
    }
    return [node.id, { x: fx, y: fy }];
  }));

  // Repulsion + collision (electrostatic-ish). Bigger than spring at close
  // range, weaker at long range — Coulomb feel.
  for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
    const left = nodes[leftIndex];
    for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
      const right = nodes[rightIndex];
      const dx = left.x - right.x;
      const dy = left.y - right.y;
      const distance = Math.max(Math.hypot(dx, dy), 0.001);
      const distanceSquared = Math.max(distance * distance, 0.006);
      const repel = repulsion / distanceSquared;
      const minDistance = collisionPadding
        + (Math.log2((left.degree || 1) + 1) + Math.log2((right.degree || 1) + 1)) * 0.014
        + (left.id === selectedId || right.id === selectedId ? 0.04 : 0);
      const collision = distance < minDistance ? (minDistance - distance) * 0.28 : 0;
      const strength = repel + collision;
      const fx = (dx / distance) * strength;
      const fy = (dy / distance) * strength;
      forces.get(left.id).x += fx;
      forces.get(left.id).y += fy;
      forces.get(right.id).x -= fx;
      forces.get(right.id).y -= fy;
    }
  }

  // Springs (orbital tethers between connected nodes).
  for (const link of links) {
    const source = nodeById.get(link.source);
    const target = nodeById.get(link.target);
    if (!source || !target) continue;
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const distance = Math.max(Math.hypot(dx, dy), 0.001);
    const desired = idealDistance + (1 - link.weight) * 0.18;
    const spring = (distance - desired) * (springStrength * (0.6 + link.weight * 0.9));
    const fx = (dx / distance) * spring;
    const fy = (dy / distance) * spring;
    forces.get(source.id).x += fx;
    forces.get(source.id).y += fy;
    forces.get(target.id).x -= fx;
    forces.get(target.id).y -= fy;
  }

  for (const node of nodes) {
    if (node.fixed) {
      // Fixed (currently dragged) nodes don't move under physics — but they
      // DO exert force on the rest of the cluster (loop above).
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    const force = forces.get(node.id);
    let vx = (node.vx + force.x * alpha) * damping;
    let vy = (node.vy + force.y * alpha) * damping;
    if (noise > 0) {
      // Subtle Brownian shimmer — the "twinkle".
      vx += (Math.random() - 0.5) * noise;
      vy += (Math.random() - 0.5) * noise;
    }
    const speed = Math.hypot(vx, vy);
    if (speed > maxVelocity) {
      vx = (vx / speed) * maxVelocity;
      vy = (vy / speed) * maxVelocity;
    }
    node.vx = vx;
    node.vy = vy;
    node.x = clamp(node.x + vx, -clampBound, clampBound);
    node.y = clamp(node.y + vy, -clampBound, clampBound);
  }
}

function normalizeHierarchyPositions(nodes, selectedId = null) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const node of nodes) {
    minX = Math.min(minX, node.x);
    maxX = Math.max(maxX, node.x);
    minY = Math.min(minY, node.y);
    maxY = Math.max(maxY, node.y);
  }

  const centerX = Number.isFinite(minX) ? (minX + maxX) / 2 : 0;
  const centerY = Number.isFinite(minY) ? (minY + maxY) / 2 : 0;
  const spanX = Math.max((maxX - minX) || 0, 0.2);
  const spanY = Math.max((maxY - minY) || 0, 0.2);
  const targetSpanX = selectedId ? 0.9 : 0.8;
  const targetSpanY = selectedId ? 0.72 : 0.7;
  const scale = Math.max(spanX / targetSpanX, spanY / targetSpanY, 0.56);

  return new Map(nodes.map((node) => [
    node.id,
    {
      x: clamp((node.x - centerX) / scale, -0.48, 0.48),
      y: clamp((node.y - centerY) / scale, -0.42, 0.42),
    },
  ]));
}

function getHierarchyChildren({ data, indices, rootType, path, nodeId, maxNeighbors = HIERARCHY_DEFAULT_LIMITS.expandedNeighbors }) {
  const node = indices.nodeById[nodeId];
  if (!node) return [];
  const ancestors = path.slice(0, -1);
  const nearestSkillAncestor = [...ancestors].reverse().find((id) => indices.nodeById[id]?.type === "skill") || null;
  const nearestCompanyAncestor = [...ancestors].reverse().find((id) => indices.nodeById[id]?.type === "company") || null;

  if (node.type === "skill") {
    return getSkillCompanies(indices, node.id)
      .sort((left, right) => {
        const leftCount = getCompanyJobs(data, indices, left.id).length;
        const rightCount = getCompanyJobs(data, indices, right.id).length;
        if (rightCount !== leftCount) return rightCount - leftCount;
        return String(left.name).localeCompare(String(right.name));
      })
      .slice(0, maxNeighbors)
      .map((company) => ({
        id: company.id,
        label: company.name,
        subtitle: `${getCompanyJobs(data, indices, company.id).length} jobs`,
        type: "company",
        degree: indices.degreeById[company.id] || 0,
        edgeType: "USES_SKILL",
      }));
  }

  if (node.type === "company") {
    let jobs = getCompanyJobs(data, indices, node.id);
    if (nearestSkillAncestor) {
      jobs = jobs.filter((job) => getJobSkills(data, job.id).some((skill) => skill.skill_id === nearestSkillAncestor));
    }
    return jobs.slice(0, maxNeighbors).map((job) => ({
      id: job.id,
      label: truncate(job.title, 30),
      subtitle: job.location_text || job.company_name || "Job",
      type: "job",
      degree: indices.degreeById[job.id] || 0,
      edgeType: "POSTS",
    }));
  }

  if (node.type === "job") {
    const children = [];
    if (!nearestCompanyAncestor) {
      const company = indices.companiesById[data.jobs?.find?.((job) => job.id === node.id)?.company_id || indices.jobsById[node.id]?.company_id];
      if (company) {
        children.push({
          id: company.id,
          label: company.name,
          subtitle: "Company",
          type: "company",
          degree: indices.degreeById[company.id] || 0,
          edgeType: "POSTS",
        });
      }
    }

    for (const skill of getJobSkills(data, node.id).slice(0, maxNeighbors)) {
      children.push({
        id: skill.skill_id,
        label: skill.label,
        subtitle: humanize(skill.edge_type),
        type: "skill",
        degree: indices.degreeById[skill.skill_id] || 0,
        edgeType: skill.edge_type,
        weight: skill.weight,
        confidence: skill.confidence,
      });
    }

    return dedupeHierarchyChildren(children).slice(0, maxNeighbors);
  }

  return (indices.adjacency[node.id] || [])
    .filter(({ nodeId: neighborId }) => indices.nodeById[neighborId])
    .slice(0, maxNeighbors)
    .map(({ nodeId: neighborId, edge }) => {
      const neighbor = indices.nodeById[neighborId];
      return {
        id: neighbor.id,
        label: truncate(neighbor.label || neighbor.id, 30),
        subtitle: buildNodeSubtitle(neighbor, indices),
        type: neighbor.type || "node",
        degree: indices.degreeById[neighbor.id] || 0,
        edgeType: edge.type,
        weight: edge.weight,
        confidence: edge.confidence,
      };
    });
}

function dedupeHierarchyChildren(children) {
  const seen = new Set();
  return children.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function positionHierarchyChildren(children, anchor, depth, rootType) {
  // Children spawn ON their parent (tiny angular offset only). The renderer's
  // continuous simulation then pushes them outward via collision + repulsion,
  // so an expand reads as the node "unfolding" rather than a re-layout flash.
  const spawnRadius = 0.05;
  const arc = Math.PI * 2;
  const start = seededJitter(anchor.id).angle * Math.PI;

  return children.map((child, index) => {
    const angle = start + ((index + 0.5) / Math.max(children.length, 1)) * arc;
    const jitter = seededJitter(`${anchor.id}:${child.id}:${depth}`);
    const x = clamp(anchor.x + Math.cos(angle) * spawnRadius + jitter.x * 0.02, -1.15, 1.15);
    const y = clamp(anchor.y + Math.sin(angle) * spawnRadius + jitter.y * 0.02, -1.05, 1.05);
    return {
      ...child,
      selected: false,
      level: depth,
      parentId: anchor.id,
      x,
      y,
      size: Math.max(2.8, Math.min(8.6, 2.8 + Math.log2((child.degree || 1) + 1) * 0.8 + (child.type === rootType ? 0.4 : 0))),
    };
  });
}

function computeNextHierarchyPath({ data, indices, rootType, path, nodeId }) {
  const cleanPath = normalizeHierarchyPath(indices, rootType, path);
  const existingIndex = cleanPath.indexOf(nodeId);
  if (existingIndex >= 0) {
    return cleanPath.slice(0, existingIndex);
  }

  const clickedNode = indices.nodeById[nodeId];
  if (!clickedNode) return cleanPath;

  if (!cleanPath.length) {
    return clickedNode.type === rootType ? [nodeId] : cleanPath;
  }

  for (let depth = cleanPath.length; depth >= 1; depth -= 1) {
    const parentPath = cleanPath.slice(0, depth);
    const parentId = parentPath[parentPath.length - 1];
    const children = getHierarchyChildren({ data, indices, rootType, path: parentPath, nodeId: parentId });
    if (children.some((child) => child.id === nodeId)) {
      return [...parentPath, nodeId];
    }
  }

  return clickedNode.type === rootType ? [nodeId] : cleanPath;
}

function buildFocusedOverviewNodeIds({ data, indices, search, type, selectedId, maxMatches, maxNodes }) {
  const allowedType = type !== "all" ? type : null;
  const matches = [];

  if (search) {
    for (const doc of data.searchIndex || []) {
      if (allowedType && doc.type !== allowedType) continue;
      const searchable = [doc.title, doc.text, doc.id, doc.type].filter(Boolean).join(" ").toLowerCase();
      if (searchable.includes(search)) matches.push(doc.id);
      if (matches.length >= maxMatches) break;
    }
  }

  if (!search && allowedType) {
    const typed = (data.graph.nodes || []).filter((node) => node.type === allowedType).map((node) => node.id);
    typed.sort((left, right) => (indices.degreeById[right] || 0) - (indices.degreeById[left] || 0));
    typed.slice(0, maxMatches).forEach((id) => matches.push(id));
  }

  if (selectedId && !matches.includes(selectedId)) {
    matches.unshift(selectedId);
  }

  const nodeIds = new Set(matches.filter((id) => indices.nodeById[id]));
  for (const id of [...nodeIds]) {
    addNeighborIds(nodeIds, indices, id, 1, maxNodes, allowedType);
    if (nodeIds.size >= maxNodes) break;
  }
  return nodeIds;
}

function addNeighborIds(nodeIds, indices, seedId, depth = 1, maxNodes = Infinity, requiredType = null) {
  let frontier = new Set([seedId]);
  for (let hop = 0; hop < depth; hop += 1) {
    const next = new Set();
    for (const current of frontier) {
      for (const item of indices.adjacency[current] || []) {
        if (nodeIds.size >= maxNodes) return;
        const node = indices.nodeById[item.nodeId];
        if (!node) continue;
        if (requiredType && node.type !== requiredType && !["job", "company", "skill"].includes(node.type)) continue;
        nodeIds.add(item.nodeId);
        next.add(item.nodeId);
      }
    }
    frontier = next;
    if (!frontier.size) break;
  }
}

function materializeSubgraph({ data, indices, nodeIds, selectedId = null }) {
  const nodes = [...nodeIds]
    .map((id) => indices.nodeById[id])
    .filter(Boolean)
    .map((node) => ({
      id: node.id,
      label: node.label || node.id,
      subtitle: buildNodeSubtitle(node, indices),
      type: node.type || "node",
      degree: indices.degreeById[node.id] || 0,
      selected: node.id === selectedId,
    }));

  const included = new Set(nodes.map((node) => node.id));
  const edges = (data.graph.edges || [])
    .filter((edge) => included.has(edge.source) && included.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      weight: edge.weight,
      confidence: edge.confidence,
    }));

  return { nodes, edges, selectedId };
}

function computeOverviewLayout(nodes, edges = [], selectedId = null) {
  if ((nodes || []).length <= FORCE_LAYOUT_LIMITS.overview) {
    return computeOverviewForceLayout(nodes, edges, selectedId);
  }

  return computeAnchoredOverviewLayout(nodes, selectedId);
}

function computeOverviewForceLayout(nodes, edges = [], selectedId = null) {
  if (!nodes?.length) return [];

  const typeCounts = new Map();
  const forceNodes = nodes.map((node) => {
    const index = typeCounts.get(node.type) || 0;
    typeCounts.set(node.type, index + 1);
    const anchor = TYPE_LAYOUT[node.type] || TYPE_LAYOUT.node;
    return seedForceNode({
      id: node.id,
      type: node.type,
      degree: node.degree || 0,
      selected: node.id === selectedId,
      anchorX: node.id === selectedId ? 0 : anchor.x,
      anchorY: node.id === selectedId ? 0 : anchor.y,
    }, index, {
      radialStep: 0.08 + (anchor.spread || 0.24) * 0.08,
      jitterScale: 0.028,
      squashY: 0.9,
    });
  });

  const links = (edges || []).map((edge) => ({
    source: edge.source,
    target: edge.target,
    weight: edge.type === "SIMILAR_TO"
      ? 1
      : edge.type === "POSTS"
        ? 0.78
        : edge.type === "REQUIRES"
          ? 0.72
          : edge.type === "PREFERS"
            ? 0.58
            : 0.52,
  }));

  runForcePass(forceNodes, links, {
    iterations: forceNodes.length > 120 ? 90 : 140,
    repulsion: forceNodes.length > 120 ? 0.011 : 0.015,
    centerStrength: 0.01,
    anchorStrength: 0.018,
    springStrength: 0.074,
    damping: 0.88,
    maxVelocity: 0.03,
    collisionPadding: 0.055,
    idealDistance: 0.2,
    selectedId,
  });

  const positions = normalizeOverviewPositions(forceNodes, selectedId);
  return nodes.map((node) => {
    const point = positions.get(node.id) || { x: 0, y: 0 };
    const emphasis = node.id === selectedId ? 1.85 : 1;
    return {
      ...node,
      x: point.x,
      y: point.y,
      size: Math.max(2.6, Math.min(12, (2.4 + Math.log2((node.degree || 1) + 1) * 1.32) * emphasis)),
    };
  });
}

function normalizeOverviewPositions(nodes, selectedId = null) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const node of nodes) {
    minX = Math.min(minX, node.x);
    maxX = Math.max(maxX, node.x);
    minY = Math.min(minY, node.y);
    maxY = Math.max(maxY, node.y);
  }

  const centerX = Number.isFinite(minX) ? (minX + maxX) / 2 : 0;
  const centerY = Number.isFinite(minY) ? (minY + maxY) / 2 : 0;
  const spanX = Math.max((maxX - minX) || 0, 0.18);
  const spanY = Math.max((maxY - minY) || 0, 0.18);
  const targetSpanX = selectedId ? 0.96 : 0.9;
  const targetSpanY = selectedId ? 0.78 : 0.82;
  const scale = Math.max(spanX / targetSpanX, spanY / targetSpanY, 0.62);

  return new Map(nodes.map((node) => [
    node.id,
    {
      x: clamp((node.x - centerX) / scale, -0.54, 0.54),
      y: clamp((node.y - centerY) / scale, -0.46, 0.46),
    },
  ]));
}

function computeAnchoredOverviewLayout(nodes, selectedId = null) {
  const groups = nodes.reduce((acc, node) => {
    (acc[node.type] ||= []).push(node);
    return acc;
  }, {});

  const positioned = [];
  for (const [type, members] of Object.entries(groups)) {
    const base = TYPE_LAYOUT[type] || TYPE_LAYOUT.node;
    const sorted = [...members].sort((left, right) => {
      if ((right.degree || 0) !== (left.degree || 0)) return (right.degree || 0) - (left.degree || 0);
      return String(left.label).localeCompare(String(right.label));
    });

    sorted.forEach((node, index) => {
      const angle = index * 2.399963229728653;
      const radius = 0.08 + Math.sqrt(index + 1) * 0.048 * (base.spread || 0.3) * 2.2;
      const jitter = seededJitter(node.id);
      const x = clamp(base.x + Math.cos(angle + jitter.angle) * radius + jitter.x * 0.05, -0.98, 0.98);
      const y = clamp(base.y + Math.sin(angle + jitter.angle) * radius + jitter.y * 0.05, -0.92, 0.92);
      const emphasis = node.id === selectedId ? 1.85 : 1;
      positioned.push({
        ...node,
        x,
        y,
        size: Math.max(2.4, Math.min(12, (2.3 + Math.log2((node.degree || 1) + 1) * 1.4) * emphasis)),
      });
    });
  }

  return positioned;
}

function seededJitter(seed) {
  let hash = 2166136261;
  const text = String(seed || "seed");
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const randA = ((hash >>> 0) % 997) / 997;
  const randB = ((Math.imul(hash, 31) >>> 0) % 991) / 991;
  return {
    x: randA - 0.5,
    y: randB - 0.5,
    angle: (randA - 0.5) * 0.65,
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function buildNodeSubtitle(node, indices) {
  if (node.type === "job") return indices.jobsById[node.id]?.company_name || "Job";
  if (node.type === "company") return "Company";
  if (node.type === "skill") return indices.skillsById[node.id]?.category || "Skill";
  if (node.type === "location") return "Location";
  if (node.type === "role_family") return "Role family";
  return humanize(node.type || "node");
}

function getJobSkills(data, jobId) {
  return [...(data.jobSkills[jobId] || [])].sort((left, right) => {
    if (left.edge_type !== right.edge_type) return left.edge_type === "REQUIRES" ? -1 : 1;
    return String(left.label).localeCompare(String(right.label));
  });
}

function getCompanyJobs(data, indices, companyId) {
  const jobIds = data.companyJobs[companyId] || [];
  return sortJobs(jobIds.map((jobId) => indices.jobsById[jobId]).filter(Boolean));
}

function getSkillJobs(data, indices, skillId) {
  const jobIds = data.skillJobs[skillId] || [];
  return sortJobs(jobIds.map((jobId) => indices.jobsById[jobId]).filter(Boolean));
}

function getSkillCompanies(indices, skillId) {
  const companyIds = indices.skillCompanies[skillId] || [];
  return companyIds.map((companyId) => indices.companiesById[companyId]).filter(Boolean);
}

function getTopSkillsForCompany(data, indices, companyId, limit = 6) {
  const stats = data.companySkillStats[companyId] || {};
  return Object.entries(stats)
    .map(([skillId, count]) => ({ skill: indices.skillsById[skillId], count }))
    .filter((item) => item.skill)
    .sort((left, right) => {
      if (left.count !== right.count) return right.count - left.count;
      return String(left.skill.label).localeCompare(String(right.skill.label));
    })
    .slice(0, limit);
}

function baseNode(id, label, subtitle, type, x, y) {
  return { id, label, subtitle, type, x, y };
}

function baseEdge(source, target, type, weight = 1, confidence = 1) {
  return { id: `${source}::${type}::${target}`, source, target, type, weight, confidence };
}

function stackPositions(count, center, gap) {
  if (!count) return [];
  const start = center - ((count - 1) * gap) / 2;
  return Array.from({ length: count }, (_, index) => start + index * gap);
}

function spreadPositions(count, center, gap) {
  if (!count) return [];
  const start = center - ((count - 1) * gap) / 2;
  return Array.from({ length: count }, (_, index) => start + index * gap);
}

function sortJobs(jobs) {
  return [...jobs].sort((left, right) => {
    const leftDate = left.posted_at || "";
    const rightDate = right.posted_at || "";
    if (leftDate !== rightDate) return rightDate.localeCompare(leftDate);
    return String(left.title).localeCompare(String(right.title));
  });
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
