from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# Gate every transaction before its first read, including background Agent writes.
RETENTION_LOCK = 729341405


@event.listens_for(engine, "begin")
def retention_transaction_lock(connection):
    if (connection.dialect.name == "postgresql"
            and not connection.get_execution_options().get("retention_cleanup")):
        connection.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": RETENTION_LOCK})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

