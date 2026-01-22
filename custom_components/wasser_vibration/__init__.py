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
    CONF_STD_THRESHOLD, CONF_MAX_RES_L,
    CONF_CAL_LOW_STD, CONF_CAL_LOW_FLOW, CONF_CAL_HIGH_STD, CONF_CAL_HIGH_FLOW, CONF_CAL_FACTOR,
    DEFAULT_STD_THRESHOLD, DEFAULT_MAX_RES_L, DEFAULT_TOTAL_UNIT,
    DEFAULT_CAL_LOW_STD, DEFAULT_CAL_LOW_FLOW, DEFAULT_CAL_HIGH_STD, DEFAULT_CAL_HIGH_FLOW, DEFAULT_CAL_FACTOR,
    CAL_ADAPT_RATE, CAL_MIN_FACTOR, CAL_MAX_FACTOR,
    PLATFORMS, LITER_MARKS,
)

_LOGGER = logging.getLogger(__name__)

# Peak-Filter Konfiguration
STD_HISTORY_SIZE = 10  # 10 Samples = 5 Sekunden bei 500ms Update
OUTLIER_THRESHOLD = 3.0  # MAD-basierter Ausreisser-Schwellwert


def _m3_to_l(v: float) -> float:
    return v * 1000.0


class WasserVibrationController:
    """Controller mit 2-Punkt Kalibrierung und Auto-Lernen bei 10L-Ticks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.vibration_entity = entry.data[CONF_VIBRATION_ENTITY]
        self.total_entity = entry.data.get(CONF_TOTAL_ENTITY)
        self.total_unit = entry.data.get(CONF_TOTAL_UNIT, DEFAULT_TOTAL_UNIT).lower()

        # Basis-Parameter
        self.std_threshold = entry.options.get(CONF_STD_THRESHOLD, DEFAULT_STD_THRESHOLD)
        self.max_res_l = entry.options.get(CONF_MAX_RES_L, DEFAULT_MAX_RES_L)

        # Kalibrierungs-Parameter (2-Punkt + Faktor)
        self.cal_low_std = entry.options.get(CONF_CAL_LOW_STD, DEFAULT_CAL_LOW_STD)
        self.cal_low_flow = entry.options.get(CONF_CAL_LOW_FLOW, DEFAULT_CAL_LOW_FLOW)
        self.cal_high_std = entry.options.get(CONF_CAL_HIGH_STD, DEFAULT_CAL_HIGH_STD)
        self.cal_high_flow = entry.options.get(CONF_CAL_HIGH_FLOW, DEFAULT_CAL_HIGH_FLOW)
        self.cal_factor = entry.options.get(CONF_CAL_FACTOR, DEFAULT_CAL_FACTOR)

        # Interne Zustaende
        self._last_ts = None
        self._last_std_raw = None  # Roher Wert vom Sensor
        self._last_std = None  # Gefilterter Wert
        self._last_flow = 0.0

        self._volume_l = 0.0
        self._offset_l = 0.0
        self._volume_since_tick = 0.0  # Volume seit letztem Hydrus-Tick
        self._last_hydrus_total = None
        self._last_hydrus_change_time = None

        # Peak-Filter: Moving Average + Ausreisser-Erkennung
        self._std_history = deque(maxlen=STD_HISTORY_SIZE)
        self._outliers_rejected = 0

        # Flow-Status
        self._flow_active = False
        self._flow_start_time = None
        self._last_flow_time = None
        self._current_liter_mark = 0

        # Kalibrierungs-Modus
        self._cal_mode = None  # None, "low", "high"
        self._cal_start_time = None
        self._cal_std_samples = []

        self._remove_vibration_listener = None
        self._remove_total_listener = None

    def _filter_std(self, raw_std: float) -> float | None:
        """
        Filtert Ausreisser mit MAD (Median Absolute Deviation) und
        glaettet mit Moving Average.

        Returns None wenn Ausreisser erkannt wurde.
        """
        self._std_history.append(raw_std)

        # Mindestens 5 Samples fuer zuverlaessige Filterung
        if len(self._std_history) < 5:
            return raw_std

        # MAD-basierte Ausreisser-Erkennung
        median = statistics.median(self._std_history)
        deviations = [abs(x - median) for x in self._std_history]
        mad = statistics.median(deviations) or 0.0001

        # Z-Score berechnen
        z_score = abs(raw_std - median) / (1.4826 * mad)

        if z_score > OUTLIER_THRESHOLD:
            self._outliers_rejected += 1
            _LOGGER.debug("Ausreisser: %.4f (z=%.1f), verworfen", raw_std, z_score)
            return None  # Ausreisser verwerfen

        # Glaettung: Gewichteter Durchschnitt (neuere Werte staerker)
        weights = list(range(1, len(self._std_history) + 1))
        weighted_sum = sum(v * w for v, w in zip(self._std_history, weights))
        smoothed = weighted_sum / sum(weights)

        return smoothed

    def _std_to_flow(self, std: float) -> float:
        """Konvertiert Std zu Flow mit 2-Punkt linearer Interpolation + Faktor."""
        if std < self.std_threshold:
            return 0.0

        # Sicherheit: low und high muessen unterschiedlich sein
        if self.cal_high_std <= self.cal_low_std:
            return 0.0

        # Lineare Interpolation zwischen den 2 Kalibrierpunkten
        if std <= self.cal_low_std:
            # Unter dem niedrigen Punkt: extrapoliere von threshold
            if self.cal_low_std <= self.std_threshold:
                flow = self.cal_low_flow
            else:
                flow = self.cal_low_flow * (std - self.std_threshold) / (self.cal_low_std - self.std_threshold)
        elif std >= self.cal_high_std:
            # Ueber dem hohen Punkt: extrapoliere
            slope = (self.cal_high_flow - self.cal_low_flow) / (self.cal_high_std - self.cal_low_std)
            flow = self.cal_high_flow + slope * (std - self.cal_high_std)
        else:
            # Zwischen den Punkten: interpoliere
            ratio = (std - self.cal_low_std) / (self.cal_high_std - self.cal_low_std)
            flow = self.cal_low_flow + ratio * (self.cal_high_flow - self.cal_low_flow)

        # Korrektur-Faktor anwenden (wird durch 10L-Ticks gelernt)
        flow *= self.cal_factor

        # Begrenzen auf sinnvolle Werte
        return max(0.0, min(flow, 50.0))

    def _get_liter_mark(self, residuum: float) -> int:
        """Gibt die aktuelle 10L-Marke zurueck."""
        for i in range(len(LITER_MARKS) - 1, -1, -1):
            if residuum >= LITER_MARKS[i]:
                return LITER_MARKS[i]
        return 0

    async def _persist_options(self, new_opts: dict):
        """Optionen im ConfigEntry speichern."""
        options = dict(self.entry.options)
        options.update(new_opts)
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    # --- Kalibrierungs-Methoden ---

    def start_calibration(self, mode: str):
        """Startet Kalibrierung fuer 'low' oder 'high'."""
        if mode not in ("low", "high"):
            return

        self._cal_mode = mode
        self._cal_start_time = time.time()
        self._cal_std_samples = []
        _LOGGER.info("Kalibrierung gestartet: %s", mode)
        self._notify_entities()

    def finish_calibration(self):
        """Beendet Kalibrierung und berechnet Flow aus 1 Liter / Zeit."""
        if self._cal_mode is None or self._cal_start_time is None:
            _LOGGER.warning("Keine Kalibrierung aktiv")
            return

        elapsed_s = time.time() - self._cal_start_time
        if elapsed_s < 2.0:
            _LOGGER.warning("Kalibrierung zu kurz: %.1f s", elapsed_s)
            self._cal_mode = None
            self._notify_entities()
            return

        # Berechne durchschnittlichen Std-Wert waehrend der Kalibrierung
        if len(self._cal_std_samples) < 3:
            _LOGGER.warning("Zu wenige Samples: %d", len(self._cal_std_samples))
            self._cal_mode = None
            self._notify_entities()
            return

        avg_std = sum(self._cal_std_samples) / len(self._cal_std_samples)

        # 1 Liter / Zeit = L/min
        elapsed_min = elapsed_s / 60.0
        flow_l_min = 1.0 / elapsed_min

        _LOGGER.info(
            "Kalibrierung %s fertig: Std=%.4f, Zeit=%.1fs, Flow=%.2f L/min",
            self._cal_mode, avg_std, elapsed_s, flow_l_min
        )

        # Speichern
        if self._cal_mode == "low":
            self.cal_low_std = avg_std
            self.cal_low_flow = flow_l_min
            self.hass.async_create_task(
                self._persist_options({
                    CONF_CAL_LOW_STD: avg_std,
                    CONF_CAL_LOW_FLOW: flow_l_min,
                })
            )
        elif self._cal_mode == "high":
            self.cal_high_std = avg_std
            self.cal_high_flow = flow_l_min
            self.hass.async_create_task(
                self._persist_options({
                    CONF_CAL_HIGH_STD: avg_std,
                    CONF_CAL_HIGH_FLOW: flow_l_min,
                })
            )

        self._cal_mode = None
        self._cal_start_time = None
        self._cal_std_samples = []
        self._notify_entities()

    def cancel_calibration(self):
        """Bricht Kalibrierung ab."""
        self._cal_mode = None
        self._cal_start_time = None
        self._cal_std_samples = []
        _LOGGER.info("Kalibrierung abgebrochen")
        self._notify_entities()

    @property
    def calibration_mode(self) -> str | None:
        return self._cal_mode

    @property
    def calibration_elapsed(self) -> float:
        if self._cal_start_time is None:
            return 0.0
        return time.time() - self._cal_start_time

    @property
    def calibration_samples(self) -> int:
        return len(self._cal_std_samples)

    @property
    def is_calibrated(self) -> bool:
        """Prueft ob mindestens ein Kalibrierpunkt gesetzt wurde."""
        return (
            self.cal_low_std != DEFAULT_CAL_LOW_STD or
            self.cal_high_std != DEFAULT_CAL_HIGH_STD
        )

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
    def last_std_raw(self) -> float | None:
        """Roher Std-Wert vom Sensor (ungefiltert)."""
        return self._last_std_raw

    @property
    def outliers_rejected(self) -> int:
        """Anzahl verworfener Ausreisser."""
        return self._outliers_rejected

    @property
    def flow_duration_s(self) -> float:
        """Dauer des aktuellen Wasserflusses in Sekunden."""
        if self._flow_start_time is None:
            return 0.0
        return time.time() - self._flow_start_time

    @property
    def idle_time_s(self) -> float:
        """Zeit seit letztem Wasserfluss in Sekunden."""
        if self._last_flow_time is None:
            return 999999.0
        return time.time() - self._last_flow_time

    @property
    def time_since_hydrus_tick(self) -> float:
        """Zeit seit letztem 10L-Tick in Sekunden."""
        if self._last_hydrus_change_time is None:
            return 999999.0
        return time.time() - self._last_hydrus_change_time

    def register_entity_listener(self, cb) -> None:
        self.__dict__.setdefault("_entity_listeners", []).append(cb)

    def reset_residuum(self) -> None:
        """Manueller Reset."""
        self._offset_l = self._volume_l
        self._volume_since_tick = 0.0
        _LOGGER.info("Residuum reset: Offset = %.3f L", self._offset_l)
        self._notify_entities()

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
        """Hydrus 10L-Tick: Auto-Kalibrierung des Faktors."""
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
            # Wenn Volume vom Sensor bereits restauriert wurde, NICHT ueberschreiben
            if getattr(self, "_restored_volume", False):
                self._last_hydrus_total = now_total_l  # nur Referenz setzen
                # Offset korrigieren falls noetig
                if self._offset_l > now_total_l:
                    self._offset_l = now_total_l
            else:
                rounded_volume = (now_total_l // 10) * 10
                self._volume_l = rounded_volume
                self._offset_l = rounded_volume
                self._last_hydrus_total = now_total_l
                self._volume_since_tick = 0.0
            self._notify_entities()
            return

        # 10L-Tick Erkennung
        delta_l = now_total_l - self._last_hydrus_total
        if 9.5 <= delta_l <= 10.5:
            # Auto-Kalibrierung: Vergleiche geschaetztes Volume mit 10L
            estimated = self._volume_since_tick

            if estimated > 1.0:  # Nur wenn wir was gemessen haben
                # Korrektur-Faktor berechnen
                correction = 10.0 / estimated

                # Sanft anpassen (CAL_ADAPT_RATE = 15%)
                target_factor = self.cal_factor * correction
                new_factor = self.cal_factor + CAL_ADAPT_RATE * (target_factor - self.cal_factor)

                # Begrenzen auf sinnvolle Werte
                new_factor = max(CAL_MIN_FACTOR, min(CAL_MAX_FACTOR, new_factor))

                _LOGGER.info(
                    "10L-Tick Auto-Lernen: Geschaetzt=%.1fL, Soll=10L, Korrektur=%.2f, Faktor: %.3f -> %.3f",
                    estimated, correction, self.cal_factor, new_factor
                )

                self.cal_factor = new_factor
                self.hass.async_create_task(
                    self._persist_options({CONF_CAL_FACTOR: new_factor})
                )

            # Reset fuer naechsten Tick
            self._offset_l = now_total_l
            self._volume_l = now_total_l
            self._volume_since_tick = 0.0
            self._last_hydrus_change_time = time.time()

        elif 10.5 < delta_l <= 100.0:
            # Sprung nach Offline
            _LOGGER.info("Hydrus Sprung %.1f L, sync", delta_l)
            self._offset_l = now_total_l
            self._volume_l = now_total_l
            self._volume_since_tick = 0.0

        self._last_hydrus_total = now_total_l
        self._notify_entities()

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

        # Peak-Filter: Ausreisser erkennen und glaetten
        filtered_std = self._filter_std(raw_std)
        if filtered_std is None:
            # Ausreisser verworfen - nichts tun
            return

        self._last_std = filtered_std

        # Kalibrierungs-Modus: Samples sammeln (nur wenn Wasser fliesst)
        if self._cal_mode is not None and filtered_std > self.std_threshold:
            self._cal_std_samples.append(raw_std)  # Rohe Werte fuer Kalibrierung

        # Flow berechnen mit 2-Punkt Interpolation
        flow = self._std_to_flow(filtered_std)
        self._last_flow = flow

        # Flow-Status mit Hysterese
        was_active = self._flow_active
        self._flow_active = flow > 0.1

        if self._flow_active and not was_active:
            self._flow_start_time = now_ts
            _LOGGER.debug("Flow gestartet")
        elif not self._flow_active and was_active:
            self._flow_start_time = None
            _LOGGER.debug("Flow beendet")

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

    def _notify_entities(self) -> None:
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
