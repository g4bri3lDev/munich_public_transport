"""Integration-local value objects."""

from __future__ import annotations

from dataclasses import dataclass

from munich_transport.models import StationDirectionOption


@dataclass(frozen=True, slots=True)
class DirectionSelection:
    """A selected line/direction pairing for a station."""

    id: str
    schedule_kind: str
    line_label: str
    direction_key: str | None
    directions: tuple[str, ...]

    @property
    def label(self) -> str:
        """Return a concise display label for the selected pairing."""

        return f"{self.line_label} → {self.normal_terminus or 'unknown'}"

    @property
    def normal_terminus(self) -> str | None:
        """Return the stable catalog terminus for the selected direction."""

        for direction in self.directions:
            if "/" not in direction:
                return direction
        return self.directions[0] if self.directions else None


def direction_selection_from_option(
    option: StationDirectionOption,
) -> DirectionSelection:
    """Convert a library option to the integration's stored selector shape."""

    return DirectionSelection(
        id=option.id,
        schedule_kind=option.schedule_kind,
        line_label=option.line_label,
        direction_key=option.direction_key,
        directions=option.directions,
    )


def fallback_direction_selection(option_id: str) -> DirectionSelection:
    """Build a selector from a stable option id when catalog data is unavailable."""

    parts = option_id.split(":", maxsplit=2)
    if len(parts) != 3:
        return DirectionSelection(
            id=option_id,
            schedule_kind="UNKNOWN",
            line_label=option_id,
            direction_key=None,
            directions=(),
        )

    schedule_kind, line_label, direction_key = parts
    return DirectionSelection(
        id=option_id,
        schedule_kind=schedule_kind,
        line_label=line_label,
        direction_key=direction_key or None,
        directions=(),
    )
