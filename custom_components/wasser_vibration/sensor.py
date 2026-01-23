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
        TotalSensor(ctrl, name),
        ResiduumSensor(ctrl, name),
        FlowStatusSensor(ctrl, name),
        # Diagnose
        AutoLearnSensor(ctrl, name),
        BucketInfoSensor(ctrl, name),  # NEU: Zeigt aktuellen Bucket + Faktoren
        DiagVibrationStd(ctrl, name),
        DiagHydrusTotal(ctrl, name),
        DiagVolumeSensor(ctrl, name),  # Volume jetzt in Diagnose
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


class TotalSensor(BaseEntity):
    """Kumuliertes Gesamt-Volumen = Hydrus + Residuum (fuer Energy Dashboard)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Total",
            unit="L",
            icon="mdi:water",
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.WATER,
        )

    @property
    def native_value(self) -> float | None:
        # Total = Hydrus + geschaetztes Residuum
        hydrus = self.ctrl.hydrus_total
        if hydrus is None:
            return None
        residuum = self.ctrl.residuum_l
        return round(hydrus + residuum, 2)

    @property
    def extra_state_attributes(self):
        return {
            "hydrus_l": round(self.ctrl.hydrus_total, 2) if self.ctrl.hydrus_total else 0,
            "residuum_l": round(self.ctrl.residuum_l, 2),
            "learn_count": self.ctrl.learn_count,
        }


class ResiduumSensor(BaseEntity):
    """Geschaetztes Volumen seit letztem 10L-Tick (0-10L)."""
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
            "volume_since_tick": round(self.ctrl.volume_since_tick, 2),
            "max_residuum_l": round(self.ctrl.max_res_l, 2),
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


# --- Diagnose-Sensoren --------------------------------------------------------

class AutoLearnSensor(BaseEntity):
    """Zeigt Auto-Learning Status."""
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
            return "Warte auf 10L-Tick..."
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
        attrs = {
            "learn_count": self.ctrl.learn_count,
            "threshold": round(self.ctrl.std_threshold, 4),
            "is_calibrated": self.ctrl.is_calibrated,
            "skip_next_learn": getattr(self.ctrl, "_skip_next_learn", False),
            "volume_since_tick": round(self.ctrl.volume_since_tick, 2),
            "info": "Lernt bei jedem 10L Hydrus-Tick automatisch",
        }
        return attrs


class BucketInfoSensor(BaseEntity):
    """Zeigt aktuellen Lern-Bucket und alle Faktoren."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Bucket Info",
            icon="mdi:format-list-bulleted",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def native_value(self) -> str:
        bucket = self.ctrl.current_bucket_label
        if bucket == "Kein Wasser":
            return "Kein Wasser"
        return f"Aktuell: {bucket}"

    @property
    def icon(self) -> str:
        bucket = self.ctrl.current_bucket_label
        if bucket == "Kein Wasser":
            return "mdi:water-off"
        elif "schwach" in bucket:
            return "mdi:speedometer-slow"
        elif "stark" in bucket:
            return "mdi:speedometer"
        else:
            return "mdi:speedometer-medium"

    @property
    def extra_state_attributes(self):
        from . import BUCKET_OFFSETS

        # Alle Bucket-Infos aufbereiten
        all_buckets = self.ctrl.get_all_bucket_info()
        time_since_tick = self.ctrl.time_per_bucket_since_tick
        threshold = self.ctrl.std_threshold

        attrs = {
            "schwelle": round(threshold, 4),
            "aktuell": self.ctrl.current_bucket_label,
        }

        # Gesamt-Zeit seit Tick
        total_since_tick = sum(time_since_tick.values())
        attrs["seit_tick_s"] = round(total_since_tick, 1)

        # Bereiche mit Von-Bis Werten anzeigen
        attrs["_bereiche"] = "──────────────────"
        for i, info in enumerate(all_buckets):
            label = info["label"]
            bucket_key = f"bucket_{info['index']}"
            current_s = time_since_tick.get(bucket_key, 0.0)

            # Bereich berechnen (von - bis)
            von = threshold + BUCKET_OFFSETS[i]
            if i < len(BUCKET_OFFSETS) - 1:
                bis = threshold + BUCKET_OFFSETS[i + 1]
                bereich = f"{von:.3f}-{bis:.3f}"
            else:
                bereich = f"{von:.3f}+"

            # Kompakte Info: Bereich | Faktor | Lern-Zyklen | Zeit
            attrs[f"{i}_{label}"] = f"{bereich} | F={info['factor']:.2f} | {info['count']}x | {info['time_s']:.0f}s"

        attrs["_lernstatus"] = "──────────────────"
        for i, info in enumerate(all_buckets):
            bucket_key = f"bucket_{info['index']}"
            current_s = time_since_tick.get(bucket_key, 0.0)
            if current_s > 0:
                attrs[f"jetzt_{info['label']}"] = f"{current_s:.0f}s"

        attrs["legende"] = "Bereich m/s² | Faktor | Lern-Zyklen | Gesamt-Zeit"
        return attrs


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

        attrs = {
            "raw_std": round(raw, 4),
            "schwelle": round(threshold, 4),
            "ueber_schwelle": std > threshold,
            "delta_zu_schwelle": round(std - threshold, 4),
            "outliers_rejected": self.ctrl.outliers_rejected,
        }

        # Baseline-Debug-Werte (Ruhezustand)
        if self.ctrl.baseline_min is not None:
            attrs["_baseline"] = "──────────────────"
            attrs["baseline_min"] = round(self.ctrl.baseline_min, 4)
            attrs["baseline_max"] = round(self.ctrl.baseline_max, 4)
            attrs["baseline_avg"] = round(self.ctrl.baseline_avg, 4)
            attrs["empfohlene_schwelle"] = self.ctrl.recommended_threshold
            # Puffer zur aktuellen Schwelle
            puffer = threshold - self.ctrl.baseline_max
            attrs["puffer_zu_max"] = round(puffer, 4)

        return attrs


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
            "geschaetzt_l": round(self.ctrl.volume_since_tick, 2),
            "learn_count": self.ctrl.learn_count,
        }

        if hydrus is not None:
            attrs["differenz_l"] = round(self.ctrl.volume_since_tick - (hydrus % 10), 2)

        time_since = self.ctrl.time_since_hydrus_tick
        if time_since < 999999:
            attrs["minuten_seit_tick"] = round(time_since / 60.0, 1)

        return attrs


class DiagVolumeSensor(BaseEntity, RestoreEntity):
    """Internes Volumen (wird bei Hydrus-Sync angepasst)."""
    def __init__(self, ctrl, name: str):
        super().__init__(
            ctrl, name, "Volume",
            unit="L",
            icon="mdi:water-sync",
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.WATER,
            entity_category=EntityCategory.DIAGNOSTIC,
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

                # NEU: volume_since_tick aus extra_state_attributes wiederherstellen
                if last_state.attributes:
                    vst = last_state.attributes.get("volume_since_tick")
                    if vst is not None:
                        try:
                            restored_vst = float(vst)
                            # Plausibilitaetspruefung
                            if 0 <= restored_vst <= 15.0:
                                self.ctrl._volume_since_tick = restored_vst
                                self.ctrl._restored_volume_since_tick = True
                        except (ValueError, TypeError):
                            pass
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
            "skip_next_learn": getattr(self.ctrl, "_skip_next_learn", False),
            "info": "Interner Wert, wird bei Hydrus-Tick synchronisiert",
        }
