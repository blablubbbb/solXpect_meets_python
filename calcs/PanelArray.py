import math
import numpy as np
import pandas as pd
import pvlib

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


class PanelArray:
    # One group of identical panels with the same orientation (e.g. one string).
    # Computes the DC power; the inverter is handled by the Inverter class.
    def __init__(self, albedo, latitude, longitude, cellsMaxPower, cellsArea, cellsEfficiency,
                 cellsTempCoeff, diffuseEfficiency, azimuthAngle, tiltAngle,
                 shadingElevation, shadingOpacity, beamMode="app"):
        if beamMode not in BEAM_MODES:
            raise ValueError(f"beamMode must be one of {BEAM_MODES}, not {beamMode!r}")
        self.albedo = albedo  # fraction (e.g. 0.18), ground reflectivity
        self.latitude = latitude  # degrees
        self.longitude = longitude  # degrees
        self.cellsMaxPower = cellsMaxPower  # W
        self.cellsArea = cellsArea  # m²
        self.cellsEfficiency = cellsEfficiency / 100.0  # fraction (e.g. 0.21)
        self.cellsTempCoeff = cellsTempCoeff / 100.0  # fraction per °C (e.g. -0.004)
        self.diffuseEfficiency = diffuseEfficiency / 100.0  # fraction (e.g. 0.85)
        self.azimuthAngle = azimuthAngle  # degrees, 0 = North, 90 = East
        self.tiltAngle = tiltAngle  # degrees from horizontal
        self.shadingElevation = np.asarray(shadingElevation, dtype=float)  # elevation threshold per 10° azimuth bin
        self.shadingOpacity = np.asarray(shadingOpacity, dtype=float)  # opacity (0–100) per 10° azimuth bin
        self.beamMode = beamMode

        # Panel normal vector
        self.normalPanel = np.array([
            math.sin(math.radians(azimuthAngle)) * math.cos(math.radians(90 - tiltAngle)),
            math.cos(math.radians(azimuthAngle)) * math.cos(math.radians(90 - tiltAngle)),
            math.sin(math.radians(90 - tiltAngle))
        ])

    def getDcPower(self, solarPowerNormal, solarPowerDiffuse, shortwaveRadiation, epochTimeSeconds, ambientTemperature,
                   intervalSeconds=3600):
        # Inputs:
        # solarPowerNormal: W/m², direct irradiance normal to sun
        # solarPowerDiffuse: W/m², diffuse irradiance
        # shortwaveRadiation: W/m², total shortwave (used for albedo)
        # epochTimeSeconds: Unix timestamp, When you want to calculate the Energy between 9am and 10am you should give the function 9:30am
        # ambientTemperature: °C
        # intervalSeconds: length of the weather interval, 3600 for hourly or 900 for 15 min data ("substep" mode only)
        efficiency = 0.0
        if solarPowerNormal > 0:
            efficiency = self.beamFactor(epochTimeSeconds, intervalSeconds)

        # Calculate reflected radiation — flat plate equivalent
        tiltRad = math.radians(self.tiltAngle)
        reflected = shortwaveRadiation * (0.5 - 0.5 * math.cos(tiltRad)) * self.albedo

        # Total irradiance on cell (W/m²)
        totalIrradianceOnCell = (
            solarPowerNormal * efficiency +
            solarPowerDiffuse * self.diffuseEfficiency +
            reflected
        )

        cellTemperature = self.calcCellTemperature(ambientTemperature, totalIrradianceOnCell)

        # Calculate DC power (W)
        if self.cellsEfficiency != 0 and self.cellsArea != 0:
            dcPower = totalIrradianceOnCell * (1 + (cellTemperature - 25) * self.cellsTempCoeff) * self.cellsEfficiency * self.cellsArea
        else: #assume cellMaxPower is defined at 1000W/sqm
            dcPower = totalIrradianceOnCell / 1000 * (1 + (cellTemperature - 25) * self.cellsTempCoeff) * self.cellsMaxPower

        return float(dcPower)

    def beamFactor(self, epochTimeSeconds, intervalSeconds=3600):
        # Share of the direct normal irradiance that reaches the panel during the interval
        # around epochTimeSeconds (cosine of the angle of incidence, including shading).
        if self.beamMode == "app":
            if intervalSeconds != 3600:
                raise ValueError("beamMode 'app' only supports hourly intervals")
            numSteps = APP_STEPS
        else:
            if intervalSeconds % SUBSTEP_SECONDS:
                raise ValueError(f"intervalSeconds must be a multiple of {SUBSTEP_SECONDS}")
            numSteps = intervalSeconds // SUBSTEP_SECONDS
        interval = intervalSeconds // numSteps  # seconds
        stepEpochs = [epochTimeSeconds - ((numSteps - 1) * interval // 2) + j * interval for j in range(numSteps)]

        # One pvlib call for the middle of the hour and all sub-steps
        times = pd.to_datetime([epochTimeSeconds] + stepEpochs, unit="s", utc=True)
        solarPosition = pvlib.solarposition.get_solarposition(times, self.latitude, self.longitude)
        solarAzimuth = solarPosition["azimuth"].to_numpy()  # degrees
        solarElevation = solarPosition["elevation"].to_numpy()  # degrees

        # Scalar product of sun direction and panel normal, 0 if sun is behind panel
        cosIncidence = np.maximum(0.0, self.sunDirection(solarAzimuth, solarElevation) @ self.normalPanel)
        shading = self.shadingFactors(solarAzimuth[1:], solarElevation[1:])

        if self.beamMode == "substep":
            return float(np.sum(cosIncidence[1:] * shading) / numSteps)

        efficiency = cosIncidence[0]
        if efficiency > 0:
            efficiency *= np.sum(shading) / numSteps  # apply shading factor
        return float(efficiency)

    def shadingFactors(self, solarAzimuth, solarElevation):
        # Share of light passing the shading (1 = unshaded) for each sun position.
        # Shading values are provided in 10 degree ranges -> total of 36 ranges
        shadingIndex = (np.round((solarAzimuth + 5) / 10).astype(int) - 1) % 36
        shaded = self.shadingElevation[shadingIndex] > solarElevation
        return np.where(shaded, (100 - self.shadingOpacity[shadingIndex]) / 100.0, 1.0)

    @staticmethod
    def sunDirection(solarAzimuth, solarElevation):
        # Unit vectors pointing to the sun, one row per sun position
        azimuth = np.radians(solarAzimuth)
        elevation = np.radians(solarElevation)
        return np.column_stack([
            np.sin(azimuth) * np.cos(elevation),
            np.cos(azimuth) * np.cos(elevation),
            np.sin(elevation)
        ])

    @staticmethod
    def calcCellTemperature(ambientTemperature, totalIrradiance):
        #Ross model: https://www.researchgate.net/publication/275438802_Thermal_effects_of_the_extended_holographic_regions_for_holographic_planar_concentrator
        #assuming "not so well cooled" : 0.0342, implementation matches solXpect
        return ambientTemperature + 0.0342 * totalIrradiance
