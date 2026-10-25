"""Tests for PanelArray and Inverter beyond the app-compatible reference."""
from datetime import datetime, timezone

import pytest

from calcs.Inverter import Inverter
from calcs.PanelArray import PanelArray, maxSunElevationPerBin
from tests.cases import LATITUDE, LONGITUDE, NO_SHADING, PLANTS, WEATHER

ARRAY_KEYS = ("albedo", "cellsMaxPower", "cellsArea", "cellsEfficiency", "cellsTempCoeff",
              "diffuseEfficiency", "azimuthAngle", "tiltAngle", "shadingElevation", "shadingOpacity")


def make_array(plant_name, **overrides):
    kwargs = {k: PLANTS[plant_name][k] for k in ARRAY_KEYS}
    kwargs.update(latitude=LATITUDE, longitude=LONGITUDE, **overrides)
    return PanelArray(**kwargs)


def epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def test_inverter_limits_only_when_asked():
    inverter = Inverter(inverterEfficiency=95, inverterPowerLimit=1000)
    assert inverter.getAcPower(800) == pytest.approx(760)
    assert inverter.getAcPower(2000) == 1000
    assert inverter.getAcPower(2000, limit=False) == pytest.approx(1900)


def test_unknown_beam_mode_is_rejected():
    with pytest.raises(ValueError):
        make_array("south_30", beamMode="hourly")


def test_no_direct_light_means_no_beam_part():
    # without direct irradiance both modes only see diffuse + reflected light
    app = make_array("east_60_shaded")
    substep = make_array("east_60_shaded", beamMode="substep")
    t = epoch("2026-06-21T08:30")
    assert app.getDcPower(epochTimeSeconds=t, **WEATHER["overcast"]) == pytest.approx(
        substep.getDcPower(epochTimeSeconds=t, **WEATHER["overcast"]))


def test_substep_sees_sun_that_sets_behind_the_panel_within_the_hour():
    # 2026-03-20, 17:00-18:00 UTC: the sun is low in the west and goes down
    # during the hour; "app" mode only looks at 17:30
    t = epoch("2026-03-20T17:30")
    app = make_array("south_30").beamFactor(t)
    substep = make_array("south_30", beamMode="substep").beamFactor(t)
    assert substep > app


def test_substep_is_close_to_app_and_slightly_lower_at_noon():
    # around noon the angle hardly changes within the hour; the panel faces the
    # sun best at the middle of the hour, so the hourly average is a bit lower
    t = epoch("2026-06-21T11:30")
    app = make_array("south_30").beamFactor(t)
    substep = make_array("south_30", beamMode="substep").beamFactor(t)
    assert substep == pytest.approx(app, rel=1e-2)
    assert substep < app


@pytest.mark.parametrize("hour_mid", ["2026-03-20T06:30", "2026-06-21T11:30", "2026-03-20T17:30"])
def test_four_quarter_hours_average_to_the_hour(hour_mid):
    # substep mode uses the same points in time for 60 and 15 min intervals
    array = make_array("east_60_shaded", beamMode="substep")
    t = epoch(hour_mid)
    quarters = [array.beamFactor(t + offset, intervalSeconds=900) for offset in (-1350, -450, 450, 1350)]
    assert sum(quarters) / 4 == pytest.approx(array.beamFactor(t), rel=1e-12, abs=1e-15)


def test_interval_checks():
    t = epoch("2026-06-21T11:30")
    with pytest.raises(ValueError):
        make_array("south_30").beamFactor(t, intervalSeconds=900)  # app mode is hourly only
    with pytest.raises(ValueError):
        make_array("south_30", beamMode="substep").beamFactor(t, intervalSeconds=1000)


def test_better_cooling_gives_more_power_and_default_is_unchanged():
    t = epoch("2026-06-21T11:30")
    sunny = WEATHER["sunny"]
    default = make_array("south_30").getDcPower(epochTimeSeconds=t, **sunny)
    explicit = make_array("south_30", cellsCoolingFactor=0.0342).getDcPower(epochTimeSeconds=t, **sunny)
    free_standing = make_array("south_30", cellsCoolingFactor=0.0208).getDcPower(epochTimeSeconds=t, **sunny)
    assert default == explicit
    assert free_standing > default            # negative temperature coefficient: cooler cells, more power


def test_rated_power_or_area_and_efficiency():
    base = {k: PLANTS["south_30"][k] for k in ARRAY_KEYS if not k.startswith(("cellsMaxPower", "cellsArea", "cellsEfficiency"))}
    t = epoch("2026-06-21T11:30")
    sunny = WEATHER["sunny"]
    by_power = PanelArray(cellsMaxPower=4500, latitude=LATITUDE, longitude=LONGITUDE, **base)
    by_area = PanelArray(cellsArea=20, cellsEfficiency=22.5, latitude=LATITUDE, longitude=LONGITUDE, **base)
    # 20 m² x 22.5 % = 4500 W at 1000 W/m², so both describe the same panels
    assert by_power.getDcPower(epochTimeSeconds=t, **sunny) == pytest.approx(
        by_area.getDcPower(epochTimeSeconds=t, **sunny))
    with pytest.raises(ValueError):
        PanelArray(cellsArea=20, **base)       # efficiency missing, no rated power


def test_contradicting_size_uses_area_and_warns(caplog):
    base = {k: PLANTS["south_30"][k] for k in ARRAY_KEYS if not k.startswith(("cellsMaxPower", "cellsArea", "cellsEfficiency"))}
    t = epoch("2026-06-21T11:30")
    sunny = WEATHER["sunny"]
    with caplog.at_level("WARNING"):
        consistent = PanelArray(name="ok", cellsMaxPower=4500, cellsArea=20, cellsEfficiency=22.5,
                                latitude=LATITUDE, longitude=LONGITUDE, **base)
    assert not caplog.records
    with caplog.at_level("WARNING"):
        conflict = PanelArray(name="roof", cellsMaxPower=1000, cellsArea=20, cellsEfficiency=22.5,
                              latitude=LATITUDE, longitude=LONGITUDE, **base)
    assert "roof" in caplog.text and "1000 W is ignored" in caplog.text
    assert conflict.getDcPower(epochTimeSeconds=t, **sunny) == pytest.approx(
        consistent.getDcPower(epochTimeSeconds=t, **sunny))


def test_max_sun_elevation_per_bin_for_a_vertical_south_facade():
    highest = maxSunElevationPerBin(53.6, 171, 90)
    # panel faces 171°: the sun can only reach it from 81° to 261°
    assert all(v is None for v in highest[:8] + highest[27:])
    assert all(v is not None for v in highest[9:26])
    # noon sun at the summer solstice: 90 - 53.6 + 23.44
    assert highest[17] == pytest.approx(59.84, abs=0.3)
    assert highest[9] < highest[13] < highest[17]


def test_max_sun_elevation_per_bin_for_tilted_and_southern_panels():
    tilted = maxSunElevationPerBin(53.6, 180, 30)
    # in summer the sun rises in the north-east, but behind a south facing 30° panel
    assert tilted[4] is None and tilted[6] is not None
    # in the southern hemisphere the sun stands in the north
    sydney = maxSunElevationPerBin(-33.9, 0, 30)
    assert sydney[0] > 75 and sydney[18] is None


def test_full_shading_blocks_beam_in_both_modes():
    full = [90] * 36
    opaque = [100] * 36
    t = epoch("2026-06-21T11:30")
    for mode in ("app", "substep"):
        array = make_array("south_30", beamMode=mode, shadingElevation=full, shadingOpacity=opaque)
        assert array.beamFactor(t) == 0
    assert make_array("south_30", shadingElevation=NO_SHADING).beamFactor(t) > 0
