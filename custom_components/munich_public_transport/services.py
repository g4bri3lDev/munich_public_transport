"""Actions for Munich Public Transport."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util
from munich_transport.models import Departure, Disruption, StationDirectionOption
from munich_transport.schedules import select_departures
import probatio

from .const import ATTR_DEVICE_ID, DOMAIN, SERVICE_GET_DEPARTURES
from .coordinator import MunichTransportConfigEntry, StationData

GET_DEPARTURES_SCHEMA = probatio.Schema({probatio.Required(ATTR_DEVICE_ID): cv.string})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        _async_get_departures,
        schema=GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def _async_get_departures(call: ServiceCall) -> ServiceResponse:
    """Return the cached departures and messages for a station.

    Answers from the station's coordinator, so it never adds MVG requests.
    Every departure of the selected directions is included, cancelled ones
    too; templates pick what they need.
    """

    entry, station = _station_for_device(call.hass, call.data[ATTR_DEVICE_ID])
    coordinator = station.coordinator
    if not coordinator.last_update_success or coordinator.data is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="station_unavailable",
            translation_placeholders={"station": station.name},
        )

    now = dt_util.utcnow()
    lines = [direction.line_label for direction in station.directions]
    return {
        "station": {"name": station.name, "global_id": station.global_id},
        "departures": [
            _departure_response(departure, station.directions, now)
            for departure in select_departures(
                coordinator.data, station.directions, include_cancelled=True
            )
        ],
        "messages": [
            _message_response(message)
            for message in entry.runtime_data.messages_coordinator.data or []
            if message.is_active(now)
            and message.affects_station(station.global_id, lines)
        ],
    }


def _station_for_device(
    hass: HomeAssistant, device_id: str
) -> tuple[MunichTransportConfigEntry, StationData]:
    device, entry = dr.async_get_device_and_config_entry_for_domain(
        hass, device_id, domain=DOMAIN
    )
    if (
        device is None
        or entry is None
        or not any(domain == DOMAIN for domain, _ in device.identifiers)
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_device"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="station_not_loaded"
        )

    loaded: MunichTransportConfigEntry = entry
    for station in loaded.runtime_data.stations.values():
        if (DOMAIN, station.global_id) in device.identifiers:
            return loaded, station
    # The station's device is disabled, so it was not set up.
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="station_not_loaded"
    )


def _departure_response(
    departure: Departure,
    directions: tuple[StationDirectionOption, ...],
    now: datetime,
) -> dict[str, Any]:
    direction = next(
        (direction for direction in directions if direction.matches(departure)), None
    )
    seconds = (departure.realtime_departure - now).total_seconds()
    return {
        "line": departure.line.label,
        "transport_type": departure.line.transport_type,
        "network": departure.line.network,
        "destination": departure.destination,
        "direction": None if direction is None else direction.id,
        "direction_key": departure.direction_key,
        "planned_departure": departure.planned_departure.isoformat(),
        "realtime_departure": departure.realtime_departure.isoformat(),
        "minutes_until_departure": max(round(seconds / 60), 0),
        "delay": departure.delay_minutes or 0,
        "cancelled": departure.cancelled,
        "realtime": departure.realtime,
        "platform": departure.platform,
        "platform_changed": departure.platform_changed,
        "occupancy": departure.occupancy,
    }


def _message_response(message: Disruption) -> dict[str, Any]:
    return {
        "title": message.title,
        "description": message.description_html,
        "type": message.kind,
        "lines": sorted({line.label for line in message.lines}),
        "valid_from": None
        if message.valid_from is None
        else message.valid_from.isoformat(),
        "valid_to": None if message.valid_to is None else message.valid_to.isoformat(),
    }
