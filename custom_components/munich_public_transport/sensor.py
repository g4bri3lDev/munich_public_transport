"""Sensors for Munich Public Transport departures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from munich_transport.models import Departure

from .const import (
    ATTR_CANCELLED,
    ATTR_DELAY_MINUTES,
    ATTR_DEPARTURES,
    ATTR_DESTINATION,
    ATTR_DIRECTION_KEY,
    ATTR_DIRECTION_VARIANTS,
    ATTR_IS_LATE,
    ATTR_LINE,
    ATTR_MINUTES_UNTIL_DEPARTURE,
    ATTR_NETWORK,
    ATTR_NORMAL_TERMINUS,
    ATTR_OCCUPANCY,
    ATTR_PLANNED_DEPARTURE,
    ATTR_PLATFORM,
    ATTR_PLATFORM_CHANGED,
    ATTR_REALTIME,
    ATTR_REALTIME_DEPARTURE,
    ATTR_SCHEDULE_KIND,
    ATTR_TOTAL_DEPARTURES,
    ATTR_TRANSPORT_TYPE,
    CONF_NAME,
    CONF_STATION_GLOBAL_ID,
    DEFAULT_DEPARTURE_LIMIT,
    DOMAIN,
)
from .coordinator import MunichTransportDepartureCoordinator
from .models import DirectionSelection

ATTRIBUTION = "Data provided by MVG"
DEFAULT_ICON = "mdi:train-car"
ALL_DEPARTURES_ICON = "mdi:train-car-multiple"

TRANSPORT_TYPE_ICONS = {
    "BAHN": "mdi:train",
    "BUS": "mdi:bus",
    "NIGHT_LINE": "mdi:bus-clock",
    "REGIONAL_BUS": "mdi:bus",
    "SBAHN": "mdi:train",
    "SEV": "mdi:bus-alert",
    "TRAM": "mdi:tram",
    "UBAHN": "mdi:subway",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up departure sensors for a config entry."""

    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator
    selections = runtime_data.direction_selections

    entities: list[SensorEntity] = [
        MunichTransportNextDepartureSensor(entry, coordinator, selections),
        MunichTransportAllDeparturesSensor(entry, coordinator, selections),
    ]
    entities.extend(
        MunichTransportLineDepartureSensor(entry, coordinator, selection)
        for selection in selections
    )
    async_add_entities(entities)


class MunichTransportBaseSensor(
    CoordinatorEntity[MunichTransportDepartureCoordinator],
    SensorEntity,
):
    """Base class for station departure sensors."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: MunichTransportDepartureCoordinator,
    ) -> None:
        """Initialize the base sensor."""

        super().__init__(coordinator)
        self._entry = entry
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def available(self) -> bool:
        """Return whether the coordinator currently has usable data."""

        return self.coordinator.last_update_success

    @property
    def device_info(self) -> DeviceInfo:
        """Return the station device."""

        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.data[CONF_STATION_GLOBAL_ID])},
            name=self._entry.data[CONF_NAME],
            manufacturer="MVG",
            model="Public Transport Station",
        )

    def _handle_coordinator_update(self) -> None:
        """Update cached attributes before writing state."""

        self._refresh_extra_state_attributes()
        super()._handle_coordinator_update()

    def _refresh_extra_state_attributes(self) -> None:
        self._attr_extra_state_attributes = self._build_extra_state_attributes()

    def _build_extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ATTRIBUTION: ATTRIBUTION}


class MunichTransportNextDepartureSensor(MunichTransportBaseSensor):
    """Sensor showing the next selected departure for a station."""

    _attr_name = "Next Departure"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: MunichTransportDepartureCoordinator,
        selections: tuple[DirectionSelection, ...],
    ) -> None:
        """Initialize the next departure sensor."""

        super().__init__(entry, coordinator)
        self._selections = selections
        self._attr_unique_id = f"{entry.entry_id}_next_departure"
        self._refresh_extra_state_attributes()

    @property
    def icon(self) -> str:
        """Return the icon for the next departure."""

        departure = self._next_departure
        if departure is None:
            return DEFAULT_ICON
        return _departure_icon(departure)

    @property
    def native_value(self) -> int | None:
        """Return minutes until the next selected departure."""

        departure = self._next_departure
        if departure is None:
            return None
        return _minutes_until(departure.realtime_departure)

    def _build_extra_state_attributes(self) -> dict[str, Any]:
        """Return details for the next selected departure."""

        attrs: dict[str, Any] = {ATTR_ATTRIBUTION: ATTRIBUTION}
        departure = self._next_departure
        if departure is not None:
            attrs.update(_departure_attributes(departure))
        return attrs

    @property
    def _next_departure(self) -> Departure | None:
        departures = _matching_departures(self.coordinator.data or [], self._selections)
        if not departures:
            return None
        return departures[0]


class MunichTransportAllDeparturesSensor(MunichTransportBaseSensor):
    """Sensor showing all selected departures for a station."""

    _attr_name = "All Departures"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: MunichTransportDepartureCoordinator,
        selections: tuple[DirectionSelection, ...],
    ) -> None:
        """Initialize the all departures sensor."""

        super().__init__(entry, coordinator)
        self._selections = selections
        self._attr_unique_id = f"{entry.entry_id}_all_departures"
        self._refresh_extra_state_attributes()

    @property
    def icon(self) -> str:
        """Return the icon for the next selected departure."""

        departures = self._departures
        if not departures:
            return ALL_DEPARTURES_ICON
        return _departure_icon(departures[0])

    @property
    def native_value(self) -> int | None:
        """Return minutes until the next selected departure."""

        departures = self._departures
        if not departures:
            return None
        return _minutes_until(departures[0].realtime_departure)

    def _build_extra_state_attributes(self) -> dict[str, Any]:
        """Return all selected departures."""

        departures = self._departures
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            ATTR_DEPARTURES: [
                _departure_attributes(departure)
                for departure in departures[:DEFAULT_DEPARTURE_LIMIT]
            ],
            ATTR_TOTAL_DEPARTURES: len(departures),
        }

    @property
    def _departures(self) -> list[Departure]:
        return _matching_departures(self.coordinator.data or [], self._selections)


class MunichTransportLineDepartureSensor(MunichTransportBaseSensor):
    """Sensor showing departures for one line/direction pairing."""

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: MunichTransportDepartureCoordinator,
        selection: DirectionSelection,
    ) -> None:
        """Initialize the line departure sensor."""

        super().__init__(entry, coordinator)
        self._selection = selection
        self._attr_name = self._display_label
        self._attr_suggested_object_id = (
            f"{entry.data[CONF_NAME]} {selection.label}"
        )
        self._attr_unique_id = f"{entry.entry_id}_{selection.id}"
        self._refresh_extra_state_attributes()

    def _handle_coordinator_update(self) -> None:
        """Update the current display name before writing state."""

        self._attr_name = self._display_label
        super()._handle_coordinator_update()

    @property
    def icon(self) -> str:
        """Return the icon for this line."""

        departure = self._next_departure
        if departure is None:
            return DEFAULT_ICON
        return _departure_icon(departure)

    @property
    def native_value(self) -> int | None:
        """Return minutes until the next matching departure."""

        departure = self._next_departure
        if departure is None:
            return None
        return _minutes_until(departure.realtime_departure)

    def _build_extra_state_attributes(self) -> dict[str, Any]:
        """Return departure details for the selected pairing."""

        departures = self._matching_departures
        next_departure = departures[0] if departures else None

        attributes: dict[str, Any] = {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            ATTR_LINE: self._selection.line_label,
            ATTR_DIRECTION_KEY: self._selection.direction_key,
            ATTR_DIRECTION_VARIANTS: list(self._selection.directions),
            ATTR_NORMAL_TERMINUS: self._selection.normal_terminus,
            ATTR_SCHEDULE_KIND: self._selection.schedule_kind,
            ATTR_DEPARTURES: [
                _departure_attributes(departure)
                for departure in departures[:DEFAULT_DEPARTURE_LIMIT]
            ],
        }
        if next_departure is not None:
            attributes.update(_departure_attributes(next_departure))
        return attributes

    @property
    def _next_departure(self) -> Departure | None:
        departures = self._matching_departures
        if not departures:
            return None
        return departures[0]

    @property
    def _matching_departures(self) -> list[Departure]:
        return _matching_departures(self.coordinator.data or [], (self._selection,))

    @property
    def _display_label(self) -> str:
        departure = self._next_departure
        if departure is None:
            return self._selection.label
        return f"{self._selection.line_label} → {departure.destination}"


def _matching_departures(
    departures: list[Departure],
    selections: tuple[DirectionSelection, ...],
) -> list[Departure]:
    if not selections:
        return sorted(departures, key=lambda departure: departure.realtime_departure)

    selected = [
        departure
        for departure in departures
        if any(_matches_selection(departure, selection) for selection in selections)
    ]
    return sorted(selected, key=lambda departure: departure.realtime_departure)


def _matches_selection(
    departure: Departure,
    selection: DirectionSelection,
) -> bool:
    if departure.line.label != selection.line_label:
        return False
    if selection.direction_key is None:
        return True
    return departure.direction_key == selection.direction_key


def _departure_attributes(departure: Departure) -> dict[str, Any]:
    minutes_until = _minutes_until(departure.realtime_departure)
    return {
        ATTR_CANCELLED: departure.cancelled,
        ATTR_DELAY_MINUTES: departure.delay_minutes,
        ATTR_DESTINATION: departure.destination,
        ATTR_DIRECTION_KEY: departure.direction_key,
        ATTR_IS_LATE: departure.realtime_departure > departure.planned_departure,
        ATTR_LINE: departure.line.label,
        ATTR_MINUTES_UNTIL_DEPARTURE: minutes_until,
        ATTR_NETWORK: departure.line.network,
        ATTR_OCCUPANCY: departure.occupancy,
        ATTR_PLATFORM: departure.platform,
        ATTR_PLATFORM_CHANGED: departure.platform_changed,
        ATTR_PLANNED_DEPARTURE: _format_time(departure.planned_departure),
        ATTR_REALTIME: departure.realtime,
        ATTR_REALTIME_DEPARTURE: _format_time(departure.realtime_departure),
        ATTR_TRANSPORT_TYPE: departure.line.transport_type,
    }


def _departure_icon(departure: Departure) -> str:
    return TRANSPORT_TYPE_ICONS.get(departure.line.transport_type, DEFAULT_ICON)


def _minutes_until(value: datetime) -> int:
    delta = value - dt_util.now(value.tzinfo)
    return max(round(delta.total_seconds() / 60), 0)


def _format_time(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%H:%M")
