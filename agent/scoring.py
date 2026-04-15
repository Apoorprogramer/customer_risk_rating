"""
Job Relevance Scoring
=====================
Uses GPT-4o-mini to score how well a job posting matches a candidate's profile.

Returns:
    {
        "score":     int,          # 0–100
        "label":     str,          # "Strong" | "Good" | "Moderate" | "Weak"
        "reasoning": str,          # 1–2 sentence explanation
    }

Falls back to keyword-based scoring when the OpenAI client is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Optional

_SYSTEM_PROMPT = """\
You are a professional career advisor and talent-matching expert.
Given a candidate's profile summary and a job posting, rate how well the job
matches the candidate on a scale of 0 to 100.

Respond ONLY with valid JSON in this exact format (no markdown, no extra keys):
{"score": <integer 0-100>, "reasoning": "<1-2 sentence explanation>"}

Scoring guide:
  90-100  Perfect fit – almost every skill, experience level, and preference aligns.
  70-89   Strong fit  – most core requirements match with minor gaps.
  50-69   Moderate    – several relevant skills but notable gaps or mismatches.
  30-49   Weak        – limited overlap; significant reskilling would be needed.
  0-29    Poor        – very little alignment.
"""


def score_job(job: dict, profile: dict, client) -> dict:
    """
    Score a job against the candidate profile using GPT-4o-mini.
    Falls back to keyword scoring if OpenAI call fails.
    """
    profile_summary = _build_profile_summary(profile)
    job_snippet     = _build_job_snippet(job)

    user_content = (
        f"## Candidate Profile\n{profile_summary}\n\n"
        f"## Job Posting\n{job_snippet}"
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        raw = completion.choices[0].message.content.strip()
        parsed = json.loads(raw)
        score = max(0, min(100, int(parsed.get("score", 0))))
        reasoning = parsed.get("reasoning", "")
        return {"score": score, "label": _label(score), "reasoning": reasoning}
    except Exception:
        return _keyword_score(job, profile)


def score_jobs_batch(jobs: list[dict], profile: dict, client) -> list[dict]:
    """
    Score a list of jobs and attach 'relevance' key to each.
    Returns jobs sorted by descending score.
    """
    scored: list[dict] = []
    for job in jobs:
        result = score_job(job, profile, client)
        enriched = dict(job)
        enriched["relevance"] = result
        scored.append(enriched)
    scored.sort(key=lambda j: j["relevance"]["score"], reverse=True)
    return scored


# ── internal helpers ──────────────────────────────────────────────────────────

def _build_profile_summary(profile: dict) -> str:
    parts = []
    if profile.get("current_title"):
        parts.append(f"Current title: {profile['current_title']}")
    if profile.get("years_of_experience"):
        parts.append(f"Years of experience: {profile['years_of_experience']}")
    if profile.get("skills"):
        parts.append(f"Skills: {', '.join(profile['skills'][:30])}")
    if profile.get("desired_titles"):
        parts.append(f"Target roles: {', '.join(profile['desired_titles'])}")
    if profile.get("desired_locations"):
        parts.append(f"Preferred locations: {', '.join(profile['desired_locations'])}")
    if profile.get("remote_preference") and profile["remote_preference"] != "any":
        parts.append(f"Remote preference: {profile['remote_preference']}")
    if profile.get("summary"):
        parts.append(f"Summary: {profile['summary'][:400]}")
    if profile.get("resume_text"):
        parts.append(f"Resume excerpt: {profile['resume_text'][:600]}")
    return "\n".join(parts) if parts else "No profile data provided."


def _build_job_snippet(job: dict) -> str:
    title   = job.get("title", "N/A")
    company = job.get("company", "N/A")
    loc     = job.get("location", "N/A")
    remote  = "Yes" if job.get("remote") else "No"
    desc    = job.get("description", "")[:800]
    tags    = ", ".join(job.get("tags", []))

    lines = [
        f"Title:       {title}",
        f"Company:     {company}",
        f"Location:    {loc}  (Remote: {remote})",
    ]
    if tags:
        lines.append(f"Tags:        {tags}")
    lines.append(f"Description: {desc}")
    return "\n".join(lines)


def _label(score: int) -> str:
    if score >= 90:
        return "🌟 Perfect"
    if score >= 70:
        return "✅ Strong"
    if score >= 50:
        return "🔶 Moderate"
    if score >= 30:
        return "🔸 Weak"
    return "❌ Poor"


def _keyword_score(job: dict, profile: dict) -> dict:
    """Fallback: simple keyword overlap scoring (no AI required)."""
    skills = set(s.lower() for s in profile.get("skills", []))
    if not skills:
        return {"score": 50, "label": _label(50), "reasoning": "Keyword scoring (no profile data)."}

    haystack = (job.get("title", "") + " " + job.get("description", "") +
                " " + " ".join(job.get("tags", []))).lower()

    matched = sum(1 for sk in skills if sk in haystack)
    score = min(100, int((matched / max(len(skills), 1)) * 100))
    return {
        "score": score,
        "label": _label(score),
        "reasoning": f"Keyword match: {matched}/{len(skills)} skills found in posting.",
    }
