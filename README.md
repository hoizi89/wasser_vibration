# Wasser-Vibration

Home Assistant Integration zur Vibrations-basierten Wassererkennung mit ADXL345 Beschleunigungssensor.

## Features

- Erkennt Wasserfluss durch Vibration (Y-Achsen Standardabweichung)
- Konfigurierbare Schwellwerte in Home Assistant UI
- Volume-Tracking mit 10L-Marken
- Optional: Auto-Reset bei Hydrus 10L-Tick

## Installation (HACS)

1. HACS öffnen → Integrationen
2. 3-Punkte-Menü → Benutzerdefinierte Repositories
3. URL: `hoizi89/wasser_vibration`
4. Kategorie: Integration
5. "Wasser Vibration" installieren
6. Home Assistant neustarten

## Konfiguration

1. Einstellungen → Geräte & Dienste → Integration hinzufügen
2. "Wasser Vibration" suchen
3. Den **Vibration Y-Std** Sensor vom ESPHome auswählen
4. Optional: Hydrus Wasserzähler für Auto-Reset

## Kalibrierung

In den Integrations-Optionen anpassbar:

| Option | Default | Beschreibung |
|--------|---------|--------------|
| `std_threshold` | 0.048 | Unter diesem Wert = kein Wasser |
| `std_max` | 0.060 | Bei diesem Wert = maximaler Flow |
| `flow_max` | 30 L/min | Maximaler Durchfluss |

## Sensoren

| Sensor | Beschreibung |
|--------|--------------|
| Flow | Aktueller Durchfluss (L/min) |
| Volume | Kumuliertes Volumen (L) |
| Residuum | Volumen seit Reset (0-10L) |
| Liter Mark | Aktuelle 10L-Marke (0, 10, 20...) |
| Flow Status | Active/Inactive mit Status-Text |

## ESPHome

Die ESPHome-Konfiguration für ESP32 + ADXL345 findest du im [wasser_residuum](https://github.com/hoizi89/wasser_residuum) Repository unter `esphome/water_flow_vibration_i2c.yaml`.
