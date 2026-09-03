"""
CareerPilot - Database connection.

Run this file directly to create the database file (careerpilot.db)
and all the tables. Run it again any time you change models.py during
early development (it's safe - it only creates tables that don't exist).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
from models import Base

load_dotenv()

# Defaults to local SQLite for development. To move to Postgres later
# (needed for real multi-user production use - SQLite doesn't handle
# concurrent writers well), just set DATABASE_URL in .env, e.g.:
#   DATABASE_URL=postgresql://user:password@host:5432/dbname
# No code changes needed here.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///careerpilot.db")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    Base.metadata.create_all(engine)
    print("Database ready: careerpilot.db")


def get_session():
    return SessionLocal()


if __name__ == "__main__":
    init_db()