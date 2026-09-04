"""
One-time fix: adds the viewport meta tag to every static HTML page, if
missing. Without this, mobile browsers render pages at a fake ~980px
"desktop width" and shrink everything to fit - which breaks ALL
responsive CSS, no matter how correct the media queries are. This is
almost always the real cause of "looks fine on desktop, broken on
mobile" even when the CSS itself is right.

Run once: python add_viewport_meta.py
Safe to run multiple times - skips any file that already has it.
"""

import re
import glob

VIEWPORT_TAG = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'

FILES = glob.glob("static/*.html")


def add_viewport(content: str) -> tuple:
    if "name=\"viewport\"" in content:
        return content, False

    # insert right after <meta charset...> if present, else right after <head>
    if re.search(r'<meta charset=[^>]*>', content, re.IGNORECASE):
        new_content = re.sub(
            r'(<meta charset=[^>]*>)',
            r'\1\n' + VIEWPORT_TAG,
            content, count=1, flags=re.IGNORECASE,
        )
    else:
        new_content = re.sub(
            r'(<head[^>]*>)',
            r'\1\n' + VIEWPORT_TAG,
            content, count=1, flags=re.IGNORECASE,
        )

    return new_content, True


if __name__ == "__main__":
    changed = 0
    for filepath in FILES:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        new_content, was_changed = add_viewport(content)

        if was_changed:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"{filepath}: added viewport meta tag")
            changed += 1
        else:
            print(f"{filepath}: already had it, skipped")

    print(f"\nDone - {changed} file(s) updated.")