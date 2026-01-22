from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_NAME, CONF_VIBRATION_ENTITY, CONF_TOTAL_ENTITY, CONF_TOTAL_UNIT,
    CONF_STD_THRESHOLD, CONF_STD_MAX, CONF_FLOW_MAX, CONF_MAX_RES_L,
    DEFAULT_NAME, DEFAULT_STD_THRESHOLD, DEFAULT_STD_MAX, DEFAULT_FLOW_MAX,
    DEFAULT_MAX_RES_L, DEFAULT_TOTAL_UNIT,
    RANGE_STD, RANGE_FLOW, RANGE_MAX_RES,
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
            description_placeholders={
                "vibration_hint": "Waehle den 'Vibration Y-Std' Sensor vom ESPHome-Geraet",
                "total_hint": "Optional: Hydrus Wasserzaehler fuer Auto-Reset bei 10L-Tick",
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return WasserVibrationOptionsFlow(config_entry)


class WasserVibrationOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Entity-Aenderungen in data speichern
            new_data = dict(self.config_entry.data)
            new_options = {}

            for key in [CONF_VIBRATION_ENTITY, CONF_TOTAL_ENTITY, CONF_TOTAL_UNIT]:
                if key in user_input:
                    new_data[key] = user_input[key]
                    del user_input[key]

            new_options = user_input

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )

            return self.async_create_entry(title="", data=new_options)

        # Aktuelle Werte
        current_vibration = self.config_entry.data.get(CONF_VIBRATION_ENTITY)
        current_total = self.config_entry.data.get(CONF_TOTAL_ENTITY)
        current_unit = self.config_entry.data.get(CONF_TOTAL_UNIT, DEFAULT_TOTAL_UNIT)

        current_threshold = self.config_entry.options.get(CONF_STD_THRESHOLD, DEFAULT_STD_THRESHOLD)
        current_std_max = self.config_entry.options.get(CONF_STD_MAX, DEFAULT_STD_MAX)
        current_flow_max = self.config_entry.options.get(CONF_FLOW_MAX, DEFAULT_FLOW_MAX)
        current_max_res = self.config_entry.options.get(CONF_MAX_RES_L, DEFAULT_MAX_RES_L)

        schema_dict = {}

        # Vibration Entity
        if current_vibration:
            schema_dict[vol.Required(CONF_VIBRATION_ENTITY, default=current_vibration)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema_dict[vol.Required(CONF_VIBRATION_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        # Total Entity (optional)
        if current_total:
            schema_dict[vol.Optional(CONF_TOTAL_ENTITY, default=current_total)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema_dict[vol.Optional(CONF_TOTAL_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        schema_dict[vol.Required(CONF_TOTAL_UNIT, default=current_unit)] = vol.In(["L", "m3"])

        # Kalibrierungs-Optionen
        schema_dict[vol.Required(CONF_STD_THRESHOLD, default=current_threshold)] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=RANGE_STD["min"],
                max=RANGE_STD["max"],
                step=RANGE_STD["step"],
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="m/s2",
            )
        )
        schema_dict[vol.Required(CONF_STD_MAX, default=current_std_max)] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=RANGE_STD["min"],
                max=RANGE_STD["max"],
                step=RANGE_STD["step"],
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="m/s2",
            )
        )
        schema_dict[vol.Required(CONF_FLOW_MAX, default=current_flow_max)] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=RANGE_FLOW["min"],
                max=RANGE_FLOW["max"],
                step=RANGE_FLOW["step"],
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="L/min",
            )
        )
        schema_dict[vol.Required(CONF_MAX_RES_L, default=current_max_res)] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=RANGE_MAX_RES["min"],
                max=RANGE_MAX_RES["max"],
                step=RANGE_MAX_RES["step"],
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="L",
            )
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict)
        )
