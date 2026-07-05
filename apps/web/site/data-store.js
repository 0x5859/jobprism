export const PATHS = {
  summary: './data/summary.json',
  jobs: './data/jobs.json',
  companies: './data/companies.json',
  skills: './data/skills.json',
  graph: './data/graph.full.json',
  companyJobs: './data/company_jobs.json',
  skillJobs: './data/skill_jobs.json',
  jobSkills: './data/job_skills.json',
  companySkillStats: './data/company_skill_stats.json',
  jobNeighbors: './data/job_neighbors.json',
  searchIndex: './data/search-index.json',
};

export async function loadSiteData(paths = PATHS) {
  const [
    summary,
    jobs,
    companies,
    skills,
    graph,
    companyJobs,
    skillJobs,
    jobSkills,
    companySkillStats,
    jobNeighbors,
    searchIndex,
  ] = await Promise.all([
    loadJson(paths.summary),
    loadJson(paths.jobs),
    loadJson(paths.companies),
    loadJson(paths.skills),
    loadJson(paths.graph),
    loadJson(paths.companyJobs),
    loadJson(paths.skillJobs),
    loadJson(paths.jobSkills),
    loadJson(paths.companySkillStats),
    loadJson(paths.jobNeighbors),
    loadJson(paths.searchIndex),
  ]);

  return {
    summary,
    jobs,
    companies,
    skills,
    graph,
    companyJobs,
    skillJobs,
    jobSkills,
    companySkillStats,
    jobNeighbors,
    searchIndex,
  };
}

export function buildIndices(data) {
  const jobsById = Object.fromEntries((data.jobs || []).map((job) => [job.id, job]));
  const companiesById = Object.fromEntries((data.companies || []).map((company) => [company.id, company]));
  const skillsById = Object.fromEntries((data.skills || []).map((skill) => [skill.id, skill]));
  const nodeById = Object.fromEntries((data.graph?.nodes || []).map((node) => [node.id, node]));
  const edgeById = Object.fromEntries((data.graph?.edges || []).map((edge) => [edge.id, edge]));
  const searchDocsById = Object.fromEntries((data.searchIndex || []).map((doc) => [doc.id, doc]));

  const adjacency = {};
  const incoming = {};
  const degreeById = {};

  for (const edge of data.graph?.edges || []) {
    (adjacency[edge.source] ||= []).push({ nodeId: edge.target, edge, direction: 'out' });
    (adjacency[edge.target] ||= []).push({ nodeId: edge.source, edge, direction: 'in' });
    (incoming[edge.target] ||= []).push(edge);
    degreeById[edge.source] = (degreeById[edge.source] || 0) + 1;
    degreeById[edge.target] = (degreeById[edge.target] || 0) + 1;
  }

  const skillCompanies = {};
  for (const [skillId, jobIds] of Object.entries(data.skillJobs || {})) {
    skillCompanies[skillId] = uniq(jobIds.map((jobId) => jobsById[jobId]?.company_id));
  }

  return {
    jobsById,
    companiesById,
    skillsById,
    nodeById,
    edgeById,
    adjacency,
    incoming,
    degreeById,
    searchDocsById,
    skillCompanies,
    remoteModes: uniq((data.jobs || []).map((job) => job.remote_mode)).sort(),
    seniorities: uniq((data.jobs || []).map((job) => job.enrichment?.seniority)).sort(),
    nodeTypes: uniq((data.graph?.nodes || []).map((node) => node.type)).sort(),
  };
}

export function createSiteStore(data) {
  return {
    data,
    indices: buildIndices(data),
  };
}

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

function uniq(values) {
  return [...new Set((values || []).filter(Boolean))];
}
