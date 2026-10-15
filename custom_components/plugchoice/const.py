"""Constants for the PlugChoice integration."""

DOMAIN = "plugchoice"

CONF_API_KEY = "api_key"
CONF_CHARGER_UUID = "charger_uuid"
CONF_TOKEN_ID = "token_id"

API_BASE_URL = "https://app.plugchoice.com/api/v3"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 3600

CONF_CONNECTOR_ID = "connector_id"
DEFAULT_CONNECTOR_ID = 1

CONF_DISTANCE_KM = "distance_km"
CONF_EFFICIENCY_KM_PER_KWH = "efficiency_km_per_kwh"
CONF_DEADLINE = "charging_deadline"
CONF_DIRECT_CHARGING = "direct_charging"
CONF_MIN_SOLAR_KWH = "min_solar_kwh"
CONF_TEST_MODE = "test_mode"

SOLCAST_FORECAST_ENTITIES = (
	"sensor.solcast_pv_forecast_voorspelling_vandaag",
	"sensor.solcast_pv_forecast_voorspelling_morgen",
	"sensor.solcast_pv_forecast_voorspelling_dag_3",
)
