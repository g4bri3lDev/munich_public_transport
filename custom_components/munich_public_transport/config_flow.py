"""Config flow for Munich Public Transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowHandler, section
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
import probatio

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_PLACE,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_TYPE_STATION,
)
from .entity import direction_label

CONF_QUERY = "query"
CONF_SELECTED_STATION = "selected_station"

# Catalog schedule kinds, plus the transport types live departures report for
# stations without a catalog, mapped to one form section each.
_SECTIONS = {
    "BAHN": "train",
    "BUS": "bus",
    "NIGHT_LINE": "night_line",
    "REGIONAL_BUS": "regional_bus",
    "SBAHN": "s_bahn",
    "SEV": "replacement_service",
    "SUBWAY": "subway",
    "TRAM": "tram",
    "UBAHN": "subway",
}
_SECTION_ORDER = (
    "subway",
    "s_bahn",
    "tram",
    "bus",
    "night_line",
    "regional_bus",
    "train",
    "replacement_service",
    "other",
)


if TYPE_CHECKING:
    # Lets the mixin call the flow API both flows share, without inheriting it.
    _FlowBase = FlowHandler[Any, Any, Any]
else:
    _FlowBase = object


class _StationFlow(_FlowBase):
    """Station search and direction selection shared by both flows."""

    _locations: dict[str, Location]
    _station: Station
    _direction_options: list[StationDirectionOption]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Ask for a station search query."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                locations = await _client(self.hass).search_locations(
                    user_input[CONF_QUERY].strip()
                )
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
            data_schema=probatio.Schema({probatio.Required(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_select_station(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Let the user choose a station from the search results."""

        errors: dict[str, str] = {}
        if user_input is not None:
            global_id = user_input[CONF_SELECTED_STATION]
            if self._station_configured(global_id):
                return self.async_abort(reason="already_configured")

            client = _client(self.hass)
            try:
                self._station = await client.station(global_id)
                self._direction_options = await client.direction_options_for_station(
                    self._station
                )
            except ParseError:
                errors["base"] = "invalid_station"
            except MunichTransportError:
                errors["base"] = "cannot_connect"
            else:
                if self._direction_options:
                    return await self.async_step_select_directions()
                errors["base"] = "no_direction_options"

        return self.async_show_form(
            step_id="select_station",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_SELECTED_STATION): probatio.In(
                        _station_choices(self._locations)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_select_directions(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Let the user choose line/direction pairings."""

        if user_input is not None:
            station = self._station
            return self._async_create_station(
                station.name,
                {
                    CONF_NAME: station.name,
                    CONF_STATION_GLOBAL_ID: station.global_id,
                    CONF_STATION_ABBREVIATION: station.abbreviation,
                    CONF_STATION_PLACE: station.place,
                    CONF_DIRECTION_OPTION_IDS: _selected_ids(user_input),
                },
                station.global_id,
            )

        return self.async_show_form(
            step_id="select_directions",
            data_schema=_directions_schema(self._direction_options),
        )

    def _station_configured(self, global_id: str) -> bool:
        raise NotImplementedError

    def _async_create_station(
        self, title: str, data: dict[str, Any], global_id: str
    ) -> Any:
        raise NotImplementedError


class MunichTransportConfigFlow(_StationFlow, ConfigFlow, domain=DOMAIN):
    """Set up the MVG entry together with its first station."""

    VERSION = CONFIG_ENTRY_VERSION

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: one per station."""

        return {SUBENTRY_TYPE_STATION: StationSubentryFlow}

    @override
    def _station_configured(self, global_id: str) -> bool:
        return False

    @override
    def _async_create_station(
        self, title: str, data: dict[str, Any], global_id: str
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=ENTRY_TITLE,
            data={},
            subentries=[
                ConfigSubentryData(
                    data=data,
                    subentry_type=SUBENTRY_TYPE_STATION,
                    title=title,
                    unique_id=global_id,
                )
            ],
        )


class StationSubentryFlow(_StationFlow, ConfigSubentryFlow):
    """Add a station, or change the directions of one."""

    @override
    def _station_configured(self, global_id: str) -> bool:
        return any(
            subentry.unique_id == global_id
            for subentry in self._get_entry().subentries.values()
        )

    @override
    def _async_create_station(
        self, title: str, data: dict[str, Any], global_id: str
    ) -> SubentryFlowResult:
        return self.async_create_entry(title=title, data=data, unique_id=global_id)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change which directions of a station are exposed."""

        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data_updates={CONF_DIRECTION_OPTION_IDS: _selected_ids(user_input)},
            )

        data = subentry.data
        try:
            options = await _client(self.hass).direction_options_for_station(
                Station(
                    global_id=data[CONF_STATION_GLOBAL_ID],
                    name=data[CONF_NAME],
                    place=data.get(CONF_STATION_PLACE),
                    latitude=0.0,
                    longitude=0.0,
                    abbreviation=data.get(CONF_STATION_ABBREVIATION),
                )
            )
        except MunichTransportError:
            # Without options the form has no fields, and submitting it would
            # save an empty selection and remove every direction.
            aborted: SubentryFlowResult = self.async_abort(reason="cannot_connect")
            return aborted

        form: SubentryFlowResult = self.async_show_form(
            step_id="reconfigure",
            data_schema=_directions_schema(
                options, selected_ids=set(data.get(CONF_DIRECTION_OPTION_IDS, ()))
            ),
            description_placeholders={"station": subentry.title},
        )
        return form


def _client(hass: HomeAssistant) -> MunichTransportClient:
    return MunichTransportClient(
        AiohttpTransport(session=async_get_clientsession(hass))
    )


def _station_choices(locations: Mapping[str, Location]) -> dict[str, str]:
    return dict(
        sorted(
            (
                (global_id, f"{location.name}, {location.place}")
                if location.place
                else (global_id, location.name)
                for global_id, location in locations.items()
            ),
            key=lambda item: item[1],
        )
    )


def _directions_schema(
    options: list[StationDirectionOption],
    selected_ids: set[str] | None = None,
) -> probatio.Schema:
    """Build one collapsible multi-select per transport type."""

    grouped: dict[str, list[StationDirectionOption]] = {}
    for option in sorted(
        options,
        key=lambda option: (option.line_label, option.direction_key or "", option.id),
    ):
        grouped.setdefault(_SECTIONS.get(option.schedule_kind, "other"), []).append(
            option
        )

    schema: dict[Any, Any] = {}
    for section_key in _SECTION_ORDER:
        if section_key not in grouped:
            continue
        group = grouped[section_key]
        schema[probatio.Required(section_key)] = section(
            probatio.Schema(
                {
                    probatio.Optional(
                        f"{CONF_DIRECTION_OPTION_IDS}_{section_key}",
                        default=[
                            option.id
                            for option in group
                            if selected_ids is None or option.id in selected_ids
                        ],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=option.id, label=direction_label(option)
                                )
                                for option in group
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            {"collapsed": False},
        )
    return probatio.Schema(schema)


def _selected_ids(user_input: dict[str, Any]) -> list[str]:
    return [
        str(option_id)
        for section_value in user_input.values()
        if isinstance(section_value, dict)
        for field_value in section_value.values()
        if isinstance(field_value, list)
        for option_id in field_value
    ]
