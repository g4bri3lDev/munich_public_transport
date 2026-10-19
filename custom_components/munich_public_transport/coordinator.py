"""Data coordinators for the Munich Public Transport integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import ApiError, MunichTransportError
from munich_transport.models import Departure, Disruption, StationDirectionOption

from .const import DEFAULT_MESSAGES_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TRANSIENT_RETRY_AFTER = 60.0
_MAX_RETRY_AFTER = 15 * 60.0

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

    async def _async_update_data(self) -> list[Departure]:
        """Fetch live station departures."""

        try:
            return await self._client.departures(self._station_global_id)
        except MunichTransportError as err:
            raise _update_failed(err) from err


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
