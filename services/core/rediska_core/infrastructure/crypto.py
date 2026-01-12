"""Encryption utilities for secret storage.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC for authenticity).
Suitable for storing OAuth tokens and other sensitive data.

Usage:
    key = CryptoService.generate_key()  # Store this securely in env
    crypto = CryptoService(key)

    encrypted = crypto.encrypt("my secret")
    decrypted = crypto.decrypt(encrypted)
"""

from cryptography.fernet import Fernet, InvalidToken


class InvalidKeyError(Exception):
    """Raised when an invalid encryption key is provided."""

    pass


class DecryptionError(Exception):
    """Raised when decryption fails."""

    pass


class CryptoService:
    """Encryption service using Fernet (symmetric encryption).

    Fernet guarantees that a message encrypted using it cannot be
    manipulated or read without the key. It uses AES-128-CBC with
    PKCS7 padding and HMAC for authenticity.
    """

    def __init__(self, key: str):
        """Initialize with a Fernet key.

        Args:
            key: A valid Fernet key (base64-encoded 32-byte key).

        Raises:
            InvalidKeyError: If the key is invalid.
        """
        if not key:
            raise InvalidKeyError("Encryption key cannot be empty")

        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as e:
            raise InvalidKeyError(f"Invalid encryption key: {e}")

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key.

        Returns:
            A base64-encoded 32-byte key suitable for Fernet.
        """
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string.

        Args:
            plaintext: The string to encrypt.

        Returns:
            Base64-encoded encrypted ciphertext.
        """
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext string.

        Args:
            ciphertext: Base64-encoded encrypted string.

        Returns:
            Decrypted plaintext string.

        Raises:
            DecryptionError: If decryption fails.
        """
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return plaintext.decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(f"Failed to decrypt: {e}")
        except Exception as e:
            raise DecryptionError(f"Decryption error: {e}")
