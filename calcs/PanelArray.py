import logging
import math
import numpy as np
import pandas as pd
import pvlib

logger = logging.getLogger(__name__)

# Ross model factor for the cell temperature (°C per W/m²), "not so well cooled" as in solXpect.
# Typical values per mounting are listed in the README.
DEFAULT_COOLING_FACTOR = 0.0342

# How the direct (beam) part is averaged over the weather interval:
#   "app":     angle of incidence once at the middle of the hour, multiplied by
#              the shading averaged over 6 sub-steps (as solXpect does it)
#   "substep": angle of incidence and shading per sub-step, their product averaged
BEAM_MODES = ("app", "substep")

# "app" mode: 6 shading sub-steps per hour, 10 min steps at xx:05 / xx:15 / xx:25 / xx:35 / xx:45 / xx:55
APP_STEPS = 6

# "substep" mode: one sub-step per 7.5 min, in the middle of each step -> 8 per hour,
# 2 per 15 min interval. Hourly and 15 min calculations use the same points in time,
# so four quarter-hour results average exactly to the hourly result.
SUBSTEP_SECONDS = 450


def stepEpochs(midEpochs, intervalSeconds, beamMode):
    # Points in time needed for each interval, one row per interval:
    # column 0 is the middle of the interval, columns 1.. are the sub-steps.
    if beamMode not in BEAM_MODES:
        raise ValueError(f"beamMode must be one of {BEAM_MODES}, not {beamMode!r}")
    if beamMode == "app":
        if intervalSeconds != 3600:
            raise ValueError("beamMode 'app' only supports hourly intervals")
        numSteps = APP_STEPS
    else:
        if intervalSeconds % SUBSTEP_SECONDS:
            raise ValueError(f"intervalSeconds must be a multiple of {SUBSTEP_SECONDS}")
        numSteps = intervalSeconds // SUBSTEP_SECONDS
    interval = intervalSeconds // numSteps  # seconds
    offsets = [0] + [-((numSteps - 1) * interval // 2) + j * interval for j in range(numSteps)]
    return np.asarray(midEpochs, dtype=np.int64)[:, None] + np.asarray(offsets, dtype=np.int64)[None, :]


def solarPositions(latitude, longitude, epochs):
    # Solar azimuth and elevation (degrees) for an array of Unix timestamps, in one pvlib call
    epochs = np.asarray(epochs)
    times = pd.to_datetime(epochs.ravel(), unit="s", utc=True)
    solarPosition = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    return (solarPosition["azimuth"].to_numpy().reshape(epochs.shape),
            solarPosition["elevation"].to_numpy().reshape(epochs.shape))


def panelNormal(azimuthAngle, tiltAngle):
    # Unit vector perpendicular to the panel front, (east, north, up)
    return np.array([
        math.sin(math.radians(azimuthAngle)) * math.cos(math.radians(90 - tiltAngle)),
        math.cos(math.radians(azimuthAngle)) * math.cos(math.radians(90 - tiltAngle)),
        math.sin(math.radians(90 - tiltAngle))
    ])


def maxSunElevationPerBin(latitude, azimuthAngle, tiltAngle):
    # For each of the 36 shading bins (azimuth 0-10°, 10-20°, ...): the highest elevation (°)
    # the sun reaches in that direction during the year while it is above the horizon and in
    # front of the panel; None if that never happens. Obstacles only matter below these values.
    # Pure geometry over all declinations and hour angles, no time series needed.
    declination = np.radians(np.linspace(-23.44, 23.44, 95))[:, None]
    hourAngle = np.radians(np.linspace(-180, 180, 1441))[None, :]
    lat = math.radians(latitude)
    sinElevation = (math.sin(lat) * np.sin(declination)
                    + math.cos(lat) * np.cos(declination) * np.cos(hourAngle))
    elevation = np.degrees(np.arcsin(np.clip(sinElevation, -1, 1)))
    azimuth = np.degrees(np.arctan2(
        -np.cos(declination) * np.sin(hourAngle),
        np.sin(declination) * math.cos(lat) - np.cos(declination) * np.cos(hourAngle) * math.sin(lat))) % 360
    inFront = PanelArray.sunDirection(azimuth, elevation) @ panelNormal(azimuthAngle, tiltAngle) > 1e-9
    visible = (elevation > 0) & inFront
    bins = (azimuth // 10).astype(int) % 36
    highest = np.full(36, -np.inf)
    np.maximum.at(highest, bins[visible], elevation[visible])
    return [float(e) if np.isfinite(e) else None for e in highest]


class PanelArray:
    # One group of identical panels with the same orientation (e.g. one string).
    # Computes the DC power; the inverter is handled by the Inverter class.
    # latitude/longitude are only needed when the array is used on its own (getDcPower,
    # beamFactor); inside a Site the site's location is used.
    # The panel size is given either as rated power (cellsMaxPower, W at 1000 W/m²) or as
    # cellsArea + cellsEfficiency. If both are given, area and efficiency win (as in solXpect).
    def __init__(self, *, albedo, cellsTempCoeff, diffuseEfficiency, azimuthAngle, tiltAngle,
                 shadingElevation, shadingOpacity, cellsMaxPower=0, cellsArea=0, cellsEfficiency=0,
                 cellsCoolingFactor=DEFAULT_COOLING_FACTOR, latitude=None, longitude=None,
                 beamMode="app", name=""):
        if beamMode not in BEAM_MODES:
            raise ValueError(f"beamMode must be one of {BEAM_MODES}, not {beamMode!r}")
        usesArea = cellsArea > 0 and cellsEfficiency > 0
        if not usesArea and not cellsMaxPower > 0:
            raise ValueError(f"array {name!r}: give cellsMaxPower or cellsArea and cellsEfficiency")
        if usesArea and cellsMaxPower > 0:
            areaPower = cellsArea * cellsEfficiency / 100 * 1000
            if abs(areaPower - cellsMaxPower) > 0.01 * cellsMaxPower:
                logger.warning(f"array {name!r}: cellsMaxPower {cellsMaxPower:.0f} W is ignored, using "
                               f"cellsArea x cellsEfficiency = {areaPower:.0f} W")
        # settings as given (units as in solXpect), for saving
        self.settings = dict(
            name=name, albedo=albedo, cellsMaxPower=cellsMaxPower, cellsArea=cellsArea,
            cellsEfficiency=cellsEfficiency, cellsTempCoeff=cellsTempCoeff,
            cellsCoolingFactor=cellsCoolingFactor,
            diffuseEfficiency=diffuseEfficiency, azimuthAngle=azimuthAngle, tiltAngle=tiltAngle,
            shadingElevation=list(shadingElevation), shadingOpacity=list(shadingOpacity))
        self.name = name
        self.albedo = albedo  # fraction (e.g. 0.18), ground reflectivity
        self.latitude = latitude  # degrees
        self.longitude = longitude  # degrees
        self.cellsMaxPower = cellsMaxPower  # W
        self.cellsArea = cellsArea  # m²
        self.cellsEfficiency = cellsEfficiency / 100.0  # fraction (e.g. 0.21)
        self.cellsTempCoeff = cellsTempCoeff / 100.0  # fraction per °C (e.g. -0.004)
        self.cellsCoolingFactor = cellsCoolingFactor  # °C per W/m², see calcCellTemperature
        self.diffuseEfficiency = diffuseEfficiency / 100.0  # fraction (e.g. 0.85)
        self.azimuthAngle = azimuthAngle  # degrees, 0 = North, 90 = East
        self.tiltAngle = tiltAngle  # degrees from horizontal
        self.shadingElevation = np.asarray(shadingElevation, dtype=float)  # elevation threshold per 10° azimuth bin
        self.shadingOpacity = np.asarray(shadingOpacity, dtype=float)  # opacity (0–100) per 10° azimuth bin
        self.beamMode = beamMode

        self.normalPanel = panelNormal(azimuthAngle, tiltAngle)

    def getDcPower(self, solarPowerNormal, solarPowerDiffuse, shortwaveRadiation, epochTimeSeconds, ambientTemperature,
                   intervalSeconds=3600):
        # Inputs:
        # solarPowerNormal: W/m², direct irradiance normal to sun
        # solarPowerDiffuse: W/m², diffuse irradiance
        # shortwaveRadiation: W/m², total shortwave (used for albedo)
        # epochTimeSeconds: Unix timestamp, When you want to calculate the Energy between 9am and 10am you should give the function 9:30am
        # ambientTemperature: °C
        # intervalSeconds: length of the weather interval, 3600 for hourly or 900 for 15 min data ("substep" mode only)
        beam = np.array([self.beamFactor(epochTimeSeconds, intervalSeconds)])
        return float(self.getDcPowers(np.array([solarPowerNormal]), np.array([solarPowerDiffuse]),
                                      np.array([shortwaveRadiation]), np.array([ambientTemperature]), beam)[0])

    def getDcPowers(self, solarPowerNormal, solarPowerDiffuse, shortwaveRadiation, ambientTemperature, beamFactors):
        # Same as getDcPower for arrays of intervals; beamFactors from getBeamFactors
        efficiency = np.where(solarPowerNormal > 0, beamFactors, 0.0)

        # Calculate reflected radiation — flat plate equivalent
        tiltRad = math.radians(self.tiltAngle)
        reflected = shortwaveRadiation * (0.5 - 0.5 * math.cos(tiltRad)) * self.albedo

        # Total irradiance on cell (W/m²)
        totalIrradianceOnCell = (
            solarPowerNormal * efficiency +
            solarPowerDiffuse * self.diffuseEfficiency +
            reflected
        )

        cellTemperature = self.calcCellTemperature(ambientTemperature, totalIrradianceOnCell, self.cellsCoolingFactor)

        # Calculate DC power (W)
        if self.cellsEfficiency != 0 and self.cellsArea != 0:
            return totalIrradianceOnCell * (1 + (cellTemperature - 25) * self.cellsTempCoeff) * self.cellsEfficiency * self.cellsArea
        #assume cellMaxPower is defined at 1000W/sqm
        return totalIrradianceOnCell / 1000 * (1 + (cellTemperature - 25) * self.cellsTempCoeff) * self.cellsMaxPower

    def beamFactor(self, epochTimeSeconds, intervalSeconds=3600):
        # Share of the direct normal irradiance that reaches the panel during the interval
        # around epochTimeSeconds (cosine of the angle of incidence, including shading).
        epochs = stepEpochs([epochTimeSeconds], intervalSeconds, self.beamMode)
        solarAzimuth, solarElevation = solarPositions(self.latitude, self.longitude, epochs)
        return float(self.getBeamFactors(solarAzimuth, solarElevation)[0])

    def getBeamFactors(self, solarAzimuth, solarElevation, beamMode=None):
        # beamFactor for many intervals at once. solarAzimuth/solarElevation have one row per
        # interval, laid out as by stepEpochs (column 0 = middle, columns 1.. = sub-steps).
        beamMode = beamMode or self.beamMode
        numSteps = solarAzimuth.shape[1] - 1

        # Scalar product of sun direction and panel normal, 0 if sun is behind panel
        cosIncidence = np.maximum(0.0, self.sunDirection(solarAzimuth, solarElevation) @ self.normalPanel)
        shading = self.shadingFactors(solarAzimuth[:, 1:], solarElevation[:, 1:])

        if beamMode == "substep":
            return np.sum(cosIncidence[:, 1:] * shading, axis=1) / numSteps

        # app mode: angle at the middle of the hour times the averaged shading factor
        return cosIncidence[:, 0] * (np.sum(shading, axis=1) / numSteps)

    def shadingFactors(self, solarAzimuth, solarElevation):
        # Share of light passing the shading (1 = unshaded) for each sun position.
        # Shading values are provided in 10 degree ranges -> total of 36 ranges
        shadingIndex = (np.round((solarAzimuth + 5) / 10).astype(int) - 1) % 36
        shaded = self.shadingElevation[shadingIndex] > solarElevation
        return np.where(shaded, (100 - self.shadingOpacity[shadingIndex]) / 100.0, 1.0)

    @staticmethod
    def sunDirection(solarAzimuth, solarElevation):
        # Unit vectors pointing to the sun, last axis = (east, north, up)
        azimuth = np.radians(solarAzimuth)
        elevation = np.radians(solarElevation)
        return np.stack([
            np.sin(azimuth) * np.cos(elevation),
            np.cos(azimuth) * np.cos(elevation),
            np.sin(elevation)
        ], axis=-1)

    @staticmethod
    def calcCellTemperature(ambientTemperature, totalIrradiance, coolingFactor=None):
        #Ross model: https://www.researchgate.net/publication/275438802_Thermal_effects_of_the_extended_holographic_regions_for_holographic_planar_concentrator
        #coolingFactor (°C per W/m²) depends on the mounting, default "not so well cooled": 0.0342 as in solXpect
        if coolingFactor is None:
            coolingFactor = DEFAULT_COOLING_FACTOR
        return ambientTemperature + coolingFactor * totalIrradiance
