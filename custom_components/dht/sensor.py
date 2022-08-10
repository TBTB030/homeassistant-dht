"""Support for Adafruit DHT temperature and humidity sensor."""
from __future__ import annotations

import logging

import adafruit_dht
# import Adafruit_DHT
import board
import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS,
    CONF_NAME,
    CONF_PIN,
    PERCENTAGE,
    TEMP_CELSIUS,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import slugify
from tenacity import retry

_LOGGER = logging.getLogger(__name__)

CONF_SENSOR = "sensor"
CONF_HUMIDITY_OFFSET = "humidity_offset"
CONF_TEMPERATURE_OFFSET = "temperature_offset"

DEFAULT_NAME = "DHT Sensor"


SENSOR_TEMPERATURE = "temperature"
SENSOR_HUMIDITY = "humidity"
SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=SENSOR_TEMPERATURE,
        name="Temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key=SENSOR_HUMIDITY,
        name="Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

SENSOR_KEYS: list[str] = [desc.key for desc in SENSOR_TYPES]


def validate_pin_input(value):
    """Validate that the GPIO PIN is prefixed with a D."""
    try:
        int(value)
        return f"D{value}"
    except ValueError:
        return value.upper()


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENSOR): cv.string,
        vol.Required(CONF_PIN): vol.All(cv.string, validate_pin_input),
        vol.Optional(CONF_MONITORED_CONDITIONS, default=[]): vol.All(
            cv.ensure_list, [vol.In(SENSOR_KEYS)]
        ),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TEMPERATURE_OFFSET, default=0): vol.All(
            vol.Coerce(float), vol.Range(min=-100, max=100)
        ),
        vol.Optional(CONF_HUMIDITY_OFFSET, default=0): vol.All(
            vol.Coerce(float), vol.Range(min=-100, max=100)
        ),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the DHT sensor."""

    available_sensors = {
        "AM2302": adafruit_dht.DHT22,
        "DHT11": adafruit_dht.DHT11,
        "DHT22": adafruit_dht.DHT22,
        # "AM2302_OLD_LIBRARY": Adafruit_DHT.AM2302,
        # "DHT11_OLD_LIBRARY": Adafruit_DHT.DHT11,
        # "DHT22_OLD_LIBRARY": Adafruit_DHT.DHT22,
    }
    sensor = available_sensors.get(config[CONF_SENSOR])
    pin = config[CONF_PIN]
    temperature_offset = config[CONF_TEMPERATURE_OFFSET]
    humidity_offset = config[CONF_HUMIDITY_OFFSET]
    name = config[CONF_NAME]

    if not sensor:
        _LOGGER.error("DHT sensor type is not supported")
        return

    data = DHTClient(sensor, pin, name)

    monitored_conditions = config[CONF_MONITORED_CONDITIONS]
    entities = [
        DHTSensor(data, name, temperature_offset, humidity_offset, description)
        for description in SENSOR_TYPES
        if description.key in monitored_conditions
    ]

    add_entities(entities, True)


class DHTSensor(SensorEntity):
    """Implementation of the DHT sensor."""

    def __init__(
        self,
        dht_client,
        name,
        temperature_offset,
        humidity_offset,
        description: SensorEntityDescription,
    ):
        """Initialize the sensor."""
        self.entity_description = description
        self.dht_client = dht_client
        self.temperature_offset = temperature_offset
        self.humidity_offset = humidity_offset

        self._attr_name: str = f"{name} {description.name}"
        self._attr_unique_id: str = slugify(self._attr_name)

    def update(self):
        """Get the latest data from the DHT and updates the states."""
        self.dht_client.update()
        temperature_offset = self.temperature_offset
        humidity_offset = self.humidity_offset
        data = self.dht_client.data

        sensor_type = self.entity_description.key
        if sensor_type == SENSOR_TEMPERATURE and sensor_type in data:
            temperature = data[SENSOR_TEMPERATURE]
            _LOGGER.debug(
                "Temperature %.1f \u00b0C + offset %.1f",
                temperature,
                temperature_offset,
            )
            if -20 <= temperature < 80:
                self._attr_native_value = round(temperature + temperature_offset, 1)
        elif sensor_type == SENSOR_HUMIDITY and sensor_type in data:
            humidity = data[SENSOR_HUMIDITY]
            _LOGGER.debug("Humidity %.1f%% + offset %.1f", humidity, humidity_offset)
            if 0 <= humidity <= 100:
                self._attr_native_value = round(humidity + humidity_offset, 1)


class DHTClient:
    """Get the latest data from the DHT sensor."""

    def __init__(self, sensor, pin, name):
        """Initialize the sensor."""
        self.sensor = sensor
        self.pin = getattr(board, pin)
        self.data = {}
        self.name = name

    # DHT11 is able to deliver data once per second, DHT22 once every two
    @retry(reraise=True, retry=retry_if_exception_type(RuntimeError), stop=stop_after_attempt(10), wait = wait_random(min = 1, max = 2), after=after_log(_LOGGER, logging.WARNING))
    def read_retry(dht):
        temperature = dht.temperature
        humidity = dht.humidity
        return (temperature, humidity)

    def update(self):
        """Get the latest data the DHT sensor."""
        dht = self.sensor(self.pin)
        try:
            temperature, humidity = self.read_retry(dht)
        except RuntimeError as e:
            _LOGGER.warning("Unexpected value from DHT sensor: %s", e)
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.exception("Error updating DHT sensor: %s", e)
        else:
            if temperature:
                self.data[SENSOR_TEMPERATURE] = temperature
            if humidity:
                self.data[SENSOR_HUMIDITY] = humidity
        finally:
            dht.exit()
