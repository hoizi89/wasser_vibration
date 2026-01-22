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
CONF_TOTAL_ENTITY: Final[str] = "total_entity"  # Optional: Hydrus Wasserzaehler
CONF_TOTAL_UNIT: Final[str] = "total_unit"

# --- Option keys --------------------------------------------------------------
CONF_STD_THRESHOLD: Final[str] = "std_threshold"  # Schwellwert fuer "kein Wasser"
CONF_MAX_RES_L: Final[str] = "max_residuum_l"
CONF_RESET_LEARNING: Final[str] = "reset_learning"  # Lerndaten zuruecksetzen

# --- Kalibrierungs-Keys (werden automatisch gelernt) --------------------------
CONF_CAL_LOW_STD: Final[str] = "cal_low_std"      # Std bei schwachem Flow
CONF_CAL_LOW_FLOW: Final[str] = "cal_low_flow"    # L/min bei schwachem Flow
CONF_CAL_HIGH_STD: Final[str] = "cal_high_std"    # Std bei starkem Flow
CONF_CAL_HIGH_FLOW: Final[str] = "cal_high_flow"  # L/min bei starkem Flow
CONF_CAL_FACTOR: Final[str] = "cal_factor"        # Korrektur-Faktor (auto-lernt)

# --- Defaults -----------------------------------------------------------------
DEFAULT_NAME: Final[str] = "Wasser Vibration"
DEFAULT_STD_THRESHOLD: Final[float] = 0.050  # Unterhalb = kein Wasser (m/s2)
DEFAULT_MAX_RES_L: Final[float] = 10.0
DEFAULT_TOTAL_UNIT: Final[str] = "L"

# Kalibrierungs-Defaults (Startwerte, werden durch Kalibrierung ueberschrieben)
DEFAULT_CAL_LOW_STD: Final[float] = 0.050    # Std bei schwach
DEFAULT_CAL_LOW_FLOW: Final[float] = 5.0     # 5 L/min bei schwach
DEFAULT_CAL_HIGH_STD: Final[float] = 0.060   # Std bei stark
DEFAULT_CAL_HIGH_FLOW: Final[float] = 15.0   # 15 L/min bei stark
DEFAULT_CAL_FACTOR: Final[float] = 0.1       # Korrektur-Faktor (konservativ starten)

# --- Ranges fuer Config Flow / Options ----------------------------------------
RANGE_STD: Final[dict] = {"min": 0.01, "max": 0.2, "step": 0.001}
RANGE_FLOW: Final[dict] = {"min": 1.0, "max": 30.0, "step": 0.5}
RANGE_MAX_RES: Final[dict] = {"min": 5.0, "max": 50.0, "step": 1.0}

# --- Kalibrierungs-Konstanten -------------------------------------------------
CAL_ADAPT_RATE: Final[float] = 0.15  # 15% Anpassung pro 10L-Tick (sanft lernen)
CAL_MIN_FACTOR: Final[float] = 0.5   # Minimaler Korrektur-Faktor
CAL_MAX_FACTOR: Final[float] = 2.0   # Maximaler Korrektur-Faktor

# --- 10L Marken ---------------------------------------------------------------
LITER_MARKS: Final[list[int]] = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
