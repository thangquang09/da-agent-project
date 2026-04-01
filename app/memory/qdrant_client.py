from __future__ import annotations

import os
from functools import lru_cache

from app.logger import logger

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    QdrantClient = None
    Distance = None
    VectorParams = None

try:
    from sentence_transformers import SentenceTransformer

    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    SentenceTransformer = None

COLLECTION_NAME = "session_memory"
VECTOR_SIZE = 384
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embedding_model() -> "SentenceTransformer":
    """
    Get or create embedding model singleton.

    Uses lru_cache to ensure model is loaded only once.
    """
    if not EMBEDDINGS_AVAILABLE:
        raise ImportError(
            "sentence-transformers not installed. "
            "Install with: pip install sentence-transformers"
        )

    logger.info("Loading embedding model: {model}", model=EMBEDDING_MODEL_NAME)
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def get_qdrant_client() -> "QdrantClient":
    """
    Get or create Qdrant client singleton.

    Falls back to in-memory mode if credentials not configured.
    """
    if not QDRANT_AVAILABLE:
        raise ImportError(
            "qdrant-client not installed. Install with: pip install qdrant-client"
        )

    url = os.getenv("QDRANT_CLUSTER_ENDPOINT")
    api_key = os.getenv("QDRANT_API_KEY")

    if not url or not api_key:
        logger.warning(
            "Qdrant credentials not found (QDRANT_CLUSTER_ENDPOINT, QDRANT_API_KEY). "
            "Using in-memory mode. Session memory will not persist across restarts."
        )
        return QdrantClient(":memory:")

    client = QdrantClient(url=url, api_key=api_key)
    _ensure_collection(client)
    logger.info("Qdrant client connected to: {url}", url=url)
    return client


def _ensure_collection(client: "QdrantClient") -> None:
    """Create collection if not exists."""
    collections = client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection: {name}", name=COLLECTION_NAME)


def embed_text(text: str) -> list[float]:
    """
    Embed text using the singleton embedding model.

    Args:
        text: Text to embed

    Returns:
        List of floats representing the embedding vector
    """
    model = get_embedding_model()
    embedding = model.encode(text)
    return embedding.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple texts using the singleton embedding model.

    Args:
        texts: List of texts to embed

    Returns:
        List of embedding vectors
    """
    model = get_embedding_model()
    embeddings = model.encode(texts)
    return [e.tolist() for e in embeddings]


def is_qdrant_available() -> bool:
    """Check if Qdrant is properly configured with credentials."""
    if not QDRANT_AVAILABLE:
        return False
    if not EMBEDDINGS_AVAILABLE:
        return False
    url = os.getenv("QDRANT_CLUSTER_ENDPOINT")
    api_key = os.getenv("QDRANT_API_KEY")
    return bool(url and api_key)


def is_qdrant_library_installed() -> bool:
    """Check if Qdrant library is installed (regardless of credentials)."""
    return QDRANT_AVAILABLE and EMBEDDINGS_AVAILABLE
