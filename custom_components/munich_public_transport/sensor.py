from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    UnitOfTime,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_DEPARTURE_COUNT

import logging
from datetime import datetime, timedelta
from typing import Any

from mvg import MvgApi, TransportType

_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = "Data provided by MVG"

DEFAULT_ICON = "mdi:train-car"

def calculate_minutes_until(timestamp: int) -> int:
    """Calculate minutes until the given timestamp."""
    departure_time = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    time_diff = departure_time - now
    return max(0, int(time_diff.total_seconds() / 60))

async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Munich Public Transport sensors."""
    _LOGGER.debug(f"Setting up sensor for config entry: {config_entry.data}")

    station_id = config_entry.data["station_id"]
    station_name = config_entry.data["station_name"]
    selected_lines = config_entry.options.get("lines", config_entry.data.get("lines", []))
    selected_directions = config_entry.options.get("directions", config_entry.data.get("directions", []))

    try:
        departure_count = int(config_entry.options.get("departure_count", config_entry.data.get("departure_count", DEFAULT_DEPARTURE_COUNT)))
    except ValueError:
        _LOGGER.warning(f"Invalid departure_count, using default of {DEFAULT_DEPARTURE_COUNT}")
        departure_count = DEFAULT_DEPARTURE_COUNT

    try:
        scan_interval = timedelta(minutes=int(config_entry.options.get("scan_interval", config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))))
    except ValueError:
        _LOGGER.warning(f"Invalid scan_interval, using default of {DEFAULT_SCAN_INTERVAL} minutes")
        scan_interval = timedelta(minutes=DEFAULT_SCAN_INTERVAL)

    _LOGGER.debug(f"Station: {station_name}, Lines: {selected_lines}, Directions: {selected_directions}, Count: {departure_count}, Scan Interval: {scan_interval}")

    async def async_update_data():
        """Fetch data from API."""
        try:
            _LOGGER.debug(f"Fetching departures for station {station_id} ({station_name})")
            departures = await MvgApi.departures_async(station_id)
            _LOGGER.debug(f"Fetched {len(departures)} departures")

            # Group departures by line and destination
            grouped_departures = {}
            for dep in departures:
                if (not selected_lines or dep["line"] in selected_lines) and \
                        (not selected_directions or dep["destination"] in selected_directions):
                    key = (dep['line'], dep['destination'])
                    if key not in grouped_departures:
                        grouped_departures[key] = []
                    grouped_departures[key].append(dep)

            # Sort and limit each group to departure_count
            for key in grouped_departures:
                grouped_departures[key] = sorted(grouped_departures[key], key=lambda x: x['time'])[:departure_count]

            # Create a flat list of all filtered departures
            all_filtered_departures = [
                dep for departures in grouped_departures.values() for dep in departures
            ]
            all_filtered_departures.sort(key=lambda x: x['time'])

            _LOGGER.debug(f"Filtered to {len(all_filtered_departures)} departures across all lines/directions")

            return {
                "all": all_filtered_departures,
                "grouped": grouped_departures,
                "next": all_filtered_departures[0] if all_filtered_departures else None
            }
        except Exception as err:
            _LOGGER.error(f"Error communicating with API: {err}", exc_info=True)
            return {
                "all": [],
                "grouped": {},
                "next": None
            }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="munich_public_transport",
        update_method=async_update_data,
        update_interval=scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    if coordinator.data is None:
        raise ConfigEntryNotReady("Failed to fetch initial data")

    entities = [
        NextDepartureSensor(coordinator, station_name, config_entry),
        AllDeparturesSensor(coordinator, station_name, config_entry)
    ]

    for (line, destination) in coordinator.data["grouped"].keys():
        if line in selected_lines and destination in selected_directions:
            entities.append(LineSensor(coordinator, station_name, line, destination, config_entry))

    async_add_entities(entities, True)

    @callback
    def async_update_sensors(entry: ConfigEntry) -> None:
        """Update sensors based on config entry update."""
        _LOGGER.debug(f"Updating sensors for config entry: {entry.data}")

        new_selected_lines = entry.options.get("lines", entry.data.get("lines", []))
        new_selected_directions = entry.options.get("directions", entry.data.get("directions", []))

        entity_reg = async_get_entity_registry(hass)
        entries = entity_reg.entities.values()

        # Remove entities that are no longer needed
        for entity_entry in entries:
            if entity_entry.config_entry_id == entry.entry_id and entity_entry.unique_id.startswith(f"{DOMAIN}_{station_name}_"):
                parts = entity_entry.unique_id.split('_')
                if len(parts) >= 4:  # Ensure it's a line sensor
                    line = parts[2]
                    direction = '_'.join(parts[3:])
                    if line not in new_selected_lines or direction not in new_selected_directions:
                        _LOGGER.debug(f"Removing entity: {entity_entry.entity_id}")
                        entity_reg.async_remove(entity_entry.entity_id)

        # Add new entities if needed
        current_entities = set(entity.unique_id for entity in entities)
        for line in new_selected_lines:
            for direction in new_selected_directions:
                unique_id = f"{DOMAIN}_{station_name}_{line}_{direction}"
                if unique_id not in current_entities:
                    _LOGGER.debug(f"Adding new entity: {unique_id}")
                    new_entity = LineSensor(coordinator, station_name, line, direction, entry)
                    entities.append(new_entity)
                    async_add_entities([new_entity], True)

        # Update coordinator
        coordinator.update_interval = timedelta(minutes=int(entry.options.get("scan_interval", entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))))

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_sensors))

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_sensors))

    async def async_remove_outdated_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Remove entities that are no longer needed."""
        entity_reg = async_get_entity_registry(hass)
        entries = entity_reg.entities.values()

        selected_lines = entry.options.get("lines", entry.data.get("lines", []))
        selected_directions = entry.options.get("directions", entry.data.get("directions", []))

        for entity_entry in entries:
            if entity_entry.config_entry_id == entry.entry_id and entity_entry.unique_id.startswith(f"{DOMAIN}_{station_name}_"):
                parts = entity_entry.unique_id.split('_')
                if len(parts) >= 4:  # Ensure it's a line sensor
                    line = parts[2]
                    direction = '_'.join(parts[3:])
                    if line not in selected_lines or direction not in selected_directions:
                        entity_reg.async_remove(entity_entry.entity_id)

    config_entry.async_on_unload(
        config_entry.add_update_listener(async_remove_outdated_entities)
    )


class MunichTransportBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Munich Transport sensors."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, station_name: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._station_name = station_name
        self._config_entry = config_entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{config_entry.entry_id}_{station_name}")},
            "name": station_name,
            "manufacturer": "MVG",
            "model": "Public Transport Station",
        }

class NextDepartureSensor(MunichTransportBaseSensor):
    """Sensor for the next departure."""

    def __init__(self, coordinator, station_name: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, station_name, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_{station_name}_next_departure"
        self._attr_name = "Next Departure"

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        if self.coordinator.data["next"]:
            return self.coordinator.data["next"]['icon']
        return DEFAULT_ICON

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data["next"]:
            return calculate_minutes_until(self.coordinator.data["next"]['time'])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        if self.coordinator.data["next"]:
            next_dep = self.coordinator.data["next"]
            attrs.update({
                "line": next_dep['line'],
                "destination": next_dep['destination'],
                "departure_time": datetime.fromtimestamp(next_dep['time']).strftime("%H:%M"),
                "type": next_dep['type'],
                "cancelled": next_dep['cancelled'],
                "messages": next_dep['messages'],
            })
        return attrs

class AllDeparturesSensor(MunichTransportBaseSensor):
    """Sensor for all departures."""

    def __init__(self, coordinator, station_name: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, station_name, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_{station_name}_all_departures"
        self._attr_name = "All Departures"
        self._attr_icon = "mdi:train-car-multiple"

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        if self.coordinator.data["all"]:
            return self.coordinator.data["all"][0]['icon']
        return DEFAULT_ICON

    @property
    def native_value(self) -> StateType:
        """Return the minutes until the next departure across all lines."""
        if self.coordinator.data["all"]:
            return calculate_minutes_until(self.coordinator.data["all"][0]['time'])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        attrs["departures"] = [
            {
                "line": dep['line'],
                "destination": dep['destination'],
                "departure_time": datetime.fromtimestamp(dep['time']).strftime("%H:%M"),
                "minutes_until_departure": calculate_minutes_until(dep['time']),
                "type": dep['type'],
                "cancelled": dep['cancelled'],
                "messages": dep['messages'],
            } for dep in self.coordinator.data["all"]
        ]
        attrs["total_departures"] = len(self.coordinator.data["all"])
        return attrs

class LineSensor(MunichTransportBaseSensor):
    """Sensor for specific line and destination."""

    def __init__(self, coordinator, station_name: str, line: str, destination: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, station_name, config_entry)
        self._line = line
        self._destination = destination
        self._attr_unique_id = f"{config_entry.entry_id}_{station_name}_{line}_{destination}"
        self._attr_name = f"{line} → {destination}"

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        departures = self.coordinator.data["grouped"].get((self._line, self._destination), [])
        if departures:
            return departures[0]['icon']
        return DEFAULT_ICON

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        departures = self.coordinator.data["grouped"].get((self._line, self._destination), [])
        if departures:
            return calculate_minutes_until(departures[0]['time'])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        departures = self.coordinator.data["grouped"].get((self._line, self._destination), [])
        if departures:
            attrs["departures"] = [
                {
                    "departure_time": datetime.fromtimestamp(dep['time']).strftime("%H:%M"),
                    "minutes_until_departure": calculate_minutes_until(dep['time']),
                    "cancelled": dep['cancelled'],
                    "messages": dep['messages'],
                } for dep in departures
            ]
            attrs["type"] = departures[0]['type']
        return attrs