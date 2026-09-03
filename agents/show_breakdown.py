"""
CareerPilot - quick diagnostic: shows the rubric breakdown for the
most recent resume version, so you can see exactly which category
is capping the score.
"""

from db import get_session
from models import ResumeVersion
from agents.critic_agent import critique

session = get_session()
resume = session.query(ResumeVersion).order_by(ResumeVersion.created_at.desc()).first()
session.close()

result = critique(resume.id, resume.job_id, resume.candidate_id)

print(f"Score: {result['quality_score']}/100\n")
print("Breakdown:")
for category, score in result["breakdown"].items():
    max_points = {"coverage": 30, "measurable_outcomes": 20, "structure": 20, "generic_phrases": 20, "repetition": 10}
    print(f"  {category}: {score}/{max_points[category]}")

print("\nRemaining issues:")
for issue in result["issues"]:
    print(f"  - {issue}")