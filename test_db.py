"""
CareerPilot - Test the data model.

This inserts one fake candidate with a skill and evidence, then reads
it back. If this runs and prints sensible output, Phase 0 works.

Run: python test_db.py
"""

from db import init_db, get_session
from models import Candidate, Skill, Project, Evidence

init_db()
session = get_session()

# 1. Create a candidate
candidate = Candidate(
    name="Test Candidate",
    raw_resume_text="Built a RAG chatbot using Python and Flask.",
    career_goals="Data Scientist role"
)
session.add(candidate)
session.commit()

# 2. Create a project
project = Project(
    candidate_id=candidate.id,
    title="RAG Teaching Assistant",
    description="A chatbot that answers questions using retrieval-augmented generation.",
    outcomes="Used by 50 students in a class pilot."
)
session.add(project)
session.commit()

# 3. Create a skill
skill = Skill(
    candidate_id=candidate.id,
    name="Python",
    category="language",
    source="inferred-from-project"
)
session.add(skill)
session.commit()

# 4. Link them with Evidence - this is the important part
evidence = Evidence(
    candidate_id=candidate.id,
    skill_id=skill.id,
    source_type="project",
    source_id=project.id,
    confidence=0.9,
    note="Project explicitly built in Python"
)
session.add(evidence)
session.commit()

# 5. Update skill strength based on evidence (simple version of the formula from the spec)
skill.strength = min(1.0, 0.3 * 1 + 0.4 * evidence.confidence + 0.3 * 1)
session.commit()

# 6. Read it all back
print("\n--- Candidate ---")
print(candidate.name, "|", candidate.career_goals)

print("\n--- Skills ---")
for s in session.query(Skill).filter_by(candidate_id=candidate.id):
    print(f"  {s.name}  strength={s.strength:.2f}  source={s.source}")

print("\n--- Evidence ---")
for e in session.query(Evidence).filter_by(candidate_id=candidate.id):
    print(f"  skill_id={e.skill_id}  source={e.source_type}  confidence={e.confidence}  note='{e.note}'")

print("\nPhase 0 works. Data is saved in careerpilot.db\n")
