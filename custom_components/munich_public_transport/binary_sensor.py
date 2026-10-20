"""Binary sensors for Munich Public Transport disruptions."""

from __future__ import annotations

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import (
    MunichTransportConfigEntry,
    MunichTransportMessagesCoordinator,
    StationData,
)
from .entity import MunichTransportEntity, async_remove_stale_entities

DISRUPTION = BinarySensorEntityDescription(
    key="disruption",
    translation_key="disruption",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


# Coordinators centralize the updates.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MunichTransportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a disruption sensor for every line a station has selected."""

    data = entry.runtime_data
    for station in data.stations.values():
        # Service messages name lines, not directions, so both directions of
        # a line share one sensor.
        lines = dict.fromkeys(direction.line_label for direction in station.directions)
        entities = [
            DisruptionBinarySensor(data.messages_coordinator, station, line)
            for line in lines
        ]
        async_add_entities(entities, config_subentry_id=station.subentry_id)
        async_remove_stale_entities(
            hass, entry, station, Platform.BINARY_SENSOR, entities
        )


class DisruptionBinarySensor(
    MunichTransportEntity[MunichTransportMessagesCoordinator], BinarySensorEntity
):
    """Whether an active service message names this line at this station."""

    def __init__(
        self,
        coordinator: MunichTransportMessagesCoordinator,
        station: StationData,
        line: str,
    ) -> None:
        """Initialize the binary sensor."""

        super().__init__(
            coordinator, station, DISRUPTION, scope=line, placeholders={"line": line}
        )
        self._line = line

    @property
    @override
    def is_on(self) -> bool:
        """Return whether the line is disrupted."""

        now = dt_util.utcnow()
        return any(
            message.is_active(now)
            and message.affects_line(self._line, self._station.global_id)
            for message in self.coordinator.data or []
        )
