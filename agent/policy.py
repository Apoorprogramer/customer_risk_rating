"""
Application Policy Engine
==========================
Applies user-defined constraints to a list of normalised job dicts and returns
only those that pass all active rules.

Rules evaluated (all optional – empty value = rule disabled):
  • title_keywords_required  – job title must contain at least one keyword
  • title_keywords_blocked   – job title must NOT contain any blocked keyword
  • company_blacklist        – skip jobs from these companies
  • company_whitelist        – keep ONLY jobs from these companies (if non-empty)
  • location_allowlist       – job location must match at least one entry
  • remote_only              – skip non-remote jobs when True
  • min_salary               – skip jobs whose max salary is below this
  • daily_limit              – maximum jobs to return in one discovery run
"""

from __future__ import annotations

import re
from typing import Optional


class PolicyEngine:
    """Stateless filter: call :meth:`filter_jobs` with a policy dict."""

    def filter_jobs(self, jobs: list[dict], policy: dict) -> list[dict]:
        """
        Parameters
        ----------
        jobs:
            List of normalised job dicts (from job_discovery module).
        policy:
            Dict produced by the UI / stored in the profile. Expected keys:

            title_keywords_required : list[str]
            title_keywords_blocked  : list[str]
            company_blacklist       : list[str]
            company_whitelist       : list[str]
            location_allowlist      : list[str]
            remote_only             : bool
            min_salary              : int   (0 = disabled)
            daily_limit             : int   (0 = no limit)
        """
        required_kws  = _lower_list(policy.get("title_keywords_required", []))
        blocked_kws   = _lower_list(policy.get("title_keywords_blocked", []))
        co_blacklist  = _lower_list(policy.get("company_blacklist", []))
        co_whitelist  = _lower_list(policy.get("company_whitelist", []))
        loc_allowlist = _lower_list(policy.get("location_allowlist", []))
        remote_only   = bool(policy.get("remote_only", False))
        min_salary    = int(policy.get("min_salary", 0) or 0)
        daily_limit   = int(policy.get("daily_limit", 0) or 0)

        filtered: list[dict] = []

        for job in jobs:
            title   = job.get("title",   "").lower()
            company = job.get("company", "").lower()
            loc     = job.get("location","").lower()
            is_remote = bool(job.get("remote", False))

            # ── remote filter ─────────────────────────────────────────────
            if remote_only and not is_remote:
                continue

            # ── required title keywords ───────────────────────────────────
            if required_kws and not any(kw in title for kw in required_kws):
                continue

            # ── blocked title keywords ────────────────────────────────────
            if blocked_kws and any(kw in title for kw in blocked_kws):
                continue

            # ── company blacklist ─────────────────────────────────────────
            if co_blacklist and any(bl in company for bl in co_blacklist):
                continue

            # ── company whitelist (only keep listed companies) ────────────
            if co_whitelist and not any(wl in company for wl in co_whitelist):
                continue

            # ── location allowlist ────────────────────────────────────────
            if loc_allowlist and not is_remote:
                if not any(allowed in loc for allowed in loc_allowlist):
                    continue

            # ── minimum salary ────────────────────────────────────────────
            if min_salary > 0:
                salary_max = job.get("salary_max")
                if salary_max is not None and salary_max < min_salary:
                    continue

            filtered.append(job)

            if daily_limit > 0 and len(filtered) >= daily_limit:
                break

        return filtered


# ── helpers ───────────────────────────────────────────────────────────────────

def _lower_list(items) -> list[str]:
    if not items:
        return []
    return [str(i).strip().lower() for i in items if str(i).strip()]


def default_policy() -> dict:
    """Return an empty policy dict (all rules disabled)."""
    return {
        "title_keywords_required": [],
        "title_keywords_blocked":  [],
        "company_blacklist":       [],
        "company_whitelist":       [],
        "location_allowlist":      [],
        "remote_only":             False,
        "min_salary":              0,
        "daily_limit":             20,
    }
