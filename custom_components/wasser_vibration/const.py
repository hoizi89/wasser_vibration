from __future__ import annotations

from typing import Final, Literal
from homeassistant.const import Platform

# --- Domain / Platforms -------------------------------------------------------
DOMAIN: Final[str] = "wasser_vibration"
DATA_CTRL: Final[str] = "ctrl"

PLATFORMS: Final[tuple[Platform, ...]] = (
    Platform.SENSOR,
    Platform.BUTTON,
)

# --- Config keys --------------------------------------------------------------
CONF_NAME: Final[str] = "name"
CONF_VIBRATION_ENTITY: Final[str] = "vibration_entity"  # ESPHome Y-Std Sensor
CONF_TOTAL_ENTITY: Final[str] = "total_entity"  # Optional: Hydrus Wasserzähler
CONF_TOTAL_UNIT: Final[str] = "total_unit"

# --- Option keys --------------------------------------------------------------
CONF_STD_THRESHOLD: Final[str] = "std_threshold"  # Schwellwert für "kein Wasser"
CONF_STD_MAX: Final[str] = "std_max"  # Std bei maximalem Flow
CONF_FLOW_MAX: Final[str] = "flow_max"  # Max L/min bei std_max
CONF_MAX_RES_L: Final[str] = "max_residuum_l"

# --- Defaults (kalibriert: 1L/12s bei Std 0.050 = 5 L/min, Faktor 2500)
DEFAULT_NAME: Final[str] = "Wasser Vibration"
DEFAULT_STD_THRESHOLD: Final[float] = 0.048  # Unterhalb = kein Wasser (m/s²)
DEFAULT_STD_MAX: Final[float] = 0.060  # Bei diesem Std = max Flow (m/s²)
DEFAULT_FLOW_MAX: Final[float] = 30.0  # L/min bei std_max
DEFAULT_MAX_RES_L: Final[float] = 10.0
DEFAULT_TOTAL_UNIT: Final[str] = "L"

# --- Ranges für Config Flow / Options -----------------------------------------
RANGE_STD: Final[dict] = {"min": 0.01, "max": 0.2, "step": 0.001}
RANGE_FLOW: Final[dict] = {"min": 1.0, "max": 30.0, "step": 0.5}
RANGE_MAX_RES: Final[dict] = {"min": 5.0, "max": 50.0, "step": 1.0}

# --- 10L Marken ---------------------------------------------------------------
LITER_MARKS: Final[list[int]] = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
