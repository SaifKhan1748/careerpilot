"""
CareerPilot - Critic Agent (Phase 2, rubric version)

Replaces the freeform "ask the LLM for a 0-100 score" approach with a
fixed rubric computed in CODE. Same resume text -> same score, every
time. No more round-to-round noise from LLM judgment variance.

Rubric (adds up to 100):
  - Requirement coverage      : 0-30  (how well matched requirements are, weighted by strength)
  - Measurable outcomes       : 0-20  (bullets containing real numbers/results)
  - Structure completeness    : 0-20  (has Education section, has Experience section)
  - Generic phrase avoidance  : 0-20  (penalty per known filler phrase found)
  - Non-repetition            : 0-10  (penalty per duplicated phrase across bullets)

Fact-check (fabrication detection) is unchanged - still deterministic,
still a hard pass/fail signal separate from the score.
"""

import json
import re

from db import get_session
from models import (
    ResumeVersion, FactCheckFlag, Requirement, Match, Skill, Evidence,
    Education, Experience, Candidate, Project,
)

STRENGTH_WEIGHTS = {"strong": 1.0, "partial": 0.6, "weak": 0.3, "none": 0.0}

GENERIC_PHRASES = [
    "detail-oriented", "detail oriented", "results-driven", "results driven",
    "hands-on experience", "hands on experience", "proven ability",
    "passionate about", "dynamic professional", "team player",
    "self-motivated", "self motivated", "go-getter", "think outside the box",
    "fast-paced environment", "fast paced environment",
]


def normalize_text(text: str) -> str:
    """
    LLM output often uses "smart" typographic punctuation (non-breaking
    hyphens, en/em dashes, curly quotes) instead of plain ASCII. This
    silently broke every hyphenated phrase check (e.g. "production-grade")
    because "production‑grade" (smart hyphen) != "production-grade"
    (ASCII hyphen) as far as Python string matching is concerned.
    Normalize BEFORE any keyword/phrase comparison, or these checks
    quietly stop working without any error.
    """
    if not text:
        return text
    replacements = {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    }
    for smart_char, ascii_char in replacements.items():
        text = text.replace(smart_char, ascii_char)
    return text


def extract_body_only(full_content: str) -> str:
    """Same logic as optimizer_agent.py - isolates body from header/certs/education."""
    chunks = full_content.split("\n\n")
    if len(chunks) < 2:
        return full_content

    body_chunks = [chunks[0]]  # keep placeholder, drop below
    body_chunks = chunks[1:]

    # drop trailing deterministic sections if present (Education, Certificates)
    while body_chunks and body_chunks[-1].strip().split("\n")[0].strip() in ("Education", "Certificates"):
        body_chunks = body_chunks[:-1]

    return "\n\n".join(body_chunks).strip()


RISKY_CLAIM_PHRASES = [
    "unit test", "automated test", "test suite", "logging", "ci/cd",
    "continuous integration", "load balanc", "caching", "cache layer",
    "microservice", "scalab", "concurrent", "simultaneous request",
    "latency", "throughput", "scheduled job", "cron job", "csv",
    "versioned", "version control", "code review", "deployment pipeline",
    "docker", "kubernetes", "cloud", "aws", "azure", "gcp",
    "cross-functional", "stakeholder",
    # added when company-culture hints were wired in - these are the
    # buzzwords an LLM reaches for when trying to sound like it matches
    # a company's stated engineering culture, even without real evidence
    "large-scale", "large scale", "distributed system", "high-scale",
    "enterprise-grade", "big data", "petabyte", "millions of users",
    "billions of", "high availability", "fault-toleran", "mission-critical",
    "production-grade", "production grade",
]

# Common named technologies/tools that are easy for an LLM to casually
# drop into a resume as if the candidate used them, even with zero
# evidence. Unlike RISKY_CLAIM_PHRASES (vague buzzwords), these are
# SPECIFIC tool names - if one appears in the resume but was never
# actually part of the candidate's real skills/evidence, that's a
# straightforward fabrication, not a judgment call.
COMMON_TECH_TERMS = [
    "pandas", "numpy", "tensorflow", "pytorch", "scikit-learn", "sklearn",
    "matplotlib", "seaborn", "django", "fastapi", "express", "react",
    "angular", "vue", "node.js", "mongodb", "postgresql", "postgres",
    "redis", "kafka", "spark", "hadoop", "jenkins", "terraform",
    "graphql", "golang", "rust", "scala", "tableau", "power bi",
    "jira", "airflow", "elasticsearch", "rabbitmq", "grpc",
]


def check_overclaiming(resume_body: str, candidate_id: str) -> list:
    """
    Catches a fabrication class the skill-name fact-check CANNOT catch:
    specific implementation claims (testing, logging, latency numbers,
    versioning, etc.) that were never extracted as Skills in the first
    place, so the original fact-check has no row to compare against.

    This scans for a known list of commonly-invented technical phrases
    and flags any that appear in the generated resume but NOT anywhere
    in the candidate's actual original source text (raw resume, project
    descriptions/outcomes, experience descriptions).
    """
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    projects = session.query(Project).filter_by(candidate_id=candidate_id).all()
    experiences = session.query(Experience).filter_by(candidate_id=candidate_id).all()
    session.close()

    source_parts = [candidate.raw_resume_text or ""]
    for p in projects:
        source_parts.append(p.description or "")
        source_parts.append(p.outcomes or "")
    for e in experiences:
        source_parts.append(e.description or "")

    source_lower = " ".join(source_parts).lower()
    body_lower = resume_body.lower()

    flags = []
    for phrase in RISKY_CLAIM_PHRASES:
        if phrase in body_lower and phrase not in source_lower:
            flags.append({"claim_text": phrase, "status": "unsupported"})

    flags.extend(check_experience_duration_claims(resume_body, candidate_id))
    flags.extend(check_unlisted_tech_terms(resume_body, candidate_id))
    return flags


def check_unlisted_tech_terms(resume_body: str, candidate_id: str) -> list:
    """
    Catches a specific technology name (pandas, PostgreSQL, Kafka, etc.)
    appearing in the resume that was NEVER part of the candidate's real
    source text or skill list. This closes the exact gap that let
    'pandas, NumPy' slip through undetected - those were never even
    created as Skill rows, so the old check had nothing to compare
    against. This check compares against the full source text directly,
    not just the Skill table, so it can't be fooled by a term that was
    never formally extracted as a skill.
    """
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    projects = session.query(Project).filter_by(candidate_id=candidate_id).all()
    experiences = session.query(Experience).filter_by(candidate_id=candidate_id).all()
    skills = session.query(Skill).filter_by(candidate_id=candidate_id).all()
    session.close()

    source_parts = [candidate.raw_resume_text or ""]
    for p in projects:
        source_parts.append(p.description or "")
        source_parts.append(p.outcomes or "")
    for e in experiences:
        source_parts.append(e.description or "")
    for s in skills:
        source_parts.append(s.name or "")
    source_lower = " ".join(source_parts).lower()

    body_lower = resume_body.lower()

    flags = []
    for term in COMMON_TECH_TERMS:
        if term in body_lower and term not in source_lower:
            flags.append({"claim_text": term, "status": "unsupported"})

    return flags


def check_experience_duration_claims(resume_body: str, candidate_id: str) -> list:
    """
    Catches invented tenure claims like '3+ years' or '5 years experience'
    that don't appear anywhere in the candidate's real source text. These
    slip past both the skill fact-check (not a skill name) and the
    phrase-list check (arbitrary numbers, can't be a fixed phrase).
    """
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    projects = session.query(Project).filter_by(candidate_id=candidate_id).all()
    experiences = session.query(Experience).filter_by(candidate_id=candidate_id).all()
    session.close()

    source_parts = [candidate.raw_resume_text or ""]
    for p in projects:
        source_parts.append(p.description or "")
        source_parts.append(p.outcomes or "")
    for e in experiences:
        source_parts.append(e.description or "")
    source_lower = " ".join(source_parts).lower()

    duration_pattern = re.compile(r"\d+\+?\s*years?\b", re.IGNORECASE)
    body_matches = duration_pattern.findall(resume_body)

    flags = []
    for match in body_matches:
        if match.lower() not in source_lower:
            flags.append({"claim_text": f"'{match}' experience claim", "status": "unsupported"})

    return flags


def get_allowed_skill_names(job_id: str, candidate_id: str) -> set:
    session = get_session()
    requirements = session.query(Requirement).filter_by(job_id=job_id).all()

    allowed = set()
    for req in requirements:
        match = session.query(Match).filter_by(requirement_id=req.id).order_by(Match.confidence.desc()).first()
        if not match or match.strength == "none" or not match.evidence_id:
            continue
        evidence = session.query(Evidence).filter_by(id=match.evidence_id).first()
        skill = session.query(Skill).filter_by(id=evidence.skill_id).first()
        if skill:
            allowed.add(skill.name.lower())

    all_candidate_skills = session.query(Skill).filter_by(candidate_id=candidate_id).all()
    for skill in all_candidate_skills:
        has_evidence = session.query(Evidence).filter_by(skill_id=skill.id).first()
        if has_evidence or skill.source == "candidate-stated":
            allowed.add(skill.name.lower())

    session.close()
    return allowed


def run_fact_check(resume_content: str, job_id: str, candidate_id: str) -> list:
    content_lower = resume_content.lower()
    allowed = get_allowed_skill_names(job_id, candidate_id)

    session = get_session()
    candidate_skills = session.query(Skill).filter_by(candidate_id=candidate_id).all()
    session.close()

    flags = []
    for skill in candidate_skills:
        name_lower = skill.name.lower()
        mentioned = name_lower in content_lower
        is_allowed = name_lower in allowed
        if mentioned and not is_allowed:
            flags.append({"claim_text": skill.name, "status": "unsupported"})
        elif mentioned and is_allowed:
            flags.append({"claim_text": skill.name, "status": "supported"})

    return flags


def score_coverage(job_id: str) -> tuple:
    """0-30 points based on weighted average requirement match strength."""
    session = get_session()
    requirements = session.query(Requirement).filter_by(job_id=job_id).all()

    if not requirements:
        session.close()
        return 0, "No requirements to evaluate against."

    total_weight = 0.0
    for req in requirements:
        match = session.query(Match).filter_by(requirement_id=req.id).order_by(Match.confidence.desc()).first()
        strength = match.strength if match else "none"
        total_weight += STRENGTH_WEIGHTS.get(strength, 0.0)

    session.close()
    avg = total_weight / len(requirements)
    score = round(avg * 30)
    issue = None if avg >= 0.7 else f"Requirement coverage is weak ({round(avg*100)}% weighted match) - resume needs stronger evidence for more job requirements."
    return score, issue


def score_measurable_outcomes(body: str) -> tuple:
    """0-20 points. Counts bullet lines containing a digit or % (a real number/result)."""
    bullets = [line for line in body.split("\n") if line.strip().startswith("-")]
    if not bullets:
        return 0, "No bullet points found to evaluate."

    quantified = [b for b in bullets if re.search(r"\d", b)]
    count = len(quantified)
    score = min(20, count * 5)
    issue = None if count >= 2 else f"Only {count} bullet(s) contain measurable outcomes (numbers/results) out of {len(bullets)} total - add real metrics where you have them."
    return score, issue


def score_structure(candidate_id: str) -> tuple:
    """0-20 points. 10 for having Education, 10 for having Experience, based on real DB rows."""
    session = get_session()
    has_education = session.query(Education).filter_by(candidate_id=candidate_id).first() is not None
    has_experience = session.query(Experience).filter_by(candidate_id=candidate_id).first() is not None
    session.close()

    score = (10 if has_education else 0) + (10 if has_experience else 0)
    issues = []
    if not has_education:
        issues.append("No Education entries on file for this candidate.")
    if not has_experience:
        issues.append("No work Experience entries on file for this candidate.")
    return score, issues


def score_generic_phrases(body: str) -> tuple:
    """0-20 points. -4 per known generic/filler phrase found."""
    body_lower = body.lower()
    found = [phrase for phrase in GENERIC_PHRASES if phrase in body_lower]
    score = max(0, 20 - 4 * len(found))
    issue = None if not found else f"Generic filler phrase(s) found: {', '.join(found)} - replace with specific, concrete language."
    return score, issue


def score_repetition(body: str) -> tuple:
    """0-10 points. Penalizes repeated 4-word phrases across bullets.
    Now reports the ACTUAL duplicated phrases, not just a count, so the
    Optimizer has something concrete to rewrite instead of a vague hint."""
    words = re.findall(r"\w+", body.lower())
    ngrams = [" ".join(words[i:i+4]) for i in range(len(words) - 3)]
    seen = {}
    for ng in ngrams:
        seen[ng] = seen.get(ng, 0) + 1
    duplicates = [ng for ng, count in seen.items() if count > 1]

    score = max(0, 10 - 2 * len(duplicates))
    if not duplicates:
        return score, None

    shown = duplicates[:3]
    issue = f"Repeated phrasing found: {'; '.join(repr(d) for d in shown)} - rewrite these bullets to avoid reusing the exact same wording."
    return score, issue


def critique(resume_version_id: str, job_id: str, candidate_id: str) -> dict:
    """
    Computes the full rubric score + fact check for a resume version.
    Saves results onto the ResumeVersion row and as FactCheckFlag rows.
    """
    session = get_session()
    resume = session.query(ResumeVersion).filter_by(id=resume_version_id).first()
    content = normalize_text(resume.content)
    session.close()

    body = extract_body_only(content)

    coverage_score, coverage_issue = score_coverage(job_id)
    outcomes_score, outcomes_issue = score_measurable_outcomes(body)
    structure_score, structure_issues = score_structure(candidate_id)
    generic_score, generic_issue = score_generic_phrases(body)
    repetition_score, repetition_issue = score_repetition(body)

    total_score = coverage_score + outcomes_score + structure_score + generic_score + repetition_score

    issues = []
    for i in [coverage_issue, outcomes_issue, generic_issue, repetition_issue]:
        if i:
            issues.append(i)
    issues.extend(structure_issues)

    fact_flags = run_fact_check(content, job_id, candidate_id)
    overclaim_flags = check_overclaiming(body, candidate_id)
    all_flags = fact_flags + overclaim_flags

    unsupported = [f for f in all_flags if f["status"] == "unsupported"]
    for f in unsupported:
        issues.append(f"FABRICATION: '{f['claim_text']}' is mentioned but has no supporting evidence.")

    session = get_session()
    resume = session.query(ResumeVersion).filter_by(id=resume_version_id).first()
    resume.critic_notes = json.dumps(issues)
    resume.quality_score = total_score
    resume.fact_check_passed = (len(unsupported) == 0)

    for f in all_flags:
        session.add(FactCheckFlag(
            resume_version_id=resume_version_id,
            claim_text=f["claim_text"],
            status=f["status"],
        ))
    session.commit()
    session.close()

    return {
        "quality_score": total_score,
        "fact_check_passed": len(unsupported) == 0,
        "issues": issues,
        "breakdown": {
            "coverage": coverage_score,
            "measurable_outcomes": outcomes_score,
            "structure": structure_score,
            "generic_phrases": generic_score,
            "repetition": repetition_score,
        },
    }


if __name__ == "__main__":
    session = get_session()
    resume = session.query(ResumeVersion).order_by(ResumeVersion.created_at.desc()).first()
    session.close()

    if not resume:
        print("Run resume_agent.py first to create a resume version.")
    else:
        result = critique(resume.id, resume.job_id, resume.candidate_id)

        print(f"Quality score: {result['quality_score']}/100")
        print(f"Breakdown: {result['breakdown']}")
        print(f"Fact check passed: {result['fact_check_passed']}")
        print("\nIssues found:")
        for issue in result["issues"]:
            print(f"  - {issue}")