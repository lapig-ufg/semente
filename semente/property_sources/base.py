"""Contract of a property source: where candidate property boundaries come from.

A source answers two questions: which candidate polygons lie around a
coordinate (``find_by_point``) and which polygon belongs to an identifier of
its own (``find_by_id``). Semente ships the approximate-circle source; an app
adapts to a country by implementing this protocol over its own property
registry and registering it (see ``semente.property_sources.registry``).
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from semente.property_sources.candidate import PropertyCandidate


class PropertySourceError(Exception):
    """A property source could not answer.

    Attributes:
        kind (str): ``"unavailable"`` (service down or error response), ``"timeout"``,
            ``"not_found"`` (unknown identifier) or ``"urban_area"`` (the point lies in
            a land use where no property candidate is offered).
    """

    KINDS = ("unavailable", "timeout", "not_found", "urban_area")

    def __init__(self, kind: str, message: str = ""):
        """Creates the error.

        Args:
            kind (str): One of ``KINDS``.
            message (str): Description for the logs (never shown to the model).
        """
        super().__init__(message or kind)
        self.kind = kind


@runtime_checkable
class PropertySource(Protocol):
    """Protocol every property source implements.

    Attributes:
        key (str): Short identifier used in configuration and app code.
    """

    key: str

    def find_by_point(self, latitude: float, longitude: float, search_radius_m: float = 2000) -> list[PropertyCandidate]:
        """Returns the candidate polygons around a coordinate, best first.

        Args:
            latitude (float): Latitude in decimal degrees.
            longitude (float): Longitude in decimal degrees.
            search_radius_m (float): Search radius in meters.

        Returns:
            list[PropertyCandidate]: Candidates ordered by relevance (possibly empty).

        Raises:
            PropertySourceError: If the source cannot answer.
        """
        ...

    def find_by_id(self, identifier: str) -> Optional[PropertyCandidate]:
        """Returns the candidate with a source-specific identifier, or None.

        Args:
            identifier (str): Identifier in the source (for example a registry number).

        Returns:
            PropertyCandidate | None: The candidate, or None when it does not exist.

        Raises:
            PropertySourceError: If the source cannot answer.
        """
        ...
