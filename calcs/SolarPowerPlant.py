import math

from .Inverter import Inverter
from .PanelArray import PanelArray

class SolarPowerPlant:
        #Class should reproduce the java class by the same name in solXpect:
        #https://github.com/woheller69/solxpect/blob/main/app/src/main/java/org/woheller69/weather/SolarPowerPlant.java
        #Only significant difference is the library which is used to calculate the solar position
        #One panel array with its own inverter; the calculation is done by PanelArray and Inverter.
    def __init__(self, albedo, latitude, longitude, cellsMaxPower, cellsArea, cellsEfficiency,
                 cellsTempCoeff, diffuseEfficiency, inverterPowerLimit, inverterEfficiency,
                 isCentralInverter, azimuthAngle, tiltAngle, shadingElevation, shadingOpacity,
                 beamMode="app"):
        self.latitude = latitude  # degrees
        self.longitude = longitude  # degrees
        self.isCentralInverter = isCentralInverter  # boolean
        self.panelArray = PanelArray(
            albedo=albedo, latitude=latitude, longitude=longitude,
            cellsMaxPower=cellsMaxPower, cellsArea=cellsArea, cellsEfficiency=cellsEfficiency,
            cellsTempCoeff=cellsTempCoeff, diffuseEfficiency=diffuseEfficiency,
            azimuthAngle=azimuthAngle, tiltAngle=tiltAngle,
            shadingElevation=shadingElevation, shadingOpacity=shadingOpacity,
            beamMode=beamMode)
        self.inverter = Inverter(inverterEfficiency=inverterEfficiency, inverterPowerLimit=inverterPowerLimit)

    def getPower(self, solarPowerNormal, solarPowerDiffuse, shortwaveRadiation, epochTimeSeconds, ambientTemperature):
        # Inputs: see PanelArray.getDcPower
        dcPower = self.panelArray.getDcPower(solarPowerNormal, solarPowerDiffuse, shortwaveRadiation,
                                             epochTimeSeconds, ambientTemperature)
        # Convert to AC power (W), no clipping for central inverter
        return self.inverter.getAcPower(dcPower, limit=not self.isCentralInverter)

    @staticmethod
    def calcDiffuseEfficiency(tilt):
        # Returns % efficiency for diffuse light based on tilt angle
        return int(50 + 50 * math.cos(math.radians(tilt)))

    calcCellTemperature = staticmethod(PanelArray.calcCellTemperature)
