"""Unit tests for message tasks.

Tests cover:
- send_manual task configuration (at-most-once)
- Payload validation

NOTE ON THE STUBBED IMPORTS
send_manual imports a stack of rediska_core symbols at the TOP of its function
body, before the `if not all([...])` payload validation. Off-container
rediska_core is not installed, so those imports raise ModuleNotFoundError and
the validation branch never executes -- which is why the validation tests here
used to be wrapped in try/except + pytest.skip and never actually ran.

Rather than restructuring the source, `stub_rediska_core` injects minimal
placeholder modules into sys.modules so the imports resolve. An invalid payload
then returns BEFORE any of those stubs is called (get_settings() is only
reached after validation passes), so the stubs are never exercised -- the real
validation branch is.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest


# =============================================================================
# FIXTURES
# =============================================================================


_STUBBED_MODULES = {
    "rediska_core": [],
    "rediska_core.config": ["get_settings"],
    "rediska_core.domain": [],
    "rediska_core.domain.models": ["Conversation", "ExternalAccount", "Message", "Attachment"],
    "rediska_core.domain.services": [],
    "rediska_core.domain.services.credentials": ["CredentialsService"],
    "rediska_core.domain.services.send_message": ["SendMessageService"],
    "rediska_core.infra": [],
    "rediska_core.infra.db": ["get_sync_session_factory"],
    "rediska_core.infrastructure": [],
    "rediska_core.infrastructure.crypto": ["CryptoService"],
    "rediska_core.providers": [],
    "rediska_core.providers.reddit": [],
    "rediska_core.providers.reddit.adapter": ["RedditAdapter"],
}


@pytest.fixture
def stub_rediska_core():
    """Install placeholder rediska_core modules for the duration of a test.

    Only lets send_manual's import block succeed; every attribute is a MagicMock
    that an invalid payload never reaches.
    """
    if "rediska_core" in sys.modules:
        # Running on-container with the real package: nothing to stub.
        yield
        return

    created = []
    for module_name, attrs in _STUBBED_MODULES.items():
        module = types.ModuleType(module_name)
        for attr in attrs:
            setattr(module, attr, MagicMock(name=f"{module_name}.{attr}"))
        sys.modules[module_name] = module
        created.append(module_name)

    try:
        yield
    finally:
        for module_name in created:
            sys.modules.pop(module_name, None)


# =============================================================================
# TASK CONFIGURATION (AT-MOST-ONCE)
# =============================================================================


class TestSendManualTaskConfig:
    """The task's Celery configuration IS the at-most-once guarantee."""

    def test_task_has_no_retries(self, mock_celery_app):
        """max_retries=0: a failed send is never automatically re-attempted."""
        from rediska_worker.tasks.message import send_manual

        assert send_manual.max_retries == 0

    def test_task_acks_early(self, mock_celery_app):
        """acks_late=False: the broker never redelivers this task.

        With acks_late=True a worker crash mid-send would requeue the task and
        the message could go out twice.
        """
        from rediska_worker.tasks.message import send_manual

        assert send_manual.acks_late is False


# =============================================================================
# PAYLOAD VALIDATION
# =============================================================================


class TestSendManualPayloadValidation:
    """The `if not all([...])` guard, actually executed."""

    REQUIRED = ("message_id", "conversation_id", "identity_id", "provider_id", "body_text")

    def _valid_payload(self):
        return {
            "message_id": 1,
            "conversation_id": 2,
            "identity_id": 3,
            "provider_id": "reddit",
            "body_text": "Test message",
        }

    @pytest.mark.parametrize("missing_field", REQUIRED)
    def test_missing_required_field_returns_error(
        self, mock_celery_app, stub_rediska_core, missing_field
    ):
        """Each required field, dropped individually, must be rejected."""
        from rediska_worker.tasks.message import send_manual

        payload = self._valid_payload()
        del payload[missing_field]

        result = send_manual.apply(args=[payload]).get()

        assert result["status"] == "error"
        assert result["error"] == "Missing required payload fields"
        # No send was attempted for the incomplete payload.
        assert "external_message_id" not in result

    def test_empty_body_text_is_rejected(self, mock_celery_app, stub_rediska_core):
        """An empty body is falsy, so `all([...])` rejects it like a missing one.

        This matters: an empty outbound message must never reach the provider.
        """
        from rediska_worker.tasks.message import send_manual

        payload = self._valid_payload()
        payload["body_text"] = ""

        result = send_manual.apply(args=[payload]).get()

        assert result["status"] == "error"
        assert result["error"] == "Missing required payload fields"

    def test_empty_payload_returns_error(self, mock_celery_app, stub_rediska_core):
        """A completely empty payload is rejected rather than crashing."""
        from rediska_worker.tasks.message import send_manual

        result = send_manual.apply(args=[{}]).get()

        assert result["status"] == "error"
        assert result["error"] == "Missing required payload fields"
        assert result["message_id"] is None

    def test_error_response_echoes_message_id(self, mock_celery_app, stub_rediska_core):
        """The rejection carries message_id back so the row can be reconciled."""
        from rediska_worker.tasks.message import send_manual

        payload = self._valid_payload()
        del payload["body_text"]

        result = send_manual.apply(args=[payload]).get()

        assert result["message_id"] == 1
