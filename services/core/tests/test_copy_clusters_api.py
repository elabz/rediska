"""Copy cluster API and the `copy` field on lead / scout read models.

Synthetic text and `test_` users only.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AuditLog,
    ExternalAccount,
    LeadPost,
    LocalUser,
    Provider,
    ScoutWatchPost,
)
from rediska_core.domain.services.post_copy import fingerprint_post
from rediska_core.domain.services.scout_watch import ScoutWatchService

BODY = " ".join(f"w{i}" for i in range(300))
NOW = datetime.utcnow()


@pytest.fixture
async def api(test_app, db_session):
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_admin"
    test_app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def ring(db_session):
    """Two live accounts posting the same text, one of them saved as a lead."""
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    acc = ExternalAccount(provider_id="reddit", external_username="test_a")
    db_session.add(acc)
    db_session.flush()
    lead = LeadPost(
        provider_id="reddit", source_location="r/test", external_post_id="test_p1",
        post_url="https://x/test_p1", author_account_id=acc.id, status="saved",
    )
    db_session.add(lead)
    fingerprint_post(db_session, provider_id="reddit", external_post_id="test_p1",
                     author_username="test_a", body_text=BODY, source="lead", posted_at=NOW)
    out = fingerprint_post(db_session, provider_id="reddit", external_post_id="test_p2",
                           author_username="test_b", body_text=BODY, source="scout",
                           posted_at=NOW + timedelta(days=2))
    solo = LeadPost(
        provider_id="reddit", source_location="r/test", external_post_id="test_solo",
        post_url="https://x/test_solo", status="saved",
    )
    db_session.add(solo)
    db_session.commit()
    return {"cluster_id": out.cluster_id, "lead_id": lead.id, "solo_id": solo.id}


@pytest.mark.asyncio
async def test_list_detail_and_filters(api, ring):
    body = (await api.get("/copy-clusters")).json()
    assert [c["id"] for c in body["items"]] == [ring["cluster_id"]]
    item = body["items"][0]
    assert item["kind"] == "ring_suspect" and item["author_count"] == 2

    assert (await api.get("/copy-clusters?kind=returning_author")).json()["items"] == []
    assert len((await api.get("/copy-clusters?decision=none")).json()["items"]) == 1
    assert len((await api.get("/copy-clusters?author=TEST_B")).json()["items"]) == 1
    assert (await api.get("/copy-clusters?author=test_nobody")).json()["items"] == []
    assert (await api.get("/copy-clusters?kind=bogus")).status_code == 400

    detail = (await api.get(f"/copy-clusters/{ring['cluster_id']}")).json()
    authors = [m["author_username"] for m in detail["members"]]
    assert authors == ["test_a", "test_b"]
    assert detail["members"][0]["lead_id"] == ring["lead_id"]
    assert detail["members"][0]["lead_status"] == "saved"
    assert (await api.get("/copy-clusters/99999")).status_code == 404


@pytest.mark.asyncio
async def test_decision_is_audited_and_leaves_leads_alone(api, db_session, ring):
    resp = await api.post(
        f"/copy-clusters/{ring['cluster_id']}/decision",
        json={"decision": "confirmed_ring", "notes": "same photos"},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "confirmed_ring" and resp.json()["computed_kind"] == "ring_suspect"
    assert db_session.query(AuditLog).filter_by(action_type="copy_cluster.decision").count() == 1
    assert db_session.get(LeadPost, ring["lead_id"]).status == "saved"

    bad = await api.post(f"/copy-clusters/{ring['cluster_id']}/decision", json={"decision": "x"})
    assert bad.status_code == 422

    resp = await api.post(
        f"/copy-clusters/{ring['cluster_id']}/decision", json={"decision": "coincidence"}
    )
    assert resp.status_code == 200
    assert (await api.get("/copy-clusters")).json()["items"] == []
    lead = (await api.get(f"/leads/{ring['lead_id']}")).json()
    assert lead["copy"] is None


@pytest.mark.asyncio
async def test_leads_carry_copy_field(api, ring):
    lead = (await api.get(f"/leads/{ring['lead_id']}")).json()
    assert lead["copy"]["cluster_id"] == ring["cluster_id"]
    assert lead["copy"]["kind"] == "ring_suspect" and lead["copy"]["author_count"] == 2
    assert lead["copy"]["earliest_other_posted_at"] is not None

    listed = (await api.get("/leads")).json()
    by_id = {item["id"]: item for item in listed["leads"]}
    assert by_id[ring["lead_id"]]["copy"]["cluster_id"] == ring["cluster_id"]
    assert by_id[ring["solo_id"]]["copy"] is None


@pytest.mark.asyncio
async def test_scout_run_detail_and_needs_review_carry_copy(api, db_session, ring):
    service = ScoutWatchService(db_session)
    watch = service.create_watch(source_location="r/test_watch", search_query="x")
    run = service.create_run(watch.id)
    db_session.add(ScoutWatchPost(
        watch_id=watch.id, run_id=run.id, external_post_id="test_p2", post_author="test_b",
        post_body=BODY, first_seen_at=NOW, analysis_status="analyzed",
        analysis_recommendation="needs_review", analysis_confidence=0.5,
    ))
    db_session.commit()

    detail = (await api.get(f"/scout-watches/{watch.id}/runs/{run.id}")).json()
    assert detail["posts"][0]["copy"]["cluster_id"] == ring["cluster_id"]

    queue = (await api.get("/scout-watches/needs-review")).json()
    assert queue["items"][0]["copy"]["kind"] == "ring_suspect"
