"""
CareerPilot - Interview Agent (Phase 6)

Runs a text-based mock interview: generates questions from REAL facts
(matched skills, real projects, real experience, real company research
if available), asks them one at a time in the terminal, evaluates each
answer, and asks ONE adaptive follow-up if the answer was weak/thin.
Ends with a summary.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from db import get_session
from models import Job, Candidate, InterviewSession, InterviewExchange
from agents.resume_agent import build_evidence_backed_context
from agents.groq_utils import call_groq_with_retry
from agents.voice_utils import speak, transcribe_audio_file, record_live_answer

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def generate_questions(job_id: str, candidate_id: str) -> list:
    """
    Generates up to 5 grounded questions: HR, technical, 2x project
    deep-dive, and company-fit (only if company research exists).
    """
    context = build_evidence_backed_context(job_id, candidate_id)

    prompt = f"""Generate mock interview questions for a {context['job_title']} role, based ONLY on these real facts:

Matched skills/requirements: {json.dumps(context['matched_facts'], indent=2)}
Real projects/experience: {json.dumps(context['experience_facts'], indent=2)}
Company culture signals (may be empty): {json.dumps(context['company_culture_hints'], indent=2)}
Skill gaps (things the candidate does NOT have evidence for): {json.dumps(context['gaps'], indent=2)}

Return ONLY valid JSON, no other text:
{{
  "questions": [
    {{"category": "hr", "question": "..."}},
    {{"category": "technical", "question": "..."}},
    {{"category": "project", "question": "... (about one of the real projects above)"}},
    {{"category": "project", "question": "... (about the other real project or experience)"}},
    {{"category": "company", "question": "... (only if company hints are non-empty, else make this a general fit question)"}}
  ]
}}

Rules:
- Base technical/project questions on the REAL facts given - don't invent scenarios about tools the candidate never used.
- It's fine to ask about a gap (e.g. "you don't have AWS experience - how would you approach learning it?") - that's honest, not fabrication.
- Keep questions realistic and specific, not generic ("tell me about yourself" is too vague - ask something a real interviewer would ask this specific candidate).
"""

    response = call_groq_with_retry(
        client, model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json\n", "", 1)

    return json.loads(text)["questions"]


def evaluate_answer(question: str, answer: str) -> dict:
    """Scores an answer 1-5, gives brief feedback, decides if a follow-up is warranted."""
    prompt = f"""Question asked: {question}
Candidate's answer: {answer}

Return ONLY valid JSON, no other text:
{{
  "score": 1-5,
  "feedback": "1-2 sentences, specific and honest",
  "needs_followup": true/false,
  "followup_question": "only if needs_followup is true - a natural follow-up probing deeper or asking for the missing detail"
}}

Score 1 = very weak/evasive, 5 = strong, specific, complete. needs_followup = true if the answer was vague, incomplete, or dodged the question.
"""

    response = call_groq_with_retry(
        client, model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json\n", "", 1)

    return json.loads(text)


def get_answer_input() -> str:
    """
    'voice' = live mic recording (press Enter to start/stop, transcribed).
    'voice:PATH' = transcribe a pre-recorded file instead.
    Anything else = typed text. 'skip' = skip this question.
    """
    raw = input("> ").strip()

    if raw.lower() == "voice":
        try:
            text = record_live_answer()
            print(f'   (transcribed: "{text}")')
            return text
        except Exception as e:
            print(f"   Live recording failed ({e}). Type your answer instead:")
            return input("> ").strip()

    if raw.lower().startswith("voice:"):
        audio_path = raw[len("voice:"):].strip()
        try:
            text = transcribe_audio_file(audio_path)
            print(f'   (transcribed: "{text}")')
            return text
        except Exception as e:
            print(f"   Couldn't transcribe that file ({e}). Type your answer instead:")
            return input("> ").strip()

    return raw


def run_interview(job_id: str, candidate_id: str) -> str:
    """
    Runs the full interactive interview in the terminal. Returns the
    InterviewSession id.
    """
    session = get_session()
    interview = InterviewSession(candidate_id=candidate_id, job_id=job_id)
    session.add(interview)
    session.commit()
    session_id = interview.id
    session.close()

    questions = generate_questions(job_id, candidate_id)
    seq = 1
    scores = []

    print("\n--- Mock Interview ---")
    print("Type your answer, type 'voice' to record live, or 'skip' to skip.\n")

    for q in questions:
        print(f"[{q['category'].upper()}] {q['question']}")
        speak(q["question"])
        answer = get_answer_input()
        if answer.lower() == "skip":
            continue

        eval_result = evaluate_answer(q["question"], answer)
        scores.append(eval_result["score"])
        print(f"   (score: {eval_result['score']}/5 - {eval_result['feedback']})\n")

        session = get_session()
        session.add(InterviewExchange(
            session_id=session_id, sequence_number=seq, category=q["category"],
            question=q["question"], candidate_answer=answer,
            evaluation_score=eval_result["score"], evaluation_feedback=eval_result["feedback"],
            is_followup=False,
        ))
        session.commit()
        session.close()
        seq += 1

        if eval_result.get("needs_followup") and eval_result.get("followup_question"):
            print(f"[FOLLOW-UP] {eval_result['followup_question']}")
            speak(eval_result["followup_question"])
            followup_answer = get_answer_input()
            if followup_answer.lower() != "skip":
                followup_eval = evaluate_answer(eval_result["followup_question"], followup_answer)
                scores.append(followup_eval["score"])
                print(f"   (score: {followup_eval['score']}/5 - {followup_eval['feedback']})\n")

                session = get_session()
                session.add(InterviewExchange(
                    session_id=session_id, sequence_number=seq, category=q["category"],
                    question=eval_result["followup_question"], candidate_answer=followup_answer,
                    evaluation_score=followup_eval["score"], evaluation_feedback=followup_eval["feedback"],
                    is_followup=True,
                ))
                session.commit()
                session.close()
                seq += 1

    session = get_session()
    interview = session.query(InterviewSession).filter_by(id=session_id).first()
    from datetime import datetime
    interview.ended_at = datetime.utcnow()
    session.commit()
    session.close()

    if scores:
        avg = sum(scores) / len(scores)
        print(f"--- Interview complete. Average score: {avg:.1f}/5 across {len(scores)} answers. ---")
    else:
        print("--- Interview ended with no answers recorded. ---")

    return session_id


if __name__ == "__main__":
    from agents.run_loop import get_best_resume_id

    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py, candidate_agent.py, and matching_engine.py first.")
    else:
        run_interview(job.id, candidate.id)