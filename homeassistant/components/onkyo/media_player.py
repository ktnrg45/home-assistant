"""Support for Onkyo Receivers."""
import logging

import defusedxml.ElementTree as ET
import eiscp
from eiscp import eISCP
import voluptuous as vol

from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    DOMAIN,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_NAME,
    STATE_OFF,
    STATE_ON,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import (
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOURCES,
    DEFAULT_NAME,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_SOURCES,
    ONKYO_DATA,
    SUPPORTED_MAX_VOLUME,
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_ONKYO = (
    SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_VOLUME_STEP
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY
    | SUPPORT_PLAY_MEDIA
)

SUPPORT_ONKYO_WO_VOLUME = (
    SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY
    | SUPPORT_PLAY_MEDIA
)

DEFAULT_PLAYABLE_SOURCES = ("fm", "am", "tuner")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_MAX_VOLUME, default=SUPPORTED_MAX_VOLUME): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional(
            CONF_RECEIVER_MAX_VOLUME, default=DEFAULT_RECEIVER_MAX_VOLUME
        ): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(CONF_SOURCES, default=DEFAULT_SOURCES): {cv.string: cv.string},
    }
)

TIMEOUT_MESSAGE = "Timeout waiting for response."


ATTR_HDMI_OUTPUT = "hdmi_output"
ATTR_PRESET = "preset"

ACCEPTED_VALUES = [
    "no",
    "analog",
    "yes",
    "out",
    "out-sub",
    "sub",
    "hdbaset",
    "both",
    "up",
]
ONKYO_SELECT_OUTPUT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_HDMI_OUTPUT): vol.In(ACCEPTED_VALUES),
    }
)

SERVICE_SELECT_HDMI_OUTPUT = "onkyo_select_hdmi_output"


def get_receiver_info(ip_address):
    """Return dict of extended device values."""
    reformat = ["AUX", "VIDEO"]
    source_mapping = {}
    info = {}
    receiver_info = {}

    receiver = eISCP(ip_address)
    if receiver.info is None:
        # Return if there is no basic info.
        return receiver_info
    data = receiver.command("dock.receiver-information=query")[1]
    data = ET.fromstring(data)
    info = list(data)[0]
    brand = info.find("brand")
    firmwareversion = info.find("firmwareversion")
    selectors = info.find("selectorlist")

    if firmwareversion is not None:
        firmwareversion = firmwareversion.text
    if brand is not None:
        brand = brand.text.title()
    if selectors is not None:
        for source in selectors.iter():
            source_name = source.attrib.get("name")
            if source.tag != "selector" or source_name == "Source":
                continue
            source_alias = source_name.replace(" ", "-").split("/")[0]
            if source_alias in reformat:
                source_alias = f"{source_alias}1"
            source_mapping[source_alias] = source_name

    receiver_info = {
        "firmwareversion": firmwareversion,
        "identifier": receiver.identifier,
        "manufacturer": brand or DOMAIN.title(),
        "model": receiver.model_name,
        "name": receiver.model_name,
        "sources": source_mapping or DEFAULT_SOURCES,
    }
    return receiver_info


def determine_zones(receiver):
    """Determine what zones are available for the receiver."""
    out = {"zone2": False, "zone3": False}
    try:
        _LOGGER.debug("Checking for zone 2 capability")
        receiver.raw("ZPW")
        out["zone2"] = True
    except ValueError as error:
        if str(error) != TIMEOUT_MESSAGE:
            raise error
        _LOGGER.debug("Zone 2 timed out, assuming no functionality")
    try:
        _LOGGER.debug("Checking for zone 3 capability")
        receiver.raw("PW3")
        out["zone3"] = True
    except ValueError as error:
        if str(error) != TIMEOUT_MESSAGE:
            raise error
        _LOGGER.debug("Zone 3 timed out, assuming no functionality")

    return out


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Onkyo from a config entry."""
    info = await hass.async_add_executor_job(
        get_receiver_info, config_entry.data[CONF_HOST]
    )
    device_registry = await hass.helpers.device_registry.async_get_registry()
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, info["identifier"])},
        manufacturer=info["manufacturer"],
        model=info["model"],
        name=info["name"],
        sw_version=info["firmwareversion"],
    )
    config = config_entry.data
    await hass.async_add_executor_job(setup_platform, hass, config, async_add_entities)
    hass.data[ONKYO_DATA][config_entry.entry_id] = config_entry.add_update_listener(
        update_listener
    )
    return True


async def update_listener(hass, config_entry):
    """Handle Onkyo options update."""
    _LOGGER.debug("Onkyo options updated")
    devices = hass.data[ONKYO_DATA].get(config_entry.data[CONF_HOST])
    if devices is not None:
        for device in devices:
            await device.async_options_update(config_entry.options)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Onkyo platform."""
    host = config.get(CONF_HOST)
    hosts = []

    def service_handle(service):
        """Handle for services."""
        entity_ids = service.data.get(ATTR_ENTITY_ID)
        devices = [d for d in hosts if d.entity_id in entity_ids]

        for device in devices:
            if service.service == SERVICE_SELECT_HDMI_OUTPUT:
                device.select_output(service.data.get(ATTR_HDMI_OUTPUT))

    hass.services.register(
        DOMAIN,
        SERVICE_SELECT_HDMI_OUTPUT,
        service_handle,
        schema=ONKYO_SELECT_OUTPUT_SCHEMA,
    )

    if CONF_HOST in config and host not in hass.data[ONKYO_DATA]:
        try:
            receiver = eiscp.eISCP(host)
            hosts.append(
                OnkyoDevice(
                    receiver,
                    config.get(CONF_SOURCES),
                    name=config.get(CONF_NAME),
                    max_volume=config.get(CONF_MAX_VOLUME),
                    receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME),
                )
            )

            zones = determine_zones(receiver)

            # Add Zone2 if available
            if zones["zone2"]:
                _LOGGER.debug("Setting up zone 2")
                hosts.append(
                    OnkyoDeviceZone(
                        "2",
                        receiver,
                        config.get(CONF_SOURCES),
                        name=f"{config[CONF_NAME]} Zone 2",
                        max_volume=config.get(CONF_MAX_VOLUME),
                        receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME),
                    )
                )
            # Add Zone3 if available
            if zones["zone3"]:
                _LOGGER.debug("Setting up zone 3")
                hosts.append(
                    OnkyoDeviceZone(
                        "3",
                        receiver,
                        config.get(CONF_SOURCES),
                        name=f"{config[CONF_NAME]} Zone 3",
                        max_volume=config.get(CONF_MAX_VOLUME),
                        receiver_max_volume=config.get(CONF_RECEIVER_MAX_VOLUME),
                    )
                )
            hass.data[ONKYO_DATA][host] = hosts
        except OSError:
            _LOGGER.error("Unable to connect to receiver at %s", host)
    else:
        for receiver in eISCP.discover():
            if receiver.host not in hass.data[ONKYO_DATA]:
                hosts.append(OnkyoDevice(receiver, config.get(CONF_SOURCES)))
                hass.data[ONKYO_DATA][receiver.host] = hosts
    add_entities(hosts, True)


class OnkyoDevice(MediaPlayerEntity):
    """Representation of an Onkyo device."""

    def __init__(
        self,
        receiver,
        sources,
        name=None,
        max_volume=SUPPORTED_MAX_VOLUME,
        receiver_max_volume=DEFAULT_RECEIVER_MAX_VOLUME,
    ):
        """Initialize the Onkyo Receiver."""
        self._receiver = receiver
        self._muted = False
        self._volume = 0
        self._pwstate = STATE_OFF
        self._name = name or DEFAULT_NAME
        self._max_volume = max_volume or SUPPORTED_MAX_VOLUME
        self._receiver_max_volume = receiver_max_volume or DEFAULT_RECEIVER_MAX_VOLUME
        self._current_source = None
        self._source_list = list(sources.values())
        self._source_mapping = sources
        self._reverse_mapping = {value: key for key, value in sources.items()}
        self._attributes = {}
        self._unique_id = f"{receiver.info['model_name']}_{receiver.info['identifier']}"

    async def async_will_remove_from_hass(self):
        """Remove Entity from Home Assistant."""
        if self._receiver.host in self.hass.data[ONKYO_DATA]:
            self.hass.data[ONKYO_DATA].pop(self._receiver.host)

    async def async_options_update(self, options):
        """Handle options updated."""
        self._max_volume = options[CONF_MAX_VOLUME]
        self._receiver_max_volume = options[CONF_RECEIVER_MAX_VOLUME]
        _LOGGER.debug(
            "Max Volume=%s Receiver Max Volume=%s",
            self._max_volume,
            self._receiver_max_volume,
        )

    def command(self, command):
        """Run an eiscp command and catch connection errors."""
        try:
            result = self._receiver.command(command)
        except (ValueError, OSError, AttributeError, AssertionError):
            if self._receiver.command_socket:
                self._receiver.command_socket = None
                _LOGGER.debug("Resetting connection to %s", self._name)
            else:
                _LOGGER.info("%s is disconnected. Attempting to reconnect", self._name)
            return False
        return result

    def update(self):
        """Get the latest state from the device."""
        status = self.command("system-power query")

        if not status:
            return
        if status[1] == "on":
            self._pwstate = STATE_ON
        else:
            self._pwstate = STATE_OFF
            return

        volume_raw = self.command("volume query")
        mute_raw = self.command("audio-muting query")
        current_source_raw = self.command("input-selector query")
        hdmi_out_raw = self.command("hdmi-output-selector query")
        preset_raw = self.command("preset query")
        if not (volume_raw and mute_raw and current_source_raw):
            return

        # eiscp can return string or tuple. Make everything tuples.
        if isinstance(current_source_raw[1], str):
            current_source_tuples = (current_source_raw[0], (current_source_raw[1],))
        else:
            current_source_tuples = current_source_raw

        for source in current_source_tuples[1]:
            if source in self._source_mapping:
                self._current_source = self._source_mapping[source]
                break
            self._current_source = "_".join(current_source_tuples[1])
        if preset_raw and self._current_source.lower() == "radio":
            self._attributes[ATTR_PRESET] = preset_raw[1]
        elif ATTR_PRESET in self._attributes:
            del self._attributes[ATTR_PRESET]

        self._muted = bool(mute_raw[1] == "on")
        #       AMP_VOL/MAX_RECEIVER_VOL*(MAX_VOL/100)
        self._volume = (
            volume_raw[1] / self._receiver_max_volume * (self._max_volume / 100)
        )

        if not hdmi_out_raw:
            return
        self._attributes["video_out"] = ",".join(hdmi_out_raw[1])

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._pwstate

    @property
    def volume_level(self):
        """Return the volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Return boolean indicating mute status."""
        return self._muted

    @property
    def supported_features(self):
        """Return media player features that are supported."""
        return SUPPORT_ONKYO

    @property
    def source(self):
        """Return the current input source of the device."""
        return self._current_source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_list

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return self._attributes

    @property
    def unique_id(self):
        """Return Unique ID for entity."""
        return self._unique_id

    def turn_off(self):
        """Turn the media player off."""
        self.command("system-power standby")

    def set_volume_level(self, volume):
        """
        Set volume level, input is range 0..1.

        However full volume on the amp is usually far too loud so allow the user to specify the upper range
        with CONF_MAX_VOLUME.  we change as per max_volume set by user. This means that if max volume is 80 then full
        volume in HA will give 80% volume on the receiver. Then we convert
        that to the correct scale for the receiver.
        """
        #        HA_VOL * (MAX VOL / 100) * MAX_RECEIVER_VOL
        self.command(
            f"volume {int(volume * (self._max_volume / 100) * self._receiver_max_volume)}"
        )

    def volume_up(self):
        """Increase volume by 1 step."""
        self.command("volume level-up")

    def volume_down(self):
        """Decrease volume by 1 step."""
        self.command("volume level-down")

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        if mute:
            self.command("audio-muting on")
        else:
            self.command("audio-muting off")

    def turn_on(self):
        """Turn the media player on."""
        self.command("system-power on")

    def select_source(self, source):
        """Set the input source."""
        if source in self._source_list:
            source = self._reverse_mapping[source]
        self.command(f"input-selector {source}")

    def play_media(self, media_type, media_id, **kwargs):
        """Play radio station by preset number."""
        source = self._reverse_mapping[self._current_source]
        if media_type.lower() == "radio" and source in DEFAULT_PLAYABLE_SOURCES:
            self.command(f"preset {media_id}")

    def select_output(self, output):
        """Set hdmi-out."""
        self.command(f"hdmi-output-selector={output}")


class OnkyoDeviceZone(OnkyoDevice):
    """Representation of an Onkyo device's extra zone."""

    def __init__(
        self,
        zone,
        receiver,
        sources,
        name=None,
        max_volume=SUPPORTED_MAX_VOLUME,
        receiver_max_volume=DEFAULT_RECEIVER_MAX_VOLUME,
    ):
        """Initialize the Zone with the zone identifier."""
        self._zone = zone
        self._supports_volume = True
        super().__init__(receiver, sources, name, max_volume, receiver_max_volume)
        self._unique_id = f"{self._unique_id}_zone_{self._zone}"

    def update(self):
        """Get the latest state from the device."""
        status = self.command(f"zone{self._zone}.power=query")

        if not status:
            return
        if status[1] == "on":
            self._pwstate = STATE_ON
        else:
            self._pwstate = STATE_OFF
            return

        volume_raw = self.command(f"zone{self._zone}.volume=query")
        mute_raw = self.command(f"zone{self._zone}.muting=query")
        current_source_raw = self.command(f"zone{self._zone}.selector=query")
        preset_raw = self.command(f"zone{self._zone}.preset=query")
        # If we received a source value, but not a volume value
        # it's likely this zone permanently does not support volume.
        if current_source_raw and not volume_raw:
            self._supports_volume = False

        if not (volume_raw and mute_raw and current_source_raw):
            return

        # It's possible for some players to have zones set to HDMI with
        # no sound control. In this case, the string `N/A` is returned.
        self._supports_volume = isinstance(volume_raw[1], (float, int))

        # eiscp can return string or tuple. Make everything tuples.
        if isinstance(current_source_raw[1], str):
            current_source_tuples = (current_source_raw[0], (current_source_raw[1],))
        else:
            current_source_tuples = current_source_raw

        for source in current_source_tuples[1]:
            if source in self._source_mapping:
                self._current_source = self._source_mapping[source]
                break
            self._current_source = "_".join(current_source_tuples[1])
        self._muted = bool(mute_raw[1] == "on")
        if preset_raw and self._current_source.lower() == "radio":
            self._attributes[ATTR_PRESET] = preset_raw[1]
        elif ATTR_PRESET in self._attributes:
            del self._attributes[ATTR_PRESET]
        if self._supports_volume:
            # AMP_VOL/MAX_RECEIVER_VOL*(MAX_VOL/100)
            self._volume = (
                volume_raw[1] / self._receiver_max_volume * (self._max_volume / 100)
            )

    @property
    def supported_features(self):
        """Return media player features that are supported."""
        if self._supports_volume:
            return SUPPORT_ONKYO
        return SUPPORT_ONKYO_WO_VOLUME

    def turn_off(self):
        """Turn the media player off."""
        self.command(f"zone{self._zone}.power=standby")

    def set_volume_level(self, volume):
        """
        Set volume level, input is range 0..1.

        However full volume on the amp is usually far too loud so allow the user to specify the upper range
        with CONF_MAX_VOLUME.  we change as per max_volume set by user. This means that if max volume is 80 then full
        volume in HA will give 80% volume on the receiver. Then we convert
        that to the correct scale for the receiver.
        """
        # HA_VOL * (MAX VOL / 100) * MAX_RECEIVER_VOL
        self.command(
            f"zone{self._zone}.volume={int(volume * (self._max_volume / 100) * self._receiver_max_volume)}"
        )

    def volume_up(self):
        """Increase volume by 1 step."""
        self.command(f"zone{self._zone}.volume=level-up")

    def volume_down(self):
        """Decrease volume by 1 step."""
        self.command(f"zone{self._zone}.volume=level-down")

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        if mute:
            self.command(f"zone{self._zone}.muting=on")
        else:
            self.command(f"zone{self._zone}.muting=off")

    def turn_on(self):
        """Turn the media player on."""
        self.command(f"zone{self._zone}.power=on")

    def select_source(self, source):
        """Set the input source."""
        if source in self._source_list:
            source = self._reverse_mapping[source]
        self.command(f"zone{self._zone}.selector={source}")
