import logging
from datetime import datetime, timedelta, timezone
import numpy as np
import requests

from .SolarPowerPlant import SolarPowerPlant

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Archive of past forecast runs, same parameters and also 15 min data
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
WEATHER_VARIABLES = ("direct_normal_irradiance", "diffuse_radiation", "shortwave_radiation", "temperature_2m")

def fetch_open_meteo_data(latitude, longitude, start_dt, end_dt, intervalSeconds=3600, historical=False):
    # Weather from Open-Meteo as a dict of numpy arrays, one value per interval:
    #   "time": end of the interval as Unix timestamp (seconds, UTC); the radiation values
    #   are the mean over the preceding interval; plus the WEATHER_VARIABLES.
    # intervalSeconds: 3600 (hourly) or 900 (15 min data, "minutely_15")
    # historical: use the archive of past forecasts instead of the current forecast
    if intervalSeconds == 3600:
        resolution = "hourly"
    elif intervalSeconds == 900:
        resolution = "minutely_15"
    else:
        raise ValueError("intervalSeconds must be 3600 or 900")
    rangeSuffix = "hour" if resolution == "hourly" else resolution
    url = HISTORICAL_FORECAST_URL if historical else FORECAST_URL
    params = {
        "latitude": latitude,
        "longitude": longitude,
        resolution: ",".join(WEATHER_VARIABLES),
        f"start_{rangeSuffix}": start_dt.strftime("%Y-%m-%dT%H:%M"),  # both ends are included
        f"end_{rangeSuffix}": end_dt.strftime("%Y-%m-%dT%H:%M"),
        "timezone": "UTC"
    }

    full_url = requests.Request('GET', url, params=params).prepare().url
    logger.debug(f"🌐 API Request: {full_url}")

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    # Print a summary of the response
    logger.debug(f"📦 API Response Keys: {list(data.keys())}")
    if resolution in data:
        logger.debug(f"📊 {resolution} Data Keys: {list(data[resolution].keys())}")
        logger.debug(f"🕒 Sample Times: {data[resolution]['time'][:3]} ...")
    else:
        logger.warning(f"⚠️ No '{resolution}' field in API response")

    values = data.get(resolution, {})
    weather = {"time": np.array(values.get("time", []), dtype="datetime64[s]").astype(np.int64)}
    for name in WEATHER_VARIABLES:
        # missing values (null) become NaN
        weather[name] = np.array(values.get(name, []), dtype=float)
    return weather


def prepare_weather(dt, weather):
    # Select weather data for the hour Note: For 12:40 the weather data from 12:00 is used
    rows = np.flatnonzero(weather["time"] == int(dt.timestamp()))
    if not len(rows):
        logger.warning(f"No weather data found for hour {dt}")
        return None

    row = rows[0]
    return {
        "solar_power_normal": weather["direct_normal_irradiance"][row],
        "solar_power_diffuse": weather["diffuse_radiation"][row],
        "shortwave_radiation": weather["shortwave_radiation"][row],
        "ambient_temperature": weather["temperature_2m"][row]
    }

def forecast_next_24_hours(plant: SolarPowerPlant, city_name: str):
    start_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(hours=24)
    latitude = plant.latitude
    longitude = plant.longitude 
    weather = fetch_open_meteo_data(latitude, longitude, start_dt, end_dt)

    logger.debug(f"📍 Forecasting for {city_name} ({latitude}, {longitude})")
    results = []

    for hour in range(24):
        hour_start = start_dt + timedelta(hours=hour)
        energy_wh = 0.0

        logger.info(f"⏱️ Hour: {hour_start.strftime('%Y-%m-%d %H:%M')}")

        dt_step = hour_start + timedelta(minutes=30) #Immitate solXpect implementataion
        hour_end = hour_start + timedelta(hours=1)
        inputs = prepare_weather(hour_end, weather)

        if inputs is None:
            logger.warning(f"{dt_step.strftime('%Y-%m-%d %H:%M')} – No data available")
            continue

        energy_wh = plant.getPower(
            solarPowerNormal=inputs["solar_power_normal"],
            solarPowerDiffuse=inputs["solar_power_diffuse"],
            shortwaveRadiation=inputs["shortwave_radiation"],
            epochTimeSeconds=int(dt_step.timestamp()),
            ambientTemperature=inputs["ambient_temperature"]
        )
        results.append((hour_end, energy_wh))
    return results
   
#Function no longer needed...
def get_shading_factor(elevation_deg, azimuth_deg, thresholds, opacities):
    """
    Applies azimuth-dependent shading logic.

    thresholds: list of elevation thresholds per azimuth bin
    opacities: list of shading percentages per azimuth bin
    Assumes 36 bins covering 0–360° in 10° increments.
    """
    bin_index = int(azimuth_deg // 10) % 36
    threshold = thresholds[bin_index]
    opacity = opacities[bin_index]

    if elevation_deg < threshold:
        factor = 1.0 - opacity
        logger.debug(
            f"⛅ Shading applied: azimuth={azimuth_deg:.1f}° → bin={bin_index}, "
            f"elevation={elevation_deg:.1f}° < threshold={threshold:.1f}°, "
            f"opacity={opacity:.1f}%, factor={factor:.2f}"
        )
        return factor
    else:
        logger.debug(
            f"☀️ No shading: azimuth={azimuth_deg:.1f}° → bin={bin_index}, "
            f"elevation={elevation_deg:.1f}° ≥ threshold={threshold:.1f}°"
        )
        return 1.0