"""Embeddings client wrapper for llama.cpp.

This module provides a high-level client for generating embeddings using
llama.cpp's OpenAI-compatible API endpoint.

Usage:
    from rediska_core.infrastructure.embeddings import EmbeddingsClient

    client = EmbeddingsClient(
        url="http://localhost:8080",
        model="nomic-embed-text",
    )

    # Single embedding
    embedding = client.embed("Hello world")

    # Batch embeddings
    embeddings = client.embed_batch(["Hello", "World"])
"""

from typing import Optional

import httpx


# =============================================================================
# EXCEPTIONS
# =============================================================================


class EmbeddingsError(Exception):
    """Base exception for embeddings-related errors."""

    pass


# =============================================================================
# CLIENT
# =============================================================================


class EmbeddingsClient:
    """Client for generating embeddings via llama.cpp API.

    Uses the OpenAI-compatible /v1/embeddings endpoint that llama.cpp provides.
    """

    def __init__(
        self,
        url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout: int = 60,
    ):
        """Initialize the embeddings client.

        Args:
            url: Base URL for the embeddings API (e.g., "http://localhost:8080").
            model: Model name to use for embeddings.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._cached_dimensions: Optional[int] = None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth if configured."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding vector,
            or None if text is empty/whitespace.

        Raises:
            EmbeddingsError: If the API request fails.
        """
        # Skip empty/whitespace text
        if not text or not text.strip():
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.url}/v1/embeddings",
                    headers=self._get_headers(),
                    json={
                        "input": text,
                        "model": self.model,
                    },
                )

                if response.status_code != 200:
                    raise EmbeddingsError(
                        f"API error: {response.status_code} - {response.text}"
                    )

                data = response.json()

                # Validate response format
                if "data" not in data or not data["data"]:
                    raise EmbeddingsError(
                        f"Invalid response format: missing 'data' field"
                    )

                embedding = data["data"][0].get("embedding")
                if embedding is None:
                    raise EmbeddingsError(
                        f"Invalid response format: missing 'embedding' field"
                    )

                # Cache dimensions for later use
                if self._cached_dimensions is None:
                    self._cached_dimensions = len(embedding)

                return embedding

        except httpx.TimeoutException as e:
            raise EmbeddingsError(f"Request timeout: {e}")
        except httpx.ConnectError as e:
            raise EmbeddingsError(f"Connection error: {e}")
        except ConnectionError as e:
            raise EmbeddingsError(f"Connection error: {e}")
        except EmbeddingsError:
            raise
        except Exception as e:
            raise EmbeddingsError(f"Unexpected error: {e}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors (one per input text).
            Empty texts are filtered out.

        Raises:
            EmbeddingsError: If the API request fails.
        """
        if not texts:
            return []

        # Filter out empty texts
        valid_texts = [t for t in texts if t and t.strip()]

        if not valid_texts:
            return []

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.url}/v1/embeddings",
                    headers=self._get_headers(),
                    json={
                        "input": valid_texts,
                        "model": self.model,
                    },
                )

                if response.status_code != 200:
                    raise EmbeddingsError(
                        f"API error: {response.status_code} - {response.text}"
                    )

                data = response.json()

                if "data" not in data:
                    raise EmbeddingsError(
                        f"Invalid response format: missing 'data' field"
                    )

                embeddings = []
                for item in data["data"]:
                    embedding = item.get("embedding")
                    if embedding is None:
                        raise EmbeddingsError(
                            f"Invalid response format: missing 'embedding' field"
                        )
                    embeddings.append(embedding)

                # Cache dimensions
                if embeddings and self._cached_dimensions is None:
                    self._cached_dimensions = len(embeddings[0])

                return embeddings

        except httpx.TimeoutException as e:
            raise EmbeddingsError(f"Request timeout: {e}")
        except httpx.ConnectError as e:
            raise EmbeddingsError(f"Connection error: {e}")
        except ConnectionError as e:
            raise EmbeddingsError(f"Connection error: {e}")
        except EmbeddingsError:
            raise
        except Exception as e:
            raise EmbeddingsError(f"Unexpected error: {e}")

    def get_dimensions(self) -> int:
        """Get the embedding dimension for the configured model.

        Makes a test request if dimensions not cached.

        Returns:
            Number of dimensions in the embedding vector.

        Raises:
            EmbeddingsError: If unable to determine dimensions.
        """
        if self._cached_dimensions is not None:
            return self._cached_dimensions

        # Make a test request to determine dimensions
        embedding = self.embed("test")
        if embedding is None:
            raise EmbeddingsError("Unable to determine embedding dimensions")

        return len(embedding)

    def health_check(self) -> bool:
        """Check if the embeddings API is reachable.

        Returns:
            True if API responds successfully, False otherwise.
        """
        try:
            self.embed("health check")
            return True
        except EmbeddingsError:
            return False

    def truncate_text(self, text: str, max_chars: int = 8000) -> str:
        """Truncate text to a maximum number of characters.

        Most embedding models have token limits. This provides a simple
        character-based truncation. For more accurate truncation,
        use a tokenizer.

        Args:
            text: Text to truncate.
            max_chars: Maximum number of characters.

        Returns:
            Truncated text.
        """
        if len(text) <= max_chars:
            return text

        # Truncate at word boundary if possible
        truncated = text[:max_chars]
        last_space = truncated.rfind(" ")

        if last_space > max_chars * 0.8:  # Only if we don't lose too much
            truncated = truncated[:last_space]

        return truncated


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "EmbeddingsClient",
    "EmbeddingsError",
]
