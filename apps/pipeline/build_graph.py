from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from . import db
from .ids import edge_id
from .io_utils import write_json
from .schema_validation import validate_many, validate_payload

def build_public_graph(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    run_id: str | None = None,
    observability: dict[str, Any] | None = None,
) -> dict[str, int]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with db.connect(db_path) as conn:
        companies = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM companies ORDER BY id ASC")]
        jobs = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM jobs ORDER BY id ASC")]
        skills = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM skills ORDER BY id ASC")]
        enrichments = {row["job_id"]: dict(row) for row in db.fetch_all(conn, "SELECT * FROM job_enrichment")}
        job_skill_edges = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM job_skill_edges ORDER BY job_id ASC, skill_id ASC")]

    company_map = {company["id"]: _hydrate_company(company) for company in companies}
    skill_map = {skill["id"]: _hydrate_skill(skill) for skill in skills}
    job_map = {job["id"]: _hydrate_job(job, enrichments.get(job["id"]), company_map.get(job["company_id"])) for job in jobs}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for company in company_map.values():
        nodes.append({"id": company["id"], "type": "company", "label": company["name"], "data": company})

    location_nodes: dict[str, dict[str, Any]] = {}
    role_family_nodes: dict[str, dict[str, Any]] = {}

    for skill in skill_map.values():
        nodes.append({"id": skill["id"], "type": "skill", "label": skill["label"], "data": skill})

    company_jobs: dict[str, list[str]] = defaultdict(list)
    skill_jobs: dict[str, list[str]] = defaultdict(list)
    job_skills: dict[str, list[dict[str, Any]]] = defaultdict(list)
    company_skill_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for job in job_map.values():
        # Keep graph nodes lean: full job details live in jobs.json (keyed by
        # id); embedding descriptions here ballooned graph.full.json to ~8MB.
        node_data = {
            "id": job["id"],
            "title": job["title"],
            "company_id": job["company_id"],
            "company_name": job.get("company_name"),
            "location_text": job.get("location_text"),
            "seniority": (job.get("enrichment") or {}).get("seniority"),
            "role_family": (job.get("enrichment") or {}).get("role_family"),
            "posted_at": job.get("posted_at"),
        }
        nodes.append({"id": job["id"], "type": "job", "label": job["title"], "data": node_data})
        company_jobs[job["company_id"]].append(job["id"])
        edges.append(
            {
                "id": edge_id(job["company_id"], "POSTS", job["id"]),
                "source": job["company_id"],
                "target": job["id"],
                "type": "POSTS",
                "weight": 1.0,
                "confidence": 1.0,
                "data": None,
            }
        )

        if job.get("location_text"):
            location_id = f"location:{_slug(job['location_text'])}"
            location_nodes.setdefault(
                location_id,
                {"id": location_id, "type": "location", "label": job["location_text"], "data": {"location_text": job["location_text"]}},
            )
            edges.append(
                {
                    "id": edge_id(job["id"], "LOCATED_IN", location_id),
                    "source": job["id"],
                    "target": location_id,
                    "type": "LOCATED_IN",
                    "weight": 1.0,
                    "confidence": 0.9,
                    "data": None,
                }
            )

        role_family = (job.get("enrichment") or {}).get("role_family")
        if role_family:
            role_id = f"role_family:{_slug(role_family)}"
            role_family_nodes.setdefault(
                role_id,
                {"id": role_id, "type": "role_family", "label": role_family, "data": {"role_family": role_family}},
            )
            edges.append(
                {
                    "id": edge_id(job["id"], "BELONGS_TO", role_id),
                    "source": job["id"],
                    "target": role_id,
                    "type": "BELONGS_TO",
                    "weight": 1.0,
                    "confidence": 0.7,
                    "data": None,
                }
            )

    nodes.extend(location_nodes.values())
    nodes.extend(role_family_nodes.values())

    for edge in job_skill_edges:
        skill = skill_map.get(edge["skill_id"])
        job = job_map.get(edge["job_id"])
        if not skill or not job:
            continue
        edges.append(
            {
                "id": edge["id"],
                "source": edge["job_id"],
                "target": edge["skill_id"],
                "type": edge["edge_type"],
                "weight": edge["weight"],
                "confidence": edge["confidence"],
                "data": {
                    "provenance": edge["provenance"],
                    "evidence": json.loads(edge["evidence_json"]) if edge.get("evidence_json") else [],
                },
            }
        )
        skill_jobs[edge["skill_id"]].append(edge["job_id"])
        company_skill_stats[job["company_id"]][edge["skill_id"]] += 1
        job_skills[edge["job_id"]].append(
            {
                "skill_id": edge["skill_id"],
                "label": skill["label"],
                "edge_type": edge["edge_type"],
                "weight": edge["weight"],
                "confidence": edge["confidence"],
            }
        )

    skill_sets = {job_id: {item["skill_id"] for item in items} for job_id, items in job_skills.items()}
    job_neighbors: dict[str, dict[str, Any]] = defaultdict(lambda: {"similar_jobs": [], "skills": [], "company_id": None})

    for job_identifier, items in job_skills.items():
        job_neighbors[job_identifier]["skills"] = items
        job_neighbors[job_identifier]["company_id"] = job_map[job_identifier]["company_id"]

    # Collect all candidate pairs first, then keep only each job's top-K
    # most-similar peers. With a small taxonomy many jobs share identical
    # skill sets (Jaccard 1.0), and the unbounded O(n^2) edge list dominated
    # graph.full.json (6k+ SIMILAR_TO edges at 500 jobs).
    similar_candidates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for job_a, job_b in combinations(sorted(job_map), 2):
        similarity = _jaccard(skill_sets.get(job_a, set()), skill_sets.get(job_b, set()))
        if similarity < 0.35:
            continue
        similar_candidates[job_a].append((job_b, similarity))
        similar_candidates[job_b].append((job_a, similarity))

    max_similar_per_job = 8
    kept_pairs: set[tuple[str, str]] = set()
    for job_identifier, candidates in similar_candidates.items():
        candidates.sort(key=lambda item: (-item[1], item[0]))
        for other, similarity in candidates[:max_similar_per_job]:
            pair = tuple(sorted((job_identifier, other)))
            kept_pairs.add(pair)
            job_neighbors[job_identifier]["similar_jobs"].append({"job_id": other, "score": round(similarity, 4)})

    for job_a, job_b in sorted(kept_pairs):
        similarity = _jaccard(skill_sets.get(job_a, set()), skill_sets.get(job_b, set()))
        edges.append(
            {
                "id": edge_id(job_a, "SIMILAR_TO", job_b),
                "source": job_a,
                "target": job_b,
                "type": "SIMILAR_TO",
                "weight": round(similarity, 4),
                "confidence": round(similarity, 4),
                "data": None,
            }
        )

    jobs_export = list(job_map.values())
    companies_export = list(company_map.values())
    skills_export = list(skill_map.values())
    search_index = _build_search_index(jobs_export, companies_export, skills_export)
    summary_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "companies": len(companies_export),
            "jobs": len(jobs_export),
            "skills": len(skills_export),
            "nodes": len(nodes),
            "edges": len(edges),
        },
    }

    validate_many("job", jobs_export, context="jobs export")
    validate_many("company", companies_export, context="companies export")
    validate_many("skill", skills_export, context="skills export")
    validate_many("graph_node", nodes, context="graph nodes")
    validate_many("graph_edge", edges, context="graph edges")
    validate_payload("graph_full", {"nodes": nodes, "edges": edges}, context="graph.full export")
    validate_payload("company_jobs", dict(company_jobs), context="company_jobs export")
    validate_payload("skill_jobs", dict(skill_jobs), context="skill_jobs export")
    validate_payload("job_skills", dict(job_skills), context="job_skills export")
    validate_payload("company_skill_stats", {k: dict(v) for k, v in company_skill_stats.items()}, context="company_skill_stats export")
    validate_payload("job_neighbors", dict(job_neighbors), context="job_neighbors export")
    validate_payload("search_index", search_index, context="search-index export")
    validate_payload("summary", summary_payload, context="summary export")
    write_json(out_dir / "jobs.json", jobs_export)
    write_json(out_dir / "companies.json", companies_export)
    write_json(out_dir / "skills.json", skills_export)
    write_json(out_dir / "graph.full.json", {"nodes": nodes, "edges": edges})
    write_json(out_dir / "company_jobs.json", company_jobs)
    write_json(out_dir / "skill_jobs.json", skill_jobs)
    write_json(out_dir / "job_skills.json", job_skills)
    write_json(out_dir / "company_skill_stats.json", {k: dict(v) for k, v in company_skill_stats.items()})
    write_json(out_dir / "job_neighbors.json", job_neighbors)
    write_json(out_dir / "search-index.json", search_index)
    write_json(
        out_dir / "summary.json",
        summary_payload,
    )

    with db.connect(db_path) as conn:
        db.log_run(
            conn,
            "build_graph",
            "ok",
            {
                "out_dir": str(out_dir),
                "companies": len(companies_export),
                "jobs": len(jobs_export),
                "skills": len(skills_export),
                "nodes": len(nodes),
                "edges": len(edges),
                **(observability or {}),
            },
            datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
        )
        conn.commit()

    return {
        "companies": len(companies_export),
        "jobs": len(jobs_export),
        "skills": len(skills_export),
        "nodes": len(nodes),
        "edges": len(edges),
    }

def _hydrate_company(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "aliases": json.loads(row["aliases_json"]) if row.get("aliases_json") else [],
        "website": row.get("website"),
        "industry": row.get("industry"),
        "metadata": json.loads(row["metadata_json"]) if row.get("metadata_json") else {},
    }

def _hydrate_skill(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "label": row["label"],
        "normalized_label": row["normalized_label"],
        "aliases": json.loads(row["aliases_json"]) if row.get("aliases_json") else [],
        "parent_id": row.get("parent_id"),
        "category": row.get("category"),
        "metadata": json.loads(row["metadata_json"]) if row.get("metadata_json") else {},
    }

def _hydrate_job(row: dict[str, Any], enrichment: dict[str, Any] | None, company: dict[str, Any] | None) -> dict[str, Any]:
    hydrated = {
        "id": row["id"],
        "company_id": row["company_id"],
        "company_name": company["name"] if company else row["company_id"],
        "external_id": row.get("external_id"),
        "title": row["title"],
        "title_normalized": row["title_normalized"],
        "location_text": row.get("location_text"),
        "remote_mode": row.get("remote_mode"),
        "employment_type": row.get("employment_type"),
        "posted_at": row.get("posted_at"),
        "source_type": row["source_type"],
        "source_url": row["source_url"],
        "description_hash": row["description_hash"],
        "dedupe_fingerprint": row["dedupe_fingerprint"],
        "status": row["status"],
        "metadata": json.loads(row["metadata_json"]) if row.get("metadata_json") else {},
    }
    if enrichment:
        hydrated["enrichment"] = {
            "summary": enrichment.get("summary"),
            "role_family": enrichment.get("role_family"),
            "seniority": enrichment.get("seniority"),
            "remote_mode_inferred": enrichment.get("remote_mode_inferred"),
            "salary_text": enrichment.get("salary_text"),
            "responsibilities": json.loads(enrichment["responsibilities_json"]) if enrichment.get("responsibilities_json") else [],
            "qualifications": json.loads(enrichment["qualifications_json"]) if enrichment.get("qualifications_json") else [],
            "evidence": json.loads(enrichment["evidence_json"]) if enrichment.get("evidence_json") else [],
            "confidence": enrichment.get("confidence"),
            "model_name": enrichment.get("model_name"),
        }
    return hydrated

def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)

def _build_search_index(jobs: list[dict[str, Any]], companies: list[dict[str, Any]], skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for company in companies:
        docs.append(
            {
                "id": company["id"],
                "type": "company",
                "title": company["name"],
                "text": " ".join([company["name"], *company.get("aliases", [])]),
            }
        )
    for skill in skills:
        docs.append(
            {
                "id": skill["id"],
                "type": "skill",
                "title": skill["label"],
                "text": " ".join([skill["label"], *skill.get("aliases", [])]),
            }
        )
    for job in jobs:
        enrichment = job.get("enrichment") or {}
        docs.append(
            {
                "id": job["id"],
                "type": "job",
                "title": job["title"],
                "text": " ".join(
                    filter(
                        None,
                        [
                            job["title"],
                            job["company_name"],
                            job.get("location_text"),
                            enrichment.get("summary"),
                            enrichment.get("role_family"),
                            enrichment.get("seniority"),
                        ],
                    )
                ),
            }
        )
    return docs

def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "unknown"
