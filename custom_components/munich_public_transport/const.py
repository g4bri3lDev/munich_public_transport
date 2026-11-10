"""Constants for the Munich Public Transport integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_NAME, Platform

DOMAIN = "munich_public_transport"

PLATFORMS = (Platform.BINARY_SENSOR, Platform.SENSOR)

# 1: one entry per station, pre-rewrite schema
# 2: one entry per station, rewrite schema (1.x releases)
# 3: one MVG entry with a subentry per station
CONFIG_ENTRY_VERSION = 3

ENTRY_TITLE = "MVG"
SUBENTRY_TYPE_STATION = "station"

CONF_STATION_GLOBAL_ID = "station_global_id"
CONF_STATION_ABBREVIATION = "station_abbreviation"
CONF_STATION_PLACE = "station_place"
CONF_DIRECTION_OPTION_IDS = "direction_option_ids"
# The selected options themselves, so starting up needs no MVG requests to
# name and match them.
CONF_DIRECTION_OPTIONS = "direction_options"
# Minutes from now that a station's departures are loaded for, which can take
# several requests since MVG caps each response.
CONF_LOOK_AHEAD = "look_ahead"
MAX_LOOK_AHEAD = 90

OLD_CONF_STATION_ID = "station_id"
OLD_CONF_STATION_NAME = "station_name"
OLD_CONF_LINES = "lines"
OLD_CONF_DIRECTIONS = "directions"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)
DEFAULT_MESSAGES_SCAN_INTERVAL = timedelta(minutes=30)

SERVICE_GET_DEPARTURES = "get_departures"
ATTR_DEVICE_ID = "device_id"

ATTRIBUTION = "Data provided by MVG"

STATION_DATA_KEYS = (
    CONF_NAME,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_PLACE,
)
