"""
CareerPilot - Database Models (Phase 0)

This file is the ACTUAL data model. Every table here matches the schema
we designed. Only the Phase 1 tables are included for now:
Candidate, Skill, Project, Experience, Evidence, Job, Requirement, Match.

We use SQLite to start (zero setup, just a file) - easy to swap for
Postgres later by changing one line in db.py.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Text, DateTime, ForeignKey, Integer, Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def gen_id():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True)
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)  # nullable for old CLI-only data
    name = Column(String, nullable=False)
    email = Column(String)
    phone = Column(String)
    portfolio_url = Column(String)
    links = Column(Text)  # stored as JSON string, e.g. {"github": "...", "linkedin": "..."}
    raw_resume_text = Column(Text)
    career_goals = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    skills = relationship("Skill", back_populates="candidate")
    projects = relationship("Project", back_populates="candidate")
    experiences = relationship("Experience", back_populates="candidate")


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    title = Column(String, nullable=False)
    issuer = Column(String)
    date_earned = Column(String)
    url = Column(String)


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String)  # language / tool / framework / soft-skill
    strength = Column(Float, default=0.0)  # 0-1, computed from evidence
    source = Column(String)  # candidate-stated | inferred-from-project | inferred-from-experience

    candidate = relationship("Candidate", back_populates="skills")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    outcomes = Column(Text)
    repo_url = Column(String)

    candidate = relationship("Candidate", back_populates="projects")


class Experience(Base):
    __tablename__ = "experiences"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    title = Column(String, nullable=False)
    organization = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    description = Column(Text)

    candidate = relationship("Candidate", back_populates="experiences")


class Education(Base):
    __tablename__ = "education"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    institution = Column(String, nullable=False)
    degree = Column(String)
    field = Column(String)
    graduation_date = Column(String)


class Evidence(Base):
    """
    THE most important table. Links a Skill to the Project/Experience
    that proves the candidate actually has it. Nothing downstream should
    trust a skill that has no Evidence row (unless source=candidate-stated).
    """
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    skill_id = Column(String, ForeignKey("skills.id"), nullable=False)
    source_type = Column(String, nullable=False)  # project | experience | education
    source_id = Column(String, nullable=False)     # id of the Project/Experience row
    confidence = Column(Float, default=0.5)         # 0-1, how directly it proves the skill
    note = Column(Text)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    company_name = Column(String)
    company_id = Column(String, ForeignKey("companies.id"), nullable=True)
    title = Column(String)
    url = Column(String)
    raw_description_text = Column(Text)
    seniority = Column(String)  # entry / mid / senior
    created_at = Column(DateTime, default=datetime.utcnow)

    requirements = relationship("Requirement", back_populates="job")


class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(String, primary_key=True, default=gen_id)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    text = Column(String, nullable=False)
    type = Column(String)      # must-have | preferred
    priority = Column(Integer)  # 1-5

    job = relationship("Job", back_populates="requirements")


class Match(Base):
    """
    Output of the Matching Engine. One row per Requirement, pointing to
    the best supporting Evidence (or null if nothing matches).
    strength is capped by the Evidence's own confidence - enforced in
    matching_engine.py, not just trusted from the LLM.
    """
    __tablename__ = "matches"

    id = Column(String, primary_key=True, default=gen_id)
    requirement_id = Column(String, ForeignKey("requirements.id"), nullable=False)
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True)
    strength = Column(String)   # none | weak | partial | strong
    confidence = Column(Float)
    reasoning = Column(Text)


class ResumeVersion(Base):
    """
    One draft of a resume for a specific candidate+job. Never edited in
    place - each critic/optimizer pass creates a NEW row, so you can
    always see v1 -> v2 -> v3 and prove the loop actually improved things.
    """
    __tablename__ = "resume_versions"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    version_number = Column(Integer, default=1)
    content = Column(Text)               # the actual resume text
    critic_notes = Column(Text)          # JSON list of issues found, as text
    quality_score = Column(Integer)      # 0-100
    fact_check_passed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class FactCheckFlag(Base):
    """
    One row per claim in a resume that the Fact Checker looked at.
    status=unsupported means the resume said something no Evidence backs up.
    """
    __tablename__ = "fact_check_flags"

    id = Column(String, primary_key=True, default=gen_id)
    resume_version_id = Column(String, ForeignKey("resume_versions.id"), nullable=False)
    claim_text = Column(Text)
    status = Column(String)   # supported | unsupported


class AgentAssessment(Base):
    """
    One row per (resume_version, assessor). Three assessors judge the
    same resume from different angles: ats, recruiter, hiring_manager.
    """
    __tablename__ = "agent_assessments"

    id = Column(String, primary_key=True, default=gen_id)
    resume_version_id = Column(String, ForeignKey("resume_versions.id"), nullable=False)
    agent_type = Column(String)   # ats | recruiter | hiring_manager
    score = Column(Integer)       # 0-100
    strengths = Column(Text)      # JSON list of strings
    concerns = Column(Text)       # JSON list of strings
    reasoning = Column(Text)


class JudgeDecision(Base):
    """
    Reconciles the three AgentAssessments for one resume version.
    final_recommendation is computed by a RULE (not LLM judgment) for
    stability. disagreement_analysis is LLM-written plain-English
    explanation of why the assessors differed, if they did.
    """
    __tablename__ = "judge_decisions"

    id = Column(String, primary_key=True, default=gen_id)
    resume_version_id = Column(String, ForeignKey("resume_versions.id"), nullable=False)
    assessment_ids = Column(Text)          # JSON list of AgentAssessment ids
    final_recommendation = Column(String)  # e.g. "strong candidate", "borderline", "not a fit"
    disagreement_analysis = Column(Text)
    debate_transcript = Column(Text)       # JSON list of {agent_type, rebuttal}, filled in by debate_agent.py


class Application(Base):
    """
    Phase 4 - tracks a real application: which resume version was
    actually used for which job, and what happened. This is what lets
    you look back later and see your real track record, not just a
    one-off resume generation.
    """
    __tablename__ = "applications"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    resume_version_id = Column(String, ForeignKey("resume_versions.id"), nullable=False)
    status = Column(String, default="drafted")  # drafted | submitted | interviewing | rejected | offer
    submitted_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)


class Company(Base):
    """
    Phase 5 - a researched company. research_confidence reflects how
    much real, source-backed claim data was found - not a vague guess.
    """
    __tablename__ = "companies"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    url = Column(String)
    industry = Column(String)
    research_summary = Column(Text)
    research_confidence = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class CompanyClaim(Base):
    """
    One row per factual claim about a company. source_url MUST point to
    a real search result the agent actually retrieved - enforced in code
    in company_research_agent.py, not just requested in the prompt. This
    is what lets the system answer "why do you think that?" with a real
    link instead of an invented one.
    """
    __tablename__ = "company_claims"

    id = Column(String, primary_key=True, default=gen_id)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    claim_text = Column(Text, nullable=False)
    source_url = Column(String, nullable=False)
    source_title = Column(String)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String, primary_key=True, default=gen_id)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)


class InterviewExchange(Base):
    __tablename__ = "interview_exchanges"

    id = Column(String, primary_key=True, default=gen_id)
    session_id = Column(String, ForeignKey("interview_sessions.id"), nullable=False)
    sequence_number = Column(Integer)
    category = Column(String)  # hr | technical | project | company
    question = Column(Text)
    candidate_answer = Column(Text)
    evaluation_score = Column(Integer)  # 1-5
    evaluation_feedback = Column(Text)
    is_followup = Column(Boolean, default=False)