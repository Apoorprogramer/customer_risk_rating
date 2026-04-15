"""
Job Application Agent
=====================
A Streamlit application that acts as an intelligent, human-in-the-loop
job application assistant.

Run with:
    streamlit run job_agent.py

Sections (sidebar navigation):
    🔐 Profile Vault    – store & manage encrypted personal data
    🔍 Job Discovery    – find jobs from Arbeitnow / Adzuna / Demo
    📋 Applications     – review, draft cover letters, and mark as submitted
    📊 Dashboard        – pipeline stats, follow-up reminders, analytics

IMPORTANT – Terms of Service & Guardrails
-----------------------------------------
• This agent never auto-submits applications.  You must confirm every submission.
• Respect each job board's ToS: do not scrape in violation of their policies.
• Your personal data is stored locally in an AES-Fernet-encrypted file.
  The passphrase is never stored on disk.
"""

from __future__ import annotations

import os
import datetime
from pathlib import Path

import streamlit as st

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Job Application Agent",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── lazy imports (tolerate missing optional deps) ─────────────────────────────
try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    from cryptography.fernet import InvalidToken
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    st.error("⚠️ `cryptography` package not installed. Run: pip install cryptography")

from agent.profile_vault import (
    save_profile, load_profile, profile_exists, get_audit_log, DEFAULT_PROFILE,
)
from agent.job_discovery import fetch_arbeitnow_jobs, fetch_adzuna_jobs, get_demo_jobs
from agent.policy        import PolicyEngine, default_policy
from agent.scoring       import score_jobs_batch
from agent.tracker       import JobTracker, STATUSES
from agent.autofill      import generate_cover_letter, generate_application_answers

# ── global singletons ─────────────────────────────────────────────────────────
_tracker = JobTracker()
_policy_engine = PolicyEngine()


def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or not _OPENAI_AVAILABLE:
        return None
    return OpenAI(api_key=api_key)


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

_PAGES = ["🔐 Profile Vault", "🔍 Job Discovery", "📋 Applications", "📊 Dashboard"]

with st.sidebar:
    st.title("💼 Job Agent")
    st.caption("Intelligent job application assistant")
    st.divider()
    page = st.radio("Navigate", _PAGES, label_visibility="collapsed")
    st.divider()
    st.caption(
        "⚠️ **Guardrails**\n"
        "- No auto-submit: you approve every application\n"
        "- Profile encrypted locally\n"
        "- Respect each job board's Terms of Service"
    )

# ── unlock helper (shared across pages) ──────────────────────────────────────

def _unlock_widget(key_prefix: str = "") -> tuple[bool, dict]:
    """
    Renders a password input and returns (unlocked: bool, profile: dict).
    Profile is cached in session_state so the user only types the password once
    per session.
    """
    ss_key = f"_profile_{key_prefix}"
    if ss_key in st.session_state and st.session_state[ss_key]:
        return True, st.session_state[ss_key]

    if not profile_exists():
        st.info("ℹ️ No saved profile found. Go to **🔐 Profile Vault** to create one first.")
        return False, {}

    pw = st.text_input(
        "🔑 Enter your vault passphrase to continue",
        type="password",
        key=f"unlock_pw_{key_prefix}",
    )
    if pw:
        try:
            profile = load_profile(pw)
            st.session_state[ss_key] = profile
            # Also store password so saves work later
            st.session_state["_vault_pw"] = pw
            st.rerun()
        except Exception:
            st.error("❌ Incorrect passphrase or corrupted vault.")
    return False, {}


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 – PROFILE VAULT
# ─────────────────────────────────────────────────────────────────────────────

def profile_vault_page() -> None:
    st.title("🔐 Profile Vault")
    st.caption(
        "All data is encrypted with AES-128-Fernet using PBKDF2-SHA256 key derivation. "
        "Your passphrase is **never** stored on disk."
    )

    # ── authenticate ─────────────────────────────────────────────────────────
    col_pw, col_btn = st.columns([3, 1])
    with col_pw:
        if profile_exists():
            label = "🔑 Passphrase (to load / save existing vault)"
        else:
            label = "🔑 Choose a passphrase for your new vault"
        passphrase = st.text_input(label, type="password", key="vault_pw_input")
    with col_btn:
        st.write("")
        load_btn = st.button("Load / Unlock", use_container_width=True)

    if not passphrase:
        if not profile_exists():
            st.info("Enter a passphrase above to create your encrypted profile vault.")
        else:
            st.info("Enter your passphrase to unlock and edit your profile.")
        _show_audit_log()
        return

    if load_btn or st.session_state.get("_profile_loaded"):
        if not st.session_state.get("_profile_loaded"):
            try:
                profile = load_profile(passphrase)
                st.session_state["_profile_loaded"] = True
                st.session_state["_profile_data"]   = profile
                st.session_state["_vault_pw"]       = passphrase
                # Also cache for other pages
                st.session_state["_profile_main"]   = profile
                st.success("✅ Vault unlocked." if profile_exists() else "✅ New vault ready.")
            except Exception:
                st.error("❌ Incorrect passphrase or corrupted vault.")
                return

    if not st.session_state.get("_profile_loaded"):
        return

    profile: dict = st.session_state["_profile_data"]

    # ── tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "👤 Personal", "💼 Work Experience", "🎓 Education",
        "⚙️ Skills & Summary", "🎯 Preferences", "❓ Common Q&A",
        "🔑 API Keys",
    ])

    # ── Personal Info ─────────────────────────────────────────────────────────
    with tabs[0]:
        st.subheader("Personal Information")
        c1, c2 = st.columns(2)
        with c1:
            profile["full_name"]    = st.text_input("Full Name",    profile.get("full_name", ""))
            profile["email"]        = st.text_input("Email",        profile.get("email", ""))
            profile["phone"]        = st.text_input("Phone",        profile.get("phone", ""))
            profile["dob"]          = st.text_input("Date of Birth (YYYY-MM-DD)", profile.get("dob", ""))
            profile["nationality"]  = st.text_input("Nationality",  profile.get("nationality", ""))
            profile["visa_status"]  = st.text_input("Visa / Work Authorisation", profile.get("visa_status", ""))
        with c2:
            profile["address"]      = st.text_input("Street Address", profile.get("address", ""))
            profile["city"]         = st.text_input("City",           profile.get("city", ""))
            profile["country"]      = st.text_input("Country",        profile.get("country", ""))
            profile["linkedin"]     = st.text_input("LinkedIn URL",   profile.get("linkedin", ""))
            profile["github"]       = st.text_input("GitHub URL",     profile.get("github", ""))
            profile["portfolio"]    = st.text_input("Portfolio / Website", profile.get("portfolio", ""))

    # ── Work Experience ───────────────────────────────────────────────────────
    with tabs[1]:
        st.subheader("Work Experience")
        work_exps: list[dict] = list(profile.get("work_experience", []))

        for i, exp in enumerate(work_exps):
            with st.expander(f"🏢 {exp.get('company','New Entry')} – {exp.get('title','')}", expanded=(i == 0)):
                c1, c2 = st.columns(2)
                with c1:
                    exp["company"] = st.text_input("Company",    exp.get("company",""), key=f"exp_co_{i}")
                    exp["title"]   = st.text_input("Job Title",  exp.get("title",""),   key=f"exp_ti_{i}")
                    exp["start"]   = st.text_input("Start (YYYY-MM)", exp.get("start",""), key=f"exp_s_{i}")
                with c2:
                    exp["end"]     = st.text_input("End (YYYY-MM or 'Present')", exp.get("end",""), key=f"exp_e_{i}")
                exp["description"] = st.text_area(
                    "Description / Key Achievements",
                    exp.get("description",""), height=100, key=f"exp_d_{i}"
                )
                if st.button("🗑️ Remove", key=f"del_exp_{i}"):
                    work_exps.pop(i)
                    profile["work_experience"] = work_exps
                    st.rerun()

        if st.button("➕ Add Work Experience"):
            work_exps.append({"company":"","title":"","start":"","end":"","description":""})
        profile["work_experience"] = work_exps

    # ── Education ─────────────────────────────────────────────────────────────
    with tabs[2]:
        st.subheader("Education")
        educations: list[dict] = list(profile.get("education", []))

        for i, edu in enumerate(educations):
            with st.expander(f"🎓 {edu.get('institution','New Entry')}", expanded=(i == 0)):
                c1, c2 = st.columns(2)
                with c1:
                    edu["institution"] = st.text_input("Institution", edu.get("institution",""), key=f"edu_inst_{i}")
                    edu["degree"]      = st.text_input("Degree",      edu.get("degree",""),      key=f"edu_deg_{i}")
                    edu["field"]       = st.text_input("Field of Study", edu.get("field",""),    key=f"edu_field_{i}")
                with c2:
                    edu["start"] = st.text_input("Start Year", edu.get("start",""), key=f"edu_s_{i}")
                    edu["end"]   = st.text_input("End Year",   edu.get("end",""),   key=f"edu_e_{i}")
                    edu["gpa"]   = st.text_input("GPA / Grade", edu.get("gpa",""),  key=f"edu_gpa_{i}")
                if st.button("🗑️ Remove", key=f"del_edu_{i}"):
                    educations.pop(i)
                    profile["education"] = educations
                    st.rerun()

        if st.button("➕ Add Education"):
            educations.append({"institution":"","degree":"","field":"","start":"","end":"","gpa":""})
        profile["education"] = educations

    # ── Skills & Summary ──────────────────────────────────────────────────────
    with tabs[3]:
        st.subheader("Skills & Professional Summary")
        profile["current_title"]       = st.text_input("Current Job Title", profile.get("current_title",""))
        profile["years_of_experience"] = st.number_input(
            "Total Years of Experience", min_value=0, max_value=60,
            value=int(profile.get("years_of_experience", 0) or 0),
        )
        skills_raw = st.text_area(
            "Skills (comma-separated)",
            ", ".join(profile.get("skills", [])),
            height=80,
        )
        profile["skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()]
        profile["summary"] = st.text_area(
            "Professional Summary", profile.get("summary",""), height=120
        )
        profile["resume_text"] = st.text_area(
            "Resume Text (paste full resume or extracted text from PDF)",
            profile.get("resume_text",""), height=200,
        )

    # ── Preferences ───────────────────────────────────────────────────────────
    with tabs[4]:
        st.subheader("Job Preferences")
        c1, c2 = st.columns(2)
        with c1:
            desired_titles_raw = st.text_area(
                "Target Job Titles (one per line)",
                "\n".join(profile.get("desired_titles", [])), height=80,
            )
            profile["desired_titles"] = [t.strip() for t in desired_titles_raw.splitlines() if t.strip()]

            profile["remote_preference"] = st.selectbox(
                "Remote Preference",
                ["any", "remote", "hybrid", "onsite"],
                index=["any", "remote", "hybrid", "onsite"].index(
                    profile.get("remote_preference","any")
                ),
            )
            profile["min_salary"]       = st.number_input(
                "Minimum Salary", min_value=0, step=5_000,
                value=int(profile.get("min_salary", 0) or 0),
            )
            profile["max_salary"]       = st.number_input(
                "Maximum Salary (0 = no limit)", min_value=0, step=5_000,
                value=int(profile.get("max_salary", 0) or 0),
            )
            profile["salary_currency"]  = st.text_input("Currency", profile.get("salary_currency","USD"))
        with c2:
            desired_locs_raw = st.text_area(
                "Preferred Locations (one per line)",
                "\n".join(profile.get("desired_locations", [])), height=80,
            )
            profile["desired_locations"] = [l.strip() for l in desired_locs_raw.splitlines() if l.strip()]

            industries_raw = st.text_area(
                "Preferred Industries (one per line)",
                "\n".join(profile.get("preferred_industries", [])), height=60,
            )
            profile["preferred_industries"] = [x.strip() for x in industries_raw.splitlines() if x.strip()]

            blacklist_raw = st.text_area(
                "Company Blacklist (one per line)",
                "\n".join(profile.get("company_blacklist", [])), height=60,
            )
            profile["company_blacklist"] = [x.strip() for x in blacklist_raw.splitlines() if x.strip()]

            whitelist_raw = st.text_area(
                "Company Whitelist – only apply here (one per line, leave blank for all)",
                "\n".join(profile.get("company_whitelist", [])), height=60,
            )
            profile["company_whitelist"] = [x.strip() for x in whitelist_raw.splitlines() if x.strip()]

    # ── Common Q&A ────────────────────────────────────────────────────────────
    with tabs[5]:
        st.subheader("Common Application Q&A")
        st.caption(
            "Pre-fill answers to questions that appear on many application forms. "
            "The AI will use these as context when generating application responses."
        )
        qa_pairs: list[dict] = list(profile.get("qa_pairs", []))
        for i, pair in enumerate(qa_pairs):
            with st.expander(f"Q{i+1}: {pair.get('question','')[:60]}", expanded=False):
                pair["question"] = st.text_input("Question", pair.get("question",""), key=f"qa_q_{i}")
                pair["answer"]   = st.text_area("Answer",   pair.get("answer",""),   key=f"qa_a_{i}", height=80)
                if st.button("🗑️ Remove", key=f"del_qa_{i}"):
                    qa_pairs.pop(i)
                    profile["qa_pairs"] = qa_pairs
                    st.rerun()
        if st.button("➕ Add Q&A Pair"):
            qa_pairs.append({"question":"","answer":""})
        profile["qa_pairs"] = qa_pairs

    # ── API Keys ──────────────────────────────────────────────────────────────
    with tabs[6]:
        st.subheader("Optional API Keys")
        st.caption("These are stored inside your encrypted vault, never in plain text.")
        profile["adzuna_app_id"]  = st.text_input("Adzuna App ID",  profile.get("adzuna_app_id",""),  type="password")
        profile["adzuna_app_key"] = st.text_input("Adzuna App Key", profile.get("adzuna_app_key",""), type="password")
        st.markdown(
            "Get free Adzuna API keys at [developer.adzuna.com](https://developer.adzuna.com)"
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    st.divider()
    save_col, _ = st.columns([2, 4])
    with save_col:
        if st.button("💾 Save Vault", type="primary", use_container_width=True):
            try:
                save_profile(profile, passphrase)
                st.session_state["_profile_data"] = profile
                st.session_state["_profile_main"] = profile
                st.session_state["_vault_pw"]     = passphrase
                st.success("✅ Profile saved and encrypted successfully.")
            except Exception as exc:
                st.error(f"❌ Failed to save: {exc}")

    _show_audit_log()


def _show_audit_log():
    logs = get_audit_log()
    if logs:
        with st.expander(f"📋 Vault Audit Log ({len(logs)} entries)", expanded=False):
            for entry in reversed(logs[-20:]):
                st.text(f"{entry['timestamp']}  {entry['action']}")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 – JOB DISCOVERY
# ─────────────────────────────────────────────────────────────────────────────

def job_discovery_page() -> None:
    st.title("🔍 Job Discovery")

    unlocked, profile = _unlock_widget("main")
    if not unlocked:
        return

    client = _get_openai_client()

    # ── policy sidebar panel ──────────────────────────────────────────────────
    with st.expander("⚙️ Discovery Policy", expanded=True):
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            kw = st.text_input(
                "Search Keywords",
                ", ".join(profile.get("desired_titles", [])),
                help="Space-separated keywords for the job title / description search",
            )
            remote_only = st.checkbox(
                "Remote only",
                value=(profile.get("remote_preference") == "remote"),
            )
            loc_filter = st.text_input(
                "Location filter",
                ", ".join(profile.get("desired_locations", [])),
                help="Leave blank for any location",
            )
        with pc2:
            required_kws = st.text_input(
                "Required title keywords (comma-sep)",
                help="Job title must contain at least one of these",
            )
            blocked_kws  = st.text_input(
                "Blocked title keywords (comma-sep)",
                help="Skip jobs whose title contains any of these",
            )
            min_salary   = st.number_input(
                "Min salary (0 = no filter)", min_value=0, step=5_000,
                value=int(profile.get("min_salary", 0) or 0),
            )
        with pc3:
            sources = st.multiselect(
                "Sources",
                ["Demo (offline)", "Arbeitnow (free API)", "Adzuna API"],
                default=["Demo (offline)"],
            )
            daily_limit = st.number_input("Max jobs to show", min_value=1, max_value=100, value=20)
            auto_score  = st.checkbox(
                "AI relevance scoring",
                value=(client is not None),
                disabled=(client is None),
                help="Requires OPENAI_API_KEY in environment",
            )

    policy = {
        "title_keywords_required": [k.strip() for k in required_kws.split(",") if k.strip()],
        "title_keywords_blocked":  [k.strip() for k in blocked_kws.split(",") if k.strip()],
        "company_blacklist":       profile.get("company_blacklist", []),
        "company_whitelist":       profile.get("company_whitelist", []),
        "location_allowlist":      [l.strip() for l in loc_filter.split(",") if l.strip()],
        "remote_only":             remote_only,
        "min_salary":              min_salary,
        "daily_limit":             daily_limit,
    }

    if st.button("🔎 Discover Jobs", type="primary"):
        raw_jobs: list[dict] = []

        with st.spinner("Fetching jobs…"):
            if "Demo (offline)" in sources:
                raw_jobs += get_demo_jobs(keywords=kw, remote_only=remote_only)
            if "Arbeitnow (free API)" in sources:
                fetched = fetch_arbeitnow_jobs(keywords=kw, remote_only=remote_only)
                raw_jobs += fetched
                if not fetched:
                    st.warning("Arbeitnow returned no results (API may be unavailable).")
            if "Adzuna API" in sources:
                fetched = fetch_adzuna_jobs(
                    keywords=kw,
                    location=loc_filter,
                    app_id=profile.get("adzuna_app_id",""),
                    app_key=profile.get("adzuna_app_key",""),
                )
                raw_jobs += fetched
                if not fetched:
                    st.warning("Adzuna returned no results – check your API keys.")

        # Deduplicate by id
        seen: set[str] = set()
        unique_jobs: list[dict] = []
        for j in raw_jobs:
            if j["id"] not in seen:
                seen.add(j["id"])
                unique_jobs.append(j)

        # Apply policy
        filtered = _policy_engine.filter_jobs(unique_jobs, policy)

        if not filtered:
            st.warning("No jobs matched your policy. Try relaxing the filters.")
            return

        # Score
        if auto_score and client:
            with st.spinner(f"Scoring {len(filtered)} jobs with AI…"):
                filtered = score_jobs_batch(filtered, profile, client)
        else:
            for j in filtered:
                j.setdefault("relevance", {"score": 0, "label": "—", "reasoning": "Scoring disabled."})

        st.session_state["_discovered_jobs"] = filtered
        st.success(f"✅ Found {len(filtered)} matching jobs.")

    # ── results ───────────────────────────────────────────────────────────────
    discovered: list[dict] = st.session_state.get("_discovered_jobs", [])
    if not discovered:
        st.info("Run a discovery to see results here.")
        return

    st.subheader(f"Results — {len(discovered)} jobs")
    for job in discovered:
        rel     = job.get("relevance", {})
        score   = rel.get("score", 0)
        label   = rel.get("label", "—")
        reason  = rel.get("reasoning", "")
        sal_min = job.get("salary_min")
        sal_max = job.get("salary_max")
        salary  = (
            f"${sal_min:,}–${sal_max:,}" if sal_min and sal_max
            else (f"${sal_min:,}+" if sal_min else "—")
        )

        existing = _tracker.get_job(job["id"])
        status_badge = f" · `{existing['status']}`" if existing else ""

        header = (
            f"**{job['title']}** @ {job['company']} · {job['location']}"
            f"{'  🌐' if job.get('remote') else ''}"
            f" · {label} ({score}/100){status_badge}"
        )

        with st.expander(header, expanded=False):
            c1, c2, c3 = st.columns([4, 2, 2])
            with c1:
                st.markdown(f"**Description:**\n{job.get('description','')[:500]}…")
                if reason:
                    st.caption(f"💡 AI insight: {reason}")
            with c2:
                st.markdown(f"**Source:** {job.get('source','')}")
                st.markdown(f"**Salary:** {salary}")
                st.markdown(f"**Posted:** {job.get('posted_at','')[:10]}")
                tags = job.get("tags",[])
                if tags:
                    st.markdown("**Tags:** " + " · ".join(f"`{t}`" for t in tags[:8]))
            with c3:
                if job.get("url"):
                    st.link_button("🔗 View Job Posting", job["url"])
                _tracker.upsert_job(job)
                curr_status = existing["status"] if existing else "discovered"
                if curr_status not in ("shortlisted","submitted"):
                    if st.button("✅ Shortlist", key=f"sl_{job['id']}"):
                        _tracker.update_status(job["id"], "shortlisted")
                        st.success("Shortlisted!")
                        st.rerun()
                else:
                    st.markdown(f"Status: **{curr_status}**")
                if curr_status != "withdrawn":
                    if st.button("🚫 Skip", key=f"skip_{job['id']}"):
                        _tracker.update_status(job["id"], "withdrawn")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 – APPLICATIONS
# ─────────────────────────────────────────────────────────────────────────────

def applications_page() -> None:
    st.title("📋 Applications")
    st.caption(
        "Review shortlisted jobs, generate AI cover letters, answer application questions, "
        "and confirm submissions — **you always approve before anything is sent**."
    )

    unlocked, profile = _unlock_widget("main")
    if not unlocked:
        return

    client = _get_openai_client()

    # ── status filter ─────────────────────────────────────────────────────────
    status_filter = st.selectbox(
        "Show jobs with status",
        ["shortlisted", "drafted", "submitted"] + STATUSES,
        index=0,
    )

    jobs = _tracker.get_jobs(status=status_filter if status_filter != "all" else None)

    if not jobs:
        st.info(f"No jobs with status **{status_filter}**. Discover and shortlist jobs first.")
        return

    st.markdown(f"**{len(jobs)} jobs** with status `{status_filter}`")
    st.divider()

    for job in jobs:
        rel   = {"score": job.get("relevance_score",0), "label": job.get("relevance_label","—")}
        score = rel["score"] or 0
        label = rel["label"] or "—"

        header = (
            f"**{job['title']}** @ {job['company']} · {job['location']}"
            f"{'  🌐' if job.get('remote') else ''}"
            f" · {label} ({score}/100)"
        )
        with st.expander(header, expanded=False):
            left, right = st.columns([3, 2])

            with left:
                st.markdown(f"**Description:**\n{job.get('description','')[:600]}…")
                if job.get("url"):
                    st.link_button("🔗 Open Original Posting", job["url"])

            with right:
                # ── cover letter ──────────────────────────────────────────
                st.markdown("#### 📄 Cover Letter")
                existing_cl = job.get("cover_letter", "")
                if existing_cl:
                    with st.expander("View / Edit saved cover letter"):
                        new_cl = st.text_area("Cover Letter", existing_cl, height=300, key=f"cl_{job['id']}")
                        if st.button("💾 Save edits", key=f"save_cl_{job['id']}"):
                            _tracker.save_cover_letter(job["id"], new_cl)
                            st.success("Saved.")
                else:
                    if client:
                        if st.button("✨ Generate Cover Letter (AI)", key=f"gen_cl_{job['id']}"):
                            with st.spinner("Generating…"):
                                cl = generate_cover_letter(job, profile, client)
                            _tracker.save_cover_letter(job["id"], cl)
                            _tracker.update_status(job["id"], "drafted")
                            st.success("Cover letter generated and saved!")
                            st.rerun()
                    else:
                        st.caption("⚠️ Add OPENAI_API_KEY to enable AI generation.")
                        manual_cl = st.text_area("Write cover letter manually", height=200, key=f"manual_cl_{job['id']}")
                        if st.button("💾 Save", key=f"save_manual_cl_{job['id']}"):
                            _tracker.save_cover_letter(job["id"], manual_cl)
                            _tracker.update_status(job["id"], "drafted")
                            st.success("Saved.")

                # ── common Q&A answers ────────────────────────────────────
                profile_qa = profile.get("qa_pairs", [])
                if profile_qa and client:
                    with st.expander("💬 Generate Application Q&A Answers"):
                        questions = [p["question"] for p in profile_qa if p.get("question")]
                        if st.button("✨ Generate Answers", key=f"gen_qa_{job['id']}"):
                            with st.spinner("Generating answers…"):
                                answers = generate_application_answers(job, profile, questions, client)
                            for pair in answers:
                                st.markdown(f"**Q:** {pair['question']}")
                                st.markdown(f"**A:** {pair['answer']}")
                                st.divider()

                # ── status management ─────────────────────────────────────
                st.markdown("#### 🔄 Status")
                new_status = st.selectbox(
                    "Update status",
                    STATUSES,
                    index=STATUSES.index(job["status"]) if job["status"] in STATUSES else 0,
                    key=f"status_{job['id']}",
                )
                notes = st.text_input("Notes", job.get("notes","") or "", key=f"notes_{job['id']}")

                # ── human-in-the-loop submission guard ────────────────────
                if new_status == "submitted" and job["status"] != "submitted":
                    st.warning(
                        "⚠️ **You are about to mark this application as submitted.**\n\n"
                        "Please confirm you have manually applied on the company's website."
                    )
                    confirm = st.checkbox(
                        "✅ I confirm I have submitted this application manually.",
                        key=f"confirm_{job['id']}",
                    )
                    if st.button("Confirm & Update Status", key=f"submit_{job['id']}", disabled=not confirm):
                        _tracker.update_status(job["id"], new_status, notes)
                        st.success(f"Status updated to **{new_status}**.")
                        st.rerun()
                else:
                    if st.button("Update Status", key=f"upd_{job['id']}"):
                        _tracker.update_status(job["id"], new_status, notes)
                        st.success(f"Status updated to **{new_status}**.")
                        st.rerun()

                # ── follow-up reminder ────────────────────────────────────
                if job["status"] == "submitted":
                    with st.expander("⏰ Set Follow-up Reminder"):
                        fu_date = st.date_input(
                            "Follow-up date",
                            value=datetime.date.today() + datetime.timedelta(days=7),
                            key=f"fu_date_{job['id']}",
                        )
                        fu_msg  = st.text_input("Message", "Follow up on application", key=f"fu_msg_{job['id']}")
                        if st.button("Set Reminder", key=f"fu_btn_{job['id']}"):
                            _tracker.add_follow_up(job["id"], str(fu_date), fu_msg)
                            st.success("Reminder set.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 – DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def dashboard_page() -> None:
    st.title("📊 Dashboard")

    stats = _tracker.get_stats()

    # ── KPI row ───────────────────────────────────────────────────────────────
    kpi_cols = st.columns(5)
    kpis = [
        ("📥 Discovered",  stats.get("discovered", 0)),
        ("⭐ Shortlisted", stats.get("shortlisted", 0)),
        ("✏️ Drafted",     stats.get("drafted", 0)),
        ("📨 Submitted",   stats.get("submitted", 0)),
        ("🎯 Responses",   stats.get("response_received",0) + stats.get("interview_scheduled",0) + stats.get("offer_received",0)),
    ]
    for col, (label, value) in zip(kpi_cols, kpis):
        with col:
            st.metric(label, value)

    # ── pipeline visualisation ────────────────────────────────────────────────
    st.divider()
    st.subheader("Application Pipeline")

    pipeline_stages = [
        "discovered", "shortlisted", "drafted",
        "submitted", "response_received", "interview_scheduled",
        "offer_received",
    ]
    pipeline_counts = [stats.get(s, 0) for s in pipeline_stages]
    pipeline_labels = [
        "Discovered", "Shortlisted", "Drafted",
        "Submitted", "Response", "Interview", "Offer",
    ]

    try:
        import pandas as pd
        df = pd.DataFrame({"Stage": pipeline_labels, "Count": pipeline_counts})
        st.bar_chart(df.set_index("Stage"))
    except ImportError:
        for label, count in zip(pipeline_labels, pipeline_counts):
            st.write(f"**{label}**: {count}")

    # ── rejection / offer counters ────────────────────────────────────────────
    st.divider()
    r1, r2, r3 = st.columns(3)
    r1.metric("❌ Rejected",  stats.get("rejected", 0))
    r2.metric("🚫 Withdrawn", stats.get("withdrawn", 0))
    r3.metric("🤝 Offers",    stats.get("offer_received", 0))

    # ── follow-up reminders ───────────────────────────────────────────────────
    st.divider()
    st.subheader("⏰ Pending Follow-up Reminders")
    follow_ups = _tracker.get_pending_follow_ups()
    if follow_ups:
        for fu in follow_ups:
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.warning(
                    f"📅 **{fu['due_date']}** — Follow up on *{fu['title']}* @ {fu['company']}\n\n"
                    f"_{fu.get('message','')}_"
                )
            with col_b:
                if st.button("Done", key=f"fu_done_{fu['id']}"):
                    _tracker.mark_follow_up_done(fu["id"])
                    st.rerun()
    else:
        st.success("No pending follow-ups. 🎉")

    # ── recent applications ───────────────────────────────────────────────────
    st.divider()
    st.subheader("🕐 All Applications")

    all_jobs = _tracker.get_jobs()
    if not all_jobs:
        st.info("No jobs tracked yet. Discover and shortlist jobs to get started.")
        return

    try:
        import pandas as pd
        rows = []
        for j in all_jobs:
            rows.append({
                "Title":    j["title"],
                "Company":  j["company"],
                "Location": j["location"],
                "Remote":   "✅" if j.get("remote") else "",
                "Status":   j["status"],
                "Score":    j.get("relevance_score") or "—",
                "Updated":  (j.get("updated_at","") or "")[:10],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    except ImportError:
        for j in all_jobs:
            st.text(f"{j['status']:20} {j['title']:40} {j['company']}")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────────────

if page == "🔐 Profile Vault":
    profile_vault_page()
elif page == "🔍 Job Discovery":
    job_discovery_page()
elif page == "📋 Applications":
    applications_page()
elif page == "📊 Dashboard":
    dashboard_page()
