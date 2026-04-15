"""
Profile Vault
=============
Stores all personal data (resume, DOB, contact info, work history, preferences,
common Q&A) in an AES-128-Fernet encrypted file derived from a user password
via PBKDF2-SHA256.  Every read/write is recorded in an append-only audit log.
"""

import base64
import datetime
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ── storage paths ────────────────────────────────────────────────────────────
_DATA_DIR = Path(".job_agent_data")
_DATA_DIR.mkdir(exist_ok=True)

PROFILE_PATH = _DATA_DIR / "profile.enc"
AUDIT_LOG_PATH = _DATA_DIR / "audit_log.json"

# ── default (empty) profile schema ───────────────────────────────────────────
DEFAULT_PROFILE: dict = {
    # Personal details
    "full_name": "",
    "email": "",
    "phone": "",
    "dob": "",
    "address": "",
    "city": "",
    "country": "",
    "linkedin": "",
    "github": "",
    "portfolio": "",
    "nationality": "",
    "visa_status": "",
    # Professional summary
    "summary": "",
    "current_title": "",
    "years_of_experience": 0,
    "skills": [],           # list of strings
    "languages": [],        # list of {"language": str, "level": str}
    # Work experience
    "work_experience": [],  # list of {company, title, start, end, description}
    # Education
    "education": [],        # list of {institution, degree, field, start, end, gpa}
    # Resume text (paste / extracted text from PDF)
    "resume_text": "",
    # Job preferences
    "desired_titles": [],
    "desired_locations": [],
    "remote_preference": "any",   # remote / hybrid / onsite / any
    "min_salary": 0,
    "max_salary": 0,
    "salary_currency": "USD",
    "preferred_industries": [],
    "company_blacklist": [],
    "company_whitelist": [],
    # Common application Q&A
    "qa_pairs": [],          # list of {question, answer}
    # Adzuna API credentials (optional)
    "adzuna_app_id": "",
    "adzuna_app_key": "",
}


# ── cryptography helpers ──────────────────────────────────────────────────────

def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


# ── public API ────────────────────────────────────────────────────────────────

def profile_exists() -> bool:
    return PROFILE_PATH.exists()


def save_profile(profile: dict, password: str) -> None:
    """Encrypt and persist the profile. Overwrites any existing file."""
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    payload = json.dumps(profile, ensure_ascii=False).encode("utf-8")
    PROFILE_PATH.write_bytes(salt + fernet.encrypt(payload))
    _log_audit("save_profile")


def load_profile(password: str) -> dict:
    """
    Decrypt and return the stored profile.
    Returns DEFAULT_PROFILE if no file exists.
    Raises InvalidToken on wrong password.
    """
    if not PROFILE_PATH.exists():
        return dict(DEFAULT_PROFILE)
    raw = PROFILE_PATH.read_bytes()
    salt, encrypted = raw[:16], raw[16:]
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    data = fernet.decrypt(encrypted)   # raises InvalidToken on wrong password
    _log_audit("load_profile")
    stored = json.loads(data.decode("utf-8"))
    # Merge with DEFAULT_PROFILE so new fields are always present
    merged = dict(DEFAULT_PROFILE)
    merged.update(stored)
    return merged


def get_audit_log() -> list:
    if not AUDIT_LOG_PATH.exists():
        return []
    try:
        return json.loads(AUDIT_LOG_PATH.read_text("utf-8"))
    except Exception:
        return []


# ── internal ──────────────────────────────────────────────────────────────────

def _log_audit(action: str) -> None:
    entry = {
        "action": action,
        "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    logs: list = []
    if AUDIT_LOG_PATH.exists():
        try:
            logs = json.loads(AUDIT_LOG_PATH.read_text("utf-8"))
        except Exception:
            logs = []
    logs.append(entry)
    AUDIT_LOG_PATH.write_text(json.dumps(logs, indent=2, ensure_ascii=False), "utf-8")
