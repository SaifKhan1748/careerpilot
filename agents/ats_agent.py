"""
CareerPilot - ATS Agent (Phase 3)

Mimics a real Applicant Tracking System: these are keyword-matching
engines, not thoughtful readers. So this agent is fully DETERMINISTIC -
no LLM - which is actually more realistic, not a limitation. An ATS
doesn't understand "strong evidence," it just checks if words appear.

Rubric (0-100):
  - Keyword coverage      : 0-50  (fraction of requirements whose key terms appear in resume text)
  - Contact info present  : 0-15  (email, phone found)
  - Section structure     : 0-20  (Skills/Experience/Education section markers found)
  - Date formatting        : 0-15  (experience entries have parseable dates)
"""

import json
import re

from db import get_session
from models import Job, Candidate, Requirement, ResumeVersion, AgentAssessment, Experience

STOPWORDS = {
    "a", "an", "the", "and", "or", "with", "in", "of", "to", "for",
    "experience", "years", "year", "strong", "good", "excellent",
    "ability", "skills", "knowledge", "understanding", "familiarity",
}


def extract_keywords(text: str) -> set:
    words = re.findall(r"[a-zA-Z0-9\+\#]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def score_keyword_coverage(job_id: str, resume_lower: str) -> tuple:
    session = get_session()
    requirements = session.query(Requirement).filter_by(job_id=job_id).all()
    session.close()

    if not requirements:
        return 0, [], []

    matched = []
    missing = []

    for req in requirements:
        keywords = extract_keywords(req.text)
        if not keywords:
            continue
        present = sum(1 for k in keywords if k in resume_lower)
        ratio = present / len(keywords)
        if ratio >= 0.6:
            matched.append(req.text)
        else:
            missing.append(req.text)

    total = len(matched) + len(missing)
    score = round((len(matched) / total) * 50) if total else 0
    return score, matched, missing


def score_contact_info(candidate_id: str) -> tuple:
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    session.close()

    score = 0
    concerns = []
    if candidate.email:
        score += 7
    else:
        concerns.append("No email found - ATS systems typically reject applications missing contact info.")
    if candidate.phone:
        score += 8
    else:
        concerns.append("No phone number found.")
    return score, concerns


def score_structure(resume_lower: str) -> tuple:
    markers = {
        "skills": ["skill"],
        "experience_or_projects": ["experience", "project"],
        "education": ["education"],
    }
    score = 0
    concerns = []
    for section, keywords in markers.items():
        found = any(k in resume_lower for k in keywords)
        if found:
            score += 20 // len(markers)
        else:
            concerns.append(f"No recognizable '{section.replace('_', ' ')}' section found - ATS parsers may fail to categorize this content.")
    return score, concerns


def score_date_formatting(candidate_id: str) -> tuple:
    session = get_session()
    experiences = session.query(Experience).filter_by(candidate_id=candidate_id).all()
    session.close()

    if not experiences:
        return 15, []  # nothing to penalize - full points, not applicable

    with_dates = [e for e in experiences if e.start_date]
    ratio = len(with_dates) / len(experiences)
    score = round(ratio * 15)
    concerns = [] if ratio == 1.0 else ["Some experience entries are missing dates - ATS systems often flag or deprioritize undated entries."]
    return score, concerns


def assess(resume_version_id: str, job_id: str, candidate_id: str) -> str:
    """Runs the full ATS assessment, saves an AgentAssessment row, returns its id."""
    session = get_session()
    resume = session.query(ResumeVersion).filter_by(id=resume_version_id).first()
    content_lower = resume.content.lower()
    session.close()

    kw_score, matched, missing = score_keyword_coverage(job_id, content_lower)
    contact_score, contact_concerns = score_contact_info(candidate_id)
    structure_score, structure_concerns = score_structure(content_lower)
    date_score, date_concerns = score_date_formatting(candidate_id)

    total_score = kw_score + contact_score + structure_score + date_score

    strengths = [f"Matched keyword requirement: {m}" for m in matched]
    concerns = [f"Missing keyword match: {m}" for m in missing] + contact_concerns + structure_concerns + date_concerns

    reasoning = (
        f"Keyword coverage: {kw_score}/50, Contact info: {contact_score}/15, "
        f"Structure: {structure_score}/20, Date formatting: {date_score}/15."
    )

    session = get_session()
    assessment = AgentAssessment(
        resume_version_id=resume_version_id,
        agent_type="ats",
        score=total_score,
        strengths=json.dumps(strengths),
        concerns=json.dumps(concerns),
        reasoning=reasoning,
    )
    session.add(assessment)
    session.commit()
    assessment_id = assessment.id
    session.close()

    return assessment_id


if __name__ == "__main__":
    from models import Job, Candidate
    from agents.run_loop import get_best_resume_id

    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py, candidate_agent.py, and matching_engine.py first.")
    else:
        resume_id = get_best_resume_id(job.id, candidate.id)

        if not resume_id:
            print("No resume versions found. Run run_loop.py first.")
        else:
            assessment_id = assess(resume_id, job.id, candidate.id)

            session = get_session()
            a = session.query(AgentAssessment).filter_by(id=assessment_id).first()
            print(f"ATS score: {a.score}/100")
            print(f"Reasoning: {a.reasoning}")
            print("\nStrengths:")
            for s in json.loads(a.strengths):
                print(f"  + {s}")
            print("\nConcerns:")
            for c in json.loads(a.concerns):
                print(f"  - {c}")
            session.close()