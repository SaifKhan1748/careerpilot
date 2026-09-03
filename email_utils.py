"""
Sends email via Gmail SMTP - free, uses Python's built-in smtplib, no
third-party service or paid API needed.

Setup: use a Gmail account, enable 2FA, then generate an "App Password"
at https://myaccount.google.com/apppasswords - use THAT (not your real
Gmail password) as EMAIL_APP_PASSWORD in .env.
"""

import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")


def send_email(to: str, subject: str, body: str) -> bool:
    """Returns True if sent, False if email isn't configured or sending failed."""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print(f"[email not configured - would have sent to {to}]: {subject}\n{body}")
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False