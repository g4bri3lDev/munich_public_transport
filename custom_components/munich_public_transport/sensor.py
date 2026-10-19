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
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from munich_transport.models import Departure, StationDirectionOption
from munich_transport.schedules import select_departures

from .coordinator import (
    MunichTransportConfigEntry,
    MunichTransportDepartureCoordinator,
    MunichTransportMessagesCoordinator,
    StationData,
)
from .entity import MunichTransportEntity

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
        key="destination",
        translation_key="destination",
        value_fn=lambda departures: _first(
            departures, lambda departure: departure.destination
        ),
    ),
    DepartureSensorEntityDescription(
        key="delay",
        translation_key="delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda departures: _first(
            departures, lambda departure: departure.delay_minutes or 0
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
    DepartureSensorEntityDescription(
        key="platform",
        translation_key="platform",
        entity_registry_enabled_default=False,
        value_fn=lambda departures: _first(
            departures,
            lambda departure: (
                None if departure.platform is None else str(departure.platform)
            ),
        ),
    ),
)

NEXT_DEPARTURE = DepartureSensorEntityDescription(
    key="next_departure",
    translation_key="next_departure",
    device_class=SensorDeviceClass.TIMESTAMP,
    value_fn=lambda departures: _first(
        departures, lambda departure: departure.realtime_departure
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
            DepartureSensor(station, NEXT_DEPARTURE),
            DisruptionsSensor(data.messages_coordinator, station),
        ]
        entities.extend(
            DepartureSensor(station, description, direction)
            for direction in station.directions
            for description in DIRECTION_SENSORS
        )
        async_add_entities(entities, config_subentry_id=station.subentry_id)


class DepartureSensor(
    MunichTransportEntity,
    CoordinatorEntity[MunichTransportDepartureCoordinator],
    SensorEntity,
):
    """A sensor about the upcoming departures of a station or one direction."""

    entity_description: DepartureSensorEntityDescription

    def __init__(
        self,
        station: StationData,
        description: DepartureSensorEntityDescription,
        direction: StationDirectionOption | None = None,
    ) -> None:
        """Initialize the sensor."""

        CoordinatorEntity.__init__(self, station.coordinator)
        MunichTransportEntity.__init__(self, station, description, direction)

    @property
    @override
    def native_value(self) -> StateValue:
        """Return the value for the next matching departures."""

        directions = (
            (self._direction,)
            if self._direction is not None
            else self._station.directions
        )
        return self.entity_description.value_fn(
            select_departures(self.coordinator.data or [], directions)
        )


class DisruptionsSensor(
    MunichTransportEntity,
    CoordinatorEntity[MunichTransportMessagesCoordinator],
    SensorEntity,
):
    """Number of active service messages about a station or its lines."""

    def __init__(
        self,
        coordinator: MunichTransportMessagesCoordinator,
        station: StationData,
    ) -> None:
        """Initialize the sensor."""

        CoordinatorEntity.__init__(self, coordinator)
        MunichTransportEntity.__init__(self, station, DISRUPTIONS)

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
