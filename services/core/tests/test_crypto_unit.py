"""Unit tests for encryption/crypto utility."""

import pytest

from rediska_core.infrastructure.crypto import (
    CryptoService,
    InvalidKeyError,
    DecryptionError,
)


class TestCryptoService:
    """Tests for CryptoService."""

    def test_generate_key_returns_valid_fernet_key(self):
        """generate_key should return a valid Fernet key."""
        key = CryptoService.generate_key()
        # Fernet keys are 44 bytes base64 encoded
        assert len(key) == 44
        # Should be valid base64
        import base64
        decoded = base64.urlsafe_b64decode(key)
        assert len(decoded) == 32  # Fernet uses 256-bit keys

    def test_generate_key_creates_unique_keys(self):
        """generate_key should create unique keys on each call."""
        key1 = CryptoService.generate_key()
        key2 = CryptoService.generate_key()
        assert key1 != key2

    def test_init_with_valid_key(self):
        """Should initialize with a valid Fernet key."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        assert crypto is not None

    def test_init_with_invalid_key_raises_error(self):
        """Should raise InvalidKeyError for invalid keys."""
        with pytest.raises(InvalidKeyError):
            CryptoService("not-a-valid-key")

    def test_init_with_empty_key_raises_error(self):
        """Should raise InvalidKeyError for empty keys."""
        with pytest.raises(InvalidKeyError):
            CryptoService("")

    def test_encrypt_returns_string(self):
        """encrypt should return a string."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        result = crypto.encrypt("hello world")
        assert isinstance(result, str)

    def test_encrypt_returns_different_from_plaintext(self):
        """Encrypted text should be different from plaintext."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = "my secret data"
        encrypted = crypto.encrypt(plaintext)
        assert encrypted != plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self):
        """Same plaintext should produce different ciphertexts (due to nonce)."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = "my secret data"
        encrypted1 = crypto.encrypt(plaintext)
        encrypted2 = crypto.encrypt(plaintext)
        assert encrypted1 != encrypted2

    def test_decrypt_returns_original_plaintext(self):
        """decrypt should return the original plaintext."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = "my secret data"
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_roundtrip_with_unicode(self):
        """encrypt/decrypt should handle unicode correctly."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = "Hello 世界 🌍"
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_roundtrip_with_empty_string(self):
        """encrypt/decrypt should handle empty strings."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = ""
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_decrypt_roundtrip_with_long_string(self):
        """encrypt/decrypt should handle long strings."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)
        plaintext = "x" * 10000
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_decrypt_with_wrong_key_raises_error(self):
        """Decrypting with wrong key should raise DecryptionError."""
        key1 = CryptoService.generate_key()
        key2 = CryptoService.generate_key()
        crypto1 = CryptoService(key1)
        crypto2 = CryptoService(key2)

        encrypted = crypto1.encrypt("secret data")
        with pytest.raises(DecryptionError):
            crypto2.decrypt(encrypted)

    def test_decrypt_corrupted_data_raises_error(self):
        """Decrypting corrupted data should raise DecryptionError."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)

        encrypted = crypto.encrypt("secret data")
        corrupted = encrypted[:-5] + "XXXXX"

        with pytest.raises(DecryptionError):
            crypto.decrypt(corrupted)

    def test_decrypt_invalid_base64_raises_error(self):
        """Decrypting invalid base64 should raise DecryptionError."""
        key = CryptoService.generate_key()
        crypto = CryptoService(key)

        with pytest.raises(DecryptionError):
            crypto.decrypt("not-valid-base64!!!")

    def test_encrypt_json_serializable_data(self):
        """Should be able to encrypt/decrypt JSON data as string."""
        import json
        key = CryptoService.generate_key()
        crypto = CryptoService(key)

        data = {"access_token": "abc123", "refresh_token": "xyz789", "expires_in": 3600}
        plaintext = json.dumps(data)
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)

        assert json.loads(decrypted) == data
