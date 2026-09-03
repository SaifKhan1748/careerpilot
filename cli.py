"""
CareerPilot CLI - one entrypoint for everything.

Wraps your existing, already-tested scripts via subprocess - no logic
duplicated, so nothing new can break.

Usage:
    python cli.py <command>

Setup / debugging:
    init-db      create the database tables
    test-db      Phase 0 sanity test (fake data round-trip)

Core pipeline:
    job          extract a job posting
    candidate    extract candidate profile
    add-job      add the built-in matching test job (Python Backend Developer)
    match        run matching engine
    resume       generate a single resume draft (v1 only, no loop)
    critic       critique the latest resume version
    optimize     optimize the latest resume version (one round)
    loop         full generate->critique->optimize loop
    breakdown    show score breakdown for the latest resume
    show-resume  show the actual BEST resume version (not just latest)

Assessment:
    ats          ATS assessment
    recruiter    recruiter assessment
    hiring       hiring manager assessment
    judge        judge decision
    debate       assessor debate round

Extras:
    gaps         skill-gap analysis
    interview    mock interview (text/voice)
    apps         log/view applications
    analytics    outcome analytics
    research     research a company
    discover     search for jobs
    browser      autofill a job application (stops before submit)

    full         runs job -> candidate -> match -> loop -> ats -> recruiter -> hiring -> judge
"""

import sys
import subprocess

AGENT_COMMANDS = {
    "job": "agents.job_agent",
    "candidate": "agents.candidate_agent",
    "add-job": "agents.add_matching_job",
    "match": "agents.matching_engine",
    "resume": "agents.resume_agent",
    "critic": "agents.critic_agent",
    "optimize": "agents.optimizer_agent",
    "loop": "agents.run_loop",
    "breakdown": "agents.show_breakdown",
    "show-resume": "agents.show_latest_resume",
    "ats": "agents.ats_agent",
    "recruiter": "agents.recruiter_agent",
    "hiring": "agents.hiring_manager_agent",
    "judge": "agents.judge_agent",
    "debate": "agents.debate_agent",
    "gaps": "agents.skill_gap_agent",
    "interview": "agents.interview_agent",
    "apps": "agents.applications",
    "analytics": "agents.outcome_analytics",
    "research": "agents.company_research_agent",
    "discover": "agents.job_discovery_agent",
    "browser": "agents.browser_agent",
}

ROOT_COMMANDS = {
    "init-db": "db",
    "test-db": "test_db",
}

ALL_COMMANDS = {**AGENT_COMMANDS, **ROOT_COMMANDS}

FULL_PIPELINE = ["job", "candidate", "match", "loop", "ats", "recruiter", "hiring", "judge"]


def run_module(module: str) -> int:
    result = subprocess.run([sys.executable, "-m", module])
    return result.returncode


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in list(ALL_COMMANDS.keys()) + ["full"]:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "full":
        for step in FULL_PIPELINE:
            print(f"\n=== {step} ===")
            code = run_module(AGENT_COMMANDS[step])
            if code != 0:
                print(f"Stopped: '{step}' failed (exit code {code}).")
                return
        print("\nDone. Run 'python cli.py debate', 'gaps', 'interview', etc. as needed.")
    else:
        run_module(ALL_COMMANDS[command])


if __name__ == "__main__":
    main()