"""
One-time accessibility fix: adds aria-label to every <input>/<textarea>
that has a placeholder but no aria-label yet, using the placeholder
text as the label. Screen readers rely on this - placeholder text
alone isn't a reliable substitute for a real accessible name.

Run once: python add_aria_labels.py
Safe to run multiple times - skips anything that already has aria-label.
"""

import re
import glob

FILES = glob.glob("static/*.html")

pattern = re.compile(r'(<(?:input|textarea)\b(?![^>]*aria-label)[^>]*placeholder="([^"]+)"[^>]*)(/?>)')


def add_aria_labels(content: str) -> tuple:
    count = 0

    def replacer(m):
        nonlocal count
        count += 1
        return f'{m.group(1)} aria-label="{m.group(2)}"{m.group(3)}'

    new_content = pattern.sub(replacer, content)
    return new_content, count


if __name__ == "__main__":
    total = 0
    for filepath in FILES:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        new_content, count = add_aria_labels(content)

        if count:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"{filepath}: added {count} aria-label attribute(s)")
            total += count
        else:
            print(f"{filepath}: no changes needed")

    print(f"\nDone - {total} accessibility labels added across {len(FILES)} files.")