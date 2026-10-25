import logging
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd
import pvlib

from .SolarPowerPlant import SolarPowerPlant

logger = logging.getLogger(__name__)

def fetch_open_meteo_data(latitude, longitude, start_dt, end_dt):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "direct_normal_irradiance,diffuse_radiation,shortwave_radiation,temperature_2m",
        "start_hour": start_dt.strftime("%Y-%m-%dT%H:%M"),  # both ends are included
        "end_hour": end_dt.strftime("%Y-%m-%dT%H:%M"),
        "timezone": "UTC"
    }

    full_url = requests.Request('GET', url, params=params).prepare().url
    logger.debug(f"🌐 API Request: {full_url}")

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    # Print a summary of the response
    logger.debug(f"📦 API Response Keys: {list(data.keys())}")
    if "hourly" in data:
        logger.debug(f"📊 Hourly Data Keys: {list(data['hourly'].keys())}")
        logger.debug(f"🕒 Sample Times: {data['hourly']['time'][:3]} ...")
    else:
        logger.warning("⚠️ No 'hourly' field in API response")

    df = pd.DataFrame(data["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def prepare_weather(dt, meteo_df):
    # Select weather data for the hour Note: For 12:40 the weather data from 12:00 is used
    row = meteo_df.loc[meteo_df["time"] == dt]
    if row.empty:
        logger.warning(f"No weather data found for hour {dt}")
        return None

    return {
        "solar_power_normal": row["direct_normal_irradiance"].values[0],
        "solar_power_diffuse": row["diffuse_radiation"].values[0],
        "shortwave_radiation": row["shortwave_radiation"].values[0],
        "ambient_temperature": row["temperature_2m"].values[0]
    }

def forecast_next_24_hours(plant: SolarPowerPlant, city_name: str):
    start_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(hours=24)
    latitude = plant.latitude
    longitude = plant.longitude 
    meteo_df = fetch_open_meteo_data(latitude, longitude, start_dt, end_dt)

    logger.debug(f"📍 Forecasting for {city_name} ({latitude}, {longitude})")
    results = []

    for hour in range(24):
        hour_start = start_dt + timedelta(hours=hour)
        energy_wh = 0.0

        logger.info(f"⏱️ Hour: {hour_start.strftime('%Y-%m-%d %H:%M')}")

        dt_step = hour_start + timedelta(minutes=30) #Immitate solXpect implementataion
        hour_end = hour_start + timedelta(hours=1)
        inputs = prepare_weather(hour_end, meteo_df)

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