from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, DATA_CTRL, CONF_NAME


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    ctrl = hass.data[DOMAIN][entry.entry_id][DATA_CTRL]
    name = entry.data[CONF_NAME]
    async_add_entities([ResiduumResetButton(ctrl, name)])


class BaseButton(ButtonEntity):
    _attr_should_poll = False

    def __init__(self, ctrl, name: str, key: str, icon: str | None = None):
        self.ctrl = ctrl
        self._attr_name = f"{name} {key}"
        self._attr_unique_id = f"{DOMAIN}_{name}_{key}".lower().replace(" ", "_")
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, name)},
            name=name,
            manufacturer="Custom",
            model="Vibration->Flow",
        )


class ResiduumResetButton(BaseButton):
    def __init__(self, ctrl, name: str):
        super().__init__(ctrl, name, "Residuum Reset", icon="mdi:backup-restore")

    async def async_press(self) -> None:
        self.ctrl.reset_residuum()
