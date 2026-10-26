import numpy as np


def sunPosition(latitude, longitude, epochs):
    # Solar azimuth (° from north, clockwise) and elevation (°, without atmospheric refraction)
    # for an array of Unix timestamps (UTC). NOAA solar position algorithm
    # (https://gml.noaa.gov/grad/solcalc/calcdetails.html), about 0.01° accurate for 1900-2100;
    # it only needs numpy, so the library doesn't need pvlib (and pandas/scipy) at runtime.
    epochs = np.asarray(epochs, dtype=float)
    julianCentury = (epochs / 86400.0 + 2440587.5 - 2451545.0) / 36525.0
    t = julianCentury

    meanLongitude = np.mod(280.46646 + t * (36000.76983 + t * 0.0003032), 360)  # °
    meanAnomaly = np.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    equationOfCenter = (np.sin(meanAnomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
                        + np.sin(2 * meanAnomaly) * (0.019993 - 0.000101 * t)
                        + np.sin(3 * meanAnomaly) * 0.000289)
    omega = np.radians(125.04 - 1934.136 * t)
    apparentLongitude = np.radians(meanLongitude + equationOfCenter - 0.00569 - 0.00478 * np.sin(omega))
    meanObliquity = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliquity = np.radians(meanObliquity + 0.00256 * np.cos(omega))
    declination = np.arcsin(np.sin(obliquity) * np.sin(apparentLongitude))

    y = np.tan(obliquity / 2) ** 2
    l0 = np.radians(meanLongitude)
    equationOfTime = 4 * np.degrees(  # minutes
        y * np.sin(2 * l0)
        - 2 * eccentricity * np.sin(meanAnomaly)
        + 4 * eccentricity * y * np.sin(meanAnomaly) * np.cos(2 * l0)
        - 0.5 * y * y * np.sin(4 * l0)
        - 1.25 * eccentricity * eccentricity * np.sin(2 * meanAnomaly))
    trueSolarTime = np.mod(np.mod(epochs, 86400) / 60 + equationOfTime + 4 * longitude, 1440)  # minutes
    hourAngle = np.radians(trueSolarTime / 4 - 180)

    lat = np.radians(latitude)
    sinElevation = np.sin(lat) * np.sin(declination) + np.cos(lat) * np.cos(declination) * np.cos(hourAngle)
    elevation = np.degrees(np.arcsin(np.clip(sinElevation, -1, 1)))
    azimuth = np.mod(np.degrees(np.arctan2(
        np.sin(hourAngle),
        np.cos(hourAngle) * np.sin(lat) - np.tan(declination) * np.cos(lat))) + 180, 360)
    return azimuth, elevation
