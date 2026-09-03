"""
CareerPilot - Browser Agent (Phase 6)

Opens a job application URL, tries to fill common fields (name, email,
phone, LinkedIn, GitHub, portfolio) from the candidate's real data, then
STOPS. Never clicks submit/apply - leaves the browser open for you to
review and submit manually.

Setup (one-time, in addition to pip install):
    playwright install chromium

Works best on simple forms. Complex multi-step ATS flows (Workday,
some Greenhouse forms) may need manual completion beyond what this fills.
"""

from playwright.sync_api import sync_playwright

from db import get_session
from models import Candidate

# Basic anti-bot-detection mitigation. This helps on simpler sites but
# will NOT reliably beat serious anti-bot systems (Workday, LinkedIn,
# etc.) - that's a real arms race, not something a small patch wins.
STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"

FIELD_PATTERNS = {
    "name": ["name", "full name", "your name"],
    "email": ["email"],
    "phone": ["phone", "mobile", "contact number"],
    "linkedin": ["linkedin"],
    "github": ["github"],
    "portfolio": ["portfolio", "website"],
}


def get_candidate_field_values(candidate_id: str) -> dict:
    import json
    session = get_session()
    candidate = session.query(Candidate).filter_by(id=candidate_id).first()
    session.close()

    links = json.loads(candidate.links) if candidate.links else {}
    return {
        "name": candidate.name,
        "email": candidate.email or "",
        "phone": candidate.phone or "",
        "linkedin": links.get("linkedin", ""),
        "github": links.get("github", ""),
        "portfolio": candidate.portfolio_url or "",
    }


def _get_associated_label_text(frame, inp) -> str:
    """Modern forms often put the real field description in a separate
    <label for="..."> element, not in the input's own attributes."""
    try:
        input_id = inp.get_attribute("id")
        if input_id:
            label_el = frame.query_selector(f"label[for='{input_id}']")
            if label_el:
                return label_el.inner_text() or ""
    except Exception:
        pass
    return ""


def launch_browser_and_fill(url: str, candidate_id: str):
    """
    Shared logic used by both the CLI and the web dashboard - launches
    with basic stealth settings, waits for real content, fills fields.
    Returns (playwright_instance, browser, page, filled_fields) so the
    caller decides whether to wait for the user or return immediately.
    """
    values = get_candidate_field_values(candidate_id)

    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(user_agent=STEALTH_USER_AGENT, viewport={"width": 1280, "height": 800})
    context.add_init_script(STEALTH_INIT_SCRIPT)
    page = context.new_page()

    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # some sites never go fully idle (websockets, polling, etc.) - proceed anyway
    page.bring_to_front()

    # Search ALL frames, not just the main page - many ATS providers
    # embed the actual application form inside an iframe, which a
    # simple page.query_selector_all("input") would completely miss.
    frame_inputs = []
    for frame in page.frames:
        try:
            for inp in frame.query_selector_all("input"):
                frame_inputs.append((frame, inp))
        except Exception:
            pass

    filled = []
    for field_key, keywords in FIELD_PATTERNS.items():
        value = values.get(field_key)
        if not value:
            continue
        for frame, inp in frame_inputs:
            own_attrs = " ".join(filter(None, [
                inp.get_attribute("name") or "",
                inp.get_attribute("id") or "",
                inp.get_attribute("placeholder") or "",
                inp.get_attribute("aria-label") or "",
            ]))
            label_text = _get_associated_label_text(frame, inp)
            combined = (own_attrs + " " + label_text).lower()

            if any(kw in combined for kw in keywords):
                try:
                    inp.fill(value)
                    filled.append(field_key)
                except Exception:
                    pass
                break

    return p, browser, page, filled


def autofill(url: str, candidate_id: str) -> None:
    p, browser, page, filled = launch_browser_and_fill(url, candidate_id)

    print(f"Filled {len(filled)} field(s): {', '.join(filled) if filled else 'none found'}")
    if not filled:
        print("If the page looked blank, this may be a bot-detection block, not a code bug -")
        print("some sites (Workday, LinkedIn, etc.) actively block automated browsers.")
    print("Review the form yourself - resume upload and any custom questions need manual attention.")
    print("This will NOT submit anything. Close the browser window when done.")

    input("\nPress Enter here once you're done reviewing (this keeps the browser open until then)...")
    browser.close()
    p.stop()


if __name__ == "__main__":
    url = input("Job application URL: ").strip()

    session = get_session()
    candidate = session.query(Candidate).order_by(Candidate.created_at.desc()).first()
    session.close()

    if not candidate:
        print("Run candidate_agent.py first.")
    elif not url:
        print("No URL given.")
    else:
        autofill(url, candidate.id)