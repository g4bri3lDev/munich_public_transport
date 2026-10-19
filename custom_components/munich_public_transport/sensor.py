"""Sensors for Munich Public Transport departures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from munich_transport.models import Departure, StationDirectionOption
from munich_transport.schedules import select_departures

from .coordinator import (
    MunichTransportConfigEntry,
    MunichTransportDepartureCoordinator,
    MunichTransportMessagesCoordinator,
    StationData,
)
from .entity import MunichTransportEntity, async_remove_stale_entities, direction_label

type StateValue = datetime | str | int | None


@dataclass(frozen=True, kw_only=True)
class DepartureSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor derived from the upcoming departures."""

    value_fn: Callable[[list[Departure]], StateValue]


def _first[T](departures: list[Departure], fn: Callable[[Departure], T]) -> T | None:
    return fn(departures[0]) if departures else None


DIRECTION_SENSORS: tuple[DepartureSensorEntityDescription, ...] = (
    DepartureSensorEntityDescription(
        key="departure",
        translation_key="departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda departures: _first(
            departures, lambda departure: departure.realtime_departure
        ),
    ),
    DepartureSensorEntityDescription(
        key="following_departure",
        translation_key="following_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda departures: (
            departures[1].realtime_departure if len(departures) > 1 else None
        ),
    ),
)

DISRUPTIONS = SensorEntityDescription(
    key="disruptions",
    translation_key="disruptions",
)


# Coordinators centralize the updates.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MunichTransportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up departure sensors for every station."""

    data = entry.runtime_data
    for station in data.stations.values():
        entities: list[SensorEntity] = [
            DisruptionsSensor(data.messages_coordinator, station)
        ]
        entities.extend(
            DepartureSensor(station, description, direction)
            for direction in station.directions
            for description in DIRECTION_SENSORS
        )
        async_add_entities(entities, config_subentry_id=station.subentry_id)
        async_remove_stale_entities(hass, entry, station, Platform.SENSOR, entities)


class DepartureSensor(
    MunichTransportEntity[MunichTransportDepartureCoordinator], SensorEntity
):
    """A sensor about the upcoming departures of one direction."""

    entity_description: DepartureSensorEntityDescription

    def __init__(
        self,
        station: StationData,
        description: DepartureSensorEntityDescription,
        direction: StationDirectionOption,
    ) -> None:
        """Initialize the sensor."""

        super().__init__(
            station.coordinator,
            station,
            description,
            scope=direction.id,
            placeholders={"direction": direction_label(direction)},
        )
        self._selected = (direction,)

    @property
    @override
    def native_value(self) -> StateValue:
        """Return the value for the next matching departures."""

        return self.entity_description.value_fn(
            select_departures(self.coordinator.data or [], self._selected)
        )


class DisruptionsSensor(
    MunichTransportEntity[MunichTransportMessagesCoordinator], SensorEntity
):
    """Number of active service messages about a station or its lines."""

    def __init__(
        self,
        coordinator: MunichTransportMessagesCoordinator,
        station: StationData,
    ) -> None:
        """Initialize the sensor."""

        super().__init__(coordinator, station, DISRUPTIONS)

    @property
    @override
    def native_value(self) -> int:
        """Return the number of relevant messages."""

        now = dt_util.utcnow()
        lines = [direction.line_label for direction in self._station.directions]
        return sum(
            message.is_active(now)
            and message.affects_station(self._station.global_id, lines)
            for message in self.coordinator.data or []
        )
