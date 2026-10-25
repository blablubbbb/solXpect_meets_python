"""Tests for PanelArray and Inverter beyond the app-compatible reference."""
from datetime import datetime, timezone

import pytest

from calcs.Inverter import Inverter
from calcs.PanelArray import PanelArray
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


def test_full_shading_blocks_beam_in_both_modes():
    full = [90] * 36
    opaque = [100] * 36
    t = epoch("2026-06-21T11:30")
    for mode in ("app", "substep"):
        array = make_array("south_30", beamMode=mode, shadingElevation=full, shadingOpacity=opaque)
        assert array.beamFactor(t) == 0
    assert make_array("south_30", shadingElevation=NO_SHADING).beamFactor(t) > 0
