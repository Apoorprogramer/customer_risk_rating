"""
Autofill & Document Generation
================================
Uses GPT-4o-mini to generate:
  • A personalised cover letter for a specific job + profile
  • Answers to common application questions

Both functions are safe to call without an OpenAI client (they return a
placeholder so the UI stays functional even without API access).
"""

from __future__ import annotations

_COVER_LETTER_SYSTEM = """\
You are an expert career coach who writes compelling, personalised cover letters.
Write a professional cover letter (≤ 300 words) for the candidate below applying
to the given job.  Tone: confident, specific, and genuine.
Do NOT use generic filler phrases like "I am excited to apply" or "I am a
hard-working individual".  Highlight 2-3 concrete achievements or skills that
directly match the job requirements.
Output ONLY the cover letter text – no subject line, no JSON wrapper.
"""

_QA_SYSTEM = """\
You are an expert career coach helping candidates fill out online job applications.
Given the candidate's profile and a job description, answer each question below
concisely and truthfully based solely on the profile data.
Respond ONLY with valid JSON: {"answers": [{"question": "...", "answer": "..."}]}
Do not invent information that is not in the profile.  If you cannot answer,
write "Please fill in manually."
"""


def generate_cover_letter(job: dict, profile: dict, client) -> str:
    """Generate a tailored cover letter.  Returns plain text."""
    profile_block = _profile_block(profile)
    job_block     = _job_block(job)

    user_content = (
        f"## Candidate\n{profile_block}\n\n"
        f"## Job Posting\n{job_block}"
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _COVER_LETTER_SYSTEM},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.7,
            max_tokens=600,
        )
        return completion.choices[0].message.content.strip()
    except Exception as exc:
        return (
            f"[Cover letter generation failed: {exc}]\n\n"
            "Please write your cover letter manually."
        )


def generate_application_answers(
    job: dict,
    profile: dict,
    questions: list[str],
    client,
) -> list[dict]:
    """
    Answer a list of common application questions.

    Returns a list of {"question": str, "answer": str} dicts.
    """
    if not questions:
        return []

    profile_block = _profile_block(profile)
    job_block     = _job_block(job)
    q_block       = "\n".join(f"- {q}" for q in questions)

    user_content = (
        f"## Candidate\n{profile_block}\n\n"
        f"## Job Posting\n{job_block}\n\n"
        f"## Questions to Answer\n{q_block}"
    )

    import json
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _QA_SYSTEM},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1_000,
        )
        raw  = completion.choices[0].message.content.strip()
        data = json.loads(raw)
        return data.get("answers", [])
    except Exception:
        return [{"question": q, "answer": "Please fill in manually."} for q in questions]


# ── helpers ───────────────────────────────────────────────────────────────────

def _profile_block(profile: dict) -> str:
    parts = []
    if profile.get("full_name"):
        parts.append(f"Name: {profile['full_name']}")
    if profile.get("current_title"):
        parts.append(f"Title: {profile['current_title']}")
    if profile.get("years_of_experience"):
        parts.append(f"Experience: {profile['years_of_experience']} years")
    if profile.get("skills"):
        parts.append(f"Skills: {', '.join(profile['skills'][:30])}")
    if profile.get("summary"):
        parts.append(f"Summary: {profile['summary'][:500]}")
    if profile.get("resume_text"):
        parts.append(f"Resume excerpt:\n{profile['resume_text'][:800]}")
    # Top 2 work experiences
    for exp in profile.get("work_experience", [])[:2]:
        company = exp.get("company", "")
        title   = exp.get("title", "")
        desc    = exp.get("description", "")[:200]
        parts.append(f"Experience: {title} at {company} – {desc}")
    return "\n".join(parts) if parts else "No profile data provided."


def _job_block(job: dict) -> str:
    return (
        f"Title:   {job.get('title', 'N/A')}\n"
        f"Company: {job.get('company', 'N/A')}\n"
        f"Location: {job.get('location', 'N/A')} "
        f"(Remote: {'Yes' if job.get('remote') else 'No'})\n"
        f"Description:\n{job.get('description', '')[:800]}"
    )
