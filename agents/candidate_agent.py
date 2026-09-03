"""
CareerPilot - Candidate Agent (Phase 2, fixed)

Same as before, PLUS: now actually extracts Education and Experience
from resume text and saves them. Previously these tables existed in
models.py but were never populated - that was the real cause of the
Critic repeatedly flagging "no dates," "no education section," etc.
the Optimizer couldn't fix that by rewording, because the data simply
didn't exist.

- Contact info + certificates: saved directly, no LLM (unchanged).
- Skills + Projects + Evidence: extracted via LLM (unchanged).
- Education + Experience: NOW also extracted via LLM.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Candidate, Skill, Project, Evidence, Certificate, Education, Experience
from agents.groq_utils import call_groq_with_retry

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

MODEL = "openai/gpt-oss-120b"


def call_llm_extract(resume_text: str) -> dict:
    prompt = f"""You are extracting structured info from a resume.

Resume:
{resume_text}

Return ONLY valid JSON, no other text, no markdown fences, in this exact shape:
{{
  "projects": [
    {{"title": "string", "description": "string", "technologies": ["string"], "outcomes": "string"}}
  ],
  "skills": ["string"],
  "education": [
    {{"institution": "string", "degree": "string", "field": "string", "graduation_date": "string"}}
  ],
  "experience": [
    {{"title": "string", "organization": "string", "start_date": "string", "end_date": "string", "description": "string"}}
  ]
}}

Rules:
- "skills" = only skills explicitly stated in the resume.
- "technologies" inside each project = only technologies that project's own description actually mentions.
- "education" = only entries actually present in the resume. If none, return an empty list.
- "experience" = only real work/internship entries actually present in the resume. If none, return an empty list. Do NOT put projects here - projects go in "projects".
- Do not guess or add any information (dates, institutions, technologies) that is not written in the text. If a date or field is missing in the resume, use an empty string "" rather than guessing.
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


def extract_and_save(
    candidate_name: str,
    resume_text: str,
    email: str = None,
    phone: str = None,
    portfolio_url: str = None,
    links: dict = None,
    certificates: list = None,
) -> str:
    """
    Saves everything about a candidate. Returns candidate_id.
    """
    parsed = call_llm_extract(resume_text)

    session = get_session()

    candidate = Candidate(
        name=candidate_name,
        raw_resume_text=resume_text,
        email=email,
        phone=phone,
        portfolio_url=portfolio_url,
        links=json.dumps(links) if links else None,
    )
    session.add(candidate)
    session.commit()
    candidate_id = candidate.id

    # Certificates - saved directly, no LLM
    for cert in (certificates or []):
        session.add(Certificate(
            candidate_id=candidate_id,
            title=cert.get("title"),
            issuer=cert.get("issuer"),
            date_earned=cert.get("date_earned"),
            url=cert.get("url"),
        ))
    session.commit()

    # Education - extracted, saved directly (no evidence-linking needed, these are just facts)
    for edu in parsed.get("education", []):
        session.add(Education(
            candidate_id=candidate_id,
            institution=edu.get("institution", ""),
            degree=edu.get("degree", ""),
            field=edu.get("field", ""),
            graduation_date=edu.get("graduation_date", ""),
        ))
    session.commit()

    # Experience - extracted, saved directly
    for exp in parsed.get("experience", []):
        session.add(Experience(
            candidate_id=candidate_id,
            title=exp.get("title", ""),
            organization=exp.get("organization", ""),
            start_date=exp.get("start_date", ""),
            end_date=exp.get("end_date", ""),
            description=exp.get("description", ""),
        ))
    session.commit()

    # Projects
    project_ids_by_title = {}
    for proj in parsed.get("projects", []):
        project = Project(
            candidate_id=candidate_id,
            title=proj["title"],
            description=proj.get("description", ""),
            outcomes=proj.get("outcomes", ""),
        )
        session.add(project)
        session.commit()
        project_ids_by_title[proj["title"]] = (project.id, proj.get("technologies", []))

    # Skills
    skill_ids_by_name = {}
    all_skill_names = set(parsed.get("skills", []))
    for _, techs in project_ids_by_title.values():
        all_skill_names.update(techs)

    for skill_name in all_skill_names:
        skill = Skill(candidate_id=candidate_id, name=skill_name, source="candidate-stated")
        session.add(skill)
        session.commit()
        skill_ids_by_name[skill_name] = skill.id

    # Evidence
    for project_id, techs in project_ids_by_title.values():
        for tech in techs:
            skill_id = skill_ids_by_name.get(tech)
            if not skill_id:
                continue
            session.add(Evidence(
                candidate_id=candidate_id,
                skill_id=skill_id,
                source_type="project",
                source_id=project_id,
                confidence=0.8,
                note="Mentioned as a technology in project",
            ))
            skill = session.query(Skill).filter_by(id=skill_id).first()
            skill.source = "inferred-from-project"
            skill.strength = min(1.0, skill.strength + 0.5)

    session.commit()
    session.close()

    return candidate_id


if __name__ == "__main__":
    sample_resume = """
    Saif Khan
    Skills: Python, SQL, Git

    Education:
    B.Tech in Computer Science, XYZ University, graduated 2025

    Experience:
    Data Science Intern, TechCorp, June 2024 - August 2024
    Assisted in building and evaluating machine learning models for a
    customer churn prediction project. Cleaned and analyzed datasets
    using Python and SQL.

    Projects:
    RAG Teaching Assistant - Built a chatbot using Python and Flask that
    answers student questions using retrieval-augmented generation.
    Used by 50 students in a class pilot.

    Attendance System - A MySQL-based system to track student attendance
    using Python.
    """

    candidate_id = extract_and_save(
        candidate_name="Saif Khan",
        resume_text=sample_resume,
        email="saif@example.com",
        phone="+91 9876543210",
        portfolio_url="https://saifkhan.dev",
        links={"github": "https://github.com/saifkhan", "linkedin": "https://linkedin.com/in/saifkhan"},
        certificates=[{"title": "AWS Cloud Practitioner", "issuer": "Amazon", "date_earned": "2025"}],
    )
    print(f"Saved candidate with id: {candidate_id}")

    session = get_session()

    print("\nEducation:")
    for e in session.query(Education).filter_by(candidate_id=candidate_id):
        print(f"  {e.degree} in {e.field}, {e.institution} ({e.graduation_date})")

    print("\nExperience:")
    for e in session.query(Experience).filter_by(candidate_id=candidate_id):
        print(f"  {e.title} at {e.organization} ({e.start_date} - {e.end_date})")
        print(f"    {e.description}")

    print("\nSkills:")
    for s in session.query(Skill).filter_by(candidate_id=candidate_id):
        print(f"  {s.name}  strength={s.strength:.2f}  source={s.source}")

    session.close()