"""Password hashing + JWT session tokens."""

import os
import datetime
import bcrypt
from dotenv import load_dotenv
from jose import jwt, JWTError

load_dotenv()  # must load .env BEFORE reading JWT_SECRET below, not rely on another module doing it first

SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    # Loud warning, not a hard crash - so a working local demo doesn't
    # suddenly break - but this MUST be fixed before any real deployment.
    # Anyone who knows this fallback value could forge login tokens for
    # ANY user. Set a real JWT_SECRET in .env before sharing this app
    # with real students.
    print("=" * 70)
    print("WARNING: JWT_SECRET is not set in .env. Using an insecure")
    print("fallback. Anyone who reads this source code could forge login")
    print("tokens. Generate a real secret and add it to .env:")
    print("  python -c \"import secrets; print(secrets.token_hex(32))\"")
    print("Then add to .env:  JWT_SECRET=<the generated value>")
    print("=" * 70)
    SECRET_KEY = "INSECURE-DEV-FALLBACK-DO-NOT-DEPLOY-LIKE-THIS"

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    """Returns user_id, or raises JWTError if invalid/expired."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload["sub"]