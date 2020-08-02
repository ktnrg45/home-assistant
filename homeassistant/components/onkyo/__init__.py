"""The onkyo component."""
from .const import ONKYO_DATA


async def async_setup(hass, config):
    """Set up the Onkyo Component."""
    hass.data[ONKYO_DATA] = {}
    return True


async def async_setup_entry(hass, config_entry):
    """Set up Onkyo from a config entry."""
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, "media_player")
    )
    return True


async def async_unload_entry(hass, entry):
    """Unload an Onkyo config entry."""
    success = await hass.config_entries.async_forward_entry_unload(
        entry, "media_player"
    )
    if success:
        unsub = hass.data[ONKYO_DATA].get(entry.entry_id)
        if unsub is not None:
            unsub()
    return success
