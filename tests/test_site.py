"""Tests for Site (several inverters with several arrays) and the app import."""
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from calcs.Inverter import Inverter
from calcs.PanelArray import PanelArray
from calcs.Site import Site
from calcs.SolarPowerPlant import SolarPowerPlant
from calcs.app_import import CENTRAL_INVERTER_NAME, sites_from_app_backup
from calcs import forecast
from tests.cases import DAYS, LATITUDE, LONGITUDE, NO_SHADING, PLANTS, WEATHER, plant_kwargs

ARRAY_KEYS = ("albedo", "cellsMaxPower", "cellsArea", "cellsEfficiency", "cellsTempCoeff",
              "diffuseEfficiency", "azimuthAngle", "tiltAngle", "shadingElevation", "shadingOpacity")


def array(plant_name, name=None, **overrides):
    kwargs = {k: PLANTS[plant_name][k] for k in ARRAY_KEYS}
    kwargs.update(name=name or plant_name, **overrides)
    return PanelArray(**kwargs)


def inverter_for(plant_name, arrays, **overrides):
    p = PLANTS[plant_name]
    kwargs = dict(name=plant_name, inverterEfficiency=p["inverterEfficiency"],
                  inverterPowerLimit=p["inverterPowerLimit"], arrays=arrays)
    kwargs.update(overrides)
    return Inverter(**kwargs)


def constant_weather(day, weather_name, intervalSeconds=3600):
    # one row per interval of the day; "time" is the end of the interval
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    steps = 86400 // intervalSeconds
    times = [start + timedelta(seconds=intervalSeconds * (i + 1)) for i in range(steps)]
    w = WEATHER[weather_name]
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "direct_normal_irradiance": w["solarPowerNormal"],
        "diffuse_radiation": w["solarPowerDiffuse"],
        "shortwave_radiation": w["shortwaveRadiation"],
        "temperature_2m": w["ambientTemperature"],
    })


@pytest.mark.parametrize("plant_name", PLANTS)
def test_single_array_site_matches_solar_power_plant(plant_name):
    # a site with one inverter and one array is the app's plant with its own inverter
    site = Site(LATITUDE, LONGITUDE, [inverter_for(plant_name, [array(plant_name)])], beamMode="app")
    plant = SolarPowerPlant(**dict(plant_kwargs(plant_name), isCentralInverter=False))
    for weather_name in WEATHER:
        for day in DAYS:
            result = site.calculate(constant_weather(day, weather_name)).to_dataframe()
            for end, ac in result["total"].items():
                mid = int(end.timestamp()) - 1800
                expected = plant.getPower(epochTimeSeconds=mid, **WEATHER[weather_name])
                assert ac == pytest.approx(expected, rel=1e-9, abs=1e-9), (weather_name, end)


def mixed_site(beamMode="substep"):
    # two strings on one inverter with a low limit, plus a micro inverter with its own limit
    deye = inverter_for("south_30", [array("south_30", "South"), array("east_60_shaded", "East")],
                        name="Deye", inverterPowerLimit=4500)
    micro = inverter_for("wall_45_90", [array("wall_45_90", "Balcony")], name="Micro")
    return Site(LATITUDE, LONGITUDE, [deye, micro], name="Home", beamMode=beamMode)


def test_inverter_limits_the_sum_of_its_arrays_only():
    site = mixed_site()
    result = site.calculate(constant_weather("2026-06-21", "sunny")).to_dataframe()
    assert list(result.columns) == ["Deye/South", "Deye/East", "Deye", "Micro/Balcony", "Micro", "total"]

    deye_ac = (result["Deye/South"] + result["Deye/East"]) * 0.97
    assert (result["Deye"] == deye_ac.clip(upper=4500)).all()
    assert (result["Deye"] == 4500).any()                       # the shared limit is reached ...
    assert (result["Deye"] < 4500).any()
    assert (result["Micro"] == (result["Micro/Balcony"] * 0.94).clip(upper=600)).all()
    assert (result["Micro"] > 0).all()                           # ... without cutting the micro inverter
    assert (result["total"] == result["Deye"] + result["Micro"]).all()


def test_quarter_hour_weather_is_supported():
    site = mixed_site()
    result = site.calculate(constant_weather("2026-06-21", "sunny", 900), intervalSeconds=900)
    assert len(result) == 96
    with pytest.raises(ValueError):
        mixed_site("app").calculate(constant_weather("2026-06-21", "sunny", 900), intervalSeconds=900)


def test_save_and_load_give_the_same_results(tmp_path):
    site = mixed_site()
    site.save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Deye.json", "Micro.json", "site.json"]
    loaded = Site.load(tmp_path)
    weather = constant_weather("2026-03-20", "sunny")
    pd.testing.assert_frame_equal(loaded.calculate(weather).to_dataframe(), site.calculate(weather).to_dataframe(), check_like=True)


def test_inverter_names_must_be_unique():
    with pytest.raises(ValueError):
        Site(LATITUDE, LONGITUDE, [Inverter(96, 1000, name="A"), Inverter(96, 1000, name="A")])
    with pytest.raises(ValueError):
        Site(LATITUDE, LONGITUDE, [Inverter(96, 1000, name="total")])


def test_forecast_fetches_quarter_hours_from_the_historical_api(monkeypatch):
    captured = {}
    times = pd.date_range("2026-06-21T00:15", "2026-06-22T00:00", freq="15min", tz="UTC")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"minutely_15": {
                "time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                "direct_normal_irradiance": [700.0] * len(times),
                "diffuse_radiation": [120.0] * len(times),
                "shortwave_radiation": [600.0] * len(times),
                "temperature_2m": [25.0] * len(times)}}

    def fake_get(url, params=None, **kwargs):
        captured.update(params, url=url)
        return Response()

    monkeypatch.setattr(forecast.requests, "get", fake_get)
    start = datetime(2026, 6, 21, tzinfo=timezone.utc)
    result = mixed_site().forecast(start, start + timedelta(days=1), intervalSeconds=900, historical=True)

    assert captured["url"] == forecast.HISTORICAL_FORECAST_URL
    assert captured["start_minutely_15"] == "2026-06-21T00:15"   # first interval ends 15 min after start
    assert captured["end_minutely_15"] == "2026-06-22T00:00"
    assert len(result) == 96


# ----------------------------------------------------------------------
# App import
# ----------------------------------------------------------------------

APP_COLUMNS = ["cities_to_watch_id", "city_id", "rank", "city_name", "longitude", "latitude",
               "cells_max_pPower", "cells_area", "cells_efficiency", "diffuse_efficiency",
               "inverter_power_limit", "inverter_efficiency", "azimuth_angle", "tilt_angle",
               "shading_elevation", "shading_opacity", "cells_temp_coeff", "albedo", "is_central_inverter"]


def app_row(rank, name, central, limit, latitude=LATITUDE, azimuth=180, efficiency=97):
    shading = ",".join("0" for _ in range(36))
    return (rank, rank, rank, name, LONGITUDE, latitude, 3000, 0, 0, 93, limit, efficiency,
            azimuth, 30, shading, shading, -0.4, 0.18, int(central))


def make_app_backup(path, rows):
    db_path = path / "SQLITE.db"
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE CITIES_TO_WATCH ({', '.join(APP_COLUMNS)})")
    conn.executemany(f"INSERT INTO CITIES_TO_WATCH VALUES ({', '.join('?' * len(APP_COLUMNS))})", rows)
    conn.commit()
    conn.close()
    zip_path = path / "solXpect.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(db_path, "org.woheller69.solxpect/databases/SQLITE.db")
    return zip_path


def test_app_import_groups_plants_by_location_and_inverter(tmp_path):
    zip_path = make_app_backup(tmp_path, [
        app_row(1, "Roof", central=True, limit=4000, azimuth=90),
        app_row(2, "Roof", central=True, limit=4000, azimuth=270),   # same name, shared inverter
        app_row(3, "Balcony", central=False, limit=600),
        app_row(4, "Garden house", central=False, limit=800, latitude=LATITUDE + 0.1),
    ])
    home, garden = sites_from_app_backup(zip_path)

    assert home.name == "Roof" and home.beamMode == "app"
    shared, balcony = home.inverters
    assert shared.name == CENTRAL_INVERTER_NAME
    assert shared.inverterPowerLimit == 8000                        # sum of the central limits
    assert [a.name for a in shared.arrays] == ["Roof", "Roof 2"]
    assert [a.azimuthAngle for a in shared.arrays] == [90, 270]
    assert (balcony.name, balcony.inverterPowerLimit) == ("Balcony", 600)

    assert garden.latitude == pytest.approx(LATITUDE + 0.1)
    assert [inv.name for inv in garden.inverters] == ["Garden house"]

    # the imported site can be saved and calculated
    home.save(tmp_path / "home")
    assert not Site.load(tmp_path / "home").calculate(constant_weather("2026-06-21", "sunny")).to_dataframe().empty


def test_app_import_can_select_plants_and_keep_them_separate(tmp_path):
    # variants of one installation: same location, all "central"
    zip_path = make_app_backup(tmp_path, [
        app_row(1, "Vertical ", central=True, limit=8000),
        app_row(2, "Horizontal", central=True, limit=8000),
        app_row(3, "Test 30 deg", central=True, limit=8000),
    ])
    (vertical,) = sites_from_app_backup(zip_path, select=["Vertical"])
    assert vertical.name == "Vertical"                               # trailing space removed
    assert [i.inverterPowerLimit for i in vertical.inverters] == [8000]

    separate = sites_from_app_backup(zip_path, select=[1, 2], combine=False)
    assert [s.name for s in separate] == ["Vertical", "Horizontal"]
    assert all(len(s.inverters) == 1 and s.inverters[0].inverterPowerLimit == 8000 for s in separate)

    with pytest.raises(ValueError):
        sites_from_app_backup(zip_path, select=["Missing"])


def test_app_import_cleans_up_32_bit_float_noise(tmp_path):
    row = list(app_row(1, "Roof", central=False, limit=8000))
    row[APP_COLUMNS.index("cells_efficiency")] = 22.530000686645508
    row[APP_COLUMNS.index("azimuth_angle")] = 161.2550048828125
    (site,) = sites_from_app_backup(make_app_backup(tmp_path, [tuple(row)]))
    settings = site.inverters[0].arrays[0].settings
    assert (settings["cellsEfficiency"], settings["azimuthAngle"]) == (22.53, 161.255)
