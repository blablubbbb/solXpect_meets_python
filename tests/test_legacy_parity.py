"""SolarPowerPlant.getPower must keep reproducing the recorded reference results."""
import json
from pathlib import Path

import pytest

from calcs.SolarPowerPlant import SolarPowerPlant
from tests.cases import DAYS, PLANTS, WEATHER, case_key, hour_midpoints, plant_kwargs

REFERENCE = json.loads(Path(__file__).with_name("reference_legacy.json").read_text())


@pytest.mark.parametrize("plant_name", PLANTS)
@pytest.mark.parametrize("weather_name", WEATHER)
def test_get_power_matches_reference(plant_name, weather_name):
    plant = SolarPowerPlant(**plant_kwargs(plant_name))
    for day in DAYS:
        for epoch in hour_midpoints(day):
            power = plant.getPower(epochTimeSeconds=epoch, **WEATHER[weather_name])
            expected = REFERENCE[case_key(plant_name, weather_name, epoch)]
            assert power == pytest.approx(expected, rel=1e-9, abs=1e-9), (day, epoch)
