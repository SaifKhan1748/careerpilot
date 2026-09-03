"""
CareerPilot - Outcome Analytics (Phase 6)

Deterministic aggregation over your Application history. No LLM - just
counts and rates. Always prints the sample size prominently and refuses
to imply statistical significance on small samples, per the original
design principle: this is "patterns observed in your data," never a
predictive claim.
"""

from agents.applications import list_applications
from db import get_session
from models import Candidate

RESPONDED_STATUSES = {"interviewing", "rejected", "offer"}
ADVANCED_STATUSES = {"interviewing", "offer"}

MIN_SAMPLE_FOR_ANY_PATTERN_TALK = 10


def analyze(candidate_id: str) -> dict:
    applications = list_applications(candidate_id)
    total = len(applications)

    submitted = [a for a in applications if a["status"] in RESPONDED_STATUSES or a["status"] == "submitted"]
    responded = [a for a in submitted if a["status"] in RESPONDED_STATUSES]
    advanced = [a for a in submitted if a["status"] in ADVANCED_STATUSES]
    offers = [a for a in submitted if a["status"] == "offer"]

    by_status = {}
    for a in applications:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1

    return {
        "total": total,
        "by_status": by_status,
        "submitted_count": len(submitted),
        "response_rate": round(len(responded) / len(submitted) * 100) if submitted else None,
        "interview_rate": round(len(advanced) / len(submitted) * 100) if submitted else None,
        "offer_rate": round(len(offers) / len(submitted) * 100) if submitted else None,
    }


if __name__ == "__main__":
    session = get_session()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not candidate:
        print("Run candidate_agent.py first.")
    else:
        stats = analyze(candidate.id)

        print(f"Total applications logged: {stats['total']}\n")

        if stats["total"] == 0:
            print("No applications yet - run applications.py to log some first.")
        else:
            print("By status:")
            for status, count in stats["by_status"].items():
                print(f"  {status}: {count}")

            print(f"\nOf {stats['submitted_count']} submitted:")
            print(f"  Response rate: {stats['response_rate']}%")
            print(f"  Interview rate: {stats['interview_rate']}%")
            print(f"  Offer rate: {stats['offer_rate']}%")

            print(f"\nSample size: {stats['total']} application(s).")
            if stats["total"] < MIN_SAMPLE_FOR_ANY_PATTERN_TALK:
                print(
                    f"This is too small a sample to draw any real conclusions from "
                    f"(need {MIN_SAMPLE_FOR_ANY_PATTERN_TALK}+ for patterns to mean anything). "
                    f"These numbers describe what happened, not what to expect next."
                )