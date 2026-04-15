"""
Job Discovery
=============
Normalises job postings from multiple sources into a common schema:

    {
        "id":          str,
        "title":       str,
        "company":     str,
        "location":    str,
        "remote":      bool,
        "url":         str,
        "description": str,        # truncated to 2 000 chars
        "salary_min":  int | None,
        "salary_max":  int | None,
        "tags":        list[str],
        "source":      str,        # arbeitnow | adzuna | demo
        "posted_at":   str,        # ISO date or empty
    }

Connectors
----------
- Arbeitnow  – free, no auth, good for remote/EU roles
- Adzuna     – free tier, requires app_id + app_key
- Demo       – built-in sample data for offline testing
"""

from __future__ import annotations

from typing import Optional
import requests

_TIMEOUT = 12   # seconds


# ── Arbeitnow ────────────────────────────────────────────────────────────────

def fetch_arbeitnow_jobs(
    keywords: str,
    location: str = "",
    remote_only: bool = False,
) -> list[dict]:
    """Free public Arbeitnow job board API (no auth required)."""
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw_jobs: list[dict] = resp.json().get("data", [])
    except Exception:
        return []

    kw_tokens = [k.strip().lower() for k in keywords.split() if k.strip()]
    results: list[dict] = []

    for job in raw_jobs:
        title = job.get("title", "").lower()
        desc  = job.get("description", "").lower()
        tags  = " ".join(job.get("tags", [])).lower()
        haystack = f"{title} {desc} {tags}"

        if kw_tokens and not any(kw in haystack for kw in kw_tokens):
            continue

        is_remote = bool(job.get("remote", False))
        if remote_only and not is_remote:
            continue

        loc = job.get("location", "")
        if location and location.lower() not in loc.lower():
            continue

        results.append(_normalise({
            "id":          job.get("slug", ""),
            "title":       job.get("title", ""),
            "company":     job.get("company_name", ""),
            "location":    loc,
            "remote":      is_remote,
            "url":         job.get("url", ""),
            "description": job.get("description", ""),
            "salary_min":  None,
            "salary_max":  None,
            "tags":        job.get("tags", []),
            "source":      "arbeitnow",
            "posted_at":   str(job.get("created_at", "")),
        }))

        if len(results) >= 50:
            break

    return results


# ── Adzuna ───────────────────────────────────────────────────────────────────

def fetch_adzuna_jobs(
    keywords: str,
    location: str = "",
    app_id: str = "",
    app_key: str = "",
    country: str = "us",
    results_per_page: int = 20,
) -> list[dict]:
    """Adzuna job search API (requires free account credentials)."""
    if not app_id or not app_key:
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params: dict = {
        "app_id":           app_id,
        "app_key":          app_key,
        "what":             keywords,
        "results_per_page": results_per_page,
        "content-type":     "application/json",
    }
    if location:
        params["where"] = location

    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw_jobs = resp.json().get("results", [])
    except Exception:
        return []

    results: list[dict] = []
    for job in raw_jobs:
        results.append(_normalise({
            "id":          str(job.get("id", "")),
            "title":       job.get("title", ""),
            "company":     job.get("company", {}).get("display_name", ""),
            "location":    job.get("location", {}).get("display_name", ""),
            "remote":      False,
            "url":         job.get("redirect_url", ""),
            "description": job.get("description", ""),
            "salary_min":  job.get("salary_min"),
            "salary_max":  job.get("salary_max"),
            "tags":        [],
            "source":      "adzuna",
            "posted_at":   str(job.get("created", "")),
        }))

    return results


# ── Demo / offline ────────────────────────────────────────────────────────────

_DEMO_JOBS: list[dict] = [
    {
        "id": "demo-001",
        "title": "Senior Python Developer",
        "company": "CloudScale Inc.",
        "location": "San Francisco, CA",
        "remote": True,
        "url": "https://example.com/jobs/demo-001",
        "description": (
            "We're looking for a Senior Python Developer with 5+ years of experience "
            "in Django, FastAPI, and AWS. You will design and build scalable microservices, "
            "collaborate with product teams, and contribute to open-source projects. "
            "Strong understanding of REST APIs, Docker, and PostgreSQL required."
        ),
        "salary_min": 120_000,
        "salary_max": 160_000,
        "tags": ["python", "django", "fastapi", "aws", "remote"],
        "source": "demo",
        "posted_at": "2026-04-13",
    },
    {
        "id": "demo-002",
        "title": "Full-Stack Engineer (React + Node)",
        "company": "StartupXYZ",
        "location": "New York, NY",
        "remote": True,
        "url": "https://example.com/jobs/demo-002",
        "description": (
            "Join our fast-growing team as a Full-Stack Engineer. You'll work on "
            "React frontends and Node.js/Express backends. Experience with TypeScript, "
            "GraphQL, and MongoDB is a plus. 3+ years required. Competitive equity package."
        ),
        "salary_min": 100_000,
        "salary_max": 140_000,
        "tags": ["react", "node", "typescript", "fullstack", "remote"],
        "source": "demo",
        "posted_at": "2026-04-12",
    },
    {
        "id": "demo-003",
        "title": "Machine Learning Engineer",
        "company": "AI Dynamics",
        "location": "Austin, TX",
        "remote": False,
        "url": "https://example.com/jobs/demo-003",
        "description": (
            "Design and deploy production ML pipelines using PyTorch and Kubeflow. "
            "You'll work on NLP and recommendation systems. PhD or 4+ years of "
            "relevant experience. Familiarity with MLflow, Spark, and A/B testing needed."
        ),
        "salary_min": 130_000,
        "salary_max": 180_000,
        "tags": ["python", "pytorch", "ml", "nlp", "kubeflow"],
        "source": "demo",
        "posted_at": "2026-04-11",
    },
    {
        "id": "demo-004",
        "title": "DevOps / Platform Engineer",
        "company": "FinTech Corp",
        "location": "London, UK",
        "remote": True,
        "url": "https://example.com/jobs/demo-004",
        "description": (
            "Own infrastructure as code (Terraform, Pulumi), manage multi-cloud "
            "deployments on AWS and GCP, and improve CI/CD pipelines (GitHub Actions, "
            "ArgoCD). Kubernetes expertise is essential. 4+ years experience."
        ),
        "salary_min": 90_000,
        "salary_max": 130_000,
        "tags": ["devops", "kubernetes", "terraform", "aws", "cicd"],
        "source": "demo",
        "posted_at": "2026-04-10",
    },
    {
        "id": "demo-005",
        "title": "Data Engineer – Streaming Pipelines",
        "company": "DataFlow Analytics",
        "location": "Remote",
        "remote": True,
        "url": "https://example.com/jobs/demo-005",
        "description": (
            "Build and maintain real-time data pipelines using Apache Kafka and Flink. "
            "Python and SQL expertise required. Experience with Snowflake, dbt, and "
            "Airflow is a strong plus. 3+ years of data engineering experience."
        ),
        "salary_min": 110_000,
        "salary_max": 150_000,
        "tags": ["data-engineering", "kafka", "python", "sql", "remote"],
        "source": "demo",
        "posted_at": "2026-04-09",
    },
    {
        "id": "demo-006",
        "title": "Frontend Engineer – React / Next.js",
        "company": "DesignFirst Studio",
        "location": "Berlin, Germany",
        "remote": True,
        "url": "https://example.com/jobs/demo-006",
        "description": (
            "Create pixel-perfect UIs in React and Next.js. Work closely with designers "
            "on Figma to product. TypeScript, Tailwind CSS, and accessibility standards "
            "(WCAG 2.1) are core skills. 2+ years of commercial experience."
        ),
        "salary_min": 70_000,
        "salary_max": 100_000,
        "tags": ["react", "nextjs", "typescript", "css", "remote"],
        "source": "demo",
        "posted_at": "2026-04-08",
    },
    {
        "id": "demo-007",
        "title": "Backend Engineer – Go / Microservices",
        "company": "Infra Labs",
        "location": "Singapore",
        "remote": False,
        "url": "https://example.com/jobs/demo-007",
        "description": (
            "Design low-latency APIs in Go serving millions of daily requests. "
            "Experience with gRPC, Protobuf, Redis, and distributed tracing (Jaeger). "
            "Strong understanding of concurrency and system design. 4+ years required."
        ),
        "salary_min": 95_000,
        "salary_max": 135_000,
        "tags": ["go", "microservices", "grpc", "redis"],
        "source": "demo",
        "posted_at": "2026-04-07",
    },
    {
        "id": "demo-008",
        "title": "Product Manager – Developer Tools",
        "company": "OpenBuild",
        "location": "Remote",
        "remote": True,
        "url": "https://example.com/jobs/demo-008",
        "description": (
            "Drive the roadmap for a developer tooling platform used by 200k engineers. "
            "Collaborate with engineering, design, and sales. Strong analytical skills "
            "and 3+ years of PM experience in B2B SaaS required."
        ),
        "salary_min": 115_000,
        "salary_max": 155_000,
        "tags": ["product-management", "developer-tools", "saas", "remote"],
        "source": "demo",
        "posted_at": "2026-04-06",
    },
]


def get_demo_jobs(keywords: str = "", remote_only: bool = False) -> list[dict]:
    """Return demo jobs optionally filtered by keywords."""
    kw_tokens = [k.strip().lower() for k in keywords.split() if k.strip()]
    results: list[dict] = []

    for job in _DEMO_JOBS:
        if remote_only and not job["remote"]:
            continue
        if kw_tokens:
            haystack = (job["title"] + " " + job["description"] + " " +
                        " ".join(job["tags"])).lower()
            if not any(kw in haystack for kw in kw_tokens):
                continue
        results.append(dict(job))   # shallow copy

    return results


# ── internal helpers ──────────────────────────────────────────────────────────

def _normalise(job: dict) -> dict:
    """Ensure description is capped and all required keys exist."""
    job["description"] = (job.get("description") or "")[:2_000]
    job.setdefault("salary_min", None)
    job.setdefault("salary_max", None)
    job.setdefault("tags", [])
    return job
