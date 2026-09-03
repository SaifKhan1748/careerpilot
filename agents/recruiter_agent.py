"""
CareerPilot - Recruiter Agent (Phase 3)

Models a human recruiter's first-impression read: clarity, impact,
whether this resume creates interest in the candidate. Unlike the ATS
Agent, this genuinely needs LLM judgment - there's no rubric for
"interesting" or "clear." Temperature kept low (not zero) since this
role is inherently a bit more holistic/subjective than the Critic's
mechanical checks, but we still want reasonably consistent output.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Job, ResumeVersion, AgentAssessment
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def assess(resume_version_id: str, job_id: str, candidate_id: str) -> str:
    session = get_session()
    resume = session.query(ResumeVersion).filter_by(id=resume_version_id).first()
    job = session.query(Job).filter_by(id=job_id).first()
    content = resume.content
    session.close()

    prompt = f"""You are an experienced recruiter reviewing a resume for a {job.title} role.
Give your honest first-impression read - not a technical deep-dive, that's someone else's job.
Focus on: clarity, does it create genuine interest, would you want to screen this candidate,
overall presentation and impact.

Resume:
{content}

Return ONLY valid JSON, no other text:
{{
  "score": 0-100,
  "strengths": ["short specific strength", "..."],
  "concerns": ["short specific concern", "..."],
  "reasoning": "2-3 sentences explaining your overall impression"
}}

Be honest and specific, not generically positive. If the resume is weak, say so and explain why.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)

    result = json.loads(text)

    session = get_session()
    assessment = AgentAssessment(
        resume_version_id=resume_version_id,
        agent_type="recruiter",
        score=result["score"],
        strengths=json.dumps(result["strengths"]),
        concerns=json.dumps(result["concerns"]),
        reasoning=result["reasoning"],
    )
    session.add(assessment)
    session.commit()
    assessment_id = assessment.id
    session.close()

    return assessment_id


if __name__ == "__main__":
    from models import Candidate
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
            print(f"Recruiter score: {a.score}/100")
            print(f"Reasoning: {a.reasoning}")
            print("\nStrengths:")
            for s in json.loads(a.strengths):
                print(f"  + {s}")
            print("\nConcerns:")
            for c in json.loads(a.concerns):
                print(f"  - {c}")
            session.close()