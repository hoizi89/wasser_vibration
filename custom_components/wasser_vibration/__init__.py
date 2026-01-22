from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN, DATA_CTRL, CONF_VIBRATION_ENTITY, CONF_TOTAL_ENTITY, CONF_TOTAL_UNIT,
    CONF_STD_THRESHOLD, CONF_STD_MAX, CONF_FLOW_MAX, CONF_MAX_RES_L,
    DEFAULT_STD_THRESHOLD, DEFAULT_STD_MAX, DEFAULT_FLOW_MAX, DEFAULT_MAX_RES_L,
    DEFAULT_TOTAL_UNIT, PLATFORMS, LITER_MARKS,
)

_LOGGER = logging.getLogger(__name__)


def _m3_to_l(v: float) -> float:
    return v * 1000.0


class WasserVibrationController:
    """Einfacher Controller für Vibrations-basierte Wassererkennung."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.vibration_entity = entry.data[CONF_VIBRATION_ENTITY]
        self.total_entity = entry.data.get(CONF_TOTAL_ENTITY)
        self.total_unit = entry.data.get(CONF_TOTAL_UNIT, DEFAULT_TOTAL_UNIT).lower()

        # Parameter
        self.std_threshold = entry.options.get(CONF_STD_THRESHOLD, DEFAULT_STD_THRESHOLD)
        self.std_max = entry.options.get(CONF_STD_MAX, DEFAULT_STD_MAX)
        self.flow_max = entry.options.get(CONF_FLOW_MAX, DEFAULT_FLOW_MAX)
        self.max_res_l = entry.options.get(CONF_MAX_RES_L, DEFAULT_MAX_RES_L)

        # Interne Zustände
        self._last_ts = None
        self._last_std = None
        self._last_flow = 0.0

        self._volume_l = 0.0
        self._offset_l = 0.0
        self._last_hydrus_total = None

        # Flow-Status
        self._flow_active = False
        self._current_liter_mark = 0

        self._remove_vibration_listener = None
        self._remove_total_listener = None

    def _std_to_flow(self, std: float) -> float:
        """Konvertiert Standardabweichung zu Flow-Rate (L/min)."""
        if std < self.std_threshold:
            return 0.0

        # Linear interpolieren: threshold→0, std_max→flow_max
        std_range = self.std_max - self.std_threshold
        if std_range <= 0:
            return 0.0

        flow = ((std - self.std_threshold) / std_range) * self.flow_max
        return min(flow, self.flow_max * 1.5)  # Max 150% für Ausreißer

    def _get_liter_mark(self, residuum: float) -> int:
        """Gibt die aktuelle 10L-Marke zurück (0, 10, 20, ...)."""
        for i in range(len(LITER_MARKS) - 1, -1, -1):
            if residuum >= LITER_MARKS[i]:
                return LITER_MARKS[i]
        return 0

    def set_options(self, std_threshold=None, std_max=None, flow_max=None, max_res_l=None):
        if std_threshold is not None:
            self.std_threshold = std_threshold
        if std_max is not None:
            self.std_max = std_max
        if flow_max is not None:
            self.flow_max = flow_max
        if max_res_l is not None:
            self.max_res_l = max_res_l

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

    def register_entity_listener(self, cb) -> None:
        self.__dict__.setdefault("_entity_listeners", []).append(cb)

    def reset_residuum(self) -> None:
        """Manueller Reset: Setzt Offset auf aktuelles Volume."""
        self._offset_l = self._volume_l
        _LOGGER.info("Residuum manuell zurückgesetzt: Offset = %.3f L", self._offset_l)
        self._notify_entities()

    def _integrate(self, flow_l_min: float, dt_s: float):
        if dt_s <= 0 or flow_l_min <= 0:
            return
        delta_volume = flow_l_min * (dt_s / 60.0)
        self._volume_l += delta_volume

        # Update 10L-Marke
        self._current_liter_mark = self._get_liter_mark(self.residuum_l)

    def _convert_total_to_l(self, val: float) -> float:
        return _m3_to_l(val) if self.total_unit == "m3" else float(val)

    @callback
    def _on_total_entity_changed(self, event: Event) -> None:
        """Optional: Sync mit Hydrus Wasserzähler bei 10L-Tick."""
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
            rounded_volume = (now_total_l // 10) * 10
            self._volume_l = rounded_volume
            self._offset_l = rounded_volume
            self._last_hydrus_total = now_total_l
            self._notify_entities()
            return

        # 10L-Tick Erkennung
        delta_l = now_total_l - self._last_hydrus_total
        if 9.5 <= delta_l <= 10.5:
            # Reset Residuum bei 10L-Tick
            _LOGGER.info(
                "Hydrus 10L-Tick: Residuum war %.1f L, reset zu 0",
                self.residuum_l
            )
            self._offset_l = now_total_l
            self._volume_l = now_total_l
        elif 10.5 < delta_l <= 100.0:
            # Sprung nach Offline → Sync
            _LOGGER.info("Hydrus Sprung %.1f L, synchronisiere", delta_l)
            self._offset_l = now_total_l
            self._volume_l = now_total_l

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
            std = float(new_state.state)
        except (ValueError, TypeError):
            return

        now_ts = time.time()
        self._last_std = std

        # Flow berechnen
        flow = self._std_to_flow(std)
        self._last_flow = flow
        self._flow_active = flow > 0.1

        # Volumen integrieren
        if self._last_ts is not None:
            dt_s = now_ts - self._last_ts
            if dt_s > 0 and dt_s < 60:  # Max 60s zwischen Updates
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
            self._remove_vibration_listener = None
        if self._remove_total_listener:
            self._remove_total_listener()
            self._remove_total_listener = None


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
