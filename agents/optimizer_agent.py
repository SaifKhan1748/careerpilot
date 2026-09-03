"""
CareerPilot - Optimizer Agent (Phase 2)

Takes a critiqued ResumeVersion + its issues list, produces a NEW,
improved ResumeVersion (v2, v3...) - never overwrites the old one.

Critical rule: the Optimizer gets the SAME evidence-backed facts the
original Resume Agent used, not just the previous resume text. It must
fix what it can using only those facts, and explicitly leave alone any
issue that would require inventing a new skill/fact.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import ResumeVersion
from agents.resume_agent import build_evidence_backed_context, build_header, build_certificates_section
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def extract_body_only(full_content: str) -> str:
    """
    The saved ResumeVersion.content is: header + blank line + body
    + blank line + certificates (optional). We only ever want to feed
    the BODY back to the LLM - never the header or certificates - or
    it starts copying/duplicating those sections into the new body.
    """
    chunks = full_content.split("\n\n")
    if len(chunks) < 2:
        return full_content  # fallback, shouldn't normally happen

    body_chunks = chunks[1:]  # drop header (first chunk)

    # drop trailing certificates chunk if present
    if body_chunks and body_chunks[-1].strip().startswith("Certificates"):
        body_chunks = body_chunks[:-1]

    return "\n\n".join(body_chunks).strip()


def optimize(resume_version_id: str) -> str:
    """
    Reads the given resume version + its critic_notes, produces an
    improved body, saves as a new ResumeVersion row. Returns new id.
    """
    session = get_session()
    old_resume = session.query(ResumeVersion).filter_by(id=resume_version_id).first()
    job_id = old_resume.job_id
    candidate_id = old_resume.candidate_id
    old_content = extract_body_only(old_resume.content)
    issues = json.loads(old_resume.critic_notes) if old_resume.critic_notes else []

    # find the highest version_number so far for this job+candidate, so
    # we always increment, even if versions were created out of order
    existing_versions = session.query(ResumeVersion).filter_by(
        job_id=job_id, candidate_id=candidate_id
    ).all()
    next_version_number = max(v.version_number for v in existing_versions) + 1
    session.close()

    context = build_evidence_backed_context(job_id, candidate_id)

    prompt = f"""Improve this resume draft based on the critique issues below.

Current draft (summary/skills/experience section only):
{old_content}

Critique issues to fix:
{json.dumps(issues, indent=2)}

You may ONLY use these evidence-backed facts - do not invent anything new:
{json.dumps(context['matched_facts'], indent=2)}

The candidate does NOT have evidence for these - never mention them, even if a critique issue suggests it:
{json.dumps(context['gaps'], indent=2)}

Rules:
- Fix writing-quality issues (vague phrasing, repetition, missing structure) freely.
- If an issue mentions repeated/duplicated phrasing, you MUST use different wording for each affected bullet - do not reuse the same 4+ word phrase (like "using Python and Flask") in more than one bullet point.
- If an issue asks for something not supported by the facts above (e.g. "mention cloud experience" when there's no cloud evidence), SKIP that specific fix - do not invent a fact to satisfy it.
- Never add implementation details not in the facts: no testing/logging claims, no performance numbers (latency, throughput), no deployment/CI-CD/versioning claims, no cloud/Docker/Kubernetes mentions, unless they already appear in the project/experience descriptions given. If a FABRICATION issue flags a specific phrase, remove that phrase entirely rather than rephrasing it.
- Never state a specific number of years of experience (e.g. "3+ years") unless that exact figure is given in the facts above.
- Do not include a header with name/contact info - that is added separately.
- Do not include a Certificates or Certifications section - that is added separately, after your output.
- Write plain text, resume-style summary and bullet points.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    new_body = response.choices[0].message.content.strip()

    header = build_header(context)
    certs_section = build_certificates_section(context)
    parts = [header, "", new_body]
    if certs_section:
        parts += ["", certs_section]
    full_content = "\n".join(parts)

    session = get_session()
    new_resume = ResumeVersion(
        candidate_id=candidate_id,
        job_id=job_id,
        version_number=next_version_number,
        content=full_content,
    )
    session.add(new_resume)
    session.commit()
    new_id = new_resume.id
    session.close()

    return new_id


if __name__ == "__main__":
    session = get_session()
    resume = session.query(ResumeVersion).order_by(ResumeVersion.created_at.desc()).first()
    session.close()

    if not resume or not resume.critic_notes:
        print("Run resume_agent.py then critic_agent.py first, so there's a critiqued version to optimize.")
    else:
        print(f"Optimizing version {resume.version_number} (score was {resume.quality_score})...")
        new_id = optimize(resume.id)

        session = get_session()
        new_resume = session.query(ResumeVersion).filter_by(id=new_id).first()
        print(f"\nSaved version {new_resume.version_number}: {new_id}\n")
        print(new_resume.content)
        session.close()