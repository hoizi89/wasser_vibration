from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, DATA_CTRL, CONF_NAME


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    ctrl = hass.data[DOMAIN][entry.entry_id][DATA_CTRL]
    cfg = {**entry.data, **entry.options}
    name = cfg.get(CONF_NAME, entry.data.get(CONF_NAME, "Wasser Vibration"))

    entities = [
        # Haupt-Sensoren
        FlowSensor(ctrl, name),
        VolumeSensor(ctrl, name),
        TotalSensor(ctrl, name),  # NEU: Kumuliertes Gesamt-Volumen
        ResiduumSensor(ctrl, name),
        FlowStatusSensor(ctrl, name),
        # Auto-Learning Status
        AutoLearnSensor(ctrl, name),
        # Diagnose
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
            model="Vibration->Flow (Auto-Learning)",
        )

    async def async_added_to_hass(self):
        self.ctrl.register_entity_listener(self._on_ctrl_update)

    @callback
    def _on_ctrl_update(self):
        self.async_write_ha_state()


# --- Haupt-Sensoren -----------------------------------------------------------

class FlowSensor(BaseEntity):
    """Aktueller geschaetzter Durchfluss."""
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
    """Kumuliertes Volumen."""
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

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            try:
                last_val = float(last_state.state)
                self.ctrl._volume_l = last_val
                if self.ctrl._offset_l == 0.0 or self.ctrl._offset_l > self.ctrl._volume_l:
                    self.ctrl._offset_l = self.ctrl._volume_l
                setattr(self.ctrl, "_restored_volume", True)
            except (ValueError, TypeError):
                pass

        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        val = self.ctrl.volume_l
        return None if val is None else round(val, 2)

    @property
    def extra_state_attributes(self):
        return {
            "offset_l": round(self.ctrl.offset_l, 2),
            "volume_since_tick": round(self.ctrl.volume_since_tick, 2),
        }


class TotalSensor(BaseEntity, RestoreEntity):
    """Kumuliertes Gesamt-Volumen (persistent)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Total",
            unit="L",
            icon="mdi:water-sync",
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.WATER,
        )
        self._total_volume = 0.0

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            try:
                self._total_volume = float(last_state.state)
            except (ValueError, TypeError):
                pass
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        # Gesamt = persistierter Wert + aktuelle Session
        return round(self._total_volume + self.ctrl.volume_l, 2)

    @property
    def extra_state_attributes(self):
        return {
            "session_volume_l": round(self.ctrl.volume_l, 2),
            "learn_count": self.ctrl.learn_count,
        }


class ResiduumSensor(BaseEntity):
    """Residuum = Volume - Offset."""
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
            "volume_since_tick": round(self.ctrl.volume_since_tick, 2),
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
        return "Wasser" if self.ctrl.flow_active else "Kein Wasser"

    @property
    def icon(self) -> str:
        return "mdi:water" if self.ctrl.flow_active else "mdi:water-off"

    @property
    def extra_state_attributes(self):
        flow = self.ctrl.last_flow_l_min
        std = self.ctrl.last_std

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


# --- Auto-Learning Status -----------------------------------------------------

class AutoLearnSensor(BaseEntity):
    """Zeigt Auto-Learning Status mit Multi-Punkt Lernen."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Auto-Learn",
            icon="mdi:brain",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def native_value(self) -> str:
        count = self.ctrl.learn_count
        if count == 0:
            return "Lerne..."
        else:
            return f"{count}x gelernt"

    @property
    def icon(self) -> str:
        if self.ctrl.learn_count == 0:
            return "mdi:brain"
        elif self.ctrl.learn_count < 5:
            return "mdi:school"
        else:
            return "mdi:check-decagram"

    @property
    def extra_state_attributes(self):
        # Bucket-Infos detailliert aufbereiten
        bucket_details = {}
        all_buckets = self.ctrl.get_all_bucket_info()

        for info in all_buckets:
            label = info["label"]
            bucket_details[f"{label}_factor"] = round(info["factor"], 3)
            bucket_details[f"{label}_count"] = info["count"]
            bucket_details[f"{label}_zeit_min"] = round(info["time_s"] / 60.0, 1)
            bucket_details[f"{label}_schwelle"] = round(info["abs_threshold"], 4)

        attrs = {
            "learn_count": self.ctrl.learn_count,
            "current_bucket": self.ctrl.current_bucket_label,
            "threshold": self.ctrl.std_threshold,
            "is_calibrated": self.ctrl.is_calibrated,
            "info": "Buckets: schwach -> stark (relativ zur Schwelle)",
        }
        attrs.update(bucket_details)
        return attrs


# --- Diagnose-Sensoren --------------------------------------------------------

class DiagVibrationStd(BaseEntity):
    """Aktuelle Vibrations-Standardabweichung."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Vibration Std",
            unit="m/s²",
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
        raw = self.ctrl.last_std_raw or 0.0
        threshold = self.ctrl.std_threshold

        return {
            "raw_std": round(raw, 4),
            "threshold": threshold,
            "above_threshold": std > threshold,
            "outliers_rejected": self.ctrl.outliers_rejected,
        }


class DiagHydrusTotal(BaseEntity):
    """Aktueller Wert des Wasserzaehlers."""
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
            "volume_since_tick": round(self.ctrl.volume_since_tick, 2),
            "cal_factor": round(self.ctrl.cal_factor, 3),
            "learn_count": self.ctrl.learn_count,
        }

        if hydrus is not None:
            attrs["delta_vibration_vs_hydrus"] = round(volume - hydrus, 2)

        time_since = self.ctrl.time_since_hydrus_tick
        if time_since < 999999:
            attrs["minutes_since_tick"] = round(time_since / 60.0, 1)

        return attrs
