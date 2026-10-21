"""Constants for the hAPI Enterprise Home Assistant integration."""

from __future__ import annotations

DOMAIN = "hapi_enterprise"
NAME = "hAPI Enterprise"

PLATFORMS = ["sensor"]

CONF_BACKEND_URL = "backend_url"
CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 86400
MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 512

# Telemetry of the add-on, served on the admin listener (ingress port 8098).
SENSORS_PATH = "/admin/api/sensors"
