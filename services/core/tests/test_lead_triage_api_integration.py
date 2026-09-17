"""API integration tests for lead-triage-and-feedback endpoints."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AuditLog,
    CalibrationReport,
    LeadPost,
    LocalUser,
    Provider,
    ScoutWatch,
    ScoutWatchPost,
)


@pytest.fixture
def mock_user():
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_user"
    return user


@pytest.fixture
async def auth_client(test_app, db_session, mock_user):
    test_app.dependency_overrides[get_current_user] = lambda: mock_user
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def watch(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    w = ScoutWatch(
        provider_id="reddit",
        source_location="r/test_triage",
        search_query="test query",
        sort_by="new",
        time_filter="day",
        min_confidence=0.7,
    )
    db_session.add(w)
    db_session.commit()
    return w


def _post(db_session, watch, ext_id, minutes_old=0, results=None, recommendation="needs_review"):
    post = ScoutWatchPost(
        watch_id=watch.id,
        external_post_id=ext_id,
        post_title=f"title {ext_id}",
        post_body="body",
        post_author="test_author",
        first_seen_at=datetime.utcnow() - timedelta(minutes=minutes_old),
        analysis_status="analyzed",
        analysis_recommendation=recommendation,
        analysis_confidence=0.5,
        **({"dimension_results_json": results} if results is not None else {}),
    )
    db_session.add(post)
    db_session.commit()
    return post


STORED_RESULTS = {
    "preferences": {"compatibility_score": 0.9},
    "meta_analysis": {"priority_level": "medium"},
    "gate_verdict": {
        "recommendation": "needs_review",
        "score": 0.55,
        "gate_results": [{"gate": "location", "status": "unclear", "reason": "location is unclear"}],
    },
}


class TestNeedsReviewEndpoints:
    @pytest.mark.asyncio
    async def test_listing_is_not_captured_by_watch_id_route(self, auth_client, db_session, watch):
        older = _post(db_session, watch, "test_nr_old", minutes_old=10, results=STORED_RESULTS)
        newer = _post(db_session, watch, "test_nr_new", minutes_old=1)
        _post(db_session, watch, "test_suitable", recommendation="suitable")

        response = await auth_client.get("/scout-watches/needs-review")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert [i["id"] for i in data["items"]] == [newer.id, older.id]
        assert data["next_cursor"] is None
        item = data["items"][1]
        assert item["watch_source_location"] == "r/test_triage"
        assert item["watch_search_query"] == "test query"
        assert item["analysis_dimensions"]["gate_verdict"]["gate_results"][0]["gate"] == "location"
        assert "final" in item["evaluations"]

    @pytest.mark.asyncio
    async def test_listing_paginates_with_cursor(self, auth_client, db_session, watch):
        for n in range(3):
            _post(db_session, watch, f"test_page_{n}", minutes_old=n)

        first = (await auth_client.get("/scout-watches/needs-review?limit=2")).json()
        assert len(first["items"]) == 2
        second = (
            await auth_client.get(
                "/scout-watches/needs-review", params={"limit": 2, "cursor": first["next_cursor"]}
            )
        ).json()
        assert len(second["items"]) == 1
        assert second["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_bad_cursor_is_400(self, auth_client, watch):
        response = await auth_client.get("/scout-watches/needs-review?cursor=nope")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_dismiss_leaves_queue_and_audits(self, auth_client, db_session, watch):
        post = _post(db_session, watch, "test_dismiss")

        response = await auth_client.post(f"/scout-watches/posts/{post.id}/dismiss")

        assert response.status_code == 200
        assert response.json()["post_id"] == post.id
        db_session.refresh(post)
        assert post.dismissed_at is not None
        assert post.lead_id is None
        assert (await auth_client.get("/scout-watches/needs-review")).json()["total"] == 0
        audit = (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "scout_watch.dismiss_post")
            .one()
        )
        assert audit.entity_id == post.id

    @pytest.mark.asyncio
    async def test_dismiss_unknown_post_is_404(self, auth_client, watch):
        response = await auth_client.post("/scout-watches/posts/999999/dismiss")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_promote_marks_triaged_and_sets_priority(self, auth_client, db_session, watch):
        post = _post(db_session, watch, "test_promote", results=STORED_RESULTS)

        response = await auth_client.post(
            f"/scout-watches/{watch.id}/posts/{post.id}/add-to-leads"
        )

        assert response.status_code == 200
        db_session.refresh(post)
        assert post.triaged_at is not None
        lead = db_session.get(LeadPost, response.json()["lead_id"])
        # Unclear gate blocks promotion to high; stays at the meta level.
        assert lead.priority == "medium"
        assert lead.compatibility_score == 0.9
        assert (await auth_client.get("/scout-watches/needs-review")).json()["total"] == 0


class TestLeadListingApi:
    def _lead(self, db_session, ext_id, status="new", priority=None, days_old=0):
        lead = LeadPost(
            provider_id="reddit",
            source_location="r/test_triage",
            external_post_id=ext_id,
            post_url=f"https://reddit.com/comments/{ext_id}",
            status=status,
            priority=priority,
            compatibility_score=0.8 if priority else None,
            lead_source="scout_watch",
            remote_visibility="unknown",
            created_at=datetime.utcnow() - timedelta(days=days_old),
        )
        db_session.add(lead)
        db_session.commit()
        return lead

    @pytest.mark.asyncio
    async def test_default_listing_ranks_and_hides_expired(self, auth_client, db_session, watch):
        low = self._lead(db_session, "test_low", priority="low")
        high = self._lead(db_session, "test_high", priority="high", days_old=2)
        self._lead(db_session, "test_expired", status="expired", priority="high")

        data = (await auth_client.get("/leads")).json()
        assert [lead["id"] for lead in data["leads"]] == [high.id, low.id]
        assert data["leads"][0]["priority"] == "high"
        assert data["leads"][0]["compatibility_score"] == 0.8

        newest = (await auth_client.get("/leads?sort=newest")).json()
        assert [lead["id"] for lead in newest["leads"]] == [low.id, high.id]

        expired = (await auth_client.get("/leads?status=expired")).json()
        assert expired["total"] == 1

    @pytest.mark.asyncio
    async def test_posted_within_days_filter(self, auth_client, db_session, watch):
        self._lead(db_session, "test_fresh", days_old=2)
        self._lead(db_session, "test_stale", days_old=20)

        assert (await auth_client.get("/leads?posted_within_days=14")).json()["total"] == 1
        assert (await auth_client.get("/leads")).json()["total"] == 2
        assert (await auth_client.get("/leads?posted_within_days=0")).status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_sort_is_400(self, auth_client, watch):
        response = await auth_client.get("/leads?sort=sideways")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_expired_status_patch_and_revive(self, auth_client, db_session, watch):
        lead = self._lead(db_session, "test_revive")

        expired = await auth_client.patch(f"/leads/{lead.id}/status", json={"status": "expired"})
        assert expired.status_code == 200
        assert expired.json()["status"] == "expired"

        revived = await auth_client.patch(f"/leads/{lead.id}/status", json={"status": "saved"})
        assert revived.status_code == 200
        assert (await auth_client.get("/leads")).json()["total"] == 1


class TestCalibrationReportApi:
    @pytest.mark.asyncio
    async def test_list_newest_first(self, auth_client, db_session):
        now = datetime(2026, 9, 14, 6, 0, 0)
        for weeks_ago in (1, 0):
            end = now - timedelta(weeks=weeks_ago)
            db_session.add(
                CalibrationReport(
                    period_start=end - timedelta(days=7),
                    period_end=end,
                    report_json={"overall": {"weeks_ago": weeks_ago}},
                    created_at=end,
                )
            )
        db_session.commit()

        response = await auth_client.get("/ops/calibration-reports")

        assert response.status_code == 200
        reports = response.json()["reports"]
        assert [r["report"]["overall"]["weeks_ago"] for r in reports] == [0, 1]

    @pytest.mark.asyncio
    async def test_empty_list(self, auth_client, db_session):
        response = await auth_client.get("/ops/calibration-reports")
        assert response.status_code == 200
        assert response.json() == {"reports": []}

    @pytest.mark.asyncio
    async def test_generate_enqueues_and_audits(self, auth_client, db_session):
        fake_app = MagicMock()
        fake_app.send_task.return_value = MagicMock(id="test-task-id")
        with patch("rediska_core.api.routes.ops.get_celery_app", return_value=fake_app):
            response = await auth_client.post("/ops/calibration-reports/generate")

        assert response.status_code == 202
        assert response.json()["job_id"] == "test-task-id"
        fake_app.send_task.assert_called_once()
        assert fake_app.send_task.call_args.args[0] == "maintenance.generate_calibration_report"
        assert (
            db_session.query(AuditLog)
            .filter(AuditLog.action_type == "calibration_report.generate")
            .count()
            == 1
        )
