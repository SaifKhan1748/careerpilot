"""
One-time SEO fix: inserts meta description, canonical URL, Open Graph
tags, and favicon link into each static HTML page's <head>, if not
already present. Edits your real files directly - safe to run
multiple times, skips anything already there.

IMPORTANT: set BASE_URL below to your real deployed URL before running.
"""

import re
import glob
import os

BASE_URL = "https://careerpilot-taqb.onrender.com"  # <-- change this to your real Render URL first!

PAGE_META = {
    "index.html": {
        "title": "CareerPilot - AI Career Copilot",
        "description": "AI-powered resume tailoring, interview practice, and job matching for students.",
        "path": "/",
    },
    "dashboard.html": {
        "title": "Dashboard - CareerPilot",
        "description": "Manage your resume, applications, and interview prep.",
        "path": "/dashboard.html",
    },
    "verify.html": {
        "title": "Verify Email - CareerPilot",
        "description": "Confirm your CareerPilot account email.",
        "path": "/verify.html",
    },
    "reset-password.html": {
        "title": "Reset Password - CareerPilot",
        "description": "Reset your CareerPilot account password.",
        "path": "/reset-password.html",
    },
}


def build_tags(meta: dict) -> str:
    url = BASE_URL.rstrip("/") + meta["path"]
    return f'''<meta name="description" content="{meta['description']}">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:title" content="{meta['title']}">
<meta property="og:description" content="{meta['description']}">
<meta property="og:type" content="website">
<meta property="og:url" content="{url}">'''


def inject(content: str, meta: dict) -> tuple:
    if 'name="description"' in content:
        return content, False

    tags = build_tags(meta)

    if re.search(r'<meta charset=[^>]*>', content, re.IGNORECASE):
        new_content = re.sub(
            r'(<meta charset=[^>]*>)',
            r'\1\n' + tags,
            content, count=1, flags=re.IGNORECASE,
        )
    else:
        new_content = re.sub(
            r'(<head[^>]*>)',
            r'\1\n' + tags,
            content, count=1, flags=re.IGNORECASE,
        )

    return new_content, True


if __name__ == "__main__":
    if "YOUR_DOMAIN" in BASE_URL:
        print("STOP: edit BASE_URL at the top of this script to your real deployed URL first.")
        exit(1)

    changed = 0
    for filepath in glob.glob("static/*.html"):
        filename = os.path.basename(filepath)
        meta = PAGE_META.get(filename)
        if not meta:
            print(f"{filepath}: no metadata defined, skipped")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        new_content, was_changed = inject(content, meta)

        if was_changed:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"{filepath}: SEO tags added")
            changed += 1
        else:
            print(f"{filepath}: already had meta description, skipped")

    print(f"\nDone - {changed} file(s) updated.")