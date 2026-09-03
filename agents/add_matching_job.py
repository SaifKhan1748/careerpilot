"""
CareerPilot - adds a job posting that actually fits Saif Khan's real
skills (Python, Flask, SQL/MySQL web development), instead of a Data
Scientist role requiring ML/AWS/Docker he has no evidence for.

This is separate from job_agent.py's sample so you don't have to edit
that file - just run this once to add a better-matching job to test
against.
"""

from agents.job_agent import extract_and_save

well_matched_job = """
We are looking for a Python Backend Developer to join our team.

Required:
- Python
- SQL
- Experience building REST APIs
- Experience with a Python web framework (Flask or Django)

Preferred:
- MySQL or other relational database experience
- Experience with chatbots or conversational applications

You will build and maintain backend services, design database schemas,
and develop APIs that power our web applications.
"""

if __name__ == "__main__":
    job_id = extract_and_save(well_matched_job, company_name="BackendCo")
    print(f"Saved well-matched job with id: {job_id}")
    print("\nNow run:")
    print("  python -m agents.matching_engine")
    print("  python -m agents.run_loop")