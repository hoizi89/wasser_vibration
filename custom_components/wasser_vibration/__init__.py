from __future__ import annotations

import logging
import time
import statistics
from collections import deque

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN, DATA_CTRL, CONF_VIBRATION_ENTITY, CONF_TOTAL_ENTITY, CONF_TOTAL_UNIT,
    CONF_STD_THRESHOLD, CONF_MAX_RES_L, CONF_CAL_FACTOR,
    DEFAULT_STD_THRESHOLD, DEFAULT_MAX_RES_L, DEFAULT_TOTAL_UNIT, DEFAULT_CAL_FACTOR,
    CAL_ADAPT_RATE, CAL_MIN_FACTOR, CAL_MAX_FACTOR,
    PLATFORMS, LITER_MARKS,
)

_LOGGER = logging.getLogger(__name__)

# Peak-Filter Konfiguration
STD_HISTORY_SIZE = 10
OUTLIER_THRESHOLD = 3.0

# Multi-Punkt Learning: Std-Bereiche mit eigenen Faktoren
# Format: {std_bucket: (factor, learn_count)}
STD_BUCKETS = [0.050, 0.055, 0.060, 0.070, 0.100]  # Grenzen der Buckets
DEFAULT_BUCKET_FACTOR = 1.0


def _m3_to_l(v: float) -> float:
    return v * 1000.0


class WasserVibrationController:
    """Controller mit vollautomatischem Lernen bei 10L-Ticks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.vibration_entity = entry.data[CONF_VIBRATION_ENTITY]
        self.total_entity = entry.data.get(CONF_TOTAL_ENTITY)
        self.total_unit = entry.data.get(CONF_TOTAL_UNIT, DEFAULT_TOTAL_UNIT).lower()

        # Basis-Parameter
        self.std_threshold = entry.options.get(CONF_STD_THRESHOLD, DEFAULT_STD_THRESHOLD)
        self.max_res_l = entry.options.get(CONF_MAX_RES_L, DEFAULT_MAX_RES_L)

        # Multi-Punkt Learning: Faktoren pro Std-Bereich
        # Gespeichert als: {"bucket_0.050": 1.0, "bucket_0.055": 1.2, ...}
        self._bucket_factors = {}
        self._bucket_counts = {}
        for bucket in STD_BUCKETS:
            key = f"bucket_{bucket:.3f}"
            self._bucket_factors[key] = entry.options.get(key, DEFAULT_BUCKET_FACTOR)
            self._bucket_counts[key] = entry.options.get(f"{key}_count", 0)

        # Fallback: Globaler Faktor (für Kompatibilität)
        self.cal_factor = entry.options.get(CONF_CAL_FACTOR, DEFAULT_CAL_FACTOR)

        # Interne Zustaende
        self._last_ts = None
        self._last_std_raw = None
        self._last_std = None
        self._last_flow = 0.0

        self._volume_l = 0.0
        self._offset_l = 0.0
        self._volume_since_tick = 0.0
        self._last_hydrus_total = None
        self._last_hydrus_change_time = None

        # Peak-Filter
        self._std_history = deque(maxlen=STD_HISTORY_SIZE)
        self._outliers_rejected = 0

        # Auto-Learning: Std-Werte seit letztem Tick sammeln
        self._std_samples_since_tick = []
        self._learn_count = 0  # Anzahl erfolgreicher Lern-Zyklen

        # Flow-Status
        self._flow_active = False
        self._flow_start_time = None
        self._last_flow_time = None
        self._current_liter_mark = 0

        # Rate-Limiting: Nur alle 2 Sekunden Entities updaten (statt alle 500ms)
        self._last_notify_time = 0.0
        self._notify_interval = 2.0  # Sekunden

        self._remove_vibration_listener = None
        self._remove_total_listener = None

    def _get_bucket_key(self, std: float) -> str:
        """Findet den passenden Bucket für einen Std-Wert."""
        for bucket in STD_BUCKETS:
            if std <= bucket:
                return f"bucket_{bucket:.3f}"
        return f"bucket_{STD_BUCKETS[-1]:.3f}"

    def _get_bucket_factor(self, std: float) -> float:
        """Holt den gelernten Faktor für einen Std-Bereich."""
        key = self._get_bucket_key(std)
        return self._bucket_factors.get(key, DEFAULT_BUCKET_FACTOR)

    def _filter_std(self, raw_std: float) -> float | None:
        """Filtert Ausreisser und glaettet mit Moving Average."""
        self._std_history.append(raw_std)

        if len(self._std_history) < 5:
            return raw_std

        median = statistics.median(self._std_history)
        deviations = [abs(x - median) for x in self._std_history]
        mad = statistics.median(deviations) or 0.0001

        z_score = abs(raw_std - median) / (1.4826 * mad)

        if z_score > OUTLIER_THRESHOLD:
            self._outliers_rejected += 1
            return None

        weights = list(range(1, len(self._std_history) + 1))
        weighted_sum = sum(v * w for v, w in zip(self._std_history, weights))
        return weighted_sum / sum(weights)

    def _std_to_flow(self, std: float) -> float:
        """
        Multi-Punkt Lernen: Verwendet bucket-spezifische Faktoren.

        Formel: flow = (std - threshold) * base_rate * bucket_factor

        Jeder Std-Bereich (Bucket) hat seinen eigenen gelernten Faktor,
        sodass schwacher und starker Wasserfluss unterschiedlich behandelt werden.
        """
        if std <= self.std_threshold:
            return 0.0

        delta_std = std - self.std_threshold
        base_rate = 4000.0  # Basis: 8 L/min bei std=0.050

        # Bucket-spezifischen Faktor verwenden
        bucket_factor = self._get_bucket_factor(std)

        flow = delta_std * base_rate * bucket_factor

        return max(0.0, min(flow, 50.0))

    def _get_liter_mark(self, residuum: float) -> int:
        for i in range(len(LITER_MARKS) - 1, -1, -1):
            if residuum >= LITER_MARKS[i]:
                return LITER_MARKS[i]
        return 0

    async def _persist_options(self, new_opts: dict):
        options = dict(self.entry.options)
        options.update(new_opts)
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    # --- Properties ---

    @property
    def residuum_l(self) -> float:
        raw = self._volume_l - self._offset_l
        return max(0.0, min(raw, self.max_res_l))

    @property
    def volume_l(self) -> float:
        return self._volume_l

    @property
    def offset_l(self) -> float:
        return self._offset_l

    @property
    def last_flow_l_min(self) -> float:
        return self._last_flow

    @property
    def last_std(self) -> float | None:
        return self._last_std

    @property
    def last_std_raw(self) -> float | None:
        return self._last_std_raw

    @property
    def flow_active(self) -> bool:
        return self._flow_active

    @property
    def current_liter_mark(self) -> int:
        return self._current_liter_mark

    @property
    def hydrus_total(self) -> float | None:
        return self._last_hydrus_total

    @property
    def volume_since_tick(self) -> float:
        return self._volume_since_tick

    @property
    def outliers_rejected(self) -> int:
        return self._outliers_rejected

    @property
    def learn_count(self) -> int:
        """Anzahl erfolgreicher Auto-Lern Zyklen."""
        return self._learn_count

    @property
    def flow_duration_s(self) -> float:
        if self._flow_start_time is None:
            return 0.0
        return time.time() - self._flow_start_time

    @property
    def idle_time_s(self) -> float:
        if self._last_flow_time is None:
            return 999999.0
        return time.time() - self._last_flow_time

    @property
    def time_since_hydrus_tick(self) -> float:
        if self._last_hydrus_change_time is None:
            return 999999.0
        return time.time() - self._last_hydrus_change_time

    @property
    def is_calibrated(self) -> bool:
        """True wenn mindestens ein Auto-Lern Zyklus durchlaufen wurde."""
        return self._learn_count > 0

    @property
    def bucket_factors(self) -> dict:
        """Gibt alle Bucket-Faktoren zurueck."""
        return self._bucket_factors.copy()

    @property
    def bucket_counts(self) -> dict:
        """Gibt Lern-Zaehler pro Bucket zurueck."""
        return self._bucket_counts.copy()

    @property
    def current_bucket(self) -> str:
        """Aktueller Bucket basierend auf letztem Std."""
        if self._last_std is None:
            return "none"
        return self._get_bucket_key(self._last_std)

    def register_entity_listener(self, cb) -> None:
        self.__dict__.setdefault("_entity_listeners", []).append(cb)

    def reset_residuum(self) -> None:
        """Manueller Reset."""
        self._offset_l = self._volume_l
        self._volume_since_tick = 0.0
        self._std_samples_since_tick = []
        _LOGGER.info("Residuum reset: Offset = %.3f L", self._offset_l)
        self._notify_entities(force=True)  # Sofort updaten bei Reset

    def _integrate(self, flow_l_min: float, dt_s: float):
        if dt_s <= 0 or flow_l_min <= 0:
            return
        delta_volume = flow_l_min * (dt_s / 60.0)
        self._volume_l += delta_volume
        self._volume_since_tick += delta_volume
        self._current_liter_mark = self._get_liter_mark(self.residuum_l)

    def _convert_total_to_l(self, val: float) -> float:
        return _m3_to_l(val) if self.total_unit == "m3" else float(val)

    @callback
    def _on_total_entity_changed(self, event: Event) -> None:
        """Hydrus 10L-Tick: Auto-Learning!"""
        if not self.total_entity:
            return
        if event.data.get("entity_id") != self.total_entity:
            return
        new_state = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        try:
            now_total_l = self._convert_total_to_l(float(new_state.state))
        except (ValueError, TypeError):
            return

        # Erste Initialisierung
        if self._last_hydrus_total is None:
            if getattr(self, "_restored_volume", False):
                self._last_hydrus_total = now_total_l
                if self._offset_l > now_total_l:
                    self._offset_l = now_total_l
            else:
                rounded_volume = (now_total_l // 10) * 10
                self._volume_l = rounded_volume
                self._offset_l = rounded_volume
                self._last_hydrus_total = now_total_l
                self._volume_since_tick = 0.0
            self._notify_entities(force=True)  # Sofort bei Initialisierung
            return

        # 10L-Tick Erkennung -> MULTI-PUNKT AUTO-LEARNING!
        delta_l = now_total_l - self._last_hydrus_total
        if 9.5 <= delta_l <= 10.5:
            estimated = self._volume_since_tick

            if estimated > 1.0 and len(self._std_samples_since_tick) > 0:
                # Durchschnittlichen Std-Wert waehrend des Flows berechnen
                avg_std = sum(self._std_samples_since_tick) / len(self._std_samples_since_tick)
                bucket_key = self._get_bucket_key(avg_std)

                # Korrektur berechnen: Soll 10L sein, haben aber X geschaetzt
                correction = 10.0 / estimated

                # Aktuellen Bucket-Faktor holen und anpassen
                old_factor = self._bucket_factors.get(bucket_key, DEFAULT_BUCKET_FACTOR)
                target_factor = old_factor * correction
                new_factor = old_factor + CAL_ADAPT_RATE * (target_factor - old_factor)
                new_factor = max(CAL_MIN_FACTOR, min(CAL_MAX_FACTOR, new_factor))

                # Speichern
                self._bucket_factors[bucket_key] = new_factor
                self._bucket_counts[bucket_key] = self._bucket_counts.get(bucket_key, 0) + 1
                self._learn_count += 1

                _LOGGER.info(
                    "AUTO-LEARN #%d [%s]: Avg-Std=%.4f, Geschaetzt=%.1fL, Faktor: %.3f -> %.3f",
                    self._learn_count, bucket_key, avg_std, estimated, old_factor, new_factor
                )

                # Persistieren
                self.hass.async_create_task(
                    self._persist_options({
                        bucket_key: new_factor,
                        f"{bucket_key}_count": self._bucket_counts[bucket_key],
                    })
                )

            # Reset fuer naechsten Tick
            self._offset_l = now_total_l
            self._volume_l = now_total_l
            self._volume_since_tick = 0.0
            self._std_samples_since_tick = []
            self._last_hydrus_change_time = time.time()
            self._notify_entities(force=True)  # Sofort nach Auto-Learn

        elif 10.5 < delta_l <= 100.0:
            _LOGGER.info("Hydrus Sprung %.1f L, sync", delta_l)
            self._offset_l = now_total_l
            self._volume_l = now_total_l
            self._volume_since_tick = 0.0
            self._std_samples_since_tick = []

        self._last_hydrus_total = now_total_l
        self._notify_entities(force=True)  # Hydrus-Änderung immer sofort anzeigen

    @callback
    def _on_vibration_entity_changed(self, event: Event) -> None:
        if event.data.get("entity_id") != self.vibration_entity:
            return
        new_state = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        try:
            raw_std = float(new_state.state)
        except (ValueError, TypeError):
            return

        now_ts = time.time()
        self._last_std_raw = raw_std

        filtered_std = self._filter_std(raw_std)
        if filtered_std is None:
            return

        self._last_std = filtered_std

        # Std-Werte sammeln fuer Auto-Learning
        if filtered_std > self.std_threshold:
            self._std_samples_since_tick.append(filtered_std)

        # Flow berechnen
        flow = self._std_to_flow(filtered_std)
        self._last_flow = flow

        # Flow-Status
        was_active = self._flow_active
        self._flow_active = flow > 0.1

        if self._flow_active and not was_active:
            self._flow_start_time = now_ts
        elif not self._flow_active and was_active:
            self._flow_start_time = None

        if self._flow_active:
            self._last_flow_time = now_ts

        # Volumen integrieren
        if self._last_ts is not None:
            dt_s = now_ts - self._last_ts
            if 0 < dt_s < 60:
                self._integrate(flow, dt_s)

        self._last_ts = now_ts
        self._current_liter_mark = self._get_liter_mark(self.residuum_l)
        self._notify_entities()

    def _notify_entities(self, force: bool = False) -> None:
        """Benachrichtigt Entities - mit Rate-Limiting um HA nicht zu ueberlasten."""
        now = time.time()

        # Rate-Limiting: Nur alle 2 Sekunden updaten (ausser bei force)
        if not force and (now - self._last_notify_time) < self._notify_interval:
            return

        self._last_notify_time = now
        self.hass.data[DOMAIN][self.entry.entry_id][DATA_CTRL] = self

        for cb in self.__dict__.get("_entity_listeners", []):
            try:
                cb()
            except Exception as e:
                _LOGGER.exception("Entity-Listener Fehler: %s", e)

    async def async_start(self):
        @callback
        def vibration_listener(event: Event):
            self._on_vibration_entity_changed(event)

        @callback
        def total_listener(event: Event):
            self._on_total_entity_changed(event)

        self._remove_vibration_listener = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, vibration_listener
        )
        if self.total_entity:
            self._remove_total_listener = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, total_listener
            )

    async def async_stop(self):
        if self._remove_vibration_listener:
            self._remove_vibration_listener()
        if self._remove_total_listener:
            self._remove_total_listener()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    ctrl = WasserVibrationController(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_CTRL: ctrl}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await ctrl.async_start()

    entry.add_update_listener(_async_update_listener)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        ctrl = hass.data[DOMAIN][entry.entry_id][DATA_CTRL]
        await ctrl.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)
