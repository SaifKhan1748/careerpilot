"""
CareerPilot - Company Research Agent (Phase 5)

Searches the web for public information about a company, then asks the
LLM to extract discrete factual claims - but every claim MUST cite a
source_url that came from an ACTUAL search result. This is enforced in
CODE: after the LLM responds, any claim citing a URL that wasn't in the
real search results is thrown out, not trusted. This is what stops the
system from inventing company facts with a fake-looking citation.

Uses ddgs (DuckDuckGo search) - free, no API key needed, but does
require real internet access. This agent cannot be tested from a
network-restricted sandbox - only from your own machine.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv
from ddgs import DDGS

from db import get_session
from models import Company, CompanyClaim, Job
from agents.groq_utils import call_groq_with_retry

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"


def search_company(company_name: str, max_results_per_query: int = 5) -> list:
    """
    Runs a few different search angles on the company. Returns a list
    of {title, url, snippet} dicts - these are the ONLY sources the
    LLM will be allowed to cite.
    """
    queries = [
        f"{company_name} technology stack engineering",
        f"{company_name} about company products",
        f"{company_name} careers engineering blog",
    ]

    results = []
    seen_urls = set()

    with DDGS() as ddgs:
        for query in queries:
            for r in ddgs.text(query, max_results=max_results_per_query):
                url = r.get("href") or r.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("body", ""),
                })

    return results


def extract_claims_with_llm(company_name: str, search_results: list) -> list:
    """
    Asks the LLM to extract factual claims from the search results.
    Every claim must cite one of the provided URLs - the prompt says
    so, and research() double-checks this in code afterward, since
    prompt instructions alone aren't enough to guarantee it.
    """
    sources_text = json.dumps(search_results, indent=2)

    prompt = f"""Here are web search results about the company "{company_name}":

{sources_text}

Extract discrete, factual claims about the company (what they build, their tech stack,
products, industry, engineering culture) based ONLY on these search results.

Return ONLY valid JSON, no other text:
{{
  "claims": [
    {{"claim_text": "string", "source_url": "must be one of the URLs given above exactly"}}
  ],
  "industry": "short string, best guess based on the sources",
  "summary": "2-3 sentence overview based only on the sources above"
}}

Rules:
- source_url for every claim MUST be copied EXACTLY from the search results above - do not alter, shorten, or invent a URL.
- Do not include a claim if you cannot point to a specific source that supports it.
- If the search results are too thin to say much, return fewer claims rather than padding with vague statements.
"""

    response = call_groq_with_retry(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)

    return json.loads(text)


def link_company_to_job(job_id: str, company_id: str) -> None:
    """Explicitly link a researched Company to a Job."""
    session = get_session()
    job = session.query(Job).filter_by(id=job_id).first()
    if job:
        job.company_id = company_id
        session.commit()
    session.close()


def auto_link_matching_jobs(company_name: str, company_id: str) -> int:
    """
    After researching a company, link it to any existing Job whose
    company_name matches (case-insensitive) and isn't linked yet.
    Returns the number of jobs linked.
    """
    session = get_session()
    jobs = session.query(Job).filter(Job.company_id.is_(None)).all()

    linked = 0
    for job in jobs:
        if job.company_name and job.company_name.strip().lower() == company_name.strip().lower():
            job.company_id = company_id
            linked += 1

    session.commit()
    session.close()
    return linked


def research(company_name: str) -> str:
    """
    Runs the full pipeline: search -> extract claims -> verify sources
    in code -> save Company + CompanyClaim rows. Returns company_id.
    """
    search_results = search_company(company_name)

    if not search_results:
        # save a Company row anyway, with zero confidence, rather than
        # silently failing - honest about not finding anything
        session = get_session()
        company = Company(name=company_name, research_summary="No search results found.", research_confidence=0.0)
        session.add(company)
        session.commit()
        company_id = company.id
        session.close()
        return company_id

    real_urls = {r["url"] for r in search_results}
    url_to_title = {r["url"]: r["title"] for r in search_results}

    parsed = extract_claims_with_llm(company_name, search_results)

    # CODE-ENFORCED CHECK: throw out any claim citing a URL that wasn't
    # actually in the search results. This is the real safeguard - the
    # prompt asking nicely is not sufficient on its own.
    verified_claims = []
    rejected_count = 0
    for claim in parsed.get("claims", []):
        if claim.get("source_url") in real_urls:
            verified_claims.append(claim)
        else:
            rejected_count += 1

    confidence = len(verified_claims) / max(len(parsed.get("claims", [])), 1)

    session = get_session()
    company = Company(
        name=company_name,
        research_summary=parsed.get("summary", ""),
        industry=parsed.get("industry", ""),
        research_confidence=round(confidence, 2),
    )
    session.add(company)
    session.commit()
    company_id = company.id

    for claim in verified_claims:
        session.add(CompanyClaim(
            company_id=company_id,
            claim_text=claim["claim_text"],
            source_url=claim["source_url"],
            source_title=url_to_title.get(claim["source_url"], ""),
        ))
    session.commit()
    session.close()

    if rejected_count:
        print(f"NOTE: rejected {rejected_count} claim(s) with a source URL that wasn't in the actual search results.")

    linked = auto_link_matching_jobs(company_name, company_id)
    if linked:
        print(f"Auto-linked this research to {linked} existing job posting(s) with matching company name.")

    return company_id


if __name__ == "__main__":
    company_name = input("Company name to research: ").strip()

    if not company_name:
        print("No company name given.")
    else:
        print(f"Searching for information about '{company_name}'...")
        company_id = research(company_name)

        session = get_session()
        company = session.query(Company).filter_by(id=company_id).first()
        claims = session.query(CompanyClaim).filter_by(company_id=company_id).all()

        print(f"\nResearch confidence: {company.research_confidence}")
        print(f"Industry: {company.industry}")
        print(f"Summary: {company.research_summary}\n")

        print(f"Claims ({len(claims)}):")
        for c in claims:
            print(f"  - {c.claim_text}")
            print(f"    source: {c.source_url}")
        session.close()