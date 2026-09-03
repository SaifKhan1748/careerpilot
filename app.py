"""
CareerPilot - Web UI (Streamlit)

Reuses every existing agent function directly - no logic duplicated.
Run with: streamlit run app.py

Not included here: interview_agent (needs live terminal input) and
browser_agent (opens its own browser window) - both still work fine
via `python cli.py interview` / `browser`.
"""

import json
import streamlit as st

from db import get_session
from models import (
    Job, Candidate, Requirement, Match, ResumeVersion, AgentAssessment,
    JudgeDecision, Company, CompanyClaim,
)
from agents.job_agent import extract_and_save as save_job
from agents.candidate_agent import extract_and_save as save_candidate
from agents.matching_engine import match_job_to_candidate
from agents.run_loop import run_loop, get_best_resume_id
from agents.ats_agent import assess as ats_assess
from agents.recruiter_agent import assess as recruiter_assess
from agents.hiring_manager_agent import assess as hiring_assess
from agents.judge_agent import judge
from agents.debate_agent import run_debate
from agents.skill_gap_agent import compute_gaps, add_suggestions
from agents.applications import log_application, update_status, list_applications, VALID_STATUSES
from agents.outcome_analytics import analyze
from agents.company_research_agent import research, link_company_to_job

st.set_page_config(page_title="CareerPilot", layout="wide")


def latest_job():
    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    session.close()
    return job


def latest_candidate():
    session = get_session()
    c = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()
    return c


st.sidebar.title("CareerPilot")
page = st.sidebar.radio("Go to", [
    "Dashboard", "Job Intake", "Candidate Intake", "Match & Resume",
    "Assessments", "Skill Gaps", "Applications", "Analytics", "Company Research",
])

job = latest_job()
candidate = latest_candidate()

# ---------------- Dashboard ----------------
if page == "Dashboard":
    st.title("Dashboard")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Current Job")
        st.write(job.title if job else "None yet - go to Job Intake")
    with col2:
        st.subheader("Current Candidate")
        st.write(candidate.name if candidate else "None yet - go to Candidate Intake")

    if job and candidate:
        best_id = get_best_resume_id(job.id, candidate.id)
        if best_id:
            session = get_session()
            r = session.query(ResumeVersion).filter_by(id=best_id).first()
            session.close()
            st.metric("Best resume score", f"{r.quality_score}/100")
            st.metric("Fact check", "PASS" if r.fact_check_passed else "FAIL")

# ---------------- Job Intake ----------------
elif page == "Job Intake":
    st.title("Job Intake")
    company_name = st.text_input("Company name (optional)")
    url = st.text_input("Job URL (optional)")
    text = st.text_area("Paste job description", height=250)
    if st.button("Extract job"):
        with st.spinner("Extracting requirements..."):
            job_id = save_job(text, company_name=company_name or None, url=url or None)
        st.success(f"Saved job: {job_id}")
        st.rerun()

    if job:
        st.subheader(f"Current: {job.title}")
        session = get_session()
        reqs = session.query(Requirement).filter_by(job_id=job.id).all()
        session.close()
        st.table([{"Requirement": r.text, "Type": r.type, "Priority": r.priority} for r in reqs])

# ---------------- Candidate Intake ----------------
elif page == "Candidate Intake":
    st.title("Candidate Intake")
    name = st.text_input("Name")
    email = st.text_input("Email")
    phone = st.text_input("Phone")
    portfolio = st.text_input("Portfolio URL")
    github = st.text_input("GitHub URL")
    linkedin = st.text_input("LinkedIn URL")
    resume_text = st.text_area("Paste resume text", height=250)

    if st.button("Extract candidate"):
        links = {k: v for k, v in {"github": github, "linkedin": linkedin}.items() if v}
        with st.spinner("Extracting skills, projects, education, experience..."):
            cid = save_candidate(name, resume_text, email=email or None, phone=phone or None,
                                  portfolio_url=portfolio or None, links=links or None)
        st.success(f"Saved candidate: {cid}")
        st.rerun()

    if candidate:
        st.subheader(f"Current: {candidate.name}")
        st.write(f"{candidate.email or ''} | {candidate.phone or ''}")

# ---------------- Match & Resume ----------------
elif page == "Match & Resume":
    st.title("Match & Resume")
    if not (job and candidate):
        st.warning("Need a job and candidate first.")
    else:
        if st.button("Run matching engine"):
            with st.spinner("Matching..."):
                match_job_to_candidate(job.id, candidate.id)
            st.success("Matched.")

        if st.button("Run generate -> critique -> optimize loop"):
            with st.spinner("Running loop (this can take a minute)..."):
                summary = run_loop(job.id, candidate.id)
            st.session_state["last_summary"] = summary

        if "last_summary" in st.session_state:
            summary = st.session_state["last_summary"]
            st.table([{"Version": h["version_number"], "Score": h["score"], "Passed": h["passed"]} for h in summary["history"]])
            st.metric("Final score", summary["final_score"])
            st.metric("Fact check", "PASS" if summary["fact_check_passed"] else "FAIL")

        best_id = get_best_resume_id(job.id, candidate.id) if job and candidate else None
        if best_id:
            session = get_session()
            r = session.query(ResumeVersion).filter_by(id=best_id).first()
            session.close()
            st.subheader(f"Best resume (v{r.version_number}, score {r.quality_score})")
            st.text(r.content)

# ---------------- Assessments ----------------
elif page == "Assessments":
    st.title("Assessments")
    if not (job and candidate):
        st.warning("Need a job and candidate first.")
    else:
        best_id = get_best_resume_id(job.id, candidate.id)
        if not best_id:
            st.warning("Run the resume loop first.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Run ATS"):
                with st.spinner("..."): ats_assess(best_id, job.id, candidate.id)
                st.rerun()
            if c2.button("Run Recruiter"):
                with st.spinner("..."): recruiter_assess(best_id, job.id, candidate.id)
                st.rerun()
            if c3.button("Run Hiring Manager"):
                with st.spinner("..."): hiring_assess(best_id, job.id, candidate.id)
                st.rerun()
            if c4.button("Run Judge"):
                with st.spinner("..."): judge(best_id, job.title)
                st.rerun()

            session = get_session()
            assessments = session.query(AgentAssessment).filter_by(resume_version_id=best_id).all()
            decision = session.query(JudgeDecision).filter_by(resume_version_id=best_id).first()
            session.close()

            for a in assessments:
                st.metric(a.agent_type, f"{a.score}/100")
                st.caption(a.reasoning)

            if decision:
                st.subheader(f"Recommendation: {decision.final_recommendation}")
                st.write(decision.disagreement_analysis)

                if st.button("Run debate round"):
                    with st.spinner("Debating..."):
                        run_debate(best_id, job.title)
                    st.rerun()

                if decision.debate_transcript:
                    for t in json.loads(decision.debate_transcript):
                        st.write(f"**{t['agent_type']}**: {t['rebuttal']}")

# ---------------- Skill Gaps ----------------
elif page == "Skill Gaps":
    st.title("Skill Gaps")
    if not job:
        st.warning("Need a job first.")
    elif st.button("Compute gaps"):
        with st.spinner("..."):
            gaps = add_suggestions(compute_gaps(job.id))
        for bucket in ["urgent", "important", "optional"]:
            bucket_gaps = [g for g in gaps if g["urgency"] == bucket]
            if bucket_gaps:
                st.subheader(bucket.upper())
                st.table([{"Requirement": g["requirement"], "Suggestion": g["suggestion"]} for g in bucket_gaps])

# ---------------- Applications ----------------
elif page == "Applications":
    st.title("Applications")
    if job and candidate:
        best_id = get_best_resume_id(job.id, candidate.id)
        if best_id and st.button("Log this resume as an application"):
            log_application(candidate.id, job.id, best_id)
            st.rerun()

    if candidate:
        apps = list_applications(candidate.id)
        for a in apps:
            col1, col2 = st.columns([3, 1])
            col1.write(f"**{a['job_title']}** - {a['status']} (score {a['resume_score']})")
            new_status = col2.selectbox("Update", VALID_STATUSES, index=VALID_STATUSES.index(a["status"]), key=a["application_id"])
            if new_status != a["status"]:
                update_status(a["application_id"], new_status)
                st.rerun()

# ---------------- Analytics ----------------
elif page == "Analytics":
    st.title("Outcome Analytics")
    if candidate:
        stats = analyze(candidate.id)
        st.metric("Total applications", stats["total"])
        if stats["submitted_count"]:
            c1, c2, c3 = st.columns(3)
            c1.metric("Response rate", f"{stats['response_rate']}%")
            c2.metric("Interview rate", f"{stats['interview_rate']}%")
            c3.metric("Offer rate", f"{stats['offer_rate']}%")
        if stats["total"] < 10:
            st.caption(f"Sample size: {stats['total']}. Too small for real patterns - describes what happened, not what to expect.")

# ---------------- Company Research ----------------
elif page == "Company Research":
    st.title("Company Research")
    name = st.text_input("Company name")
    if st.button("Research") and name:
        with st.spinner("Searching the web..."):
            company_id = research(name)
        st.session_state["last_company_id"] = company_id
        if job:
            link_company_to_job(job.id, company_id)
        st.rerun()

    if "last_company_id" in st.session_state:
        session = get_session()
        company = session.query(Company).filter_by(id=st.session_state["last_company_id"]).first()
        claims = session.query(CompanyClaim).filter_by(company_id=company.id).all()
        session.close()

        st.metric("Confidence", company.research_confidence)
        st.write(company.research_summary)
        for c in claims:
            st.write(f"- {c.claim_text}")
            st.caption(c.source_url)