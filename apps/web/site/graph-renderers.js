import { runForceStep } from "./graph-adapter.js";

function readCssColor(varName, fallback) {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return value || fallback;
}

function buildTypeTheme() {
  return {
    company: { color: readCssColor("--company", "#38bdf8"), border: readCssColor("--company-border", "#0ea5e9") },
    job: { color: readCssColor("--job", "#34d399"), border: readCssColor("--job-border", "#10b981") },
    skill: { color: readCssColor("--skill", "#fbbf24"), border: readCssColor("--skill-border", "#f59e0b") },
    location: { color: readCssColor("--location", "#a78bfa"), border: readCssColor("--location-border", "#8b5cf6") },
    role_family: { color: readCssColor("--role-family", "#fb7185"), border: readCssColor("--role-family-border", "#f43f5e") },
    source: { color: "#64748b", border: "#475569" },
    node: { color: readCssColor("--node", "#94a3b8"), border: readCssColor("--node-border", "#64748b") },
  };
}

let TYPE_THEME = typeof document === "undefined" ? null : buildTypeTheme();
function getTheme(type) {
  if (!TYPE_THEME) TYPE_THEME = buildTypeTheme();
  return TYPE_THEME[type] || TYPE_THEME.node;
}

// Convert a hex or rgb(...) color to rgba with target alpha. Falls back to a
// warm-gray if the input is unparseable (e.g. already rgba or CSS var).
function withAlpha(color, alpha) {
  if (!color) return `rgba(160, 152, 129, ${alpha})`;
  const trimmed = String(color).trim();
  if (trimmed.startsWith("#")) {
    let hex = trimmed.slice(1);
    if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
    if (hex.length !== 6) return `rgba(160, 152, 129, ${alpha})`;
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  const match = trimmed.match(/rgba?\(([^)]+)\)/);
  if (match) {
    const parts = match[1].split(",").map((s) => s.trim());
    if (parts.length >= 3) return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`;
  }
  return `rgba(160, 152, 129, ${alpha})`;
}

const CDN = {
  graphology: {
    test: () => window.graphology?.Graph,
    src: "https://cdnjs.cloudflare.com/ajax/libs/graphology/0.26.0/graphology.umd.min.js",
  },
  sigma: {
    test: () => window.Sigma,
    src: "https://cdnjs.cloudflare.com/ajax/libs/sigma.js/3.0.2/sigma.min.js",
  },
  cytoscape: {
    test: () => window.cytoscape,
    src: "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.33.1/cytoscape.min.js",
  },
};

let sigmaRenderer = null;
let sigmaGraph = null;
let sigmaContainer = null;
let localRenderer = null;
let sigmaCameraKey = null;
let sigmaSimulation = null;
// Global flag: set when a drag just ended, so clickNode/clickStage can ignore
// the fake "click" that sigma emits on pointerup after a drag.
let sigmaLastDragEndAt = 0;
const DRAG_CLICK_SUPPRESS_MS = 260;
const sigmaCameraMemory = new Map();
const sigmaViewState = {
  selectedId: null,
  neighborIds: new Set(),
  hasFocus: false,
  lastRenderedSelectedId: null,
  // Depth-of-field state: how deep the current expansion goes and which
  // nodes form the expanded ancestor chain.
  maxLevel: 0,
  pathIds: new Set(),
};
// Click/stage callbacks are delegated through this object so a REUSED
// renderer always calls the latest render's handlers. Binding options.*
// directly in the cold path froze the first render's closure (with its
// stale renderToken), which silently swallowed every click after the
// first expansion.
const sigmaHandlers = {
  onNodeSelect: null,
  onStageReset: null,
};

export async function renderSigmaOverview(container, snapshot, options = {}) {
  if (!container) return;
  if (!snapshot?.nodes?.length) {
    container.innerHTML = renderUnavailable("No overview nodes match the current lens.");
    return;
  }

  try {
    await ensureLibraries(["graphology", "sigma"]);
  } catch (error) {
    console.error(error);
    container.innerHTML = renderOverviewSvgFallback(snapshot, options);
    bindFallbackClicks(container, options.onNodeSelect);
    return;
  }

  const sigmaData = createSigmaData(snapshot);
  const selectedId = snapshot.selectedId || null;
  const neighborIds = new Set();

  for (const edge of sigmaData.edges) {
    if (edge.source === selectedId) neighborIds.add(edge.target);
    if (edge.target === selectedId) neighborIds.add(edge.source);
  }

  sigmaViewState.selectedId = selectedId;
  sigmaViewState.neighborIds = neighborIds;
  sigmaViewState.hasFocus = Boolean(snapshot.hasFocus);
  sigmaViewState.maxLevel = sigmaData.maxLevel || 0;
  sigmaViewState.pathIds = new Set(snapshot.expandedPath || []);

  if (!container.isConnected) return;
  // Refresh delegated handlers on EVERY render so the persistent renderer
  // always talks to the current app state.
  sigmaHandlers.onNodeSelect = options.onNodeSelect || null;
  sigmaHandlers.onStageReset = options.onStageReset || null;
  const nextCameraKey = options.cameraKey || container.id || "overview";
  const canReuse = Boolean(sigmaRenderer && sigmaGraph && sigmaContainer === container && sigmaCameraKey === nextCameraKey);

  if (canReuse) {
    const camera = sigmaRenderer.getCamera();
    const preservedState = camera?.getState ? camera.getState() : null;
    const previousSelected = sigmaViewState.lastRenderedSelectedId || null;
    replaceSigmaGraphData(sigmaGraph, sigmaData, snapshot);
    delete container.dataset.hoverNode;
    sigmaRenderer.refresh();
    if (preservedState) {
      camera.setState(preservedState);
      sigmaCameraMemory.set(nextCameraKey, preservedState);
    }
    startContinuousSimulation(sigmaGraph, sigmaData, sigmaRenderer);
    // Selection changed within the same canvas: glide the camera toward the
    // selected node instead of jump-cutting. This is the "Apple-fluid" moment
    // — expansion unfolds while the camera eases in.
    if (selectedId && selectedId !== previousSelected && sigmaGraph.hasNode(selectedId) && camera?.animate) {
      // getNodeDisplayData returns the node position in the camera's framed
      // space — the coordinate system camera.x/y actually live in.
      const displayData = sigmaRenderer.getNodeDisplayData?.(selectedId);
      if (displayData) {
        const currentRatio = camera.getState().ratio;
        camera.animate(
          { x: displayData.x, y: displayData.y, ratio: Math.min(currentRatio, 0.9) },
          { duration: 650, easing: "cubicInOut" },
          () => sigmaCameraMemory.set(nextCameraKey, camera.getState())
        );
      }
    } else if (!selectedId && previousSelected && camera?.animate) {
      // Collapsed back to the root web: ease the camera home.
      camera.animate({ x: 0.5, y: 0.5, ratio: 1.05, angle: 0 }, { duration: 650, easing: "cubicInOut" });
    }
    sigmaViewState.lastRenderedSelectedId = selectedId;
    return;
  }

  destroySigmaOverview();
  sigmaCameraKey = nextCameraKey;
  container.innerHTML = "";

  const Graph = window.graphology.Graph;
  const graph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
  replaceSigmaGraphData(graph, sigmaData, snapshot);

  sigmaGraph = graph;
  sigmaContainer = container;
  sigmaRenderer = new window.Sigma(graph, container, {
    allowInvalidContainer: true,
    defaultEdgeType: "line",
    defaultEdgeColor: "rgba(245, 245, 247, 0.08)",
    // Labels are the interface: the user must always be able to tell what a
    // node is. High density + tiny threshold ≈ every node names itself.
    labelDensity: 1.2,
    labelGridCellSize: 72,
    labelRenderedSizeThreshold: 2,
    labelColor: { color: "#d8d8dd" },
    labelFont: '"Instrument Sans", "Noto Sans SC", "PingFang SC", sans-serif',
    labelWeight: "500",
    labelSize: 12,
    minCameraRatio: 0.08,
    maxCameraRatio: 22,
    renderEdgeLabels: false,
    renderLabels: true,
    zIndex: true,
    nodeReducer(node, data) {
      const hovered = container.dataset.hoverNode;
      // Rest state: every node keeps its label — knowing what a node is
      // should never require interaction.
      if (!sigmaViewState.selectedId && !hovered) {
        return data;
      }
      const isSelected = node === sigmaViewState.selectedId;
      const isHovered = node === hovered;
      const isNeighbor = sigmaViewState.neighborIds.has(node);
      const isOnPath = sigmaViewState.pathIds.has(node);

      // Depth of field: distance (in hierarchy levels) from the frontier —
      // the newest expanded layer. Frontier + ancestors stay in focus,
      // everything else recedes in graded steps while keeping its type hue.
      const level = typeof data.level === "number" ? data.level : 0;
      const depthGap = Math.max(0, sigmaViewState.maxLevel - level);

      if (isSelected || isHovered) {
        return {
          ...data,
          size: isSelected ? data.size * 1.7 : data.size * 1.4,
          color: data.color,
          label: data.label,
          zIndex: isSelected ? 5 : 4,
        };
      }
      if (isOnPath) {
        // Open ancestors: fully lit, slightly enlarged — the breadcrumb
        // rendered in space.
        return { ...data, size: data.size * 1.25, color: data.color, label: data.label, zIndex: 4 };
      }
      if (isNeighbor || depthGap === 0) {
        // The working set: current frontier and direct neighbors.
        return { ...data, size: data.size * 1.05, color: data.color, label: data.label, zIndex: 3 };
      }
      if (depthGap === 1) {
        return { ...data, size: Math.max(3, data.size * 0.85), color: withAlpha(data.color, 0.5), label: data.label, zIndex: 2 };
      }
      // Far background (two or more levels behind): dimmest tier. Labels
      // yield to reduce noise — hover still reveals them instantly.
      return { ...data, size: Math.max(2.5, data.size * 0.7), color: withAlpha(data.color, 0.26), label: "", zIndex: 1 };
    },
    edgeReducer(edge, data) {
      const source = sigmaGraph.source(edge);
      const target = sigmaGraph.target(edge);
      if (!sigmaViewState.selectedId) {
        // The woven web is a first-class visual: hairlines stay visible,
        // weighted slightly by similarity.
        const weightBoost = typeof data.weight === "number" ? data.weight : 0.5;
        return { ...data, color: `rgba(245, 245, 247, ${0.05 + weightBoost * 0.07})`, size: 0.5 + weightBoost * 0.5 };
      }
      const connected = source === sigmaViewState.selectedId || target === sigmaViewState.selectedId;
      if (connected) {
        return { ...data, color: "rgba(56, 189, 248, 0.62)", size: Math.max(1.4, data.size * 1.5), zIndex: 3 };
      }
      // Hierarchy edges fade with their distance from the frontier, so each
      // expansion ring reads as its own stratum.
      const level = typeof data.level === "number" ? data.level : 0;
      if (level > 0) {
        const gap = Math.max(0, sigmaViewState.maxLevel - level);
        const alpha = gap === 0 ? 0.35 : gap === 1 ? 0.16 : 0.08;
        return { ...data, color: `rgba(245, 245, 247, ${alpha})`, size: gap === 0 ? 1 : 0.6, zIndex: 2 };
      }
      return { ...data, color: "rgba(245, 245, 247, 0.035)", size: 0.4, zIndex: 1 };
    },
  });

  sigmaRenderer.on("clickNode", ({ node }) => {
    // Suppress the phantom click that fires immediately after a drag ends.
    if (performance.now() - sigmaLastDragEndAt < DRAG_CLICK_SUPPRESS_MS) return;
    if (sigmaHandlers.onNodeSelect) sigmaHandlers.onNodeSelect(node);
  });

  sigmaRenderer.on("clickStage", () => {
    if (performance.now() - sigmaLastDragEndAt < DRAG_CLICK_SUPPRESS_MS) return;
    if (sigmaHandlers.onStageReset) sigmaHandlers.onStageReset();
  });

  sigmaRenderer.on("enterNode", ({ node }) => {
    container.dataset.hoverNode = node;
    sigmaRenderer.refresh();
  });

  sigmaRenderer.on("leaveNode", () => {
    delete container.dataset.hoverNode;
    sigmaRenderer.refresh();
  });

  const camera = sigmaRenderer.getCamera();
  const cameraState = sigmaCameraMemory.get(sigmaCameraKey) || computeCameraState(container, sigmaData.nodes, selectedId);
  if (cameraState) {
    camera.setState(cameraState);
  }

  sigmaViewState.lastRenderedSelectedId = selectedId;
  attachSigmaDragHandlers(sigmaRenderer, sigmaGraph);
  startContinuousSimulation(sigmaGraph, sigmaData, sigmaRenderer);
  ensureParticleLayer(container, sigmaRenderer, sigmaGraph);
  if (typeof window !== "undefined") {
    window.__sigmaDebug = { renderer: sigmaRenderer, graph: sigmaGraph, getSimulation: () => sigmaSimulation };
  }
}

export async function renderLocalCytoscape(container, snapshot, options = {}) {
  if (!container) return;
  if (!snapshot?.nodes?.length) {
    container.innerHTML = renderUnavailable("No local neighborhood is available for this selection.");
    return;
  }

  try {
    await ensureLibraries(["cytoscape"]);
  } catch (error) {
    console.error(error);
    container.innerHTML = renderSvgFallback(snapshot);
    bindFallbackClicks(container, options.onNodeSelect);
    return;
  }

  if (!container.isConnected) return;
  destroyLocalRenderer();
  container.innerHTML = "";

  const elements = toCytoscapeElements(snapshot);
  localRenderer = window.cytoscape({
    container,
    elements,
    layout: snapshot.layout === "preset"
      ? { name: "preset", fit: true, padding: 30 }
      : { name: "breadthfirst", fit: true, padding: 30 },
    minZoom: 0.34,
    maxZoom: 3.4,
    wheelSensitivity: 0.18,
    boxSelectionEnabled: false,
    autoungrabify: false,
    selectionType: "single",
    style: [
      {
        selector: "node",
        style: {
          shape: "round-rectangle",
          width: "label",
          height: "label",
          padding: "14px",
          label: "data(label)",
          color: "#e8dfc4",
          "font-family": '"Newsreader", "Noto Serif SC", Georgia, serif',
          "font-size": 13,
          "font-weight": 500,
          "text-wrap": "wrap",
          "text-max-width": 140,
          "text-valign": "center",
          "text-halign": "center",
          "background-color": "data(fill)",
          "border-color": "data(borderColor)",
          "border-width": 1.2,
          "background-opacity": 0.32,
          "overlay-opacity": 0,
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-width": 2,
          "background-opacity": 0.55,
          "shadow-blur": 28,
          "shadow-color": "data(borderColor)",
          "shadow-opacity": 0.7,
        },
      },
      {
        selector: "edge",
        style: {
          width: "mapData(weight, 0.4, 1.0, 1, 2.4)",
          "line-color": "rgba(232, 223, 196, 0.1)",
          "curve-style": "bezier",
          "overlay-opacity": 0,
        },
      },
      {
        selector: 'edge[type = "SIMILAR_TO"]',
        style: {
          "line-style": "dashed",
          "line-color": "rgba(212, 168, 87, 0.35)",
          width: 1.6,
        },
      },
      {
        selector: 'edge[type = "POSTS"]',
        style: {
          "line-color": "rgba(107, 155, 210, 0.35)",
          width: 1.8,
        },
      },
      {
        selector: 'edge[type = "REQUIRES"]',
        style: {
          "line-color": "rgba(139, 171, 120, 0.4)",
        },
      },
      {
        selector: 'edge[type = "PREFERS"]',
        style: {
          "line-color": "rgba(214, 140, 90, 0.4)",
        },
      },
    ],
  });

  localRenderer.nodes().forEach((node) => {
    const theme = inferTheme(node.data("type"));
    node.data("fill", theme.fill);
    node.data("borderColor", theme.border);
  });

  if (snapshot.selectedId && localRenderer.getElementById(snapshot.selectedId).nonempty()) {
    localRenderer.getElementById(snapshot.selectedId).select();
  }

  localRenderer.on("tap", "node", (event) => {
    if (options.onNodeSelect) options.onNodeSelect(event.target.id(), event.target.data());
  });

  localRenderer.fit(localRenderer.elements(), 34);
}

export function destroyGraphRenderers() {
  destroySigmaOverview();
  destroyLocalRenderer();
}

export function renderSvgFallback(snapshot) {
  if (!snapshot?.nodes?.length) {
    return renderUnavailable("No local neighborhood is available for this selection.");
  }

  const width = 960;
  const height = Math.max(420, ...snapshot.nodes.map((node) => (node.y || 0) + 90));
  const nodeMap = Object.fromEntries(snapshot.nodes.map((node) => [node.id, node]));

  return `
    <div class="graph-shell graph-shell-fallback">
      <div class="graph-caption">${escapeHtml(snapshot.caption || "Static fallback graph")}</div>
      <div class="graph-stage">
        <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(snapshot.title || "Local graph")}">
          ${(snapshot.edges || [])
            .map((edge) => {
              const source = nodeMap[edge.source];
              const target = nodeMap[edge.target];
              if (!source || !target) return "";
              return `<line class="graph-edge edge-${escapeHtml(String(edge.type).toLowerCase())}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"></line>`;
            })
            .join("")}
          ${(snapshot.nodes || []).map((node) => renderSvgNode(node)).join("")}
        </svg>
      </div>
    </div>
  `;
}

function renderOverviewSvgFallback(snapshot) {
  if (!snapshot?.nodes?.length) {
    return renderUnavailable("No overview nodes are available.");
  }

  const width = 1600;
  const height = 1000;
  return `
    <div class="graph-shell graph-shell-fallback graph-overview-fallback">
      <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Overview graph fallback">
        ${(snapshot.edges || []).map((edge) => renderOverviewEdge(edge, snapshot.nodes, width, height)).join("")}
        ${(snapshot.nodes || []).map((node) => renderOverviewNode(node, width, height)).join("")}
      </svg>
    </div>
  `;
}

function createSigmaData(snapshot) {
  // Modern-minimal sizing: crisp dots, not orbs. Hubs earn presence through
  // degree, and every node is big enough to carry a label.
  // Deliberately uneven sizes: companies read as planets, skills as suns,
  // jobs as small satellites — size is a type signal, not just degree.
  const baseSize = (type) => {
    if (type === "company") return 11;
    if (type === "skill") return 10;
    if (type === "job") return 6.5;
    if (type === "location" || type === "role_family") return 5.5;
    return 5.5;
  };
  const pathIds = new Set(snapshot.expandedPath || []);
  return {
    maxLevel: (snapshot.expandedPath || []).length,
    nodes: (snapshot.nodes || []).map((node) => {
      const theme = getTheme(node.type);
      const degreeBoost = Math.min(7, Math.log2((node.degree || 1) + 1) * 1.7);
      return {
        id: node.id,
        label: node.label,
        nodeType: node.type,
        x: node.x,
        y: node.y,
        size: Math.max(node.size || 0, baseSize(node.type) + degreeBoost),
        color: theme.color,
        borderColor: theme.border,
        degree: node.degree || 0,
        // Depth-of-field metadata: which hierarchy level this node lives on
        // and whether it is an expanded ancestor ("open folder").
        level: typeof node.level === "number" ? node.level : 0,
        onPath: pathIds.has(node.id),
      };
    }),
    edges: (snapshot.edges || []).map((edge) => ({
      id: edge.id || `${edge.source}::${edge.type}::${edge.target}`,
      source: edge.source,
      target: edge.target,
      edgeType: edge.type,
      weight: typeof edge.weight === "number" ? edge.weight : 0.5,
      level: typeof edge.level === "number" ? edge.level : 0,
      size: edge.type === "WOVEN" ? 0.6 : edge.type === "SIMILAR_TO" ? 1 : 0.8,
      color: edge.type === "WOVEN"
        ? "rgba(245, 245, 247, 0.09)"
        : edge.type === "SIMILAR_TO"
          ? "rgba(56, 189, 248, 0.18)"
          : "rgba(245, 245, 247, 0.1)",
    })),
  };
}

function computeCameraState(container, nodes, selectedId) {
  if (!nodes?.length) {
    return null;
  }
  const fit = computeFitRatio(nodes);
  const bounds = computeNodeBounds(nodes);
  const centroid = selectedId ? computeNodeCentroid(nodes, selectedId) : { x: 0, y: 0 };
  return {
    x: 0.5 + (centroid.x * 0.5),
    y: 0.5 + (centroid.y * 0.5),
    ratio: fitForContainer(fit, bounds, container),
    angle: 0,
  };
}

function computeFitRatio(nodes) {
  const bounds = computeNodeBounds(nodes);
  const spanX = Math.max(0.1, bounds.maxX - bounds.minX);
  const spanY = Math.max(0.1, bounds.maxY - bounds.minY);
  const span = Math.max(spanX, spanY);
  return Math.min(3.2, Math.max(1.25, span * 1.8));
}

function fitForContainer(baseRatio, bounds, container) {
  const width = Math.max(container?.clientWidth || 0, 1);
  const height = Math.max(container?.clientHeight || 0, 1);
  const aspect = width / height;
  const spanX = Math.max(0.1, bounds.maxX - bounds.minX);
  const spanY = Math.max(0.1, bounds.maxY - bounds.minY);
  const widthBias = aspect < 1.2 ? (spanX / Math.max(aspect, 0.55)) * 1.45 : spanX * 1.55;
  const heightBias = spanY * 1.55;
  return Math.min(3.6, Math.max(baseRatio, widthBias, heightBias));
}

function computeNodeBounds(nodes) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const node of nodes) {
    minX = Math.min(minX, node.x ?? 0);
    maxX = Math.max(maxX, node.x ?? 0);
    minY = Math.min(minY, node.y ?? 0);
    maxY = Math.max(maxY, node.y ?? 0);
  }

  if (!Number.isFinite(minX)) {
    return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  }

  return { minX, maxX, minY, maxY };
}

function computeNodeCentroid(nodes, selectedId = null) {
  let totalWeight = 0;
  let sumX = 0;
  let sumY = 0;
  let selectedNode = null;

  for (const node of nodes) {
    if (node.id === selectedId) selectedNode = node;
    const weight = node.id === selectedId ? 1.35 : Math.max(0.8, (node.size || 4) / 6);
    totalWeight += weight;
    sumX += (node.x ?? 0) * weight;
    sumY += (node.y ?? 0) * weight;
  }

  if (!totalWeight) return { x: 0, y: 0 };
  const centroid = {
    x: sumX / totalWeight,
    y: sumY / totalWeight,
  };
  if (!selectedNode) return centroid;
  return {
    x: (selectedNode.x * 0.62) + (centroid.x * 0.38),
    y: (selectedNode.y * 0.62) + (centroid.y * 0.38),
  };
}

function toCytoscapeElements(snapshot) {
  return {
    nodes: (snapshot.nodes || []).map((node) => ({
      data: {
        id: node.id,
        label: node.label,
        subtitle: node.subtitle || "",
        type: node.type || "node",
        degree: node.degree || 0,
        selected: node.id === snapshot.selectedId,
        fill: inferTheme(node.type).fill,
        borderColor: inferTheme(node.type).border,
      },
      position: typeof node.x === "number" && typeof node.y === "number" ? { x: node.x, y: node.y } : undefined,
      selectable: true,
      grabbable: true,
    })),
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

async function ensureLibraries(names) {
  for (const name of names) {
    if (CDN[name].test()) continue;
    await loadScript(CDN[name].src);
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-external-graph-lib="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.defer = true;
    script.dataset.externalGraphLib = src;
    script.onload = () => {
      script.dataset.loaded = "true";
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

function bindFallbackClicks(container, onNodeSelect) {
  if (!container || !onNodeSelect) return;
  container.querySelectorAll("[data-fallback-node]").forEach((el) => {
    el.addEventListener("click", (event) => {
      event.preventDefault();
      onNodeSelect(el.dataset.fallbackNode);
    });
  });
}

/* ── Particle layer ─────────────────────────────────────────────────────
   A 2D canvas above the sigma stack (pointer-events: none). Every node
   type carries its own particle signature, which doubles as a THIRD
   distinction dimension besides hue and size:
     skill        → an amber sun: 3 slow orbiting sparks
     company      → a cyan planet: one thin ring + a moon
     job          → a mint satellite: 1 small fast orbiter
     location/etc → a single lazy mote
   Intensity follows the depth-of-field tiers, and newborn nodes emit a
   radial burst when they unfold from their parent. */

let particleLayer = null;

function hash01(text, salt = 0) {
  let hash = 2166136261 ^ salt;
  const value = String(text);
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 9973) / 9973;
}

function particleSprite(color) {
  if (!particleLayer) return null;
  let sprite = particleLayer.sprites.get(color);
  if (!sprite) {
    const size = 24;
    sprite = document.createElement("canvas");
    sprite.width = size;
    sprite.height = size;
    const ctx = sprite.getContext("2d");
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, withAlpha(color, 0.95));
    gradient.addColorStop(0.35, withAlpha(color, 0.5));
    gradient.addColorStop(1, withAlpha(color, 0));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
    particleLayer.sprites.set(color, sprite);
  }
  return sprite;
}

function ensureParticleLayer(container, renderer, graph) {
  if (typeof window === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  destroyParticleLayer();

  const canvas = document.createElement("canvas");
  canvas.className = "particle-layer";
  container.appendChild(canvas);
  particleLayer = {
    canvas,
    ctx: canvas.getContext("2d"),
    renderer,
    graph,
    container,
    sprites: new Map(),
    bursts: [],
    rafId: null,
    start: performance.now(),
  };

  const TWO_PI = Math.PI * 2;

  function tierIntensity(id, attrs) {
    const state = sigmaViewState;
    if (!state.selectedId) return 0.55;
    if (id === state.selectedId) return 1;
    if (state.pathIds.has(id)) return 0.85;
    const level = typeof attrs.level === "number" ? attrs.level : 0;
    const gap = Math.max(0, state.maxLevel - level);
    if (state.neighborIds.has(id) || gap === 0) return 0.7;
    if (gap === 1) return 0.28;
    return 0;
  }

  function draw(now) {
    const layer = particleLayer;
    if (!layer || layer.canvas !== canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    const ctx = layer.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";

    const t = (now - layer.start) / 1000;
    const ratio = renderer.getCamera().getState().ratio || 1;
    const sizeScale = 1 / Math.sqrt(Math.max(ratio, 0.01));
    const tooMany = graph.order > 260;

    graph.forEachNode((id, attrs) => {
      const intensity = tierIntensity(id, attrs);
      if (intensity <= 0) return;
      if (tooMany && intensity < 0.6) return;
      const pos = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
      if (pos.x < -40 || pos.y < -40 || pos.x > width + 40 || pos.y > height + 40) return;

      const nodeRadius = (attrs.size || 6) * sizeScale;
      const type = attrs.nodeType;
      const color = attrs.color;
      const sprite = particleSprite(color);
      if (!sprite) return;
      const phase = hash01(id) * TWO_PI;

      if (type === "skill") {
        // Amber sun: three slow sparks.
        for (let i = 0; i < 3; i += 1) {
          const angle = phase + t * (0.35 + hash01(id, i) * 0.2) + (i * TWO_PI) / 3;
          const orbit = nodeRadius * (1.75 + Math.sin(t * 0.9 + phase + i) * 0.22);
          const px = pos.x + Math.cos(angle) * orbit;
          const py = pos.y + Math.sin(angle) * orbit;
          const pulse = 0.55 + Math.sin(t * 2 + phase + i * 2.1) * 0.35;
          const s = (2.4 + pulse * 1.6) * Math.min(sizeScale, 1.6);
          ctx.globalAlpha = intensity * (0.35 + pulse * 0.4);
          ctx.drawImage(sprite, px - s, py - s, s * 2, s * 2);
        }
      } else if (type === "company") {
        // Cyan planet: a thin ring plus one moon.
        ctx.globalAlpha = intensity * 0.3;
        ctx.strokeStyle = withAlpha(color, 0.8);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(pos.x, pos.y, nodeRadius * 1.9, nodeRadius * 0.72, phase * 0.6, 0, TWO_PI);
        ctx.stroke();
        const moonAngle = phase + t * 0.55;
        const mx = pos.x + Math.cos(moonAngle) * nodeRadius * 1.9;
        const my = pos.y + Math.sin(moonAngle) * nodeRadius * 0.72;
        const ms = 2.6 * Math.min(sizeScale, 1.6);
        ctx.globalAlpha = intensity * 0.75;
        ctx.drawImage(sprite, mx - ms, my - ms, ms * 2, ms * 2);
      } else if (type === "job") {
        // Mint satellite: one small fast orbiter.
        const angle = phase + t * 1.5;
        const orbit = nodeRadius * 1.65;
        const px = pos.x + Math.cos(angle) * orbit;
        const py = pos.y + Math.sin(angle) * orbit * 0.9;
        const s = 2 * Math.min(sizeScale, 1.6);
        ctx.globalAlpha = intensity * 0.7;
        ctx.drawImage(sprite, px - s, py - s, s * 2, s * 2);
      } else {
        // Lazy mote for locations / role families / misc.
        const angle = phase + t * 0.25;
        const orbit = nodeRadius * 1.6;
        const px = pos.x + Math.cos(angle) * orbit;
        const py = pos.y + Math.sin(angle) * orbit;
        const s = 1.8 * Math.min(sizeScale, 1.6);
        ctx.globalAlpha = intensity * 0.4;
        ctx.drawImage(sprite, px - s, py - s, s * 2, s * 2);
      }
    });

    // Newborn bursts: radial sparks that live ~650ms.
    const alive = [];
    for (const burst of layer.bursts) {
      const age = now - burst.born;
      if (age > 650) continue;
      alive.push(burst);
      if (!graph.hasNode(burst.id)) continue;
      const attrs = graph.getNodeAttributes(burst.id);
      const pos = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
      const progress = age / 650;
      const sprite = particleSprite(attrs.color);
      if (!sprite) continue;
      for (let i = 0; i < 6; i += 1) {
        const angle = (i * TWO_PI) / 6 + hash01(burst.id, i) * 0.8;
        const dist = (attrs.size || 6) * sizeScale * (1 + progress * 2.4);
        const px = pos.x + Math.cos(angle) * dist;
        const py = pos.y + Math.sin(angle) * dist;
        const s = 2.6 * (1 - progress);
        ctx.globalAlpha = (1 - progress) * 0.8;
        ctx.drawImage(sprite, px - s, py - s, s * 2, s * 2);
      }
    }
    layer.bursts = alive;

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    layer.rafId = requestAnimationFrame(draw);
  }

  particleLayer.rafId = requestAnimationFrame(draw);
}

function destroyParticleLayer() {
  if (!particleLayer) return;
  if (particleLayer.rafId) cancelAnimationFrame(particleLayer.rafId);
  particleLayer.canvas?.remove();
  particleLayer = null;
}

function emitParticleBursts(nodeIds) {
  if (!particleLayer || !nodeIds?.length) return;
  const born = performance.now();
  for (const id of nodeIds.slice(0, 24)) {
    particleLayer.bursts.push({ id, born });
  }
}

function destroySigmaOverview() {
  destroyParticleLayer();
  stopContinuousSimulation();
  if (sigmaRenderer && typeof sigmaRenderer.getCamera === "function" && sigmaCameraKey) {
    try {
      const camera = sigmaRenderer.getCamera();
      if (camera && typeof camera.getState === "function") {
        sigmaCameraMemory.set(sigmaCameraKey, camera.getState());
      }
    } catch (_error) {
      // noop
    }
  }
  if (sigmaRenderer?.__dragDetach) {
    try { sigmaRenderer.__dragDetach(); } catch (_e) { /* noop */ }
  }
  if (sigmaRenderer && typeof sigmaRenderer.kill === "function") {
    sigmaRenderer.kill();
  }
  sigmaRenderer = null;
  sigmaGraph = null;
  sigmaContainer = null;
  sigmaCameraKey = null;
}

function stopContinuousSimulation() {
  if (sigmaSimulation) sigmaSimulation.stop();
  sigmaSimulation = null;
}

function startContinuousSimulation(graph, sigmaData, renderer) {
  const prevSnapshot = sigmaSimulation?._snapshot?.() || null;
  stopContinuousSimulation();
  if (!graph || !sigmaData?.nodes?.length || !renderer) return;
  if (sigmaData.nodes.length > 400) return;

  const simNodes = sigmaData.nodes.map((node) => {
    const prev = prevSnapshot?.get(node.id);
    const current = graph.hasNode(node.id)
      ? { x: graph.getNodeAttribute(node.id, "x"), y: graph.getNodeAttribute(node.id, "y") }
      : { x: node.x, y: node.y };
    return {
      id: node.id,
      x: prev?.x ?? current.x,
      y: prev?.y ?? current.y,
      anchorX: prev?.anchorX ?? node.x,
      anchorY: prev?.anchorY ?? node.y,
      vx: prev?.vx ?? 0,
      vy: prev?.vy ?? 0,
      degree: node.degree || 1,
      fixed: prev?.fixed ?? false,
    };
  });
  const simNodeById = new Map(simNodes.map((node) => [node.id, node]));
  const simLinks = sigmaData.edges
    .map((edge) => ({
      source: edge.source,
      target: edge.target,
      // Hierarchy (leveled) edges get a longer spring rest length: children
      // ring out from their parent instead of piling on top of it. In
      // runForceStep, desired = idealDistance + (1 - weight) * 0.18, so
      // capping weight at 0.45 buys ~0.1 extra units of breathing room.
      weight: edge.level > 0
        ? Math.min(0.45, typeof edge.weight === "number" ? edge.weight : 0.45)
        : (typeof edge.weight === "number" ? edge.weight : 0.5),
    }))
    .filter((link) => simNodeById.has(link.source) && simNodeById.has(link.target));

  // Obsidian-feel physics: a burst of energy that settles DECISIVELY
  // (fast alpha decay + strong braking), then rests at a barely-alive
  // twinkle. Previous tuning (damping .93, maxVel .022) glided like ice
  // and took many seconds to reach steady state.
  let alpha = 0.55;
  const alphaTwinkle = 0.006;
  const alphaDecay = 0.015;
  let rafId = null;
  let running = true;

  function step() {
    if (!running) { rafId = null; return; }
    runForceStep(simNodes, simLinks, {
      alpha,
      iterations: 1,
      // High ceiling + strong braking = big corrections happen fast and
      // stop dead, instead of slow endless coasting.
      maxVelocity: 0.06,
      damping: 0.68,
      springStrength: 0.09,
      // Tiny Brownian shimmer scaled with energy — never zero, so the field
      // always feels alive without ever being chaotic.
      noise: 0.00004 + alpha * 0.0001,
      // Center force only nudges things back if they drift miles out, leaves
      // local motion alone.
      centerStrength: 0.0014,
      anchorStrength: 0,
      collisionPadding: 0.085,
      clampBound: 5.0,
    });
    // Rigid recentering: translate the whole constellation so its centroid
    // eases back to the origin. A translation can't deform the web — it just
    // keeps the universe from wandering out of frame.
    let cx = 0;
    let cy = 0;
    for (const node of simNodes) { cx += node.x; cy += node.y; }
    cx /= simNodes.length;
    cy /= simNodes.length;
    const recenter = 0.04;
    for (const node of simNodes) {
      if (!node.fixed) {
        node.x -= cx * recenter;
        node.y -= cy * recenter;
      }
    }
    for (const node of simNodes) {
      if (graph.hasNode(node.id)) {
        graph.setNodeAttribute(node.id, "x", node.x);
        graph.setNodeAttribute(node.id, "y", node.y);
      }
    }
    // Decay toward twinkle, never below it. A reheat (drag, hover) pumps
    // energy back in.
    if (alpha > alphaTwinkle) alpha = Math.max(alphaTwinkle, alpha - alphaDecay);
    rafId = requestAnimationFrame(step);
  }

  sigmaSimulation = {
    getAlpha() { return alpha; },
    isRunning() { return running; },
    getSimNode(id) { return simNodeById.get(id); },
    _snapshot() {
      const map = new Map();
      for (const node of simNodes) {
        map.set(node.id, {
          x: node.x,
          y: node.y,
          anchorX: node.anchorX,
          anchorY: node.anchorY,
          vx: node.vx,
          vy: node.vy,
          fixed: node.fixed,
        });
      }
      return map;
    },
    setFixed(id, fixed) {
      const node = simNodeById.get(id);
      if (node) node.fixed = Boolean(fixed);
    },
    setPosition(id, x, y) {
      const node = simNodeById.get(id);
      if (node) {
        node.x = x;
        node.y = y;
        node.vx = 0;
        node.vy = 0;
      }
    },
    /** Apply a velocity (drag inertia) so a released node keeps coasting. */
    kick(id, vx, vy) {
      const node = simNodeById.get(id);
      if (node) {
        // Cap so a fast flick doesn't fling the node off the map.
        const cap = 0.05;
        const speed = Math.hypot(vx, vy);
        const scale = speed > cap ? cap / speed : 1;
        node.vx = vx * scale;
        node.vy = vy * scale;
      }
    },
    reanchor(id) {
      const node = simNodeById.get(id);
      if (node) {
        node.anchorX = node.x;
        node.anchorY = node.y;
      }
    },
    reheat(next = 0.25) {
      alpha = Math.max(alpha, next);
      if (!running) {
        running = true;
        rafId = requestAnimationFrame(step);
      }
    },
    stop() {
      running = false;
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
    },
  };
  rafId = requestAnimationFrame(step);
}

function attachSigmaDragHandlers(renderer, graph) {
  if (!renderer || !graph) return;
  // Idempotency: never attach twice to the same renderer.
  if (renderer.__dragHandlersAttached) return;
  renderer.__dragHandlersAttached = true;

  const drag = {
    node: null,
    armed: false,
    isDragging: false,
    startX: 0, startY: 0,
    lastGraphX: 0, lastGraphY: 0,
    lastT: 0,
    velocityX: 0, velocityY: 0,
  };
  const mouseCaptor = renderer.getMouseCaptor();

  renderer.on("downNode", ({ node, event }) => {
    drag.node = node;
    drag.armed = true;
    drag.isDragging = false;
    drag.startX = event?.x ?? 0;
    drag.startY = event?.y ?? 0;
    drag.velocityX = 0;
    drag.velocityY = 0;
    drag.lastT = performance.now();
  });

  mouseCaptor.on("mousemovebody", (event) => {
    if (!drag.armed || !drag.node) return;
    if (!drag.isDragging) {
      const dx = (event.x ?? 0) - drag.startX;
      const dy = (event.y ?? 0) - drag.startY;
      if (dx * dx + dy * dy < 9) return;
      drag.isDragging = true;
      const startPos = renderer.viewportToGraph({ x: drag.startX, y: drag.startY });
      drag.lastGraphX = startPos.x;
      drag.lastGraphY = startPos.y;
      if (sigmaSimulation) {
        sigmaSimulation.setFixed(drag.node, true);
        // Pump the system so the rest of the cluster reacts visibly.
        sigmaSimulation.reheat(0.6);
      }
      if (graph.hasNode(drag.node)) {
        graph.setNodeAttribute(drag.node, "highlighted", true);
      }
    }
    const pos = renderer.viewportToGraph(event);
    if (graph.hasNode(drag.node)) {
      graph.setNodeAttribute(drag.node, "x", pos.x);
      graph.setNodeAttribute(drag.node, "y", pos.y);
    }
    if (sigmaSimulation) sigmaSimulation.setPosition(drag.node, pos.x, pos.y);

    // Track velocity (graph units per frame) so we can carry inertia on release.
    const now = performance.now();
    const dt = Math.max(8, now - drag.lastT);
    // Smooth via low-pass filter so a single jittery frame doesn't dominate.
    const smoothing = 0.45;
    drag.velocityX = drag.velocityX * (1 - smoothing) + ((pos.x - drag.lastGraphX) / dt) * 16 * smoothing;
    drag.velocityY = drag.velocityY * (1 - smoothing) + ((pos.y - drag.lastGraphY) / dt) * 16 * smoothing;
    drag.lastGraphX = pos.x;
    drag.lastGraphY = pos.y;
    drag.lastT = now;

    // Block camera pan; do NOT stopPropagation (sigma's pointer capture
    // bookkeeping needs the event flow uninterrupted).
    if (typeof event.preventSigmaDefault === "function") event.preventSigmaDefault();
    if (event.original) event.original.preventDefault?.();
  });

  const endDrag = () => {
    const wasDragging = drag.isDragging;
    if (drag.node && wasDragging) {
      if (sigmaSimulation) {
        // Reanchor first (so anchor pull, if any, won't yank it back),
        // then unfix, then transfer the drag's terminal velocity so it
        // glides on like a flicked star, then reheat the field.
        sigmaSimulation.reanchor(drag.node);
        sigmaSimulation.setFixed(drag.node, false);
        sigmaSimulation.kick(drag.node, drag.velocityX, drag.velocityY);
        sigmaSimulation.reheat(0.5);
      }
      if (graph.hasNode(drag.node)) graph.removeNodeAttribute(drag.node, "highlighted");
    }
    drag.node = null;
    drag.armed = false;
    drag.isDragging = false;
    drag.velocityX = 0;
    drag.velocityY = 0;
    if (wasDragging) sigmaLastDragEndAt = performance.now();
  };

  mouseCaptor.on("mouseup", endDrag);

  // Safety net: if the pointer is released outside sigma's capture area (e.g.
  // user drags a node off the canvas and releases over a side panel), sigma's
  // mouseup might not fire. Catch it on the document.
  const documentEndDrag = () => {
    if (drag.armed) endDrag();
  };
  document.addEventListener("pointerup", documentEndDrag);
  document.addEventListener("pointercancel", documentEndDrag);
  // Store removers so destroySigmaOverview can unbind them.
  renderer.__dragDetach = () => {
    document.removeEventListener("pointerup", documentEndDrag);
    document.removeEventListener("pointercancel", documentEndDrag);
  };
}

let nodeGrowthRafId = null;

function replaceSigmaGraphData(graph, sigmaData, snapshot) {
  const previousPositions = new Map();
  graph.forEachNode((id, attrs) => {
    if (typeof attrs.x === "number" && typeof attrs.y === "number") {
      previousPositions.set(id, { x: attrs.x, y: attrs.y });
    }
  });
  const hadNodes = previousPositions.size > 0;
  graph.clear();
  const newborn = [];
  for (const node of sigmaData.nodes) {
    if (!graph.hasNode(node.id)) {
      const prev = previousPositions.get(node.id);
      const isNew = hadNodes && !prev;
      graph.addNode(node.id, {
        ...node,
        x: prev ? prev.x : node.x,
        y: prev ? prev.y : node.y,
        // Newborn nodes start at zero size and grow in — paired with
        // spawn-at-parent positions this makes expansion feel organic.
        size: isNew ? 0.01 : node.size,
      });
      if (isNew) newborn.push({ id: node.id, targetSize: node.size });
    }
  }
  for (const edge of sigmaData.edges) {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && !graph.hasEdge(edge.id)) {
      graph.addUndirectedEdgeWithKey(edge.id, edge.source, edge.target, edge);
    }
  }
  if (newborn.length) {
    animateNodeGrowth(graph, newborn);
    emitParticleBursts(newborn.map((item) => item.id));
  }
}

function animateNodeGrowth(graph, newborn, duration = 420) {
  if (nodeGrowthRafId) cancelAnimationFrame(nodeGrowthRafId);
  const start = performance.now();
  const easeOutBack = (t) => {
    const c1 = 1.30158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  };
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = easeOutBack(t);
    for (const item of newborn) {
      if (graph.hasNode(item.id)) {
        graph.setNodeAttribute(item.id, "size", Math.max(0.01, item.targetSize * eased));
      }
    }
    if (t < 1) {
      nodeGrowthRafId = requestAnimationFrame(step);
    } else {
      nodeGrowthRafId = null;
    }
  };
  nodeGrowthRafId = requestAnimationFrame(step);
}

function destroyLocalRenderer() {
  if (localRenderer && typeof localRenderer.destroy === "function") {
    localRenderer.destroy();
  }
  localRenderer = null;
}

function inferTheme(type) {
  const theme = getTheme(type);
  const softVarName = type === "role_family" ? "--role-family-soft" : `--${type}-soft`;
  const fill = readCssColor(softVarName, theme.color);
  return { fill, border: theme.border };
}

function renderUnavailable(message) {
  return `<div class="empty-inline"><p>${escapeHtml(message)}</p></div>`;
}

function renderOverviewNode(node, width, height) {
  const { x, y } = scaleNode(node, width, height);
  const radius = Math.max(3.2, Math.min(12, (node.size || 4) * 1.8));
  const theme = getTheme(node.type);
  return `
    <g class="overview-node" data-fallback-node="${escapeHtml(node.id)}" tabindex="0">
      <circle cx="${x}" cy="${y}" r="${radius}" fill="${theme.color}" fill-opacity="0.8"></circle>
      ${node.selected ? `<circle cx="${x}" cy="${y}" r="${radius + 7}" fill="none" stroke="${theme.border}" stroke-opacity="0.24" stroke-width="2"></circle>` : ""}
    </g>
  `;
}

function renderOverviewEdge(edge, nodes, width, height) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target) return "";
  const a = scaleNode(source, width, height);
  const b = scaleNode(target, width, height);
  return `<line class="graph-edge edge-${escapeHtml(String(edge.type).toLowerCase())}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke-opacity="0.22"></line>`;
}

function scaleNode(node, width, height) {
  return {
    x: ((node.x + 1) / 2) * width,
    y: ((node.y + 1) / 2) * height,
  };
}

function renderSvgNode(node) {
  const width = 180;
  const height = 56;
  const x = (node.x || 0) - width / 2;
  const y = (node.y || 0) - height / 2;
  const label = truncate(node.label, 28);
  const subtitle = truncate(node.subtitle || "", 24);
  const type = escapeHtml(node.type || "node");
  return `
    <g class="graph-node node-${type}" data-fallback-node="${escapeHtml(node.id)}">
      <rect x="${x}" y="${y}" width="${width}" height="${height}" rx="18" ry="18"></rect>
      <text x="${node.x}" y="${subtitle ? node.y - 6 : node.y + 4}" text-anchor="middle">
        <tspan class="graph-node-title">${escapeHtml(label)}</tspan>
        ${subtitle ? `<tspan class="graph-node-subtitle" x="${node.x}" dy="16">${escapeHtml(subtitle)}</tspan>` : ""}
      </text>
    </g>
  `;
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
