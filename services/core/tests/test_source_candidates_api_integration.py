"""API integration tests for /source-candidates (source-discovery).

All candidates, locations, and search results are synthetic. The provider and
Celery are patched: no request leaves the test.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AuditLog,
    LocalUser,
    Provider,
    ScoutWatch,
    SourceCandidate,
    SourceTrial,
)
from rediska_core.providers.base import ProviderLocation

NOW = datetime.utcnow()


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
def provider(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.commit()


def add_candidate(db, name, kind="location", lift: float | None = 2.0, status="new", info=True):
    c = SourceCandidate(
        provider_id="reddit", kind=kind, name=name, origin="mined", status=status,
        evidence_json={"qualified_authors": 4}, evidence_count=4, lift=lift,
        created_at=NOW, updated_at=NOW,
    )
    if info and kind == "location":
        # Pre-cached so list calls don't try the provider.
        c.location_info_json = {"name": name, "description": "synthetic", "is_nsfw": True}
        c.location_info_fetched_at = NOW
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def no_enqueue():
    with patch("rediska_core.api.routes.source_candidates._enqueue_trial") as mock:
        yield mock


def audit_actions(db):
    return [a.action_type for a in db.query(AuditLog).order_by(AuditLog.id).all()]


class TestList:
    async def test_default_list_sorted_by_lift_with_info(self, auth_client, db_session, provider):
        add_candidate(db_session, "r/test_low", lift=1.1)
        add_candidate(db_session, "r/test_high", lift=3.5)
        add_candidate(db_session, "r/test_gone", status="dismissed")
        add_candidate(db_session, "listings.example.test", kind="external_host", lift=None)

        resp = await auth_client.get("/source-candidates")

        assert resp.status_code == 200
        body = resp.json()
        assert [c["name"] for c in body["items"]] == [
            "r/test_high", "r/test_low", "listings.example.test"
        ]
        assert body["items"][0]["location_info"]["is_nsfw"] is True
        assert body["total"] == 3 and body["next_cursor"] is None

    async def test_filters_and_cursor(self, auth_client, db_session, provider):
        for i in range(3):
            add_candidate(db_session, f"r/test_{i}", lift=float(i + 1))
        add_candidate(db_session, "r/test_gone", status="dismissed")

        page = (await auth_client.get("/source-candidates?kind=location&limit=2")).json()
        assert len(page["items"]) == 2 and page["next_cursor"] == "2"
        rest = (await auth_client.get(f"/source-candidates?limit=2&cursor={page['next_cursor']}")).json()
        assert [c["name"] for c in rest["items"]] == ["r/test_0"]

        dismissed = (await auth_client.get("/source-candidates?status=dismissed")).json()
        assert [c["name"] for c in dismissed["items"]] == ["r/test_gone"]

        assert (await auth_client.get("/source-candidates?status=bogus")).status_code == 400
        assert (await auth_client.get("/source-candidates?cursor=x")).status_code == 400

    async def test_empty_list(self, auth_client, db_session, provider):
        body = (await auth_client.get("/source-candidates")).json()
        assert body["items"] == [] and body["total"] == 0

    async def test_location_info_fetched_lazily_and_cached(self, auth_client, db_session, provider):
        add_candidate(db_session, "r/test_fresh", info=False)
        add_candidate(db_session, "r/test_private", info=False)
        adapter = MagicMock()

        async def info(name):
            if name == "r/test_private":
                return None
            return ProviderLocation(name=name, description="about", member_count=50, is_nsfw=True)

        adapter.get_location_info = AsyncMock(side_effect=info)
        adapter.aclose = AsyncMock()

        with patch(
            "rediska_core.providers.reddit.factory.adapter_for_identity", return_value=adapter
        ):
            first = (await auth_client.get("/source-candidates")).json()
            second = (await auth_client.get("/source-candidates")).json()

        by_name = {c["name"]: c for c in first["items"]}
        assert by_name["r/test_fresh"]["location_info"]["member_count"] == 50
        assert by_name["r/test_private"]["location_unavailable"] is True
        assert adapter.get_location_info.await_count == 2  # cached for the second call
        assert second["items"]


class TestLifecycle:
    async def test_dismiss_restore_snooze(self, auth_client, db_session, provider):
        c = add_candidate(db_session, "r/test_c")

        resp = await auth_client.post(f"/source-candidates/{c.id}/dismiss")
        assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
        assert (await auth_client.post(f"/source-candidates/{c.id}/snooze",
                                       json={"until": (NOW + timedelta(days=3)).isoformat()})
                ).status_code == 409

        resp = await auth_client.post(f"/source-candidates/{c.id}/restore")
        assert resp.json()["status"] == "new"

        until = (NOW + timedelta(days=3)).isoformat()
        resp = await auth_client.post(f"/source-candidates/{c.id}/snooze", json={"until": until})
        assert resp.json()["status"] == "snoozed"
        listed = (await auth_client.get("/source-candidates")).json()
        assert listed["items"] == []

        assert audit_actions(db_session) == [
            "source_candidate.dismiss", "source_candidate.restore", "source_candidate.snooze",
        ]

    async def test_unknown_candidate_404(self, auth_client, db_session, provider):
        assert (await auth_client.post("/source-candidates/999/dismiss")).status_code == 404

    async def test_accept_creates_exactly_one_watch(self, auth_client, db_session, provider):
        c = add_candidate(db_session, "r/test_accept")

        resp = await auth_client.post(
            f"/source-candidates/{c.id}/accept",
            json={"search_query": "test query", "sort_by": "new", "min_confidence": 0.8},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["candidate"]["status"] == "accepted"
        assert body["converted_trial_watch"] is False
        watches = db_session.query(ScoutWatch).all()
        assert len(watches) == 1
        assert watches[0].id == body["watch_id"] and watches[0].search_query == "test query"
        assert watches[0].is_trial is False and watches[0].is_active is True

        again = await auth_client.post(f"/source-candidates/{c.id}/accept", json={})
        assert again.status_code == 409
        assert db_session.query(ScoutWatch).count() == 1
        assert audit_actions(db_session) == ["source_candidate.accept"]

    async def test_external_host_cannot_be_accepted(self, auth_client, db_session, provider):
        c = add_candidate(db_session, "listings.example.test", kind="external_host", lift=None)

        resp = await auth_client.post(f"/source-candidates/{c.id}/accept", json={})

        assert resp.status_code == 400
        assert db_session.query(ScoutWatch).count() == 0


class TestManualAndSearch:
    async def test_search_annotates_watched_candidate_dismissed(self, auth_client, db_session, provider):
        db_session.add(ScoutWatch(provider_id="reddit", source_location="r/test_watched"))
        db_session.commit()
        cand = add_candidate(db_session, "r/test_cand")
        gone = add_candidate(db_session, "r/test_gone", status="dismissed")

        adapter = MagicMock()
        adapter.search_locations = AsyncMock(return_value=[
            ProviderLocation(name=n, is_nsfw=True)
            for n in ("r/Test_Watched", "r/test_cand", "r/test_gone", "r/test_new")
        ])
        adapter.aclose = AsyncMock()

        with patch(
            "rediska_core.providers.reddit.factory.adapter_for_identity", return_value=adapter
        ):
            resp = await auth_client.get("/source-candidates/search?q=test")

        assert resp.status_code == 200
        results = {r["name"]: r for r in resp.json()["results"]}
        assert results["r/Test_Watched"]["watched"] is True
        assert results["r/test_cand"]["candidate_id"] == cand.id
        assert results["r/test_gone"]["candidate_status"] == "dismissed"
        assert results["r/test_new"] == {**results["r/test_new"], "watched": False,
                                        "candidate_id": None}
        assert all(r["is_nsfw"] for r in results.values())  # never filtered
        assert gone.status == "dismissed"

    async def test_manual_add_then_trial(self, auth_client, db_session, provider, no_enqueue):
        resp = await auth_client.post(
            "/source-candidates",
            json={"name": "r/test_manual", "location_info": {"name": "r/test_manual", "member_count": 9}},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["origin"] == "manual" and body["location_info"]["member_count"] == 9

        trial = await auth_client.post(f"/source-candidates/{body['id']}/trial", json={})
        assert trial.status_code == 202

        dup = await auth_client.post("/source-candidates", json={"name": "r/test_manual"})
        assert dup.status_code == 409

    async def test_watched_location_cannot_be_added(self, auth_client, db_session, provider):
        db_session.add(ScoutWatch(provider_id="reddit", source_location="r/test_watched"))
        db_session.commit()

        resp = await auth_client.post("/source-candidates", json={"name": "test_watched"})

        assert resp.status_code == 409
        assert db_session.query(SourceCandidate).count() == 0


class TestTrials:
    async def test_trial_start_conflict_and_cancel(self, auth_client, db_session, provider, no_enqueue):
        a = add_candidate(db_session, "r/test_a")
        b = add_candidate(db_session, "r/test_b")

        resp = await auth_client.post(f"/source-candidates/{a.id}/trial", json={"sample_size": 10})
        assert resp.status_code == 202
        trial = resp.json()
        assert trial["status"] == "queued" and trial["sample_size"] == 10
        no_enqueue.assert_called_once_with(trial["id"])

        second = await auth_client.post(f"/source-candidates/{b.id}/trial", json={})
        assert second.status_code == 409
        assert no_enqueue.call_count == 1
        assert db_session.query(SourceTrial).count() == 1

        listed = (await auth_client.get("/source-candidates")).json()
        assert listed["running_trial"]["id"] == trial["id"]
        row = next(c for c in listed["items"] if c["id"] == a.id)
        assert row["latest_trial"]["sample_size"] == 10

        cancelled = await auth_client.post(f"/source-candidates/trials/{trial['id']}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

        assert audit_actions(db_session) == ["source_trial.start", "source_trial.cancel"]

    async def test_external_host_trial_rejected(self, auth_client, db_session, provider, no_enqueue):
        c = add_candidate(db_session, "listings.example.test", kind="external_host", lift=None)

        resp = await auth_client.post(f"/source-candidates/{c.id}/trial", json={})

        assert resp.status_code == 400
        no_enqueue.assert_not_called()

    async def test_trial_watch_hidden_from_watch_list(self, auth_client, db_session, provider, no_enqueue):
        c = add_candidate(db_session, "r/test_hidden")
        await auth_client.post(f"/source-candidates/{c.id}/trial", json={})

        watches = (await auth_client.get("/scout-watches")).json()["watches"]

        assert watches == []

    async def test_accept_after_trial_converts_in_place(self, auth_client, db_session, provider, no_enqueue):
        c = add_candidate(db_session, "r/test_conv")
        trial_id = (await auth_client.post(f"/source-candidates/{c.id}/trial", json={})).json()["id"]
        trial = db_session.get(SourceTrial, trial_id)
        trial.status = "completed"
        db_session.commit()

        resp = await auth_client.post(f"/source-candidates/{c.id}/accept", json={})

        assert resp.json()["converted_trial_watch"] is True
        assert resp.json()["watch_id"] == trial.watch_id
        assert db_session.query(ScoutWatch).count() == 1
        watches = (await auth_client.get("/scout-watches")).json()["watches"]
        assert [w["id"] for w in watches] == [trial.watch_id]
        assert watches[0]["yield_30d"]["window_days"] == 30
