"""
CareerPilot - Job Agent (Phase 1)

Takes a raw job description, asks the LLM to extract structured
requirements, and SAVES them into the database as Job + Requirement rows.

Uses Groq (free) instead of a paid API.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Job, Requirement
from agents.groq_utils import call_groq_with_retry

load_dotenv()  # reads .env file in this folder

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

MODEL = "openai/gpt-oss-120b"


def call_llm_extract(job_description: str) -> dict:
    """Ask the LLM to turn raw text into structured JSON. Returns a dict."""

    prompt = f"""You are extracting structured requirements from a job posting.

Job posting:
{job_description}

Return ONLY valid JSON, no other text, no markdown fences, in this exact shape:
{{
  "title": "string",
  "seniority": "entry" | "mid" | "senior",
  "requirements": [
    {{"text": "string", "type": "must-have" | "preferred", "priority": 1-5}}
  ]
}}

Rules:
- Each requirement should be ONE skill or qualification, not bundled ("Python and SQL" = two entries).
- Do not add requirements that are not in the text.
- priority 5 = most important, 1 = least important.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = response.choices[0].message.content.strip()

    # Safety net in case the model adds ```json fences anyway
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)

    return json.loads(text)


def extract_and_save(job_description: str, company_name: str = None, url: str = None) -> str:
    """
    Runs the LLM extraction, then writes Job + Requirement rows to the DB.
    Returns the new job_id (as a plain string, safe to use after the
    session closes).
    """
    parsed = call_llm_extract(job_description)

    session = get_session()

    job = Job(
        company_name=company_name,
        title=parsed.get("title"),
        url=url,
        raw_description_text=job_description,
        seniority=parsed.get("seniority"),
    )
    session.add(job)
    session.commit()  # commit now so job.id exists

    # Grab the id into a plain variable NOW, while the object is still
    # attached to the session. Reading job.id after session.close() can
    # raise DetachedInstanceError, so we never touch job.id after this line.
    job_id = job.id

    for req in parsed.get("requirements", []):
        requirement = Requirement(
            job_id=job_id,
            text=req["text"],
            type=req["type"],
            priority=req.get("priority", 3),
        )
        session.add(requirement)

    session.commit()
    session.close()

    return job_id


if __name__ == "__main__":
    sample_job = """
    We are looking for a Data Scientist to join our team.
    Required: Python, SQL, 2+ years experience with machine learning.
    Preferred: experience with AWS and Docker.
    You will build models, analyze data, and deploy them to production.
    """

    job_id = extract_and_save(sample_job, company_name="Acme Corp")
    print(f"Saved job with id: {job_id}")

    # Open a FRESH session to read it back - this proves the data is
    # really persisted, not just held in memory from the same session.
    session = get_session()
    job = session.query(Job).filter_by(id=job_id).first()

    print(f"\nTitle: {job.title} | Seniority: {job.seniority}")
    print("Requirements:")
    for r in job.requirements:
        print(f"  [{r.type}] priority={r.priority}  {r.text}")

    session.close()
