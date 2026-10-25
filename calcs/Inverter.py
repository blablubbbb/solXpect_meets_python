import numpy as np


class Inverter:
    # Converts the summed DC power of its panel arrays to AC power.
    def __init__(self, inverterEfficiency, inverterPowerLimit, name="", arrays=()):
        self.name = name
        self.inverterEfficiency = inverterEfficiency / 100.0  # fraction (e.g. 0.96)
        self.inverterPowerLimit = inverterPowerLimit  # W, AC output limit
        self.arrays = list(arrays)  # PanelArray objects connected to this inverter (used by Site)
        # settings as given (units as in solXpect), for saving
        self.settings = dict(name=name, inverterEfficiency=inverterEfficiency,
                             inverterPowerLimit=inverterPowerLimit)

    def getAcPower(self, dcPower, limit=True):
        # dcPower: W, sum of all panel arrays connected to this inverter
        # limit: False skips the power limit (solXpect's central inverter, limited on system level)
        acPower = dcPower * self.inverterEfficiency
        if limit:
            acPower = min(acPower, self.inverterPowerLimit)
        return float(acPower)

    def getAcPowers(self, dcPowers):
        # getAcPower (with limit) for an array of intervals
        return np.minimum(dcPowers * self.inverterEfficiency, self.inverterPowerLimit)
