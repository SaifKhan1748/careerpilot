"""
CareerPilot - Judge Agent (Phase 3, final piece)

Reconciles the three AgentAssessments (ats, recruiter, hiring_manager)
for one resume version.

Design (agreed with the user before building):
- final_recommendation is a RULE, not an LLM guess - same lesson as the
  Critic fix: keep the actual decision deterministic and stable.
- disagreement_analysis is LLM-written prose explaining WHY the three
  assessors differed (or agreed) - the LLM's job here is narrower and
  safer: summarize existing reasoning, not decide the outcome.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import AgentAssessment, JudgeDecision
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def compute_recommendation(scores: dict) -> str:
    """
    Rule-based decision. scores = {"ats": int, "recruiter": int, "hiring_manager": int}
    """
    values = list(scores.values())
    avg = sum(values) / len(values)
    lowest = min(values)
    spread = max(values) - min(values)

    if avg >= 75 and lowest >= 60:
        return "strong candidate"
    elif avg >= 55 and lowest >= 40:
        return "borderline - recommend further review"
    elif spread >= 30:
        return "mixed signals - recommend manual review before deciding"
    else:
        return "not a fit for this role as currently presented"


def write_disagreement_analysis(assessments: list, job_title: str) -> str:
    """
    LLM writes a short explanation of why the assessors agreed/disagreed.
    Does NOT decide the recommendation - only explains the existing scores.
    """
    summary = [
        {"agent": a["agent_type"], "score": a["score"], "reasoning": a["reasoning"]}
        for a in assessments
    ]

    prompt = f"""Three assessors independently scored the same resume for a {job_title} role:

{json.dumps(summary, indent=2)}

Write 2-4 sentences explaining WHY these scores agree or disagree, based on their reasoning.
Do not restate the scores themselves - explain the underlying tension or agreement, e.g. if
the ATS is high but the Hiring Manager is low, explain that this usually means the resume has
the right keywords but lacks depth. Return plain text, no JSON, no markdown.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    return response.choices[0].message.content.strip()


def judge(resume_version_id: str, job_title: str) -> str:
    """
    Reads all AgentAssessment rows for this resume version, computes the
    rule-based recommendation, gets the LLM-written explanation, saves
    a JudgeDecision row. Returns the JudgeDecision id.
    """
    session = get_session()
    assessments = session.query(AgentAssessment).filter_by(resume_version_id=resume_version_id).all()
    session.close()

    if len(assessments) < 3:
        raise ValueError(
            f"Expected 3 assessments (ats, recruiter, hiring_manager), found {len(assessments)}. "
            f"Run ats_agent.py, recruiter_agent.py, and hiring_manager_agent.py on this resume version first."
        )

    scores = {a.agent_type: a.score for a in assessments}
    assessment_dicts = [
        {"agent_type": a.agent_type, "score": a.score, "reasoning": a.reasoning}
        for a in assessments
    ]

    recommendation = compute_recommendation(scores)
    explanation = write_disagreement_analysis(assessment_dicts, job_title)

    session = get_session()
    decision = JudgeDecision(
        resume_version_id=resume_version_id,
        assessment_ids=json.dumps([a.id for a in assessments]),
        final_recommendation=recommendation,
        disagreement_analysis=explanation,
    )
    session.add(decision)
    session.commit()
    decision_id = decision.id
    session.close()

    return decision_id


if __name__ == "__main__":
    from models import Job, Candidate, ResumeVersion
    from agents.run_loop import get_best_resume_id

    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py, candidate_agent.py, matching_engine.py, and run_loop.py first.")
    else:
        resume_id = get_best_resume_id(job.id, candidate.id)

        if not resume_id:
            print("No resume versions found. Run run_loop.py first.")
        else:
            session = get_session()
            existing = session.query(AgentAssessment).filter_by(resume_version_id=resume_id).count()
            session.close()

            if existing < 3:
                print(f"Only {existing}/3 assessments found for this resume version.")
                print("Run these first, in this order:")
                print("  python -m agents.ats_agent")
                print("  python -m agents.recruiter_agent")
                print("  python -m agents.hiring_manager_agent")
            else:
                decision_id = judge(resume_id, job.title)

                session = get_session()
                decision = session.query(JudgeDecision).filter_by(id=decision_id).first()
                assessments = session.query(AgentAssessment).filter_by(resume_version_id=resume_id).all()

                print("Individual scores:")
                for a in assessments:
                    print(f"  {a.agent_type}: {a.score}/100")

                print(f"\nFinal recommendation: {decision.final_recommendation}")
                print(f"\nDisagreement analysis:\n{decision.disagreement_analysis}")
                session.close()