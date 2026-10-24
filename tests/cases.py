"""Fixed test cases shared by the reference generator and the tests.

Location and plants are made up (not a real installation). Weather is
synthetic and constant, so the results only depend on the model code.
"""
from datetime import datetime, timedelta, timezone

LATITUDE = 50.0
LONGITUDE = 8.0

NO_SHADING = [0] * 36


def _shading(bins, elevation, opacity):
    elev = [0] * 36
    opac = [0] * 36
    for b in bins:
        elev[b] = elevation
        opac[b] = opacity
    return elev, opac


_east_elev, _east_opac = _shading(range(6, 12), 20, 80)     # obstacle 60-120 deg
_west_elev, _west_opac = _shading(range(24, 30), 35, 100)   # obstacle 240-300 deg

PLANTS = {
    # rated power path (cellsArea = 0), central inverter
    "south_30": dict(
        albedo=0.18, cellsMaxPower=6000, cellsArea=0, cellsEfficiency=0,
        cellsTempCoeff=-0.4, diffuseEfficiency=93, inverterPowerLimit=8000,
        inverterEfficiency=97, isCentralInverter=True, azimuthAngle=180,
        tiltAngle=30, shadingElevation=NO_SHADING, shadingOpacity=NO_SHADING),
    # area/efficiency path, steep east facing, partly shaded
    "east_60_shaded": dict(
        albedo=0.25, cellsMaxPower=0, cellsArea=12, cellsEfficiency=21,
        cellsTempCoeff=-0.35, diffuseEfficiency=75, inverterPowerLimit=5000,
        inverterEfficiency=96, isCentralInverter=True, azimuthAngle=90,
        tiltAngle=60, shadingElevation=_east_elev, shadingOpacity=_east_opac),
    # own inverter with a low limit, so clipping happens
    "west_15_clipped": dict(
        albedo=0.18, cellsMaxPower=2400, cellsArea=0, cellsEfficiency=0,
        cellsTempCoeff=-0.3, diffuseEfficiency=97, inverterPowerLimit=1200,
        inverterEfficiency=95, isCentralInverter=False, azimuthAngle=270,
        tiltAngle=15, shadingElevation=_west_elev, shadingOpacity=_west_opac),
    # vertical, north-east facing wall
    "wall_45_90": dict(
        albedo=0.5, cellsMaxPower=800, cellsArea=0, cellsEfficiency=0,
        cellsTempCoeff=-0.4, diffuseEfficiency=50, inverterPowerLimit=600,
        inverterEfficiency=94, isCentralInverter=False, azimuthAngle=45,
        tiltAngle=90, shadingElevation=NO_SHADING, shadingOpacity=NO_SHADING),
}

WEATHER = {
    "sunny": dict(solarPowerNormal=700.0, solarPowerDiffuse=120.0,
                  shortwaveRadiation=600.0, ambientTemperature=25.0),
    "overcast": dict(solarPowerNormal=0.0, solarPowerDiffuse=150.0,
                     shortwaveRadiation=150.0, ambientTemperature=5.0),
}

DAYS = ["2026-03-20", "2026-06-21", "2026-12-21"]


def hour_midpoints(day):
    """The 24 hour midpoints (UTC, epoch seconds) of a day, as getPower expects."""
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return [int((start + timedelta(hours=h, minutes=30)).timestamp()) for h in range(24)]


def plant_kwargs(name):
    return dict(PLANTS[name], latitude=LATITUDE, longitude=LONGITUDE)


def case_key(plant, weather, epoch):
    return f"{plant}|{weather}|{epoch}"
