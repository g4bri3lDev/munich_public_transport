from __future__ import annotations

from .api import MunichTransportAPI
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


_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = "Data provided by MVG"

DEFAULT_ICON = "mdi:train-car"

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

    async def async_update_departures():
        """Fetch data from API."""
        try:
            _LOGGER.debug(f"Fetching departures for station {station_id} ({station_name})")
            departures = await MunichTransportAPI.fetch_departures(station_id)
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
                grouped_departures[key] = sorted(grouped_departures[key], key=lambda x: x['realtime_departure'])[:departure_count]

            # Create a flat list of all filtered departures
            all_filtered_departures = [
                dep for departures in grouped_departures.values() for dep in departures
            ]
            all_filtered_departures.sort(key=lambda x: x['realtime_departure'])

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

    async def async_update_messages():
        """Fetch message data from API."""
        try:
            _LOGGER.debug("Fetching transport messages")
            messages = await MunichTransportAPI.fetch_messages()
            _LOGGER.debug(f"Fetched {len(messages)} messages")
            return {"messages": messages}
        except Exception as err:
            _LOGGER.error(f"Error fetching messages: {err}", exc_info=True)
            return {"messages": []}

    departure_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="munich_public_transport",
        update_method=async_update_departures,
        update_interval=scan_interval,
    )

    message_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="munich_public_transport_messages",
        update_method=async_update_messages,
        update_interval=timedelta(minutes=30),
    )

    await departure_coordinator.async_config_entry_first_refresh()
    await message_coordinator.async_config_entry_first_refresh()

    if departure_coordinator.data is None or message_coordinator.data is None:
        raise ConfigEntryNotReady("Failed to fetch initial data")

    entities = [
        NextDepartureSensor(departure_coordinator, station_name, config_entry),
        AllDeparturesSensor(departure_coordinator, station_name, config_entry),
        MessagesSensor(message_coordinator, station_name, config_entry, selected_lines)
    ]

    for (line, destination) in departure_coordinator.data["grouped"].keys():
        if line in selected_lines and destination in selected_directions:
            entities.append(LineSensor(departure_coordinator, station_name, line, destination, config_entry))

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
                    new_entity = LineSensor(departure_coordinator, station_name, line, direction, entry)
                    entities.append(new_entity)
                    async_add_entities([new_entity], True)

        # Update coordinator
        departure_coordinator.update_interval = timedelta(minutes=int(entry.options.get("scan_interval", entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))))

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

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

class NextDepartureSensor(MunichTransportBaseSensor):
    """Sensor for the next departure."""

    def __init__(self, departure_coordinator, station_name: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(departure_coordinator, station_name, config_entry)
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
            return MunichTransportAPI.calculate_minutes_until(self.coordinator.data["next"]['realtime_departure'])
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
                "realtime_departure": datetime.fromtimestamp(next_dep['realtime_departure']).strftime("%H:%M"),
                "planned_departure": datetime.fromtimestamp(next_dep['planned_departure']).strftime("%H:%M"),
                "is_late": next_dep['realtime_departure'] > next_dep['planned_departure'],
                "type": next_dep['type'],
                "occupancy": next_dep['occupancy'],
                "cancelled": next_dep['cancelled'],
                "network": next_dep['network'],
            })
        return attrs

class AllDeparturesSensor(MunichTransportBaseSensor):
    """Sensor for all departures."""

    def __init__(self, departure_coordinator, station_name: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(departure_coordinator, station_name, config_entry)
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
            return MunichTransportAPI.calculate_minutes_until(self.coordinator.data["all"][0]['realtime_departure'])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        attrs["departures"] = [
            {
                "line": dep['line'],
                "destination": dep['destination'],
                "realtime_departure": datetime.fromtimestamp(dep['realtime_departure']).strftime("%H:%M"),
                "planned_departure": datetime.fromtimestamp(dep['planned_departure']).strftime("%H:%M"),
                "is_late": dep['realtime_departure'] > dep['planned_departure'],
                "minutes_until_departure": MunichTransportAPI.calculate_minutes_until(dep['realtime_departure']),
                "type": dep['type'],
                "occupancy": dep['occupancy'],
                "cancelled": dep['cancelled'],
                "network": dep['network'],
            } for dep in self.coordinator.data["all"]
        ]
        attrs["total_departures"] = len(self.coordinator.data["all"])
        return attrs

class LineSensor(MunichTransportBaseSensor):
    """Sensor for specific line and destination."""

    def __init__(self, departure_coordinator, station_name: str, line: str, destination: str, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(departure_coordinator, station_name, config_entry)
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
            return MunichTransportAPI.calculate_minutes_until(departures[0]['realtime_departure'])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        departures = self.coordinator.data["grouped"].get((self._line, self._destination), [])
        if departures:
            attrs["departures"] = [
                {
                    "realtime_departure": datetime.fromtimestamp(dep['realtime_departure']).strftime("%H:%M"),
                    "planned_departure": datetime.fromtimestamp(dep['planned_departure']).strftime("%H:%M"),
                    "is_late": dep['realtime_departure'] > dep['planned_departure'],
                    "minutes_until_departure": MunichTransportAPI.calculate_minutes_until(dep['realtime_departure']),
                    "occupancy": dep['occupancy'],
                    "cancelled": dep['cancelled'],
                    "network": dep['network'],
                } for dep in departures
            ]
            attrs["type"] = departures[0]['type']
        return attrs

class MessagesSensor(CoordinatorEntity, SensorEntity):
    """Sensor for transport messages."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, station_name: str, config_entry: ConfigEntry, selected_lines: list[str]) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.entry_id}_{station_name}_messages"
        self._attr_name = "Messages"
        self._attr_icon = "mdi:message-alert"
        self._selected_lines = selected_lines
        self._attr_native_unit_of_measurement = "messages"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{config_entry.entry_id}_{station_name}")},
            "name": station_name,
            "manufacturer": "MVG",
            "model": "Public Transport Station",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return len(self._filter_messages(self.coordinator.data["messages"]))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        filtered_messages = self._filter_messages(self.coordinator.data["messages"])
        attrs["messages"] = [self._format_message(msg) for msg in filtered_messages]
        return attrs

    def _filter_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter messages relevant to this station."""
        now = datetime.now()
        return [
            msg for msg in messages
            if (not msg['lines'] or any(line in self._selected_lines for line in msg['lines'])) and
               (not msg['valid_from'] or datetime.fromisoformat(msg['valid_from']) <= now) and
               (not msg['valid_to'] or datetime.fromisoformat(msg['valid_to']) >= now)
        ]

    def _format_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Format a single message."""
        return {
            "title": self._truncate_title(msg['title']),
            "lines": self._format_lines(msg['lines']),
            # "valid_from": msg['valid_from'],
            # "valid_to": msg['valid_to'],
            "validity": self._format_validity(msg['valid_from'], msg['valid_to'])
        }

    def _format_lines(self, lines: list[str]) -> list[str]:
        """Format the affected lines, removing duplicates."""
        return sorted(set(lines)) if lines else ["All lines"]

    def _format_validity(self, valid_from: str, valid_to: str) -> str:
        """Format the validity period."""
        from_date = datetime.fromisoformat(valid_from) if valid_from else None
        to_date = datetime.fromisoformat(valid_to) if valid_to else None

        if from_date and to_date:
            if from_date.date() == to_date.date():
                return f"{from_date.strftime('%d.%m.%Y')} {from_date.strftime('%H:%M')} - {to_date.strftime('%H:%M')}"
            return f"{from_date.strftime('%d.%m.%Y %H:%M')} - {to_date.strftime('%d.%m.%Y %H:%M')}"
        elif from_date:
            return f"From {from_date.strftime('%d.%m.%Y %H:%M')}"
        elif to_date:
            return f"Until {to_date.strftime('%Y.%m.%d %H:%M')}"
        return "No specific time"

    def _truncate_title(self, title: str, max_length: int = 100) -> str:
        """Truncate the title if it's too long."""
        return title if len(title) <= max_length else title[:max_length-3] + "..."