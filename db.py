from sqlalchemy import create_engine, inspect, text
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
SessionLocal = sessionmaker(bind=engine)


def migrate_missing_columns():
    """
    create_all() only creates tables that don't exist yet - it never
    adds new columns to a table that's already there. This adds any
    columns the code now expects but the existing table doesn't have
    yet, without touching any existing rows/data. Safe to run every
    startup - it's a no-op once columns already exist.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return  # table doesn't exist yet - create_all() will make it fresh, no migration needed

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    needed_columns = {
        "email_verified": "BOOLEAN DEFAULT FALSE",
        "verification_token": "VARCHAR",
        "reset_token": "VARCHAR",
        "reset_token_expires": "TIMESTAMP",
    }

    with engine.connect() as conn:
        for col_name, col_type in needed_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                print(f"Migration: added missing column users.{col_name}")


def init_db():
    Base.metadata.create_all(engine)
    migrate_missing_columns()
    print("Database ready: careerpilot.db")


def get_session():
    return SessionLocal()


if __name__ == "__main__":
    init_db()