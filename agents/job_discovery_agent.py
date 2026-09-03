"""
CareerPilot - Job Discovery Agent (Phase 6)

Searches the web for real job postings, then reuses job_agent.py and
matching_engine.py (already built and tested) to extract requirements
and score fit against the candidate. Ranks by weighted match strength.
"""

from ddgs import DDGS
from db import get_session
from models import Candidate, Job, Requirement, Match
from agents.job_agent import extract_and_save
from agents.matching_engine import match_job_to_candidate

STRENGTH_WEIGHTS = {"strong": 1.0, "partial": 0.6, "weak": 0.3, "none": 0.0}


def search_postings(query: str, max_results: int = 5) -> list:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""), "snippet": r.get("body", "")})
    return results


def compute_fit_score(job_id: str) -> int:
    session = get_session()
    reqs = session.query(Requirement).filter_by(job_id=job_id).all()
    if not reqs:
        session.close()
        return 0
    total = 0.0
    for req in reqs:
        match = session.query(Match).filter_by(requirement_id=req.id).order_by(Match.confidence.desc()).first()
        total += STRENGTH_WEIGHTS.get(match.strength if match else "none", 0.0)
    session.close()
    return round((total / len(reqs)) * 100)


def discover(query: str, candidate_id: str, max_results: int = 5) -> list:
    postings = search_postings(query, max_results)
    ranked = []

    for p in postings:
        if len(p["snippet"]) < 50:
            continue  # too thin to extract real requirements from

        job_id = extract_and_save(p["snippet"], company_name=None, url=p["url"])
        match_job_to_candidate(job_id, candidate_id)
        fit = compute_fit_score(job_id)

        session = get_session()
        job = session.query(Job).filter_by(id=job_id).first()
        title = job.title
        session.close()

        ranked.append({"title": title, "url": p["url"], "fit_score": fit})

    ranked.sort(key=lambda x: -x["fit_score"])
    return ranked


if __name__ == "__main__":
    query = input("Job search (e.g. 'Python backend developer remote'): ").strip()

    session = get_session()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not candidate:
        print("Run candidate_agent.py first.")
    elif not query:
        print("No search query given.")
    else:
        print("Searching...")
        ranked = discover(query, candidate.id)

        if not ranked:
            print("No usable postings found.")
        else:
            print("\nRanked by fit:\n")
            for r in ranked:
                print(f"  {r['fit_score']}% - {r['title']}")
                print(f"    {r['url']}")