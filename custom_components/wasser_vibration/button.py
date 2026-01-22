from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN, DATA_CTRL, CONF_NAME


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    ctrl = hass.data[DOMAIN][entry.entry_id][DATA_CTRL]
    name = entry.data[CONF_NAME]
    async_add_entities([
        ResiduumResetButton(ctrl, name),
        CalibrateLowButton(ctrl, name),
        CalibrateHighButton(ctrl, name),
        CalibrateFinishButton(ctrl, name),
        CalibrateCancelButton(ctrl, name),
    ])


class BaseButton(ButtonEntity):
    _attr_should_poll = False

    def __init__(self, ctrl, name: str, key: str, icon: str | None = None,
                 entity_category: EntityCategory | None = None):
        self.ctrl = ctrl
        self._attr_name = f"{name} {key}"
        self._attr_unique_id = f"{DOMAIN}_{name}_{key}".lower().replace(" ", "_")
        self._attr_icon = icon
        self._attr_entity_category = entity_category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, name)},
            name=name,
            manufacturer="Custom",
            model="Vibration->Flow",
        )


class ResiduumResetButton(BaseButton):
    """Setzt das Residuum auf 0 zurueck."""
    def __init__(self, ctrl, name: str):
        super().__init__(ctrl, name, "Residuum Reset", icon="mdi:backup-restore")

    async def async_press(self) -> None:
        self.ctrl.reset_residuum()


class CalibrateLowButton(BaseButton):
    """Startet Kalibrierung fuer schwachen Wasserfluss (1L Eimer)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Kalibrierung Schwach Start",
            icon="mdi:water-outline",
            entity_category=EntityCategory.CONFIG
        )

    async def async_press(self) -> None:
        self.ctrl.start_calibration("low")


class CalibrateHighButton(BaseButton):
    """Startet Kalibrierung fuer starken Wasserfluss (1L Eimer)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Kalibrierung Stark Start",
            icon="mdi:water",
            entity_category=EntityCategory.CONFIG
        )

    async def async_press(self) -> None:
        self.ctrl.start_calibration("high")


class CalibrateFinishButton(BaseButton):
    """Beendet Kalibrierung und speichert (1 Liter wurde gefuellt)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "1 Liter Fertig",
            icon="mdi:check-circle",
            entity_category=EntityCategory.CONFIG
        )

    async def async_press(self) -> None:
        self.ctrl.finish_calibration()


class CalibrateCancelButton(BaseButton):
    """Bricht laufende Kalibrierung ab."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Kalibrierung Abbrechen",
            icon="mdi:cancel",
            entity_category=EntityCategory.CONFIG
        )

    async def async_press(self) -> None:
        self.ctrl.cancel_calibration()
