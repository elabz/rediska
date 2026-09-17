"""API-level tests for the inbox export / import / clear endpoints.

Celery dispatch is mocked -- these tests cover the HTTP contract (validation,
confirmation, path safety, audit logging), not the background execution, which
`test_inbox_transfer_unit.py` covers directly against the services.

All payloads are synthetic.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.domain.models import AuditLog, LocalUser
from rediska_core.domain.services.inbox_transfer import DUMP_FORMAT, DUMP_VERSION

CLEAR_PHRASE = "CLEAR MY INBOX"


def _valid_dump() -> dict:
    return {
        "format": DUMP_FORMAT,
        "version": DUMP_VERSION,
        "identities": [],
        "external_accounts": [],
        "conversations": [],
        "messages": [],
        "attachments": [],
    }


@pytest.fixture
def transfer_app(test_app, db_session, tmp_path):
    """Test app with auth stubbed out and the export dir pointed at tmp_path."""
    from rediska_core.api.deps import get_current_user

    user = LocalUser(username="tester", password_hash="x")
    db_session.add(user)
    db_session.commit()

    test_app.dependency_overrides[get_current_user] = lambda: user

    export_dir = tmp_path / "inbox-exports"
    export_dir.mkdir(parents=True)

    with patch("rediska_core.api.routes.inbox.export_dir", return_value=export_dir):
        yield test_app, export_dir

    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def api(transfer_app):
    app, export_dir = transfer_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, export_dir


@pytest.fixture
def mock_celery():
    """Stub Celery dispatch, returning a predictable task id."""
    task = MagicMock()
    task.id = "test-task-id"
    app = MagicMock()
    app.send_task.return_value = task

    with patch("rediska_core.api.routes.inbox.get_celery_app", return_value=app):
        yield app


# =============================================================================
# Export
# =============================================================================


class TestExportEndpoints:
    async def test_export_queues_job(self, api, mock_celery, db_session):
        client, _ = api

        response = await client.post("/inbox/export", json={})

        assert response.status_code == 202
        assert response.json()["job_id"] == "test-task-id"
        mock_celery.send_task.assert_called_once()
        assert mock_celery.send_task.call_args.args[0] == "inbox.export"

    async def test_export_is_audited(self, api, mock_celery, db_session):
        client, _ = api
        await client.post("/inbox/export", json={})

        entry = (
            db_session.query(AuditLog)
            .filter_by(action_type="inbox.export.trigger")
            .one()
        )
        assert entry.result == "ok"

    async def test_list_exports_empty(self, api):
        client, _ = api

        response = await client.get("/inbox/exports")

        assert response.status_code == 200
        assert response.json()["exports"] == []

    async def test_list_exports_returns_files(self, api):
        client, export_dir = api
        (export_dir / "inbox_a.json").write_text("{}")
        (export_dir / "inbox_b.json").write_text("{}")

        response = await client.get("/inbox/exports")

        names = {item["filename"] for item in response.json()["exports"]}
        assert names == {"inbox_a.json", "inbox_b.json"}

    async def test_download_export(self, api):
        client, export_dir = api
        (export_dir / "inbox_a.json").write_text('{"format": "rediska.inbox"}')

        response = await client.get("/inbox/exports/inbox_a.json")

        assert response.status_code == 200
        assert response.json()["format"] == "rediska.inbox"

    async def test_download_missing_export_404s(self, api):
        client, _ = api

        response = await client.get("/inbox/exports/nope.json")

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "filename",
        ["../secrets.json", "..%2Fsecrets.json", "sub/dir.json"],
    )
    async def test_download_rejects_path_traversal(self, api, filename):
        client, _ = api

        response = await client.get(f"/inbox/exports/{filename}")

        # Either rejected outright or simply not found -- never a file outside
        # the export directory.
        assert response.status_code in (400, 404)


# =============================================================================
# Import
# =============================================================================


class TestImportEndpoint:
    async def test_import_accepts_valid_dump(self, api, mock_celery):
        client, _ = api
        payload = json.dumps(_valid_dump()).encode()

        response = await client.post(
            "/inbox/import",
            files={"file": ("dump.json", payload, "application/json")},
        )

        assert response.status_code == 202
        assert response.json()["job_id"] == "test-task-id"
        assert mock_celery.send_task.call_args.args[0] == "inbox.import"

    async def test_import_rejects_malformed_json(self, api, mock_celery):
        client, _ = api

        response = await client.post(
            "/inbox/import",
            files={"file": ("dump.json", b"{not json", "application/json")},
        )

        assert response.status_code == 400
        assert "Invalid dump file" in response.json()["detail"]
        mock_celery.send_task.assert_not_called()

    async def test_import_rejects_wrong_format(self, api, mock_celery):
        client, _ = api
        payload = json.dumps({"format": "some-other-tool", "version": 1}).encode()

        response = await client.post(
            "/inbox/import",
            files={"file": ("dump.json", payload, "application/json")},
        )

        assert response.status_code == 400
        mock_celery.send_task.assert_not_called()

    async def test_rejected_import_is_audited_as_error(
        self, api, mock_celery, db_session
    ):
        client, _ = api
        await client.post(
            "/inbox/import",
            files={"file": ("dump.json", b"{not json", "application/json")},
        )

        entry = (
            db_session.query(AuditLog)
            .filter_by(action_type="inbox.import.trigger")
            .one()
        )
        assert entry.result == "error"

    async def test_rejected_upload_is_not_left_on_disk(self, api, mock_celery):
        client, export_dir = api
        await client.post(
            "/inbox/import",
            files={"file": ("dump.json", b"{not json", "application/json")},
        )

        staged = list((export_dir / "incoming").glob("*")) if (
            export_dir / "incoming"
        ).exists() else []
        assert staged == []


# =============================================================================
# Clear
# =============================================================================


class TestClearEndpoint:
    async def test_clear_requires_exact_phrase(self, api, mock_celery):
        client, _ = api

        response = await client.post(
            "/inbox/clear", json={"confirmation": "clear my inbox"}
        )

        assert response.status_code == 400
        mock_celery.send_task.assert_not_called()

    async def test_clear_rejects_empty_confirmation(self, api, mock_celery):
        client, _ = api

        response = await client.post("/inbox/clear", json={"confirmation": ""})

        assert response.status_code == 400
        mock_celery.send_task.assert_not_called()

    async def test_clear_queues_job_with_correct_phrase(self, api, mock_celery):
        client, _ = api

        response = await client.post(
            "/inbox/clear", json={"confirmation": CLEAR_PHRASE}
        )

        assert response.status_code == 202
        assert mock_celery.send_task.call_args.args[0] == "inbox.clear"
        assert mock_celery.send_task.call_args.kwargs["kwargs"] == {"confirm": True}

    async def test_failed_confirmation_is_audited(self, api, mock_celery, db_session):
        client, _ = api
        await client.post("/inbox/clear", json={"confirmation": "wrong"})

        entry = (
            db_session.query(AuditLog).filter_by(action_type="inbox.clear.trigger").one()
        )
        assert entry.result == "error"


# =============================================================================
# Progress
# =============================================================================


class TestJobStatusEndpoint:
    async def test_reports_progress_state(self, api):
        client, _ = api
        result = MagicMock()
        result.state = "PROGRESS"
        result.info = {"stage": "messages", "done": 5, "total": 20}

        with patch("rediska_core.api.routes.inbox.AsyncResult", return_value=result):
            response = await client.get("/inbox/jobs/test-task-id")

        body = response.json()
        assert body["status"] == "running"
        assert body["stage"] == "messages"
        assert body["percent"] == 25.0

    async def test_reports_completion(self, api):
        client, _ = api
        result = MagicMock()
        result.state = "SUCCESS"
        result.ready.return_value = True
        result.successful.return_value = True
        result.result = {"messages": {"created": 3}}

        with patch("rediska_core.api.routes.inbox.AsyncResult", return_value=result):
            response = await client.get("/inbox/jobs/test-task-id")

        body = response.json()
        assert body["status"] == "completed"
        assert body["percent"] == 100.0
        assert body["result"]["messages"]["created"] == 3

    async def test_reports_failure(self, api):
        client, _ = api
        result = MagicMock()
        result.state = "FAILURE"
        result.ready.return_value = True
        result.successful.return_value = False
        result.result = RuntimeError("boom")

        with patch("rediska_core.api.routes.inbox.AsyncResult", return_value=result):
            response = await client.get("/inbox/jobs/test-task-id")

        body = response.json()
        assert body["status"] == "failed"
        assert "boom" in body["error"]

    async def test_reports_pending(self, api):
        client, _ = api
        result = MagicMock()
        result.state = "PENDING"
        result.ready.return_value = False

        with patch("rediska_core.api.routes.inbox.AsyncResult", return_value=result):
            response = await client.get("/inbox/jobs/test-task-id")

        assert response.json()["status"] == "pending"
