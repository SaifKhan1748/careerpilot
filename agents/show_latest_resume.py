"""
CareerPilot - shows the ACTUAL best resume version for the most recent
job+candidate pair - not just whatever was created last. Uses the same
selection rule as run_loop.py: a version that fails the fact check can
never be shown as if it were the winner.
"""

from db import get_session
from models import Job, Candidate, ResumeVersion
from agents.run_loop import get_best_resume_id

session = get_session()
job = session.query(Job).order_by(Job.created_at.desc()).first()
candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
session.close()

if not job or not candidate:
    print("No job/candidate found. Run the earlier agents first.")
else:
    best_id = get_best_resume_id(job.id, candidate.id)

    if not best_id:
        print("No resume versions found for this job/candidate. Run run_loop.py first.")
    else:
        session = get_session()
        resume = session.query(ResumeVersion).filter_by(id=best_id).first()
        session.close()

        print(f"Showing version {resume.version_number} (id: {resume.id})")
        print(f"Quality score: {resume.quality_score} | Fact check passed: {resume.fact_check_passed}")
        if not resume.fact_check_passed:
            print("WARNING: no version passed the fact check - this is a fallback, review before using.")
        print()
        print(resume.content)