import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest
from sqlalchemy import inspect

from app.core.config import settings
from app.db.base import build_engine, build_sessionmaker, create_all_tables


def test_build_engine_requires_a_url():
    # database_url="" alone isn't enough to prove this -- build_engine()
    # falls back to settings.database_url, which this dev .env has set.
    # Clear that too, so there's genuinely no URL anywhere.
    original = settings.database_url
    settings.database_url = ""
    try:
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            build_engine(database_url="")
    finally:
        settings.database_url = original


def test_build_engine_accepts_sqlite_url():
    engine = build_engine(database_url="sqlite:///:memory:")
    assert engine.url.get_backend_name() == "sqlite"


def test_create_all_tables_creates_every_model_table():
    engine = build_engine(database_url="sqlite:///:memory:")
    create_all_tables(engine=engine)

    tables = set(inspect(engine).get_table_names())
    assert {"account_state", "risk_evaluations", "compliance_checks", "candles"} <= tables


def test_build_sessionmaker_produces_working_sessions():
    engine = build_engine(database_url="sqlite:///:memory:")
    create_all_tables(engine=engine)
    Session = build_sessionmaker(engine=engine)

    from app.db.models import ComplianceCheckRow

    with Session() as session:
        session.add(ComplianceCheckRow(check_name="static_ip", ok=True, detail="matches"))
        session.commit()

    with Session() as session:
        row = session.query(ComplianceCheckRow).one()
        assert row.check_name == "static_ip"
