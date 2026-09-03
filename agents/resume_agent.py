"""
CareerPilot - Resume Agent (Phase 2, fixed)

Same structure as before, PLUS:
- Education section: built deterministically from the DB, like
  Certificates. Degrees/dates/institutions can never be hallucinated.
- Experience: real Experience rows are now passed to the LLM as facts
  it must write bullets FROM (not invent) - title/org/dates come from
  the database, only the bullet phrasing is LLM-generated.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import (
    Job, Candidate, Requirement, Match, Skill, Evidence, Project,
    ResumeVersion, Certificate, Education, Experience, CompanyClaim
)
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def build_evidence_backed_context(job_id: str, candidate_id: str) -> dict:
    session = get_session()

    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    job = session.query(Job).filter_by(id=job_id).first()
    certificates = session.query(Certificate).filter_by(candidate_id=candidate_id).all()
    education = session.query(Education).filter_by(candidate_id=candidate_id).all()
    experience = session.query(Experience).filter_by(candidate_id=candidate_id).all()

    requirements = session.query(Requirement).filter_by(job_id=job_id).all()
    matched_facts = []
    gaps = []

    for req in requirements:
        match = session.query(Match).filter_by(requirement_id=req.id).order_by(Match.confidence.desc()).first()
        if not match or match.strength == "none" or not match.evidence_id:
            gaps.append(req.text)
            continue

        evidence = session.query(Evidence).filter_by(id=match.evidence_id).first()
        skill = session.query(Skill).filter_by(id=evidence.skill_id).first()
        project = None
        if evidence.source_type == "project":
            project = session.query(Project).filter_by(id=evidence.source_id).first()

        matched_facts.append({
            "requirement": req.text,
            "skill": skill.name if skill else None,
            "strength": match.strength,
            "project_title": project.title if project else None,
            "project_description": project.description if project else None,
        })

    context = {
        "candidate_name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "portfolio_url": candidate.portfolio_url,
        "links": json.loads(candidate.links) if candidate.links else {},
        "certificates": [
            {"title": c.title, "issuer": c.issuer, "date_earned": c.date_earned, "url": c.url}
            for c in certificates
        ],
        "education": [
            {"institution": e.institution, "degree": e.degree, "field": e.field, "graduation_date": e.graduation_date}
            for e in education
        ],
        "experience_facts": [
            {"title": e.title, "organization": e.organization, "start_date": e.start_date,
             "end_date": e.end_date, "description": e.description}
            for e in experience
        ],
        "job_title": job.title,
        "matched_facts": matched_facts,
        "gaps": gaps,
        "company_culture_hints": [c.claim_text for c in session.query(CompanyClaim).filter_by(company_id=job.company_id).limit(6).all()] if job.company_id else [],
    }

    session.close()
    return context


def build_header(context: dict) -> str:
    """Deterministic - no LLM involved."""
    lines = [context["candidate_name"]]

    contact_bits = []
    if context["email"]:
        contact_bits.append(context["email"])
    if context["phone"]:
        contact_bits.append(context["phone"])
    if context["portfolio_url"]:
        contact_bits.append(context["portfolio_url"])
    if contact_bits:
        lines.append(" | ".join(contact_bits))

    if context["links"]:
        link_bits = [f"{name.capitalize()}: {url}" for name, url in context["links"].items()]
        lines.append(" | ".join(link_bits))

    return "\n".join(lines)


def build_education_section(context: dict) -> str:
    """Deterministic - no LLM involved. Dates/degrees can't be hallucinated."""
    if not context["education"]:
        return ""

    lines = ["Education"]
    for edu in context["education"]:
        line = f"- {edu['degree']}"
        if edu.get("field"):
            line += f" in {edu['field']}"
        if edu.get("institution"):
            line += f", {edu['institution']}"
        if edu.get("graduation_date"):
            line += f" ({edu['graduation_date']})"
        lines.append(line)

    return "\n".join(lines)


def build_certificates_section(context: dict) -> str:
    """Deterministic - no LLM involved."""
    if not context["certificates"]:
        return ""

    lines = ["Certificates"]
    for cert in context["certificates"]:
        line = f"- {cert['title']}"
        if cert.get("issuer"):
            line += f", {cert['issuer']}"
        if cert.get("date_earned"):
            line += f" ({cert['date_earned']})"
        lines.append(line)

    return "\n".join(lines)


def generate_body_with_llm(context: dict) -> str:
    """
    Summary + Skills + Projects + Work Experience bullets - LLM writes
    the phrasing, but title/organization/dates for experience_facts
    come directly from the database and must not be altered.
    """
    prompt = f"""Write a resume summary + skills + project experience + work experience section for {context['candidate_name']}, targeting a {context['job_title']} role.

ONLY use the facts below. Do not add any skill, tool, technology, employer, or date that is not listed here.

Evidence-backed skill/project facts you may use:
{json.dumps(context['matched_facts'], indent=2)}

Real work experience entries (use the title/organization/dates EXACTLY as given - only write the descriptive bullet points from the description text provided):
{json.dumps(context['experience_facts'], indent=2)}

Requirements this candidate does NOT have evidence for (do not mention these as skills, do not imply the candidate has them):
{json.dumps(context['gaps'], indent=2)}

Company culture/technical signals (for TONE AND EMPHASIS ONLY - see hard rule below):
{json.dumps(context['company_culture_hints'], indent=2)}

Rules:
- Write plain text, no markdown headers needed - just a clean resume-style summary and bullet points.
- Do not include a header with name/contact info - that is added separately.
- Do not include a Certificates or Education section - those are added separately, after your output.
- If experience_facts is empty, skip the work experience section entirely - do not invent one.
- Do not invent implementation details that aren't in the facts above: no testing/logging claims, no performance numbers (latency, throughput), no deployment/CI-CD/versioning claims, no cloud/Docker/Kubernetes mentions, unless they appear in the project/experience descriptions given. Stick to describing what the facts actually say.
- Do not state a specific number of years of experience (e.g. "3+ years") unless that exact figure is given in the facts above. If you don't know the candidate's total years of experience, don't mention a number at all.
- HARD RULE on company culture hints: use them ONLY to decide which of the facts above to emphasize, and what tone/phrasing to use. NEVER use them to add a new skill, technology, achievement, or scale claim that isn't already in matched_facts or experience_facts. If a hint mentions something the candidate has no evidence for (e.g. "large-scale systems" when the candidate's projects are small), do not mention it at all - do not try to sound like you have it.
- Never name a specific tool, library, or technology (e.g. pandas, PostgreSQL, Kafka, TensorFlow) unless it is explicitly named in the facts above. Do not add plausible-sounding tools just because they're commonly used alongside what the candidate actually has.
- Never invent unstated implementation details (how something was delivered, who it was presented to, what format it used) beyond what the facts above actually say.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    return response.choices[0].message.content.strip()


def generate_draft(job_id: str, candidate_id: str) -> str:
    context = build_evidence_backed_context(job_id, candidate_id)

    header = build_header(context)
    body = generate_body_with_llm(context)
    education_section = build_education_section(context)
    certs_section = build_certificates_section(context)

    parts = [header, "", body]
    if education_section:
        parts += ["", education_section]
    if certs_section:
        parts += ["", certs_section]

    full_content = "\n".join(parts)

    session = get_session()
    resume = ResumeVersion(
        candidate_id=candidate_id,
        job_id=job_id,
        version_number=1,
        content=full_content,
    )
    session.add(resume)
    session.commit()
    resume_id = resume.id
    session.close()

    return resume_id


if __name__ == "__main__":
    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py, candidate_agent.py, and matching_engine.py first.")
    else:
        resume_id = generate_draft(job.id, candidate.id)
        print(f"Saved resume version: {resume_id}\n")

        session = get_session()
        resume = session.query(ResumeVersion).filter_by(id=resume_id).first()
        print(resume.content)
        session.close()