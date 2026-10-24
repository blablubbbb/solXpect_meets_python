"""Write tests/reference_legacy.json from the current SolarPowerPlant.getPower.

Run from the repo root: python -m tests.make_reference
Only rerun this on purpose, when the legacy (app-compatible) results are
meant to change.
"""
import json
from pathlib import Path

from calcs.SolarPowerPlant import SolarPowerPlant
from tests.cases import DAYS, PLANTS, WEATHER, case_key, hour_midpoints, plant_kwargs

OUT = Path(__file__).with_name("reference_legacy.json")


def main():
    results = {}
    for plant_name in PLANTS:
        plant = SolarPowerPlant(**plant_kwargs(plant_name))
        for weather_name, weather in WEATHER.items():
            for day in DAYS:
                for epoch in hour_midpoints(day):
                    power = plant.getPower(epochTimeSeconds=epoch, **weather)
                    results[case_key(plant_name, weather_name, epoch)] = power
    OUT.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(results)} values to {OUT}")


if __name__ == "__main__":
    main()
