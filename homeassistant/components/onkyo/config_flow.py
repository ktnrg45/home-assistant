"""Config flow for Onkyo."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback

from .const import (
    CONF_MAX_VOLUME,
    CONF_RECEIVER_MAX_VOLUME,
    CONF_SOURCES,
    DEFAULT_NAME,
    DEFAULT_RECEIVER_MAX_VOLUME,
    DEFAULT_SOURCES,
    DOMAIN,
    SUPPORTED_MAX_VOLUME,
)
from .media_player import get_receiver_info

_LOGGER = logging.getLogger(__name__)


# async def _async_has_devices(hass) -> bool:
#     """Return if there are devices that can be discovered."""
#     devices = await hass.async_add_executor_job(eisp.eISCP.discover)
#     _LOGGER.error(devices)
#     return len(devices) > 0


# config_entry_flow.register_discovery_flow(
#     DOMAIN, "Media Player", _async_has_devices, config_entries.CONN_CLASS_LOCAL_POLL
# )


@config_entries.HANDLERS.register(DOMAIN)
class OnkyoFlowHandler(config_entries.ConfigFlow):
    """Handle a Onkyo config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OnkyoOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a user config flow."""
        errors = {}
        config = {}

        if user_input:
            ip_address = user_input[CONF_HOST]
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if entries:
                for entry in entries:
                    if entry.data[CONF_HOST] == ip_address:
                        return self.async_abort(reason="single_instance_allowed")

            info = await self.hass.async_add_executor_job(get_receiver_info, ip_address)
            if not info:
                return self.async_abort(reason="no_devices_found")
            config[CONF_HOST] = ip_address
            config[CONF_NAME] = info.get("name") or DEFAULT_NAME
            config[CONF_SOURCES] = info.get("sources") or DEFAULT_SOURCES

            return self.async_create_entry(title=info["model"], data=config)

        config_schema = vol.Schema({vol.Required(CONF_HOST): str})

        return self.async_show_form(
            step_id="user", data_schema=config_schema, errors=errors
        )


class OnkyoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Onkyo options."""

    def __init__(self, config_entry):
        """Initialize Onkyo options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Start Onkyo Options Flow."""
        errors = {}

        if user_input:
            self.options.update(user_input)
            return await self._update_options()

        if not self.options:
            self.options = {
                CONF_MAX_VOLUME: SUPPORTED_MAX_VOLUME,
                CONF_RECEIVER_MAX_VOLUME: DEFAULT_RECEIVER_MAX_VOLUME,
            }
        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAX_VOLUME, default=self.options[CONF_MAX_VOLUME]
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Required(
                    CONF_RECEIVER_MAX_VOLUME,
                    default=self.options[CONF_RECEIVER_MAX_VOLUME],
                ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors,
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)
