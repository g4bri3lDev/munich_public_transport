"""Constants for the Munich Public Transport integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_NAME, Platform

DOMAIN = "munich_public_transport"

PLATFORMS = (Platform.SENSOR,)

CONF_STATION_GLOBAL_ID = "station_global_id"
CONF_STATION_ABBREVIATION = "station_abbreviation"
CONF_STATION_PLACE = "station_place"
CONF_DIRECTION_OPTION_IDS = "direction_option_ids"

OLD_CONF_STATION_ID = "station_id"
OLD_CONF_STATION_NAME = "station_name"
OLD_CONF_LINES = "lines"
OLD_CONF_DIRECTIONS = "directions"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=45)
DEFAULT_DEPARTURE_LIMIT = 10

ATTR_CANCELLED = "cancelled"
ATTR_DELAY = "delay"
ATTR_DEPARTURES = "departures"
ATTR_DESTINATION = "destination"
ATTR_DIRECTION_KEY = "direction_key"
ATTR_DIRECTION_VARIANTS = "direction_variants"
ATTR_IS_LATE = "is_late"
ATTR_LINE = "line"
ATTR_MINUTES_UNTIL_DEPARTURE = "minutes_until_departure"
ATTR_NETWORK = "network"
ATTR_NORMAL_TERMINUS = "normal_terminus"
ATTR_OCCUPANCY = "occupancy"
ATTR_PLATFORM = "platform"
ATTR_PLATFORM_CHANGED = "platform_changed"
ATTR_PLANNED_DEPARTURE = "planned_departure"
ATTR_REALTIME = "realtime"
ATTR_REALTIME_DEPARTURE = "realtime_departure"
ATTR_SCHEDULE_KIND = "schedule_kind"
ATTR_TOTAL_DEPARTURES = "total_departures"
ATTR_TRANSPORT_TYPE = "type"

ENTRY_DATA_KEYS = {
    CONF_NAME,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_PLACE,
}
