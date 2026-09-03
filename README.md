# CareerPilot — Phase 0

This is the real, runnable start of the project. It creates an actual
database with the tables we designed, and proves they work with real data.

## What's in this folder

```
careerpilot/
  models.py       <- the data model (tables: Candidate, Skill, Project, Evidence, Job, Requirement, Match)
  db.py           <- connects to the database, creates tables
  test_db.py      <- inserts fake data and reads it back, to prove it works
  agents/         <- empty for now, Phase 1 agents go here next
  requirements.txt
  .env.example
```

## Setup (run once)

```bash
cd careerpilot
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Step 1: create the database

```bash
python db.py
```

You should see: `Database ready: careerpilot.db`
A new file `careerpilot.db` appears in the folder. That's your real database — you can open it with any SQLite viewer (e.g. the "SQLite Viewer" VS Code extension) to look inside.

## Step 2: test it with real data

```bash
python test_db.py
```

You should see printed output showing a fake candidate, a skill, and the
evidence linking them together, with a computed strength score.

If both of those run without errors, **Phase 0 is done** — you have a
real, working data model that agents will read and write to in Phase 1.

## Step 3: run the real Job Agent

1. Copy `.env.example` to `.env`
2. Get a free key at console.groq.com/keys and put it in `.env`:
   ```
   GROQ_API_KEY=your_actual_key
   ```
3. Run:
   ```bash
   python -m agents.job_agent
   ```

You should see it print a saved `job_id`, then read the job back out of
the database along with the extracted requirements (title, seniority,
must-have vs preferred, priority).

**Important:** never paste real API keys into chat or commit `.env` to
git — `.gitignore` already excludes it. If a key is ever exposed, revoke
it immediately at the provider's dashboard and generate a new one.

## Next step

Once this works, we build `agents/candidate_agent.py` — reads a resume
and writes `Skill` + `Project` + `Evidence` rows into the same database.
