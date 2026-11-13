"""Contract of a property source: where candidate property boundaries come from."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from semente.property_sources.candidate import PropertyCandidate


class PropertySourceError(Exception):
    """The source could not answer; ``kind`` is one of ``KINDS``."""

    KINDS = ("unavailable", "timeout", "not_found", "urban_area")

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


@runtime_checkable
class PropertySource(Protocol):
    """A source of candidates, identified by ``key`` in configuration and app code."""

    key: str

    def find_by_point(self, latitude: float, longitude: float, search_radius_m: float = 2000) -> list[PropertyCandidate]:
        """Candidates around a coordinate, best first (``search_radius_m`` in meters).

        Raises:
            PropertySourceError: If the source cannot answer.
        """
        ...

    def find_by_id(self, identifier: str) -> Optional[PropertyCandidate]:
        """The candidate with a source-specific identifier, or None.

        Raises:
            PropertySourceError: If the source cannot answer.
        """
        ...
