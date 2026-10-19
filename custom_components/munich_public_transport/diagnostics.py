"""Diagnostics for Munich Public Transport."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import MunichTransportConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MunichTransportConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the MVG entry.

    Station ids and line names are public timetable data, so nothing is
    redacted.
    """

    data = entry.runtime_data
    messages = data.messages_coordinator
    return {
        "stations": [
            {
                "subentry": dict(entry.subentries[station.subentry_id].data),
                "directions": [
                    {
                        "id": direction.id,
                        "line": direction.line_label,
                        "direction_key": direction.direction_key,
                        "directions": list(direction.directions),
                    }
                    for direction in station.directions
                ],
                "last_update_success": station.coordinator.last_update_success,
                "departures": len(station.coordinator.data or []),
            }
            for station in data.stations.values()
        ],
        "disabled_stations": [
            subentry.title
            for subentry_id, subentry in entry.subentries.items()
            if subentry_id not in data.stations
        ],
        "messages": {
            "last_update_success": messages.last_update_success,
            "count": len(messages.data or []),
        },
    }
