"""Data coordinators for the Munich Public Transport integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import ApiError, MunichTransportError
from munich_transport.models import Departure, Disruption, StationDirectionOption

from .const import DEFAULT_MESSAGES_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TRANSIENT_RETRY_AFTER = 60.0
_MAX_RETRY_AFTER = 15 * 60.0

# A look-ahead never takes more requests than this per update.
_MAX_DEPARTURE_REQUESTS = 4
# Departures further apart than this are not back to back, see _covered_until.
_MAX_DEPARTURE_GAP = timedelta(hours=1)

type MunichTransportConfigEntry = ConfigEntry[MunichTransportData]


@dataclass(frozen=True, slots=True)
class StationData:
    """Runtime objects for one configured station."""

    subentry_id: str
    global_id: str
    name: str
    coordinator: MunichTransportDepartureCoordinator
    directions: tuple[StationDirectionOption, ...]


@dataclass(frozen=True, slots=True)
class MunichTransportData:
    """Runtime objects shared by the integration platforms."""

    client: MunichTransportClient
    messages_coordinator: MunichTransportMessagesCoordinator
    stations: dict[str, StationData]


class MunichTransportDepartureCoordinator(DataUpdateCoordinator[list[Departure]]):
    """Fetch live departures once for a configured station."""

    config_entry: MunichTransportConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MunichTransportConfigEntry,
        client: MunichTransportClient,
        station_global_id: str,
        station_name: str,
        look_ahead: timedelta = timedelta(0),
    ) -> None:
        """Initialize the station departure coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{station_name}",
            config_entry=config_entry,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self._client = client
        self._station_global_id = station_global_id
        self._look_ahead = look_ahead

    async def _async_update_data(self) -> list[Departure]:
        """Fetch live station departures."""

        try:
            departures = await self._client.departures(self._station_global_id)
            if self._look_ahead:
                departures = await self._fetch_look_ahead(departures)
        except MunichTransportError as err:
            raise _update_failed(err) from err
        return departures

    async def _fetch_look_ahead(self, departures: list[Departure]) -> list[Departure]:
        """Request later departures until the look-ahead is covered.

        MVG answers at most 30 departures per request, which at busy stations
        reaches only about 20 minutes ahead. Each further request starts at the
        minute the departures so far end, so consecutive responses overlap at
        that minute and are merged.
        """

        now = dt_util.utcnow()
        until = now + self._look_ahead
        merged = {_departure_key(departure): departure for departure in departures}
        offset = 0
        for _ in range(_MAX_DEPARTURE_REQUESTS - 1):
            covered = _covered_until(departures)
            if covered is None or covered >= until:
                break
            next_offset = int((covered - now).total_seconds() // 60)
            if next_offset <= offset:
                break
            offset = next_offset
            departures = await self._client.departures(
                self._station_global_id, offset_minutes=offset
            )
            for departure in departures:
                merged.setdefault(_departure_key(departure), departure)
        return list(merged.values())


class MunichTransportMessagesCoordinator(DataUpdateCoordinator[list[Disruption]]):
    """Fetch MVG service messages once for all stations."""

    config_entry: MunichTransportConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MunichTransportConfigEntry,
        client: MunichTransportClient,
    ) -> None:
        """Initialize the messages coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-messages",
            config_entry=config_entry,
            update_interval=DEFAULT_MESSAGES_SCAN_INTERVAL,
            always_update=False,
        )
        self._client = client

    async def _async_update_data(self) -> list[Disruption]:
        """Fetch MVG service messages."""

        try:
            return await self._client.messages()
        except MunichTransportError as err:
            raise _update_failed(err) from err


def _departure_key(
    departure: Departure,
) -> tuple[str, str | None, str, datetime, str | None]:
    return (
        departure.line.label,
        departure.line_id,
        departure.destination,
        departure.planned_departure,
        departure.stop_point_global_id,
    )


def _covered_until(departures: list[Departure]) -> datetime | None:
    """Return when a response's back-to-back departures end.

    MVG sometimes appends departures hours later, past departures it left
    out, so the latest one does not show how far a response reaches.
    """

    times = sorted(departure.realtime_departure for departure in departures)
    if not times:
        return None
    covered = times[0]
    for time in times[1:]:
        if time - covered > _MAX_DEPARTURE_GAP:
            break
        covered = time
    return covered


def _update_failed(err: MunichTransportError) -> UpdateFailed:
    """Translate a client error, deferring the next poll when MVG asks to."""

    if isinstance(err, ApiError) and err.transient:
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="temporarily_unavailable",
            translation_placeholders={"status": str(err.status)},
            retry_after=_sanitize_retry_after(err.retry_after),
        )
    if isinstance(err, ApiError):
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"status": str(err.status)},
        )
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="cannot_connect",
        translation_placeholders={"error": str(err)},
    )


def _sanitize_retry_after(value: float | None) -> float:
    if value is None:
        return _DEFAULT_TRANSIENT_RETRY_AFTER
    return min(max(value, 1.0), _MAX_RETRY_AFTER)
