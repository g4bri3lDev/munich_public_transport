from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from mvg import MvgApi

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_DEPARTURE_COUNT

import logging

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Munich Public Transport."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.stations = []
        self.selected_station = None
        self.departures = []
        self.lines = []
        self.selected_lines = []
        self.directions = set()
        self.selected_directions = []
        self.departure_count = DEFAULT_DEPARTURE_COUNT
        self.scan_interval = DEFAULT_SCAN_INTERVAL

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required("search_query"): str,
                }),
                description_placeholders={
                    "query_instructions": "Enter part of the station name to search"
                },
            )

        search_query = user_input["search_query"].lower()
        try:
            all_stations = await MvgApi.stations_async()
            self.stations = [
                station for station in all_stations
                if search_query in station["name"].lower()
            ]
            if not self.stations:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({
                        vol.Required("search_query"): str,
                    }),
                    errors={"base": "no_stations_found"},
                    description_placeholders={
                        "query_instructions": "No stations found. Try a different search term."
                    },
                )
            return await self.async_step_select_station()
        except Exception as err:
            _LOGGER.error("Error searching for stations: %s", err)
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required("search_query"): str,
                }),
                errors={"base": "cannot_connect"},
                description_placeholders={
                    "query_instructions": "An error occurred. Please try again."
                },
            )

    async def async_step_select_station(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the station selection step."""
        if user_input is None:
            station_names = [station["name"] for station in self.stations]
            return self.async_show_form(
                step_id="select_station",
                data_schema=vol.Schema({
                    vol.Required("station"): vol.In(station_names),
                }),
            )

        self.selected_station = next(
            station for station in self.stations if station["name"] == user_input["station"]
        )
        try:
            self.departures = await MvgApi.departures_async(self.selected_station["id"])
        except Exception as err:
            _LOGGER.error(f"Error fetching departures: {err}")
            return self.async_abort(reason="cannot_connect")

        return await self.async_step_select_lines()

    async def async_step_select_lines(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the line selection step."""
        if user_input is None:
            self.lines = sorted(set(dep["line"] for dep in self.departures))
            return self.async_show_form(
                step_id="select_lines",
                data_schema=vol.Schema({
                    vol.Required("lines", default=self.lines): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self.lines,
                            multiple=True,
                            custom_value=False,
                        ),
                    ),
                }),
                description_placeholders={
                    "instructions": "Select the lines you want to track (all are selected by default)"
                },
            )

        self.selected_lines = user_input["lines"]
        return await self.async_step_select_directions()

    async def async_step_select_directions(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the direction selection step."""
        if user_input is None:
            self.directions = sorted(set(
                dep["destination"] for dep in self.departures
                if dep["line"] in self.selected_lines
            ))
            return self.async_show_form(
                step_id="select_directions",
                data_schema=vol.Schema({
                    vol.Required("directions", default=self.directions): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(self.directions),
                            multiple=True,
                            custom_value=False,
                        ),
                    ),
                }),
                description_placeholders={
                    "instructions": "Select the directions you want to track (all are selected by default)"
                },
            )

        self.selected_directions = user_input["directions"]
        return await self.async_step_other_options()

    async def async_step_other_options(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the departure count and scan interval selection step."""
        if user_input is None:
            return self.async_show_form(
                step_id="other_options",
                data_schema=vol.Schema({
                    vol.Required("departure_count", default=DEFAULT_DEPARTURE_COUNT): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=20,
                            mode=selector.NumberSelectorMode.BOX
                        ),
                    ),
                    vol.Required("scan_interval", default=DEFAULT_SCAN_INTERVAL): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=60,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX
                        ),
                    ),
                }),
            )

        self.departure_count = user_input["departure_count"]
        self.scan_interval = user_input["scan_interval"]

        await self.async_set_unique_id(self.selected_station["id"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self.selected_station["name"],
            data={
                "station_id": self.selected_station["id"],
                "station_name": self.selected_station["name"],
                "lines": self.selected_lines,
                "directions": self.selected_directions,
                "departure_count": self.departure_count,
                "scan_interval": self.scan_interval,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Munich Public Transport."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.departures = []

    async def async_step_init(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_directions()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "lines",
                        default=self.config_entry.options.get("lines", self.config_entry.data.get("lines", []))
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self.options.get("lines", []),
                            multiple=True,
                            custom_value=False,
                        ),
                    ),
                }
            ),
        )

    async def async_step_directions(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage direction options."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_other_options()

        return self.async_show_form(
            step_id="directions",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "directions",
                        default=self.config_entry.options.get("directions", self.config_entry.data.get("directions", []))
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self.options.get("directions", []),
                            multiple=True,
                            custom_value=False,
                        ),
                    ),
                }
            ),
        )

    async def async_step_other_options(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage other options."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="other_options",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "departure_count",
                        default=self.config_entry.options.get("departure_count", self.config_entry.data.get("departure_count", DEFAULT_DEPARTURE_COUNT))
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=20,
                            mode=selector.NumberSelectorMode.BOX
                        ),
                    ),
                    vol.Required(
                        "scan_interval",
                        default=self.config_entry.options.get("scan_interval", self.config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=60,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX
                        ),
                    ),
                }
            ),
        )