"""Config flow for Munich Public Transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import MunichTransportError, ParseError
from munich_transport.models import Location, Station, StationDirectionOption
from munich_transport.transport import AiohttpTransport

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_PLACE,
    DOMAIN,
)
from .models import direction_selection_from_option

CONF_QUERY = "query"
CONF_SELECTED_STATION = "selected_station"

_SECTION_LABELS = {
    "BUS": ("bus", "Bus"),
    "NIGHT_LINE": ("night_line", "Night bus"),
    "REGIONAL_BUS": ("regional_bus", "Regional bus"),
    "SEV": ("replacement_service", "Replacement service"),
    "SBAHN": ("s_bahn", "S-Bahn"),
    "SUBWAY": ("subway", "U-Bahn"),
    "TRAM": ("tram", "Tram"),
}


class MunichTransportConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Munich Public Transport config flow."""

    VERSION = 2

    _locations: dict[str, Location]
    _station: Station | None = None
    _direction_options: list[StationDirectionOption]

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Ask for a station search query."""

        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_QUERY].strip()
            try:
                locations = await self._client().search_locations(query)
            except MunichTransportError:
                errors["base"] = "cannot_connect"
            else:
                self._locations = {
                    location.global_id: location
                    for location in locations
                    if location.global_id is not None
                }
                if self._locations:
                    return await self.async_step_select_station()
                errors["base"] = "no_stations_found"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_select_station(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose a station from search results."""

        errors: dict[str, str] = {}
        if user_input is not None:
            global_id = user_input[CONF_SELECTED_STATION]
            await self.async_set_unique_id(global_id)
            self._abort_if_unique_id_configured()

            try:
                self._station = await self._client().station(global_id)
                self._direction_options = await _fetch_direction_options(
                    self._client(),
                    self._station,
                )
            except ParseError:
                errors["base"] = "invalid_station"
            except MunichTransportError:
                errors["base"] = "cannot_connect"
            else:
                if not self._direction_options:
                    errors["base"] = "no_direction_options"
                else:
                    return await self.async_step_select_directions()

        return self.async_show_form(
            step_id="select_station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_STATION): vol.In(
                        _station_choices(self._locations),
                    ),
                },
            ),
            errors=errors,
        )

    async def async_step_select_directions(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose line/direction pairings."""

        station = self._station
        if station is None:
            return await self.async_step_user()

        if user_input is not None:
            selected_ids = _selected_direction_ids_from_sections(user_input)
            return self.async_create_entry(
                title=station.name,
                data={
                    CONF_NAME: station.name,
                    CONF_STATION_GLOBAL_ID: station.global_id,
                    CONF_STATION_ABBREVIATION: station.abbreviation,
                    CONF_STATION_PLACE: station.place,
                },
                options={CONF_DIRECTION_OPTION_IDS: selected_ids},
            )

        return self.async_show_form(
            step_id="select_directions",
            data_schema=_direction_sections_schema(self._direction_options),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MunichTransportOptionsFlow:
        """Create the options flow."""

        return MunichTransportOptionsFlow(config_entry)

    def _client(self) -> MunichTransportClient:
        session = async_get_clientsession(self.hass)
        return MunichTransportClient(AiohttpTransport(session=session))


class MunichTransportOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing station entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""

        self._config_entry = config_entry
        self._direction_options: list[StationDirectionOption] = []

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user update selected line/direction pairings."""

        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_DIRECTION_OPTION_IDS: _selected_direction_ids_from_sections(
                        user_input,
                    ),
                },
            )

        try:
            station = Station(
                global_id=self._config_entry.data[CONF_STATION_GLOBAL_ID],
                name=self._config_entry.data[CONF_NAME],
                place=self._config_entry.data.get(CONF_STATION_PLACE),
                latitude=0.0,
                longitude=0.0,
                abbreviation=self._config_entry.data.get(CONF_STATION_ABBREVIATION),
            )
            self._direction_options = await _fetch_direction_options(
                self._client(),
                station,
            )
        except MunichTransportError:
            errors["base"] = "cannot_connect"

        option_ids = set(_direction_option_ids(self._direction_options))
        selected = [
            option_id
            for option_id in self._config_entry.options.get(
                CONF_DIRECTION_OPTION_IDS,
                (),
            )
            if option_id in option_ids
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=_direction_sections_schema(
                self._direction_options,
                selected_ids=set(selected),
            ),
            errors=errors,
        )

    def _client(self) -> MunichTransportClient:
        session = async_get_clientsession(self.hass)
        return MunichTransportClient(AiohttpTransport(session=session))


async def _fetch_direction_options(
    client: MunichTransportClient,
    station: Station,
) -> list[StationDirectionOption]:
    if station.abbreviation:
        return await client.station_direction_options_by_abbreviation(
            station.abbreviation,
        )
    return await client.station_direction_options(station.global_id)


def _station_choices(locations: Mapping[str, Location]) -> dict[str, str]:
    return {
        global_id: _format_station(location)
        for global_id, location in sorted(
            locations.items(),
            key=lambda item: _format_station(item[1]),
        )
    }


def _direction_sections_schema(
    options: list[StationDirectionOption],
    selected_ids: set[str] | None = None,
) -> vol.Schema:
    data_schema: dict[Any, Any] = {}
    grouped_options = _options_by_schedule_kind(options)

    for schedule_kind, group_options in grouped_options.items():
        section_key = _section_key(schedule_kind)
        field_key = _section_field_key(schedule_kind)
        default = [
            option.id
            for option in _sorted_direction_options(group_options)
            if selected_ids is None or option.id in selected_ids
        ]
        data_schema[vol.Required(section_key)] = section(
            vol.Schema(
                {
                    vol.Optional(
                        field_key,
                        default=default,
                    ): _direction_option_selector(group_options),
                },
            ),
            {"collapsed": False},
        )

    return vol.Schema(data_schema)


def _direction_option_selector(options: list[StationDirectionOption]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=option.id, label=_direction_option_label(option))
                for option in _sorted_direction_options(options)
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


def _selected_direction_ids_from_sections(user_input: dict[str, Any]) -> list[str]:
    if CONF_DIRECTION_OPTION_IDS in user_input:
        return list(user_input[CONF_DIRECTION_OPTION_IDS])

    selected_ids: list[str] = []
    for section_value in user_input.values():
        if not isinstance(section_value, dict):
            continue
        for field_value in section_value.values():
            if isinstance(field_value, list):
                selected_ids.extend(str(option_id) for option_id in field_value)
    return selected_ids


def _direction_option_ids(options: list[StationDirectionOption]) -> list[str]:
    return [option.id for option in _sorted_direction_options(options)]


def _options_by_schedule_kind(
    options: list[StationDirectionOption],
) -> dict[str, list[StationDirectionOption]]:
    grouped_options: dict[str, list[StationDirectionOption]] = {}
    for option in _sorted_direction_options(options):
        grouped_options.setdefault(option.schedule_kind, []).append(option)
    return grouped_options


def _sorted_direction_options(
    options: list[StationDirectionOption],
) -> list[StationDirectionOption]:
    return sorted(
        options,
        key=lambda option: (
            _schedule_kind_label(option.schedule_kind),
            option.line_label,
            option.direction_key or "",
            option.id,
        ),
    )


def _direction_option_label(option: StationDirectionOption) -> str:
    selection = direction_selection_from_option(option)
    return selection.label


def _schedule_kind_label(schedule_kind: str) -> str:
    return _SECTION_LABELS.get(
        schedule_kind,
        ("other", schedule_kind.replace("_", " ").title()),
    )[1]


def _section_key(schedule_kind: str) -> str:
    return _SECTION_LABELS.get(schedule_kind, ("other", "Other"))[0]


def _section_field_key(schedule_kind: str) -> str:
    return f"{CONF_DIRECTION_OPTION_IDS}_{_section_key(schedule_kind)}"


def _format_station(location: Location) -> str:
    if location.place:
        return f"{location.name}, {location.place}"
    return location.name
