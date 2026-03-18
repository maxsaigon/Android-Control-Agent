"""Database engine and session management."""

from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

# Create engine
engine = create_engine(settings.database_url, echo=False)


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency: yields a database session."""
    with Session(engine) as session:
        yield session
