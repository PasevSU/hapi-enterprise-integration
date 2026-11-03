"""Constants for the hAPI Enterprise Home Assistant integration."""

from __future__ import annotations

DOMAIN = "hapi_enterprise"
NAME = "hAPI Enterprise"

# `sensor` носи числата и решението, `binary_sensor` — „има ли проблем сега“ (problem)
# и „живо ли е API-то“ (connectivity). Двете платформи ползват ОБЩА снимка от
# координатора, значи едно обновяване на 60 s стига за всички обекти.
PLATFORMS = ["sensor", "binary_sensor"]

CONF_BACKEND_URL = "backend_url"
CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"
# Адресът, който човек отваря в браузъра (панелът на hAPI). Може да е ingress адрес или
# публичен адрес — различен от `backend_url`, който Home Assistant ползва за заявки.
# По подразбиране се взима `backend_url` + `/ui/`, но когато add-on-ът е достъпен само през
# Supervisor ingress, този адрес не се отваря от браузъра и полето е задължително за връзка.
CONF_PANEL_URL = "panel_url"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 86400
MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 512

# Telemetry of the add-on. The integration talks to the PUBLIC listener (8099) with a Bearer
# token: the ingress listener (8098) accepts only the Supervisor and loopback, so Home
# Assistant cannot reach it (it is not either of those).
SENSORS_PATH = "/admin/api/sensors"
