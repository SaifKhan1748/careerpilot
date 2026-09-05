"""
CareerPilot web backend. Run: uvicorn main:app --reload
"""

from fastapi import FastAPI, Depends, HTTPException, Header, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from jose import JWTError
import json
import io
import os
from pypdf import PdfReader

from db import get_session, init_db
from models import (
    User, Candidate, Job, Requirement, Match, ResumeVersion,
    AgentAssessment, JudgeDecision, Company, CompanyClaim,
    InterviewSession, InterviewExchange,
)
from auth import hash_password, verify_password, create_token, decode_token
from email_utils import send_email
import secrets
import datetime
from agents.job_agent import extract_and_save as save_job
from agents.candidate_agent import extract_and_save as save_candidate
from agents.matching_engine import match_job_to_candidate
from agents.run_loop import run_loop, get_best_resume_id
from agents.ats_agent import assess as ats_assess
from agents.recruiter_agent import assess as recruiter_assess
from agents.hiring_manager_agent import assess as hiring_assess
from agents.judge_agent import judge as run_judge
from agents.debate_agent import run_debate
from agents.skill_gap_agent import compute_gaps, add_suggestions
from agents.applications import log_application, update_status, list_applications, VALID_STATUSES
from agents.outcome_analytics import analyze
from agents.company_research_agent import research as research_company, link_company_to_job
from agents.job_discovery_agent import discover
from agents.interview_agent import generate_questions, evaluate_answer
from agents.voice_utils import transcribe_audio_file

from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI()

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.on_event("startup")
def create_tables_on_startup():
    """
    Creates any missing tables automatically. Safe to run on every
    startup - it only creates tables that don't already exist, never
    touches existing data. This means deployment never needs manual
    Shell access (which isn't available on Render's free tier anyway).
    """
    init_db()


@app.exception_handler(Exception)
async def surface_real_errors(request: Request, exc: Exception):
    """
    Without this, an unhandled error (e.g. a Groq API issue) returns a
    generic 500 that the frontend can't extract a message from, so it
    falls back to a vague "Request failed." This puts the REAL error
    text in the response so it's actually visible and debuggable.
    """
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

from fastapi.responses import FileResponse

@app.exception_handler(404)
async def custom_404(request, exc):
    return FileResponse("static/404.html", status_code=404)

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


def get_current_user(authorization: str = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        user_id = decode_token(token)
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

    session = get_session()
    user = session.query(User).filter_by(id=user_id).first()
    session.close()
    if not user:
        raise HTTPException(401, "User not found")
    return user


@app.post("/api/signup")
def signup(req: SignupRequest):
    session = get_session()
    if session.query(User).filter_by(email=req.email).first():
        session.close()
        raise HTTPException(400, "Email already registered")

    verification_token = secrets.token_urlsafe(32)
    user = User(email=req.email, phone=req.phone, name=req.name,
                password_hash=hash_password(req.password), verification_token=verification_token)
    session.add(user)
    session.commit()
    user_id = user.id
    session.close()

    send_email(req.email, "Verify your CareerPilot account",
               f"Welcome to CareerPilot!\n\nVerify your email: {os.environ.get('APP_URL', 'http://localhost:8000')}/verify.html?token={verification_token}")

    return {"token": create_token(user_id), "name": req.name}


@app.get("/api/verify-email")
def verify_email(token: str):
    session = get_session()
    user = session.query(User).filter_by(verification_token=token).first()
    if not user:
        session.close()
        raise HTTPException(400, "Invalid or expired verification link.")
    user.email_verified = True
    user.verification_token = None
    session.commit()
    session.close()
    return {"status": "verified"}


class ForgotPasswordRequest(BaseModel):
    email: str


@app.post("/api/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    session = get_session()
    user = session.query(User).filter_by(email=req.email).first()
    if user:
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        session.commit()
        send_email(req.email, "Reset your CareerPilot password",
                   f"Reset your password: {os.environ.get('APP_URL', 'http://localhost:8000')}/reset-password.html?token={reset_token}\n\nThis link expires in 1 hour.")
    session.close()
    # Always return the same response whether or not the email exists -
    # prevents leaking which emails are registered.
    return {"status": "if that email is registered, a reset link was sent"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@app.post("/api/reset-password")
def reset_password(req: ResetPasswordRequest):
    session = get_session()
    user = session.query(User).filter_by(reset_token=req.token).first()

    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.datetime.utcnow():
        session.close()
        raise HTTPException(400, "Invalid or expired reset link. Request a new one.")

    user.password_hash = hash_password(req.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    session.commit()
    session.close()
    return {"status": "password reset - log in with your new password"}


@app.post("/api/login")
def login(req: LoginRequest):
    session = get_session()
    user = session.query(User).filter_by(email=req.email).first()
    session.close()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")

    return {"token": create_token(user.id), "name": user.name}


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    session = get_session()
    candidate = session.query(Candidate).filter_by(user_id=user.id).first()
    session.close()
    return {
        "email": user.email,
        "name": user.name,
        "has_candidate_profile": candidate is not None,
    }


def get_user_candidate(user_id: str):
    session = get_session()
    c = session.query(Candidate).filter_by(user_id=user_id).order_by(Candidate.created_at.desc()).first()
    session.close()
    return c


def get_user_job(user_id: str):
    session = get_session()
    j = session.query(Job).filter_by(user_id=user_id).order_by(Job.created_at.desc()).first()
    session.close()
    return j


def require_candidate_and_job(user: User):
    candidate = get_user_candidate(user.id)
    job = get_user_job(user.id)
    if not candidate:
        raise HTTPException(400, "No candidate profile yet - submit your resume first.")
    if not job:
        raise HTTPException(400, "No job posting yet - submit one first.")
    return candidate, job


# ---------------- Job ----------------

class JobRequest(BaseModel):
    text: str
    company_name: Optional[str] = None
    url: Optional[str] = None


@app.post("/api/job")
def api_job(req: JobRequest, user: User = Depends(get_current_user)):
    job_id = save_job(req.text, company_name=req.company_name, url=req.url)
    session = get_session()
    job = session.query(Job).filter_by(id=job_id).first()
    job.user_id = user.id
    session.commit()
    title = job.title
    reqs = session.query(Requirement).filter_by(job_id=job_id).all()
    result = {"job_id": job_id, "title": title,
              "requirements": [{"text": r.text, "type": r.type, "priority": r.priority} for r in reqs]}
    session.close()
    return result


# ---------------- Candidate ----------------

@app.post("/api/extract-pdf-text")
def api_extract_pdf_text(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    try:
        reader = PdfReader(io.BytesIO(file.file.read()))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as e:
        raise HTTPException(400, f"Couldn't read this PDF: {e}")

    if not text:
        raise HTTPException(
            400,
            "No text found in this PDF. It may be a scanned image rather than "
            "real text - try a PDF exported directly from Word/Google Docs instead."
        )

    return {"text": text}


class CandidateRequest(BaseModel):
    name: str
    resume_text: str
    email: Optional[str] = None
    phone: Optional[str] = None
    portfolio_url: Optional[str] = None
    links: Optional[dict] = None


@app.post("/api/candidate")
def api_candidate(req: CandidateRequest, user: User = Depends(get_current_user)):
    cid = save_candidate(req.name, req.resume_text, email=req.email, phone=req.phone,
                          portfolio_url=req.portfolio_url, links=req.links)
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=cid).first()
    candidate.user_id = user.id
    session.commit()
    session.close()
    return {"candidate_id": cid, "name": req.name}


# ---------------- Match + Resume loop ----------------

@app.post("/api/match")
def api_match(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    match_job_to_candidate(job.id, candidate.id)
    return {"status": "matched"}


@app.post("/api/loop")
def api_loop(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    summary = run_loop(job.id, candidate.id)
    return summary


@app.get("/api/resume")
def api_resume(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    if not best_id:
        raise HTTPException(400, "No resume generated yet - run the loop first.")
    session = get_session()
    r = session.query(ResumeVersion).filter_by(id=best_id).first()
    result = {"resume_id": r.id, "version": r.version_number, "content": r.content,
               "score": r.quality_score, "fact_check_passed": r.fact_check_passed}
    session.close()
    return result


# ---------------- Assessments ----------------

@app.post("/api/assess/{assessor_type}")
def api_assess(assessor_type: str, user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    if not best_id:
        raise HTTPException(400, "No resume yet.")

    fn = {"ats": ats_assess, "recruiter": recruiter_assess, "hiring": hiring_assess}.get(assessor_type)
    if not fn:
        raise HTTPException(404, "Unknown assessor type")
    fn(best_id, job.id, candidate.id)
    return {"status": "assessed"}


@app.get("/api/assessments")
def api_get_assessments(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    session = get_session()
    assessments = session.query(AgentAssessment).filter_by(resume_version_id=best_id).all()
    decision = session.query(JudgeDecision).filter_by(resume_version_id=best_id).first()
    result = {
        "assessments": [{"agent_type": a.agent_type, "score": a.score, "reasoning": a.reasoning} for a in assessments],
        "recommendation": decision.final_recommendation if decision else None,
        "disagreement_analysis": decision.disagreement_analysis if decision else None,
        "debate_transcript": json.loads(decision.debate_transcript) if decision and decision.debate_transcript else None,
    }
    session.close()
    return result


@app.post("/api/judge")
def api_judge(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    run_judge(best_id, job.title)
    return {"status": "judged"}


@app.post("/api/debate")
def api_debate(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    run_debate(best_id, job.title)
    return {"status": "debated"}


# ---------------- Skill gaps ----------------

@app.get("/api/gaps")
def api_gaps(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    gaps = add_suggestions(compute_gaps(job.id))
    return {"gaps": gaps}


# ---------------- Applications ----------------

@app.post("/api/applications")
def api_log_application(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)
    best_id = get_best_resume_id(job.id, candidate.id)
    if not best_id:
        raise HTTPException(400, "No resume yet.")
    app_id = log_application(candidate.id, job.id, best_id)
    return {"application_id": app_id}


@app.get("/api/applications")
def api_list_applications(user: User = Depends(get_current_user)):
    candidate = get_user_candidate(user.id)
    if not candidate:
        return {"applications": []}
    return {"applications": list_applications(candidate.id), "valid_statuses": VALID_STATUSES}


class StatusUpdate(BaseModel):
    status: str


@app.patch("/api/applications/{application_id}")
def api_update_application(application_id: str, req: StatusUpdate, user: User = Depends(get_current_user)):
    update_status(application_id, req.status)
    return {"status": "updated"}


# ---------------- Analytics ----------------

@app.get("/api/analytics")
def api_analytics(user: User = Depends(get_current_user)):
    candidate = get_user_candidate(user.id)
    if not candidate:
        raise HTTPException(400, "No candidate profile yet.")
    return analyze(candidate.id)


# ---------------- Company research ----------------

class ResearchRequest(BaseModel):
    company_name: str


@app.post("/api/research")
def api_research(req: ResearchRequest, user: User = Depends(get_current_user)):
    company_id = research_company(req.company_name)
    job = get_user_job(user.id)
    if job:
        link_company_to_job(job.id, company_id)

    session = get_session()
    company = session.query(Company).filter_by(id=company_id).first()
    claims = session.query(CompanyClaim).filter_by(company_id=company_id).all()
    result = {
        "confidence": company.research_confidence,
        "summary": company.research_summary,
        "claims": [{"text": c.claim_text, "url": c.source_url} for c in claims],
    }
    session.close()
    return result


class DiscoverRequest(BaseModel):
    query: str


@app.post("/api/discover")
def api_discover(req: DiscoverRequest, user: User = Depends(get_current_user)):
    candidate = get_user_candidate(user.id)
    if not candidate:
        raise HTTPException(400, "No candidate profile yet.")
    return {"results": discover(req.query, candidate.id)}


# ---------------- Interview (stateful, in-memory per session) ----------------
# Note: interview state lives in process memory, not the DB - simplest
# approach for a single dev server. Restarting the server loses any
# in-progress interview (already-saved InterviewExchange rows are safe).

_interview_state = {}


class InterviewAnswerRequest(BaseModel):
    session_id: str
    answer: str


def _next_question_response(session_id: str) -> dict:
    state = _interview_state[session_id]
    if state["index"] >= len(state["questions"]):
        return {"done": True}
    q = state["questions"][state["index"]]
    return {"done": False, "category": q["category"], "question": q["question"], "is_followup": False}


@app.post("/api/interview/start")
def api_interview_start(user: User = Depends(get_current_user)):
    candidate, job = require_candidate_and_job(user)

    session = get_session()
    interview = InterviewSession(candidate_id=candidate.id, job_id=job.id)
    session.add(interview)
    session.commit()
    session_id = interview.id
    session.close()

    questions = generate_questions(job.id, candidate.id)
    _interview_state[session_id] = {"questions": questions, "index": 0, "pending_followup": None, "scores": []}

    resp = _next_question_response(session_id)
    resp["session_id"] = session_id
    return resp


def _process_answer(session_id: str, answer_text: str) -> dict:
    if session_id not in _interview_state:
        raise HTTPException(400, "Interview session not found - start a new one.")
    state = _interview_state[session_id]

    if state["pending_followup"]:
        question_text = state["pending_followup"]
        is_followup = True
        state["pending_followup"] = None
    else:
        q = state["questions"][state["index"]]
        question_text = q["question"]
        is_followup = False

    eval_result = evaluate_answer(question_text, answer_text)
    state["scores"].append(eval_result["score"])

    session = get_session()
    session.add(InterviewExchange(
        session_id=session_id, sequence_number=len(state["scores"]),
        category="followup" if is_followup else state["questions"][state["index"]]["category"],
        question=question_text, candidate_answer=answer_text,
        evaluation_score=eval_result["score"], evaluation_feedback=eval_result["feedback"],
        is_followup=is_followup,
    ))
    session.commit()
    session.close()

    result = {"score": eval_result["score"], "feedback": eval_result["feedback"]}

    if not is_followup and eval_result.get("needs_followup") and eval_result.get("followup_question"):
        state["pending_followup"] = eval_result["followup_question"]
        result.update({"done": False, "next_is_followup": True, "next_question": eval_result["followup_question"]})
        return result

    state["index"] += 1
    if state["index"] >= len(state["questions"]):
        avg = sum(state["scores"]) / len(state["scores"]) if state["scores"] else 0
        result.update({"done": True, "average_score": round(avg, 1)})
        del _interview_state[session_id]
    else:
        nxt = state["questions"][state["index"]]
        result.update({"done": False, "next_is_followup": False, "next_question": nxt["question"], "next_category": nxt["category"]})

    return result


@app.post("/api/interview/answer")
def api_interview_answer(req: InterviewAnswerRequest, user: User = Depends(get_current_user)):
    return _process_answer(req.session_id, req.answer)


@app.post("/api/interview/answer-voice")
def api_interview_answer_voice(session_id: str, file: UploadFile = File(...), user: User = Depends(get_current_user)):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    try:
        text = transcribe_audio_file(tmp_path)
    finally:
        os.remove(tmp_path)
    result = _process_answer(session_id, text)
    result["transcribed_text"] = text
    return result


# Browser Autofill (backend endpoint) intentionally removed - it opens
# a real Chrome window "on this machine," which only makes sense for a
# single local user (still works via `python cli.py browser`). On a
# deployed server, "this machine" is Render's headless container with
# no display - the window would never be visible to any actual user.


app.mount("/", StaticFiles(directory="static", html=True), name="static")