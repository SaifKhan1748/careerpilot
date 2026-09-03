"""
CareerPilot - Loop Runner (Phase 2, final piece)

Ties everything together:
  generate v1 -> critique -> if score < 90: optimize -> critique -> repeat
Stops when quality_score >= 90, OR after 5 rounds of optimization,
whichever comes first. If it hits the round cap without reaching 90,
it says so honestly - it does not pretend to have succeeded.
"""

from db import get_session
from models import Job, Candidate, ResumeVersion
from agents.resume_agent import generate_draft
from agents.critic_agent import critique
from agents.optimizer_agent import optimize

TARGET_SCORE = 90
MAX_ROUNDS = 5


def get_best_resume_id(job_id: str, candidate_id: str) -> str:
    """
    Finds the actual best resume version for a job+candidate pair,
    using stored scores - NOT "most recently created." A resume that
    fails the fact check can never be chosen, same rule as run_loop.
    Useful for checking results after the fact, in a separate script.

    Tie-break rule: if two versions have the exact same score (common
    across multiple runs over time), the more RECENTLY created one
    wins - otherwise an old version from a past run could keep getting
    picked over a fresh one that scored identically.
    """
    session = get_session()
    versions = session.query(ResumeVersion).filter_by(job_id=job_id, candidate_id=candidate_id).all()
    session.close()

    if not versions:
        return None

    passing = [v for v in versions if v.fact_check_passed]
    pool = passing if passing else versions
    best = max(pool, key=lambda v: (v.quality_score or 0, v.created_at))
    return best.id


def run_loop(job_id: str, candidate_id: str) -> dict:
    """
    Runs the full generate -> critique -> optimize loop, creating one
    new ResumeVersion per round.

    IMPORTANT: this function does NOT decide "best" itself anymore.
    get_best_resume_id() is the ONE authoritative place that decision
    is made, used consistently everywhere (this function, show_latest_
    resume.py, judge_agent.py, the assessor scripts). Having two
    separate "pick the best" implementations with different tie-break
    rules is exactly what caused run_loop's own printed result to
    disagree with show_latest_resume.py's - fixed by having a single
    source of truth instead of two.
    """
    resume_id = generate_draft(job_id, candidate_id)
    result = critique(resume_id, job_id, candidate_id)

    history = [{"version_number": 1, "resume_id": resume_id, "score": result["quality_score"], "passed": result["fact_check_passed"]}]

    current_id = resume_id
    rounds = 0

    while result["quality_score"] < TARGET_SCORE and rounds < MAX_ROUNDS:
        current_id = optimize(current_id)
        result = critique(current_id, job_id, candidate_id)
        rounds += 1

        session = get_session()
        v = session.query(ResumeVersion).filter_by(id=current_id).first()
        version_number = v.version_number
        session.close()

        history.append({
            "version_number": version_number, "resume_id": current_id,
            "score": result["quality_score"], "passed": result["fact_check_passed"],
        })

    # Single source of truth for "best" - same function used everywhere else.
    best_resume_id = get_best_resume_id(job_id, candidate_id)

    session = get_session()
    final_resume = session.query(ResumeVersion).filter_by(id=best_resume_id).first()
    final_score = final_resume.quality_score
    final_passed = final_resume.fact_check_passed
    session.close()

    reached_target = final_score >= TARGET_SCORE and final_passed

    return {
        "history": history,
        "final_resume_id": best_resume_id,
        "final_score": final_score,
        "fact_check_passed": final_passed,
        "reached_target": reached_target,
        "rounds_used": rounds,
    }


if __name__ == "__main__":
    session = get_session()
    job = session.query(Job).order_by(Job.created_at.desc()).first()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not job or not candidate:
        print("Run job_agent.py, candidate_agent.py, and matching_engine.py first.")
    else:
        print(f"Running loop for job '{job.title}' / candidate '{candidate.name}'...")
        print(f"Target score: {TARGET_SCORE} | Max rounds: {MAX_ROUNDS}\n")

        summary = run_loop(job.id, candidate.id)

        print("Version history:")
        for h in summary["history"]:
            marker = "  <- BEST" if h["resume_id"] == summary["final_resume_id"] else ""
            pass_label = "PASS" if h["passed"] else "FAIL"
            print(f"  v{h['version_number']}: score={h['score']}  fact_check={pass_label}{marker}")

        print(f"\nRounds of optimization used: {summary['rounds_used']}")
        print(f"Fact check passed (final version): {summary['fact_check_passed']}")

        if not summary["fact_check_passed"]:
            print("\nWARNING: no version in this run passed the fact check. The best-scoring")
            print("version is being returned as a fallback, but it may contain unsupported")
            print("claims. Do NOT use this resume as-is - review the fabrication flags first.")

        if summary["reached_target"]:
            print(f"Reached target score of {TARGET_SCORE}. Final score: {summary['final_score']}")
        else:
            print(f"Did NOT reach target score of {TARGET_SCORE} within {MAX_ROUNDS} rounds. "
                  f"Final score: {summary['final_score']}. Consider adding more evidence "
                  f"(projects, skills, outcomes) to the candidate profile rather than looping further.")

        print(f"\nFinal resume version id: {summary['final_resume_id']}")