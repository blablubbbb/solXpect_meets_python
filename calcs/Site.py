import json
import re
from datetime import timedelta
from pathlib import Path

import numpy as np

from .Inverter import Inverter
from .PanelArray import PanelArray, solarPositions, stepEpochs
from .forecast import fetch_open_meteo_data

SITE_FILE = "site.json"


class SiteResult:
    # Result of Site.calculate: mean power (W) per interval.
    #   times:   end of each interval, Unix timestamps (seconds, UTC)
    #   columns: "<inverter>/<array>" (DC), "<inverter>" (AC), "total" (AC) -> numpy arrays
    def __init__(self, times, columns):
        self.times = times
        self.columns = columns

    def __getitem__(self, name):
        return self.columns[name]

    def __len__(self):
        return len(self.times)

    def to_dataframe(self):
        # The same as a pandas DataFrame indexed by the interval end (needs pandas)
        import pandas as pd
        return pd.DataFrame(self.columns, index=pd.to_datetime(self.times, unit="s", utc=True))


def _epochSeconds(times):
    # Interval ends as Unix seconds; accepts Unix seconds, numpy datetime64 or datetime objects
    times = np.asarray(times)
    if times.dtype.kind in "iuf":
        return times.astype(np.int64)
    if times.dtype.kind == "M":
        return times.astype("datetime64[s]").astype(np.int64)
    return np.array([int(t.timestamp()) for t in times], dtype=np.int64)


class Site:
    # One location with one or more inverters, each with one or more panel arrays.
    # The weather and the sun position are calculated once for all arrays.
    def __init__(self, latitude, longitude, inverters, name="", beamMode="substep"):
        self.name = name
        self.latitude = latitude  # degrees
        self.longitude = longitude  # degrees
        self.inverters = list(inverters)
        self.beamMode = beamMode  # see PanelArray.BEAM_MODES
        names = [inv.name for inv in self.inverters]
        if len(set(names)) != len(names):
            raise ValueError(f"inverter names must be unique: {names}")
        fileNames = [_fileName(n) for n in names]
        if len(set(fileNames)) != len(fileNames) or SITE_FILE[:-5] in fileNames:
            raise ValueError(f"inverter names must give unique file names: {names}")
        if "total" in names:
            raise ValueError("'total' can't be used as inverter name")
        for inv in self.inverters:
            arrayNames = [arr.name for arr in inv.arrays]
            if len(set(arrayNames)) != len(arrayNames):
                raise ValueError(f"array names of inverter {inv.name!r} must be unique: {arrayNames}")

    def calculate(self, weather, intervalSeconds=3600):
        # weather: as from fetch_open_meteo_data ("time" = end of interval, UTC); a pandas
        # DataFrame with the same columns works too.
        # Returns a SiteResult with the mean power (W) over each interval:
        #   "<inverter>/<array>"  DC power of each array
        #   "<inverter>"          AC power of each inverter (efficiency and limit applied to the summed DC)
        #   "total"               AC power of the whole site
        times = _epochSeconds(weather["time"])
        midEpochs = times - intervalSeconds // 2
        epochs = stepEpochs(midEpochs, intervalSeconds, self.beamMode)
        solarAzimuth, solarElevation = solarPositions(self.latitude, self.longitude, epochs)

        solarPowerNormal = np.asarray(weather["direct_normal_irradiance"], dtype=float)
        solarPowerDiffuse = np.asarray(weather["diffuse_radiation"], dtype=float)
        shortwaveRadiation = np.asarray(weather["shortwave_radiation"], dtype=float)
        ambientTemperature = np.asarray(weather["temperature_2m"], dtype=float)

        columns = {}
        total = np.zeros(len(times))
        for inv in self.inverters:
            dcSum = np.zeros(len(times))
            for arr in inv.arrays:
                beam = arr.getBeamFactors(solarAzimuth, solarElevation, self.beamMode)
                dc = arr.getDcPowers(solarPowerNormal, solarPowerDiffuse, shortwaveRadiation, ambientTemperature, beam)
                columns[f"{inv.name}/{arr.name}"] = dc
                dcSum = dcSum + dc
            ac = inv.getAcPowers(dcSum)
            columns[inv.name] = ac
            total = total + ac
        columns["total"] = total
        return SiteResult(times, columns)

    def forecast(self, start_dt, end_dt, intervalSeconds=3600, historical=False):
        # Fetch the weather for start_dt..end_dt (UTC) and calculate the site's power for it
        weather = fetch_open_meteo_data(self.latitude, self.longitude,
                                        start_dt + timedelta(seconds=intervalSeconds), end_dt,
                                        intervalSeconds=intervalSeconds, historical=historical)
        return self.calculate(weather, intervalSeconds)

    # ------------------------------------------------------------------
    # Settings files: <folder>/site.json plus one <inverter>.json per inverter
    # ------------------------------------------------------------------

    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        site = dict(name=self.name, latitude=self.latitude, longitude=self.longitude, beamMode=self.beamMode)
        (folder / SITE_FILE).write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
        for inv in self.inverters:
            data = dict(inv.settings, arrays=[arr.settings for arr in inv.arrays])
            (folder / f"{_fileName(inv.name)}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        site = json.loads((folder / SITE_FILE).read_text(encoding="utf-8"))
        inverters = []
        for path in sorted(folder.glob("*.json")):
            if path.name == SITE_FILE:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            arrays = [PanelArray(**arr) for arr in data.pop("arrays")]
            inverters.append(Inverter(arrays=arrays, **data))
        return cls(inverters=inverters, **site)


def _fileName(name):
    # inverter name -> safe file name
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "inverter"
