"""Source-neutral artwork contracts and value objects.

The Picard provider and scoring engine operate on :class:`ArtworkCandidate`
instances without knowing which remote API produced them.  Concrete adapters
implement :class:`ArtworkSource` and deliver their results asynchronously through
one completion callback, matching Picard 2.13's non-blocking network model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


CompletionCallback = Callable[
    [List[Tuple[Dict[str, Any], "ArtworkCandidate"]], List[str]],
    None,
]


def positive_int(value: Any) -> Optional[int]:
    """Convert a positive integer-like API value, otherwise return ``None``."""
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    return converted if converted > 0 else None


class ArtworkCandidate:
    """Normalized artwork metadata emitted by every source adapter.

    ``source_confidence`` describes the general authority of the source, while
    ``match_confidence`` describes how reliably this particular image maps to
    the MusicBrainz release.  Both are normalized to ``0.0 .. 1.0``.
    """

    __slots__ = (
        "source",
        "image_id",
        "image_url",
        "thumbnail_url",
        "width",
        "height",
        "front",
        "approved",
        "source_confidence",
        "match_confidence",
        "popularity",
        "comment",
        "metadata",
    )

    def __init__(
        self,
        source: str,
        image_id: str,
        image_url: str,
        thumbnail_url: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
        front: bool = True,
        approved: bool = False,
        source_confidence: float = 0.0,
        match_confidence: float = 0.0,
        popularity: float = 0.0,
        comment: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Initialize one normalized, source-independent artwork candidate."""
        self.source = source
        self.image_id = image_id
        self.image_url = image_url
        self.thumbnail_url = thumbnail_url
        self.width = width
        self.height = height
        self.front = front
        self.approved = approved
        self.source_confidence = source_confidence
        self.match_confidence = match_confidence
        self.popularity = popularity
        self.comment = comment
        self.metadata = metadata or {}

    def get(self, key: str, default: Any = None) -> Any:
        """Expose the legacy image-dictionary fields consumed by the scorer."""
        values = {
            "id": self.image_id,
            "image": self.image_url,
            "width": self.width,
            "height": self.height,
            "front": self.front,
            "approved": self.approved,
            "comment": self.comment,
            "types": ["front"] if self.front else [],
        }
        return values.get(key, self.metadata.get(key, default))

    @property
    def delivery_url(self) -> str:
        """Return the preferred URL to queue through Picard."""
        return self.thumbnail_url or self.image_url


class ArtworkSource(ABC):
    """Abstract asynchronous contract implemented by artwork providers."""

    NAME = "unknown"

    @abstractmethod
    def fetch(self, releases: Iterable[dict[str, Any]], completed: CompletionCallback) -> None:
        """Fetch candidates and invoke ``completed`` exactly once."""
