"""Identity management service for Rediska.

Provides identity CRUD operations, default identity management,
and voice configuration validation.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from rediska_core.domain.models import Identity, Provider

# Maximum length for system prompt
MAX_SYSTEM_PROMPT_LENGTH = 10000


def validate_voice_config(voice_config: Optional[dict]) -> None:
    """Validate voice configuration.

    Args:
        voice_config: The voice configuration to validate.

    Raises:
        ValueError: If the configuration is invalid.
    """
    if voice_config is None or voice_config == {}:
        return

    # Validate system_prompt length
    system_prompt = voice_config.get("system_prompt")
    if system_prompt and len(system_prompt) > MAX_SYSTEM_PROMPT_LENGTH:
        raise ValueError(
            f"system_prompt must not exceed {MAX_SYSTEM_PROMPT_LENGTH} characters"
        )


class IdentityService:
    """Service for identity management operations."""

    def __init__(self, db: DBSession):
        """Initialize the identity service.

        Args:
            db: SQLAlchemy database session.
        """
        self.db = db

    def create_identity(
        self,
        provider_id: str,
        external_username: str,
        display_name: str,
        external_user_id: Optional[str] = None,
        voice_config: Optional[dict] = None,
    ) -> Identity:
        """Create a new identity.

        Args:
            provider_id: The provider ID.
            external_username: The external username.
            display_name: The display name for the identity.
            external_user_id: Optional external user ID.
            voice_config: Optional voice configuration.

        Returns:
            The created Identity.

        Raises:
            ValueError: If validation fails.
        """
        # Validate provider exists
        provider = self.db.query(Provider).filter_by(provider_id=provider_id).first()
        if provider is None:
            raise ValueError(f"provider '{provider_id}' does not exist")

        # Validate username
        if not external_username or len(external_username.strip()) == 0:
            raise ValueError("external_username must not be empty")

        # Validate display name
        if not display_name or len(display_name.strip()) == 0:
            raise ValueError("display_name must not be empty")

        # Check for duplicate username
        existing = (
            self.db.query(Identity)
            .filter_by(provider_id=provider_id, external_username=external_username)
            .first()
        )
        if existing is not None:
            raise ValueError(
                f"identity with username '{external_username}' already exists for provider '{provider_id}'"
            )

        # Validate voice config
        validate_voice_config(voice_config)

        # Check if this is the first identity for this provider
        existing_count = (
            self.db.query(Identity)
            .filter_by(provider_id=provider_id, is_active=True)
            .count()
        )
        is_default = existing_count == 0

        # Create identity
        identity = Identity(
            provider_id=provider_id,
            external_username=external_username.strip(),
            external_user_id=external_user_id,
            display_name=display_name.strip(),
            voice_config_json=voice_config or {},
            is_default=is_default,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.db.add(identity)
        self.db.flush()

        return identity

    def get_identity(
        self, identity_id: int, include_inactive: bool = False
    ) -> Optional[Identity]:
        """Get an identity by ID.

        Args:
            identity_id: The identity ID.
            include_inactive: Whether to include inactive identities.

        Returns:
            The Identity or None if not found.
        """
        query = self.db.query(Identity).filter_by(id=identity_id)

        if not include_inactive:
            query = query.filter_by(is_active=True)

        return query.first()

    def list_identities(
        self,
        provider_id: Optional[str] = None,
        include_inactive: bool = False,
    ) -> list[Identity]:
        """List identities with optional filtering.

        Args:
            provider_id: Optional provider ID to filter by.
            include_inactive: Whether to include inactive identities.

        Returns:
            List of identities.
        """
        query = self.db.query(Identity)

        if provider_id:
            query = query.filter_by(provider_id=provider_id)

        if not include_inactive:
            query = query.filter_by(is_active=True)

        return query.order_by(Identity.created_at.desc()).all()

    def list_identities_grouped(
        self, include_inactive: bool = False
    ) -> dict[str, list[Identity]]:
        """List identities grouped by provider.

        Args:
            include_inactive: Whether to include inactive identities.

        Returns:
            Dictionary mapping provider_id to list of identities.
        """
        identities = self.list_identities(include_inactive=include_inactive)

        grouped: dict[str, list[Identity]] = {}
        for identity in identities:
            if identity.provider_id not in grouped:
                grouped[identity.provider_id] = []
            grouped[identity.provider_id].append(identity)

        return grouped

    def update_identity(
        self,
        identity_id: int,
        display_name: Optional[str] = None,
        voice_config: Optional[dict] = None,
        is_active: Optional[bool] = None,
    ) -> Identity:
        """Update an identity.

        Args:
            identity_id: The identity ID.
            display_name: New display name (optional).
            voice_config: New voice configuration (optional).
            is_active: New active status (optional).

        Returns:
            The updated Identity.

        Raises:
            ValueError: If identity not found or validation fails.
        """
        identity = self.get_identity(identity_id, include_inactive=True)
        if identity is None:
            raise ValueError(f"identity {identity_id} not found")

        if display_name is not None:
            if len(display_name.strip()) == 0:
                raise ValueError("display_name must not be empty")
            identity.display_name = display_name.strip()

        if voice_config is not None:
            validate_voice_config(voice_config)
            identity.voice_config_json = voice_config

        if is_active is not None:
            identity.is_active = is_active

        identity.updated_at = datetime.now(timezone.utc)
        self.db.flush()

        return identity

    def delete_identity(self, identity_id: int) -> None:
        """Delete (deactivate) an identity.

        Args:
            identity_id: The identity ID.

        Raises:
            ValueError: If identity not found or cannot be deleted.
        """
        identity = self.get_identity(identity_id, include_inactive=True)
        if identity is None:
            raise ValueError(f"identity {identity_id} not found")

        # If already inactive, nothing to do
        if not identity.is_active:
            return

        # Check if this is the only default identity
        if identity.is_default:
            # Check if there are other active identities for this provider
            other_active = (
                self.db.query(Identity)
                .filter(
                    Identity.provider_id == identity.provider_id,
                    Identity.id != identity.id,
                    Identity.is_active == True,  # noqa: E712
                )
                .first()
            )

            if other_active is None:
                raise ValueError(
                    "cannot delete the only default identity; "
                    "create another identity first or set a different default"
                )

            # Promote the next identity to default
            other_active.is_default = True

        # Soft delete
        identity.is_active = False
        identity.is_default = False
        identity.updated_at = datetime.now(timezone.utc)
        self.db.flush()

    def set_default_identity(self, identity_id: int) -> Identity:
        """Set an identity as the default for its provider.

        Args:
            identity_id: The identity ID.

        Returns:
            The updated Identity.

        Raises:
            ValueError: If identity not found.
        """
        identity = self.get_identity(identity_id)
        if identity is None:
            raise ValueError(f"identity {identity_id} not found")

        # Clear existing default for this provider
        self.db.query(Identity).filter(
            Identity.provider_id == identity.provider_id,
            Identity.is_default == True,  # noqa: E712
        ).update({"is_default": False})

        # Set new default
        identity.is_default = True
        identity.updated_at = datetime.now(timezone.utc)
        self.db.flush()

        return identity

    def get_default_identity(self, provider_id: str) -> Optional[Identity]:
        """Get the default identity for a provider.

        Args:
            provider_id: The provider ID.

        Returns:
            The default Identity or None if not found.
        """
        return (
            self.db.query(Identity)
            .filter_by(provider_id=provider_id, is_default=True, is_active=True)
            .first()
        )

    def has_any_identity(self) -> bool:
        """Check if any active identity exists.

        Returns:
            True if at least one active identity exists.
        """
        return self.db.query(Identity).filter_by(is_active=True).count() > 0

    def get_setup_status(self) -> dict:
        """Get the onboarding setup status.

        Returns:
            Dictionary with setup status information.
        """
        has_identity = self.has_any_identity()

        return {
            "has_identity": has_identity,
            "is_complete": has_identity,
        }
