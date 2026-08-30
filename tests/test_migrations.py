"""Base.metadata.create_all() only creates tables that don't exist yet — it
silently does NOT add new columns to a table that already exists. This
reproduces that exact scenario against a standalone SQLite file (a table
created with an old schema, missing a column the current models define) and
confirms run_lightweight_migrations() patches it before any query touches
the missing column.
"""
import sqlite3

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, LargeBinary


def test_lightweight_migration_adds_missing_column(tmp_path):
    db_path = tmp_path / "old_schema.db"

    # Simulate a pre-existing DB created before a column was added to the model.
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base = declarative_base()

    class Widget(Base):
        __tablename__ = "widgets"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        embedding = Column(LargeBinary, nullable=True)  # the "new" column

    def run_lightweight_migrations():
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing_columns:
                        continue
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))

    inspector = inspect(engine)
    before = {c["name"] for c in inspector.get_columns("widgets")}
    assert "embedding" not in before

    run_lightweight_migrations()

    inspector = inspect(engine)
    after = {c["name"] for c in inspector.get_columns("widgets")}
    assert "embedding" in after

    # And a query against the newly-added column no longer raises.
    Session = sessionmaker(bind=engine)
    session = Session()
    result = session.query(Widget).filter(Widget.embedding.isnot(None)).all()
    assert result == []
    session.close()


def test_database_module_migration_matches_live_app(tmp_path, monkeypatch):
    """Same check, but against the actual database.run_lightweight_migrations
    and the actual models.KnowledgeEntry — proves the real migration path
    (not just the reproduction above) fixes the real gap. Points the real
    database module at a throwaway engine via monkeypatch so it doesn't
    disturb the shared session-scoped app/engine used by the rest of the
    suite."""
    db_path = tmp_path / "real_old_schema.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE knowledge_base (
            id INTEGER PRIMARY KEY,
            question TEXT,
            answer TEXT,
            confidence FLOAT DEFAULT 0.8,
            times_used INTEGER DEFAULT 0,
            positive_feedback INTEGER DEFAULT 0,
            negative_feedback INTEGER DEFAULT 0,
            created_at DATETIME
        )
    """)
    conn.commit()
    conn.close()

    import database as database_module
    import models  # noqa: F401  (registers KnowledgeEntry etc. on Base.metadata)

    throwaway_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database_module, "engine", throwaway_engine)

    inspector_before = inspect(throwaway_engine)
    cols_before = {c["name"] for c in inspector_before.get_columns("knowledge_base")}
    assert "embedding" not in cols_before

    database_module.Base.metadata.create_all(bind=throwaway_engine)
    database_module.run_lightweight_migrations()

    inspector_after = inspect(throwaway_engine)
    cols_after = {c["name"] for c in inspector_after.get_columns("knowledge_base")}
    assert "embedding" in cols_after
