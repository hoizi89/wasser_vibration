from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, DATA_CTRL, CONF_NAME, LITER_MARKS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    ctrl = hass.data[DOMAIN][entry.entry_id][DATA_CTRL]
    cfg = {**entry.data, **entry.options}
    name = cfg.get(CONF_NAME, entry.data.get(CONF_NAME, "Wasser Vibration"))

    entities = [
        FlowSensor(ctrl, name),
        VolumeSensor(ctrl, name),
        ResiduumSensor(ctrl, name),
        LiterMarkSensor(ctrl, name),
        FlowStatusSensor(ctrl, name),
        DiagVibrationStd(ctrl, name),
        DiagHydrusTotal(ctrl, name),
    ]

    async_add_entities(entities)


class BaseEntity(SensorEntity):
    _attr_should_poll = False

    def __init__(self, ctrl, name: str, key: str, unit=None, icon=None,
                 state_class=None, device_class=None, entity_category=None):
        self.ctrl = ctrl
        self._attr_name = f"{name} {key}"
        uid_name = "".join(c if c.isalnum() else "_" for c in name).lower()
        self._attr_unique_id = f"{DOMAIN}_{uid_name}_{key.lower().replace(' ', '_')}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, name)},
            name=name,
            manufacturer="Custom",
            model="Vibration->Flow",
        )

    async def async_added_to_hass(self):
        self.ctrl.register_entity_listener(self._on_ctrl_update)

    @callback
    def _on_ctrl_update(self):
        self.async_write_ha_state()


# --- Haupt-Sensoren -----------------------------------------------------------

class FlowSensor(BaseEntity):
    """Aktueller geschaetzter Durchfluss basierend auf Vibration."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Flow",
            unit="L/min",
            icon="mdi:water-pump",
            state_class=SensorStateClass.MEASUREMENT,
        )

    @property
    def native_value(self) -> float | None:
        val = self.ctrl.last_flow_l_min
        return None if val is None else round(val, 2)


class VolumeSensor(BaseEntity, RestoreEntity):
    """Kumuliertes Volumen (ohne Offset)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Volume",
            unit="L",
            icon="mdi:water",
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.WATER,
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        # Letzten State laden
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            try:
                last_val = float(last_state.state)
                self.ctrl._volume_l = last_val
                if self.ctrl._offset_l == 0.0 or self.ctrl._offset_l > self.ctrl._volume_l:
                    self.ctrl._offset_l = self.ctrl._volume_l
            except (ValueError, TypeError):
                pass

        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        val = self.ctrl.volume_l
        return None if val is None else round(val, 2)


class ResiduumSensor(BaseEntity):
    """Residuum = Volume - Offset, geclampt [0..max_res_l]."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Residuum",
            unit="L",
            icon="mdi:gauge",
            state_class=SensorStateClass.MEASUREMENT,
        )

    @property
    def native_value(self) -> float | None:
        return round(self.ctrl.residuum_l, 2)

    @property
    def extra_state_attributes(self):
        return {
            "offset_l": round(self.ctrl.offset_l, 2),
            "max_residuum_l": round(self.ctrl.max_res_l, 2),
        }


class LiterMarkSensor(BaseEntity):
    """Zeigt die aktuelle 10L-Marke an (0, 10, 20, ...)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Liter Mark",
            unit="L",
            icon="mdi:ruler",
            state_class=SensorStateClass.MEASUREMENT,
        )

    @property
    def native_value(self) -> int:
        return self.ctrl.current_liter_mark

    @property
    def extra_state_attributes(self):
        residuum = self.ctrl.residuum_l
        current_mark = self.ctrl.current_liter_mark

        # Naechste Marke berechnen
        next_mark = current_mark + 10
        remaining = next_mark - residuum

        return {
            "current_residuum": round(residuum, 2),
            "next_mark": next_mark,
            "remaining_to_next": round(remaining, 2),
            "available_marks": LITER_MARKS,
        }


class FlowStatusSensor(BaseEntity):
    """Zeigt ob aktuell Wasser fliesst."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Flow Status",
            icon="mdi:water-check",
        )

    @property
    def native_value(self) -> str:
        return "Active" if self.ctrl.flow_active else "Inactive"

    @property
    def icon(self) -> str:
        return "mdi:water" if self.ctrl.flow_active else "mdi:water-off"

    @property
    def extra_state_attributes(self):
        std = self.ctrl.last_std
        flow = self.ctrl.last_flow_l_min

        # Status-Text basierend auf Flow
        if flow < 0.1:
            status = "Kein Wasser"
        elif flow < 3.0:
            status = "Schwach"
        elif flow < 8.0:
            status = "Mittel"
        elif flow < 15.0:
            status = "Stark"
        else:
            status = "Sehr stark"

        return {
            "flow_l_min": round(flow, 2) if flow else 0.0,
            "vibration_std": round(std, 4) if std else None,
            "status_text": status,
        }


# --- Diagnose-Sensoren --------------------------------------------------------

class DiagVibrationStd(BaseEntity):
    """Aktuelle Vibrations-Standardabweichung vom Sensor."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Vibration Std",
            unit="m/s2",
            icon="mdi:vibrate",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def native_value(self) -> float | None:
        val = self.ctrl.last_std
        return None if val is None else round(val, 4)

    @property
    def extra_state_attributes(self):
        std = self.ctrl.last_std or 0.0
        threshold = self.ctrl.std_threshold
        std_max = self.ctrl.std_max

        return {
            "threshold": threshold,
            "std_max": std_max,
            "above_threshold": std > threshold,
            "percent_to_max": round((std - threshold) / (std_max - threshold) * 100, 1) if std > threshold and std_max > threshold else 0.0,
        }


class DiagHydrusTotal(BaseEntity):
    """Aktueller Wert des Wasserzaehlers (wenn konfiguriert)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Hydrus Total",
            unit="L",
            icon="mdi:counter",
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.WATER,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def native_value(self) -> float | None:
        val = self.ctrl.hydrus_total
        return None if val is None else round(val, 2)

    @property
    def extra_state_attributes(self):
        hydrus = self.ctrl.hydrus_total
        volume = self.ctrl.volume_l

        attrs = {
            "vibration_volume_l": round(volume, 2),
            "residuum_l": round(self.ctrl.residuum_l, 2),
        }

        if hydrus is not None:
            attrs["delta_vibration_vs_hydrus"] = round(volume - hydrus, 2)

        return attrs
