from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_NAME, CONF_VIBRATION_ENTITY, CONF_TOTAL_ENTITY, CONF_TOTAL_UNIT,
    CONF_STD_THRESHOLD, CONF_MAX_RES_L,
    DEFAULT_NAME, DEFAULT_STD_THRESHOLD, DEFAULT_MAX_RES_L, DEFAULT_TOTAL_UNIT,
    RANGE_STD, RANGE_MAX_RES,
)


class WasserVibrationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_VIBRATION_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_TOTAL_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_TOTAL_UNIT, default=DEFAULT_TOTAL_UNIT): vol.In(["L", "m3"]),
            }),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return WasserVibrationOptionsFlow()


class WasserVibrationOptionsFlow(config_entries.OptionsFlow):
    """Minimal Options Flow - ohne config_entry im __init__."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Reset-Checkbox pruefen
            do_reset = user_input.pop("reset_learning", False)

            # WICHTIG: Bestehende Optionen mit neuen mergen (nicht ersetzen!)
            # Sonst gehen gelernte Bucket-Daten verloren!
            merged = dict(self.config_entry.options)
            merged.update(user_input)

            if do_reset:
                merged["learn_count"] = 0
                for i in range(5):
                    merged[f"bucket_{i}"] = 0.1
                    merged[f"bucket_{i}_count"] = 0
                    merged[f"bucket_{i}_time"] = 0.0

            return self.async_create_entry(title="", data=merged)

        # Aktuelle Werte holen
        current_threshold = self.config_entry.options.get(
            CONF_STD_THRESHOLD, DEFAULT_STD_THRESHOLD
        )
        current_max_res = self.config_entry.options.get(
            CONF_MAX_RES_L, DEFAULT_MAX_RES_L
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_STD_THRESHOLD, default=current_threshold): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=RANGE_STD["min"],
                        max=RANGE_STD["max"],
                        step=RANGE_STD["step"],
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_MAX_RES_L, default=current_max_res): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=RANGE_MAX_RES["min"],
                        max=RANGE_MAX_RES["max"],
                        step=RANGE_MAX_RES["step"],
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional("reset_learning", default=False): selector.BooleanSelector(),
            }),
        )
