# Wasser-Vibration (ADXL345 Water Flow Detection)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/hoizi89/wasser_vibration.svg)](https://github.com/hoizi89/wasser_vibration/releases)

Home Assistant integration that detects water flow by measuring pipe vibrations with an ADXL345 accelerometer on an ESP32.

## How It Works

1. An **ADXL345 accelerometer** is mounted on the water pipe and connected to an **ESP32** via I2C
2. The ESP32 reads the Y-axis acceleration at 100 Hz and calculates the **standard deviation** every 500 ms
3. This integration receives the std deviation value and maps it to a **flow rate** (L/min) using linear interpolation between a configurable threshold (no flow) and max value (full flow)
4. Flow rate is integrated over time to calculate **volume** (liters)
5. At every **10L tick** from the water meter, the integration auto-calibrates its mapping factors

### Vibration Signal

| State | Y-Axis Std Dev |
|-------|---------------|
| No water flow | ~0.041 m/s |
| Water flowing | ~0.052 m/s (+26%) |

The integration uses a **multi-bucket learning system** that maintains separate calibration factors for different vibration intensity ranges, improving accuracy over time.

## Hardware

### Tested Setup

| Component | Model | Notes |
|-----------|-------|-------|
| Microcontroller | **ESP32 DevKit V1** (ESP-WROOM-32) | Any ESP32 board works |
| Accelerometer | **ADXL345** breakout board (I2C) | GY-291 or similar, ~$2-3 |
| Water Meter | **Diehl Hydrus** (wMBus) | For auto-calibration at 10L ticks |

### Wiring

| ADXL345 Pin | ESP32 Pin |
|-------------|-----------|
| SDA | GPIO21 |
| SCL | GPIO22 |
| VCC | 3.3V |
| GND | GND |

### Mounting

Mount the ADXL345 firmly on the water pipe using zip ties, hose clamps, or adhesive tape. The Y-axis of the sensor should be aligned along the pipe for best sensitivity. A solid mechanical connection is critical — loose mounting reduces signal quality.

## ESPHome Firmware

Flash the ESP32 with the provided ESPHome configuration:

```
esphome/wasser_vibration.yaml
```

Before flashing, create a `secrets.yaml` in your ESPHome config directory with:

```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "YourWiFiPassword"
api_encryption_key: "generate-a-key-with-esphome"
ota_password: "generate-a-password"
```

The firmware:
- Reads ADXL345 via raw I2C at ~100 Hz (10 ms interval)
- Calculates Y-axis standard deviation over 500 ms windows
- Exposes `Vibration Y-Std` sensor to Home Assistant via ESPHome API
- Includes a basic binary `Wasser Fliesst` sensor (threshold-based)
- Has a web server on port 80 for monitoring/debugging
- Includes a "Collect Data" button for 10s raw data capture (useful for calibration)

## Installation (HACS)

1. Open HACS -> Integrations
2. Three-dot menu -> Custom repositories
3. URL: `https://github.com/hoizi89/wasser_vibration`, Category: Integration
4. Install "Wasser-Vibration"
5. Restart Home Assistant

### Manual Installation

Copy `custom_components/wasser_vibration` to your HA `custom_components/` directory and restart.

## Configuration

1. Settings -> Devices & Services -> Add Integration
2. Search for "Wasser Vibration"
3. Select the **Vibration Y-Std** sensor entity (from the ESP32)
4. Optionally select a **water meter** entity (e.g., Hydrus total) for auto-calibration

### Options

Adjustable via integration options:

| Option | Default | Description |
|--------|---------|-------------|
| `std_threshold` | 0.050 m/s | Below this = no water flow |
| `std_max` | 0.060 m/s | At this value = maximum flow |
| `flow_max` | 30 L/min | Maximum flow rate |
| `max_residuum` | 10.0 L | Reset interval (matches meter tick) |

These values auto-calibrate over time if a water meter entity is configured.

## Sensors

| Sensor | Description |
|--------|-------------|
| Flow | Current flow rate (L/min) |
| Volume | Cumulative volume (L), persists across restarts |
| Residuum | Volume since last reset (0-10 L) |
| Flow Status | Active/Inactive text |
| Auto Learn | Current learning state and bucket info |

## Related

This integration works standalone but pairs well with [wasser_residuum](https://github.com/hoizi89/wasser_residuum) which uses temperature-based flow detection as an alternative/complementary approach.

---

Experimental hobby project. Use calibrated meters for billing purposes.
