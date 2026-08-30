import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


def run_lightweight_migrations():
    """There is no Alembic in this project. Base.metadata.create_all() only
    creates tables that don't exist yet — it silently does NOT add new columns
    to a table that already exists. Against a pre-existing DB (e.g. a
    deployed app.db from before a model change), that leaves the ORM issuing
    SELECT/INSERT statements against columns the actual table doesn't have,
    which fails at request time, not at startup, with an unhelpful 500.

    This adds any column that's on a model but missing from the live table,
    via SQLite's ALTER TABLE ... ADD COLUMN (which only supports adding
    nullable columns / columns with a constant default — matching every
    column added by this project's schema changes so far). It is not a
    substitute for a real migration tool if the schema needs anything more
    involved (renames, constraint changes, backfills).
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table — already created by create_all()
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                print(f"Migrated schema: added column {table.name}.{column.name}")