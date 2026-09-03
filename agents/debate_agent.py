"""
CareerPilot - Debate Agent (Phase 6)

Runs AFTER ats_agent.py, recruiter_agent.py, hiring_manager_agent.py,
and judge_agent.py have already run for a resume version. Each of the
3 assessors sees the OTHER two's score and reasoning, then writes one
brief rebuttal: do they agree, disagree, and would they change their
score. One LLM call per assessor - no multi-round spiral.
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


def get_rebuttal(agent_type: str, own: dict, others: list, job_title: str) -> dict:
    prompt = f"""You are the {agent_type} assessor reviewing a resume for a {job_title} role.
You already gave this assessment:
  Score: {own['score']}/100
  Reasoning: {own['reasoning']}

The other two assessors gave:
{json.dumps(others, indent=2)}

Write a brief rebuttal (2-3 sentences): do you agree or disagree with them, and why? Would you
change your score based on their point of view? Be direct - defend your view if you think it's
right, or concede if their point is genuinely stronger.

Return ONLY valid JSON, no other text:
{{"rebuttal": "...", "would_change_score": true/false, "new_score": integer or null}}
"""

    response = call_groq_with_retry(
        client, model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json\n", "", 1)

    return json.loads(text)


def run_debate(resume_version_id: str, job_title: str) -> list:
    """
    Runs one rebuttal round for all 3 assessors. Saves the transcript
    onto the existing JudgeDecision row for this resume version.
    Returns the transcript list.
    """
    session = get_session()
    assessments = session.query(AgentAssessment).filter_by(resume_version_id=resume_version_id).all()
    decision = session.query(JudgeDecision).filter_by(resume_version_id=resume_version_id).first()
    session.close()

    if len(assessments) < 3:
        raise ValueError("Need all 3 assessments first - run ats_agent.py, recruiter_agent.py, hiring_manager_agent.py.")
    if not decision:
        raise ValueError("Run judge_agent.py first - debate builds on an existing JudgeDecision.")

    by_type = {a.agent_type: {"score": a.score, "reasoning": a.reasoning} for a in assessments}

    transcript = []
    for agent_type, own in by_type.items():
        others = [{"agent": t, "score": d["score"], "reasoning": d["reasoning"]} for t, d in by_type.items() if t != agent_type]
        rebuttal = get_rebuttal(agent_type, own, others, job_title)
        transcript.append({"agent_type": agent_type, **rebuttal})

    session = get_session()
    decision = session.query(JudgeDecision).filter_by(resume_version_id=resume_version_id).first()
    decision.debate_transcript = json.dumps(transcript)
    session.commit()
    session.close()

    return transcript


if __name__ == "__main__":
    from models import Job, Candidate
    from agents.run_loop import get_best_resume_id

    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run the earlier agents first.")
    else:
        resume_id = get_best_resume_id(job.id, candidate.id)
        try:
            transcript = run_debate(resume_id, job.title)
            print("Debate:\n")
            for t in transcript:
                print(f"[{t['agent_type'].upper()}] {t['rebuttal']}")
                if t["would_change_score"]:
                    print(f"   -> would revise score to {t['new_score']}")
                print()
        except ValueError as e:
            print(str(e))