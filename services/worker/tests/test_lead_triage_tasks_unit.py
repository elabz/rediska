"""Unit tests for maintenance.expire_stale_leads and maintenance.generate_calibration_report.

The tasks build their own engine from MYSQL_URL; tests swap in a shared
in-memory SQLite engine.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from rediska_core.domain.models import (
    AuditLog,
    Base,
    CalibrationReport,
    Job,
    LeadPost,
    Provider,
)
from rediska_worker.tasks import maintenance


@pytest.fixture
def engine():
    from sqlalchemy.dialects import sqlite

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # SQLite only autoincrements INTEGER PRIMARY KEY; compile BIGINT as INTEGER.
    original_visit = sqlite.dialect.type_compiler_cls.visit_BIGINT
    sqlite.dialect.type_compiler_cls.visit_BIGINT = lambda self, type_, **kw: "INTEGER"
    try:
        Base.metadata.create_all(eng)
    finally:
        sqlite.dialect.type_compiler_cls.visit_BIGINT = original_visit
    with Session(eng) as session:
        session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
        session.commit()
    with patch("sqlalchemy.create_engine", return_value=eng):
        yield eng


def _seed_leads(engine, days_old_list):
    with Session(engine) as session:
        for n, days_old in enumerate(days_old_list):
            session.add(
                LeadPost(
                    provider_id="reddit",
                    source_location="r/test_triage",
                    external_post_id=f"test_expire_{n}",
                    post_url=f"https://reddit.com/comments/test_expire_{n}",
                    status="new",
                    lead_source="scout_watch",
                    remote_visibility="unknown",
                    created_at=datetime.utcnow() - timedelta(days=days_old),
                )
            )
        session.commit()


def _statuses(engine):
    with Session(engine) as session:
        return sorted(lead.status for lead in session.query(LeadPost).all())


class TestExpireStaleLeadsTask:
    def test_live_run_refused_before_any_dry_run(self, engine):
        _seed_leads(engine, [30, 1])

        result = maintenance.expire_stale_leads.run(dry_run=False, expiry_days=14)

        assert result["status"] == "dry_run_required"
        assert _statuses(engine) == ["new", "new"]

    def test_dry_run_then_live_run(self, engine):
        _seed_leads(engine, [30, 20, 1])

        dry = maintenance.expire_stale_leads.run(dry_run=True, expiry_days=14)
        assert dry["status"] == "success"
        assert dry["count"] == 2
        assert _statuses(engine) == ["new", "new", "new"]

        live = maintenance.expire_stale_leads.run(dry_run=False, expiry_days=14)
        assert live["status"] == "success"
        assert live["count"] == 2
        assert _statuses(engine) == ["expired", "expired", "new"]

        with Session(engine) as session:
            jobs = {j.dedupe_key: j.status for j in session.query(Job).all()}
            assert jobs == {
                maintenance.EXPIRE_DRY_RUN_KEY: "done",
                maintenance.EXPIRE_LIVE_KEY: "done",
            }
            actions = sorted(a.action_type for a in session.query(AuditLog).all())
            assert actions == ["lead.expire", "lead.expire_dry_run"]

        # A second live run finds nothing left to expire.
        again = maintenance.expire_stale_leads.run(dry_run=False, expiry_days=14)
        assert again["count"] == 0

    def test_zero_days_disables(self, engine):
        _seed_leads(engine, [30])
        maintenance.expire_stale_leads.run(dry_run=True, expiry_days=0)
        result = maintenance.expire_stale_leads.run(dry_run=False, expiry_days=0)
        assert result["status"] == "disabled"
        assert _statuses(engine) == ["new"]


class TestGenerateCalibrationReportTask:
    def test_generates_once_per_day(self, engine):
        end = "2026-09-14T06:00:00"

        first = maintenance.generate_calibration_report.run(period_end=end)
        second = maintenance.generate_calibration_report.run(period_end="2026-09-14T07:00:00")

        assert first["status"] == "success"
        assert second["status"] == "skipped"
        with Session(engine) as session:
            reports = session.query(CalibrationReport).all()
            assert len(reports) == 1
            assert reports[0].period_end == datetime(2026, 9, 14, 6, 0, 0)
            assert "overall" in reports[0].report_json
            job = session.query(Job).one()
            assert job.status == "done"


class TestBeatSchedule:
    def test_new_maintenance_tasks_are_scheduled(self):
        from rediska_worker.celery_app import app

        schedule = {entry["task"]: entry for entry in app.conf.beat_schedule.values()}
        assert schedule["maintenance.expire_stale_leads"]["kwargs"] == {"dry_run": False}
        assert "maintenance.generate_calibration_report" in schedule
