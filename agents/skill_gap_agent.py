"""
CareerPilot - Skill-Gap Agent (Phase 6)

Uses the REAL Match/Requirement data already computed by matching_engine.py
to bucket gaps by urgency (deterministic - reads real strength values,
no guessing). LLM is only used to phrase a generic, practical suggestion
for closing each gap - explicitly told not to name specific courses,
certifications, or URLs it can't verify, since that would just be a
new flavor of fabrication.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Job, Requirement, Match
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def bucket_urgency(req_type: str, strength: str) -> str:
    """Deterministic - reads real stored data, no LLM guessing."""
    if req_type == "must-have" and strength == "none":
        return "urgent"
    if req_type == "must-have" and strength == "weak":
        return "important"
    if req_type == "preferred" and strength == "none":
        return "important"
    if req_type == "preferred" and strength == "weak":
        return "optional"
    return None  # partial/strong matches aren't gaps


def compute_gaps(job_id: str) -> list:
    """Returns list of gap dicts, deterministic, no LLM."""
    session = get_session()
    requirements = session.query(Requirement).filter_by(job_id=job_id).all()

    gaps = []
    for req in requirements:
        match = session.query(Match).filter_by(requirement_id=req.id).order_by(Match.confidence.desc()).first()
        strength = match.strength if match else "none"

        urgency = bucket_urgency(req.type, strength)
        if urgency:
            gaps.append({
                "requirement": req.text,
                "type": req.type,
                "priority": req.priority,
                "current_strength": strength,
                "urgency": urgency,
            })
    session.close()

    urgency_order = {"urgent": 0, "important": 1, "optional": 2}
    gaps.sort(key=lambda g: (urgency_order[g["urgency"]], -g["priority"]))
    return gaps


def add_suggestions(gaps: list) -> list:
    """
    LLM adds ONE practical, generic suggestion per gap. Explicitly
    forbidden from naming specific courses/certs/URLs - those would be
    unverifiable claims, the same category of problem as everything
    else this system refuses to fabricate.
    """
    if not gaps:
        return gaps

    prompt = f"""For each skill gap below, write ONE short, practical suggestion (1 sentence) for how
someone could start closing it.

Gaps:
{json.dumps([g['requirement'] for g in gaps], indent=2)}

Return ONLY valid JSON, no other text:
{{"suggestions": ["suggestion for gap 1", "suggestion for gap 2", ...]}}

Rules:
- Keep suggestions GENERIC and actionable: e.g. "build a small project using X", "read the official docs and complete a beginner tutorial", "practice X in an existing project."
- Do NOT name specific course platforms, course titles, certification names, book titles, or URLs - you cannot verify these exist or are current, so don't invent them.
- One suggestion per gap, in the same order as given.
"""

    response = call_groq_with_retry(
        client, model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json\n", "", 1)

    suggestions = json.loads(text)["suggestions"]
    for gap, suggestion in zip(gaps, suggestions):
        gap["suggestion"] = suggestion

    return gaps


if __name__ == "__main__":
    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    session.close()

    if not job:
        print("Run job_agent.py, candidate_agent.py, and matching_engine.py first.")
    else:
        gaps = compute_gaps(job.id)

        if not gaps:
            print(f"No gaps found for '{job.title}' - all requirements are matched well.")
        else:
            gaps = add_suggestions(gaps)

            print(f"Skill gaps for '{job.title}':\n")
            for bucket in ["urgent", "important", "optional"]:
                bucket_gaps = [g for g in gaps if g["urgency"] == bucket]
                if not bucket_gaps:
                    continue
                print(f"{bucket.upper()}")
                for g in bucket_gaps:
                    print(f"  - {g['requirement']} (current: {g['current_strength']})")
                    print(f"    -> {g['suggestion']}")
                print()