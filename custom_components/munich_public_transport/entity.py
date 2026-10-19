"""Base entities for Munich Public Transport."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from munich_transport.models import StationDirectionOption

from .const import ATTRIBUTION, DOMAIN
from .coordinator import StationData


class MunichTransportEntity(Entity):
    """An entity on a station device, optionally for one line/direction."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        station: StationData,
        description: EntityDescription,
        direction: StationDirectionOption | None = None,
    ) -> None:
        """Initialize the entity."""

        self.entity_description = description
        self._station = station
        self._direction = direction

        prefix = station.global_id
        if direction is not None:
            prefix = f"{prefix}_{direction.id}"
            self._attr_translation_placeholders = {
                "direction": direction_label(direction)
            }
        self._attr_unique_id = f"{prefix}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station.global_id)},
            name=station.name,
            manufacturer="MVG",
            model="Station",
            entry_type=DeviceEntryType.SERVICE,
        )


def direction_label(direction: StationDirectionOption) -> str:
    """Return the stable "<line> → <terminus>" label for a direction."""

    return f"{direction.line_label} → {direction.normal_terminus or 'unknown'}"
