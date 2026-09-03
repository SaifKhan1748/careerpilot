"""
CareerPilot - Application tracking (Phase 4)

Tracks which resume version was actually used for which job, and what
happened. Three functions:
  log_application()    - record that you're applying (or drafted a resume for) a job
  update_status()       - update it later as things progress (submitted -> interviewing -> offer/rejected)
  list_applications()   - see your full history for a candidate

No LLM calls - this is pure record-keeping, fully deterministic.
"""

from datetime import datetime
from db import get_session
from models import Application, Job, ResumeVersion, Candidate

VALID_STATUSES = ["drafted", "submitted", "interviewing", "rejected", "offer"]


def log_application(candidate_id: str, job_id: str, resume_version_id: str, status: str = "drafted", notes: str = None) -> str:
    """Creates a new Application record. Returns its id."""
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got '{status}'")

    session = get_session()
    application = Application(
        candidate_id=candidate_id,
        job_id=job_id,
        resume_version_id=resume_version_id,
        status=status,
        submitted_at=datetime.utcnow() if status == "submitted" else None,
        notes=notes,
    )
    session.add(application)
    session.commit()
    application_id = application.id
    session.close()

    return application_id


def update_status(application_id: str, new_status: str, notes: str = None) -> None:
    """Updates an existing application's status - e.g. after you hear back."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got '{new_status}'")

    session = get_session()
    application = session.query(Application).filter_by(id=application_id).first()
    if not application:
        session.close()
        raise ValueError(f"No application found with id {application_id}")

    application.status = new_status
    application.updated_at = datetime.utcnow()
    if new_status == "submitted" and not application.submitted_at:
        application.submitted_at = datetime.utcnow()
    if notes:
        application.notes = notes

    session.commit()
    session.close()


def list_applications(candidate_id: str) -> list:
    """
    Returns all applications for a candidate, newest first, with job
    title and resume score joined in for readability.
    """
    session = get_session()
    applications = session.query(Application).filter_by(candidate_id=candidate_id).order_by(Application.updated_at.desc()).all()

    results = []
    for app in applications:
        job = session.query(Job).filter_by(id=app.job_id).first()
        resume = session.query(ResumeVersion).filter_by(id=app.resume_version_id).first()
        results.append({
            "application_id": app.id,
            "job_title": job.title if job else "(unknown job)",
            "status": app.status,
            "resume_score": resume.quality_score if resume else None,
            "fact_check_passed": resume.fact_check_passed if resume else None,
            "submitted_at": app.submitted_at,
            "updated_at": app.updated_at,
            "notes": app.notes,
        })

    session.close()
    return results


if __name__ == "__main__":
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
            # only log a new application if one doesn't already exist for
            # this exact job+resume combo, so re-running this script
            # doesn't create duplicate entries every time
            session = get_session()
            existing = session.query(Application).filter_by(
                candidate_id=candidate.id, job_id=job.id, resume_version_id=resume_id
            ).first()
            session.close()

            if not existing:
                app_id = log_application(candidate.id, job.id, resume_id, status="drafted")
                print(f"Logged new application: {app_id}\n")
            else:
                print(f"Application already logged for this job+resume (id: {existing.id})\n")

            print("Application history:")
            for app in list_applications(candidate.id):
                print(f"  [{app['status'].upper()}] {app['job_title']} - resume score: {app['resume_score']} "
                      f"(fact check: {'PASS' if app['fact_check_passed'] else 'FAIL'})")
                if app["notes"]:
                    print(f"      notes: {app['notes']}")