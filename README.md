# ☀️ solXpect_meets_python

This Python library reproduces the energy output calculations of the original `SolarPowerPlant.java` class from [solXpect](https://github.com/woheller69/solxpect), with one minor difference: it uses a different package (`pvlib`) to calculate the sun's position.

The goal is to provide a transparent, reproducible, and physically aligned implementation of solXpect's solar energy model — useful for validation, experimentation, and integration into larger forecasting workflows.

---

## 📦 Features

- ✅ Reproduces solXpect's energy output logic hour-by-hour
- ✅ Uses Open-Meteo API for weather data (irradiance, temperature)
- ✅ Supports shading logic, temperature derating, and inverter clipping
- ✅ Reads plant configuration from a ZIP file (Backup database file from solXpect)
- ✅ Outputs hourly energy forecasts in Wh, adjusted to local time zone

---

## 🧩 Structure

| Class | File | Purpose |
|-------|------|---------|
| `PanelArray` | `calcs/PanelArray.py` | One group of panels with the same orientation (e.g. one string): sun position, angle of incidence, shading, temperature → **DC power** |
| `Inverter` | `calcs/Inverter.py` | Efficiency and AC power limit, applied to the **summed DC power** of its arrays |
| `SolarPowerPlant` | `calcs/SolarPowerPlant.py` | solXpect-compatible wrapper: one `PanelArray` with one `Inverter`, same `getPower` as the app |

### Beam modes

`PanelArray` (and `SolarPowerPlant`) take `beamMode`, which decides how the direct sunlight is averaged over the hour:

- `"app"` (default): the angle of incidence is calculated once at the middle of the hour and multiplied by the shading averaged over 6 sub-steps of 10 minutes. This is exactly what solXpect does.
- `"substep"`: angle of incidence and shading are calculated together every 7.5 minutes (8 sub-steps per hour), and their product is averaged. This is more accurate around sunrise/sunset and at shading edges, and slightly lower around noon (the average around a maximum is below the peak). It also works for 15-minute weather data (`intervalSeconds=900`, 2 sub-steps per quarter hour); the four quarter-hour results average exactly to the hourly result.

---

## 🧪 Tests

```bash
pip install pytest
python -m pytest
```

`tests/reference_legacy.json` holds results of the original implementation for made-up plants and synthetic weather; the tests check that `beamMode="app"` still reproduces them. Regenerate it only on purpose with `python -m tests.make_reference`.

---

## 🔧 Requirements

- Python 3.9+
- Internet connection (for Open-Meteo API)
- Backup database file from solXpect (ZIP containing `SQLITE.db`)

### 📚 Dependencies

| Library         | Purpose                                      |
|----------------|----------------------------------------------|
| `pvlib`         | Solar position calculation                  |
| `requests`      | API calls to Open-Meteo                     |
| `sqlite3`       | Reading plant configuration from ZIP        |
| `pandas`        | Data handling and time series manipulation  |

---

## 🚀 Quick Start

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/solar-forecast-repro.git
   cd solar-forecast-repro
