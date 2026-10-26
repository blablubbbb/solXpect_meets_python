# ☀️ solXpect_meets_python

This Python library reproduces the energy output calculations of the original `SolarPowerPlant.java` class from [solXpect](https://github.com/woheller69/solxpect), with one minor difference: the sun's position comes from the NOAA solar position algorithm (`calcs/sunposition.py`, plain numpy, within about 0.02° of pvlib's NREL SPA).

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
| `Site` | `calcs/Site.py` | One location with several inverters, each with several arrays; one weather request and one sun position calculation for all of them |
| — | `calcs/app_import.py` | Turns the plants of a solXpect backup ZIP into `Site` objects |

### Panel size

Give **either** the rated power `cellsMaxPower` (W at 1000 W/m², from the datasheet) **or** `cellsArea` (m²) together with `cellsEfficiency` (%). If both are given, area × efficiency is used, as in solXpect; when the two differ by more than 1 %, a warning names the ignored rated power.

### Cell temperature (cooling factor)

The cell temperature follows the Ross model: `T_cell = T_ambient + k × G`, with `G` the irradiance on the panel (W/m²) and `k = cellsCoolingFactor` (°C per W/m²). The default is **0.0342** ("not so well cooled"), as hardcoded in solXpect. Better cooled panels have a smaller `k`, which means cooler cells and, with the usual negative temperature coefficient, more power.

Typical values by mounting, as guidance:

| Mounting | k |
|---|---|
| well cooled | 0.0200 |
| free standing | 0.0208 |
| flat on roof | 0.0260 |
| not so well cooled (default) | 0.0342 |
| transparent PV | 0.0455 |
| facade integrated | 0.0538 |
| on sloped roof | 0.0563 |

⚠️ These values are commonly attributed to Nordmann & Clavadetscher, *Understanding temperature effects on PV system performance*, 3rd WCPEC, Osaka 2003, and are collected in Skoplaki & Palyvos, *Operating temperature of photovoltaic modules: A survey of pertinent correlations*, Renewable Energy 34 (2009) 23–29, [doi:10.1016/j.renene.2008.04.009](https://doi.org/10.1016/j.renene.2008.04.009). They have not been checked against the original papers yet.

Notes:
- The values come from modules with much lower efficiency than today's. Energy that leaves the cell as electricity doesn't heat it, so modern high-efficiency modules run somewhat cooler than these values suggest. The PVsyst model makes this explicit: `T_cell = T_ambient + α × G × (1 − η) / (U_c + U_v × wind)`; with its free-standing default `U_c = 29 W/m²K`, `α = 0.9` and `η = 22 %` this corresponds to `k ≈ 0.024`.
- Wind is not taken into account yet (the Faiman model used in IEC 61853 adds it).

### Sites

```python
from datetime import datetime, timedelta, timezone
from calcs.Inverter import Inverter
from calcs.PanelArray import PanelArray
from calcs.Site import Site

site = Site(latitude=50.0, longitude=8.0, name="Home", inverters=[
    Inverter(name="Hybrid", inverterEfficiency=97, inverterPowerLimit=8000, arrays=[
        PanelArray(name="South", azimuthAngle=180, tiltAngle=30, cellsMaxPower=4000, ...),
        PanelArray(name="East", azimuthAngle=90, tiltAngle=30, cellsMaxPower=2000, ...),
    ]),
    Inverter(name="Micro", inverterEfficiency=95, inverterPowerLimit=800, arrays=[
        PanelArray(name="Balcony", azimuthAngle=200, tiltAngle=90, cellsMaxPower=800, ...),
    ]),
])

start = datetime(2026, 6, 21, tzinfo=timezone.utc)
result = site.forecast(start, start + timedelta(days=1), intervalSeconds=900)  # or 3600; historical=True for past days
```

`result` is a `SiteResult`: `result.times` are the ends of the intervals (Unix seconds, UTC), and `result["<name>"]` gives the mean power in W per interval as a numpy array, for `"<inverter>/<array>"` (DC per array), `"<inverter>"` (AC per inverter: efficiency and limit applied to the **sum** of its arrays) and `"total"`. Energy in Wh is power × interval length in hours. `result.to_dataframe()` returns the same as a pandas DataFrame (needs pandas). `Site.calculate(weather)` does the same for weather you already have; `fetch_open_meteo_data` returns the weather as a dict of numpy arrays (`"time"` in Unix seconds), and a pandas DataFrame with the same columns works too.

Settings are stored as one JSON file per inverter (with its arrays) plus `site.json` (name, location, beam mode): `site.save(folder)` / `Site.load(folder)`. Units are the same as in solXpect (percent for efficiencies, W, degrees).

**Import from solXpect:** `sites_from_app_backup("solXpect.zip")` from `calcs/app_import.py` makes one site per location. Plants without "central inverter" get their own inverter; the central plants of a location share one inverter whose limit is the sum of their limits (as with the app's "summarize" option). Imported sites use `beamMode="app"` unless you pass `beamMode="substep"`.

- `select=["Roof", 3]` imports only the plants with these names or ranks.
- `combine=False` makes every plant its own site with its own inverter, for example when the plants in the app are alternative variants of the same installation rather than parts of it.

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

`tests/reference_legacy.json` holds results of the original implementation (with pvlib's solar position) for made-up plants and synthetic weather; the tests check that `beamMode="app"` still reproduces them within 0.1 % (the NOAA solar position changes them by at most 0.03 %). Regenerate it only on purpose with `python -m tests.make_reference`. `tests/test_sunposition.py` compares the solar position with pvlib directly; it is skipped when pvlib isn't installed.

---

## 🔧 Requirements

- Python 3.9+
- Internet connection (for Open-Meteo API)
- Backup database file from solXpect (ZIP containing `SQLITE.db`)

### 📚 Dependencies

| Library         | Purpose                                      |
|----------------|----------------------------------------------|
| `numpy`         | All calculations, including the solar position |
| `requests`      | API calls to Open-Meteo                     |
| `sqlite3`       | Reading plant configuration from ZIP (standard library) |
| `pandas`        | Optional: `SiteResult.to_dataframe()`, tests |
| `pvlib`         | Optional: only for the solar position test  |

The calculation needs only numpy and requests, which keeps the memory use low (about 25 MB instead of about 110 MB with pandas and pvlib), e.g. for Home Assistant on a small NAS.

---

## 🚀 Quick Start

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/solar-forecast-repro.git
   cd solar-forecast-repro
