"""
CareerPilot - Matching Engine (Phase 1)

For every Requirement of a Job, finds the best supporting Evidence from
a Candidate and saves a Match row with strength + reasoning.

Key rule: strength is CAPPED by the evidence's own confidence.
An LLM can say "strong" all it wants - if the evidence confidence is
low, we downgrade it in code. This is what stops hallucinated matches.
"""

import os
import json
import re
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Requirement, Skill, Evidence, Match
from agents.groq_utils import call_groq_with_retry

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

MODEL = "openai/gpt-oss-120b"

STRENGTH_ORDER = ["none", "weak", "partial", "strong"]

STOPWORDS = {"a", "an", "the", "and", "or", "with", "in", "of", "to", "for", "experience", "years", "year"}


def has_word_overlap(requirement_text: str, skill_name: str) -> bool:
    """
    Cheap, deterministic pre-filter - no LLM call needed. Returns True
    if the skill and requirement share at least one significant word,
    OR if either is a substring of the other (catches "SQL" vs
    "MySQL" type cases). Used to skip LLM calls for pairs that are
    obviously unrelated (e.g. "Git" vs "REST API design").
    """
    req_words = {w for w in re.findall(r"[a-zA-Z0-9\+\#]+", requirement_text.lower()) if w not in STOPWORDS}
    skill_words = {w for w in re.findall(r"[a-zA-Z0-9\+\#]+", skill_name.lower()) if w not in STOPWORDS}

    if req_words & skill_words:
        return True

    skill_lower = skill_name.lower()
    req_lower = requirement_text.lower()
    return skill_lower in req_lower or req_lower in skill_lower


def cap_strength_by_confidence(llm_strength: str, evidence_confidence: float) -> str:
    """
    Enforce: evidence confidence < 0.5 -> max 'weak'
              evidence confidence < 0.8 -> max 'partial'
              evidence confidence >= 0.8 -> LLM's strength allowed as-is
    This is a hard rule in code, not just a prompt instruction.
    """
    if evidence_confidence < 0.5:
        cap = "weak"
    elif evidence_confidence < 0.8:
        cap = "partial"
    else:
        cap = "strong"

    llm_idx = STRENGTH_ORDER.index(llm_strength)
    cap_idx = STRENGTH_ORDER.index(cap)
    return STRENGTH_ORDER[min(llm_idx, cap_idx)]


def call_llm_judge(requirement_text: str, skill_name: str, evidence_note: str) -> dict:
    prompt = f"""A job requires: "{requirement_text}"

The candidate has this skill: "{skill_name}"
Evidence for this skill: "{evidence_note}"

Does this evidence support the requirement? Return ONLY valid JSON, no other text:
{{
  "strength": "none" | "weak" | "partial" | "strong",
  "reasoning": "one sentence explaining your judgment"
}}
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)

    return json.loads(text)


def match_job_to_candidate(job_id: str, candidate_id: str) -> list:
    """
    Runs matching for every requirement of job_id against every skill
    of candidate_id. Saves Match rows. Returns list of match_ids.
    """
    session = get_session()

    requirements = session.query(Requirement).filter_by(job_id=job_id).all()
    skills = session.query(Skill).filter_by(candidate_id=candidate_id).all()

    match_ids = []

    for req in requirements:
        best_match = None  # (strength, confidence, evidence_id, reasoning)

        for skill in skills:
            evidence = session.query(Evidence).filter_by(skill_id=skill.id).first()
            evidence_confidence = evidence.confidence if evidence else 0.3
            evidence_note = evidence.note if evidence else "No supporting evidence, skill only stated."

            # Skip the LLM call entirely when the skill and requirement
            # share literally no words in common - clearly irrelevant
            # pairs (e.g. "Git" vs "REST API design") don't need an LLM
            # judgment call, they're obviously not a match. This is what
            # was cutting the number of LLM calls dramatically - before
            # this fix, EVERY skill got an LLM call for EVERY requirement
            # regardless of relevance, which is why matching was so slow.
            if not has_word_overlap(req.text, skill.name):
                candidate_tuple = ("none", evidence_confidence, evidence.id if evidence else None,
                                    "No lexical overlap between skill and requirement - not evaluated by LLM.")
            else:
                judged = call_llm_judge(req.text, skill.name, evidence_note)
                capped_strength = cap_strength_by_confidence(judged["strength"], evidence_confidence)
                candidate_tuple = (capped_strength, evidence_confidence, evidence.id if evidence else None, judged["reasoning"])

            if best_match is None or STRENGTH_ORDER.index(candidate_tuple[0]) > STRENGTH_ORDER.index(best_match[0]):
                best_match = candidate_tuple

        if best_match is None:
            match = Match(requirement_id=req.id, evidence_id=None, strength="none", confidence=0.0, reasoning="No candidate skills to compare.")
        else:
            strength, confidence, evidence_id, reasoning = best_match
            match = Match(requirement_id=req.id, evidence_id=evidence_id, strength=strength, confidence=confidence, reasoning=reasoning)

        session.add(match)
        session.commit()
        match_ids.append(match.id)

    session.close()
    return match_ids


if __name__ == "__main__":
    # Uses whatever job_id / candidate_id already exist in your database
    # from running job_agent.py and candidate_agent.py earlier.
    session = get_session()
    from models import Job, Candidate

    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py and candidate_agent.py first to create a job and candidate.")
    else:
        print(f"Matching job '{job.title}' against candidate '{candidate.name}'...")
        match_ids = match_job_to_candidate(job.id, candidate.id)

        session = get_session()
        print(f"\nCreated {len(match_ids)} matches:\n")
        for mid in match_ids:
            m = session.query(Match).filter_by(id=mid).first()
            req = session.query(Requirement).filter_by(id=m.requirement_id).first()
            print(f"  [{m.strength.upper()}] {req.text}")
            print(f"      reasoning: {m.reasoning}\n")
        session.close()