"""
CareerPilot - shared helper for calling Groq with automatic retry on
rate limits. Groq's free tier has a tokens-per-minute cap - when the
loop makes several LLM calls back to back, it's normal to hit this.
Instead of crashing, wait a moment and retry.
"""

import re
import time
from groq import RateLimitError


def call_groq_with_retry(client, max_retries: int = 5, **kwargs):
    """
    Same signature as client.chat.completions.create(**kwargs), but
    catches RateLimitError and waits before retrying, using the wait
    time Groq suggests in its error message when available.
    """
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            wait_seconds = 5.0
            match = re.search(r"try again in ([\d.]+)s", str(e))
            if match:
                wait_seconds = float(match.group(1)) + 1.0  # small buffer

            if attempt == max_retries - 1:
                raise  # out of retries, let it fail for real

            print(f"Rate limit hit - waiting {wait_seconds:.1f}s before retry ({attempt + 1}/{max_retries})...")
            time.sleep(wait_seconds)