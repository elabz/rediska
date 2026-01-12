"""Credentials service for secure storage of provider secrets.

Handles storage, retrieval, and rotation of encrypted credentials
(OAuth tokens, API keys, etc.) for provider integrations.

Usage:
    from rediska_core.infrastructure.crypto import CryptoService
    from rediska_core.domain.services.credentials import CredentialsService

    crypto = CryptoService(settings.encryption_key)
    service = CredentialsService(db_session, crypto)

    # Store OAuth tokens
    service.store_credential(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_refresh_token",
        secret=refresh_token,
    )

    # Retrieve decrypted token
    token = service.get_credential_decrypted(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_refresh_token",
    )
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.domain.models import ProviderCredential
from rediska_core.infrastructure.crypto import CryptoService


class CredentialsService:
    """Service for managing encrypted provider credentials."""

    def __init__(self, db: Session, crypto: CryptoService):
        """Initialize the service.

        Args:
            db: SQLAlchemy database session.
            crypto: CryptoService instance for encryption/decryption.
        """
        self.db = db
        self.crypto = crypto

    def store_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
        secret: str,
    ) -> ProviderCredential:
        """Store or update a credential with encryption.

        If a credential with the same (provider_id, identity_id, credential_type)
        already exists, it will be updated and rotated_at will be set.

        Args:
            provider_id: Provider identifier (e.g., "reddit").
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential (e.g., "oauth_refresh_token").
            secret: Plaintext secret to encrypt and store.

        Returns:
            The created or updated ProviderCredential.
        """
        # Check for existing credential
        existing = self._find_credential(provider_id, identity_id, credential_type)

        encrypted = self.crypto.encrypt(secret)

        if existing:
            # Update existing credential
            existing.secret_encrypted = encrypted
            existing.rotated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # Create new credential
        credential = ProviderCredential(
            provider_id=provider_id,
            identity_id=identity_id,
            credential_type=credential_type,
            secret_encrypted=encrypted,
        )
        self.db.add(credential)
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def get_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
    ) -> Optional[ProviderCredential]:
        """Get a credential record (secret remains encrypted).

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.

        Returns:
            ProviderCredential if found, None otherwise.
        """
        return self._find_credential(provider_id, identity_id, credential_type)

    def get_credential_decrypted(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
    ) -> Optional[str]:
        """Get a credential's decrypted secret.

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.

        Returns:
            Decrypted secret string if found, None otherwise.
        """
        credential = self._find_credential(provider_id, identity_id, credential_type)
        if credential is None:
            return None
        return self.crypto.decrypt(credential.secret_encrypted)

    def rotate_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
        new_secret: str,
    ) -> Optional[ProviderCredential]:
        """Rotate a credential with a new secret.

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.
            new_secret: New plaintext secret.

        Returns:
            Updated ProviderCredential if found, None otherwise.
        """
        credential = self._find_credential(provider_id, identity_id, credential_type)
        if credential is None:
            return None

        credential.secret_encrypted = self.crypto.encrypt(new_secret)
        credential.rotated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def delete_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
    ) -> bool:
        """Delete a credential.

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.

        Returns:
            True if deleted, False if not found.
        """
        credential = self._find_credential(provider_id, identity_id, credential_type)
        if credential is None:
            return False

        self.db.delete(credential)
        self.db.commit()
        return True

    def list_credentials(
        self,
        provider_id: str,
        identity_id: Optional[int] = None,
    ) -> list[ProviderCredential]:
        """List credentials for a provider.

        Args:
            provider_id: Provider identifier.
            identity_id: Optional identity ID to filter by.

        Returns:
            List of ProviderCredential records.
        """
        query = self.db.query(ProviderCredential).filter(
            ProviderCredential.provider_id == provider_id
        )

        if identity_id is not None:
            query = query.filter(ProviderCredential.identity_id == identity_id)

        return query.all()

    def has_valid_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
    ) -> bool:
        """Check if a valid credential exists.

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.

        Returns:
            True if credential exists, False otherwise.
        """
        credential = self._find_credential(provider_id, identity_id, credential_type)
        return credential is not None

    def _find_credential(
        self,
        provider_id: str,
        identity_id: Optional[int],
        credential_type: str,
    ) -> Optional[ProviderCredential]:
        """Find a credential by its unique key.

        Args:
            provider_id: Provider identifier.
            identity_id: Identity ID (None for app-level credentials).
            credential_type: Type of credential.

        Returns:
            ProviderCredential if found, None otherwise.
        """
        query = self.db.query(ProviderCredential).filter(
            ProviderCredential.provider_id == provider_id,
            ProviderCredential.credential_type == credential_type,
        )

        if identity_id is None:
            query = query.filter(ProviderCredential.identity_id.is_(None))
        else:
            query = query.filter(ProviderCredential.identity_id == identity_id)

        return query.first()
