"""Read the plants from a solXpect backup ZIP and turn them into Site objects."""
import logging
import sqlite3
import tempfile
import zipfile

from .Inverter import Inverter
from .PanelArray import PanelArray
from .Site import Site

logger = logging.getLogger(__name__)

CENTRAL_INVERTER_NAME = "Central inverter"


def read_app_plants(zip_path):
    # All rows of the CITIES_TO_WATCH table (one per plant), ordered as in the app
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        db_candidates = [f for f in zip_ref.namelist() if f.endswith('SQLITE.db') and 'databases/' in f]
        if not db_candidates:
            raise FileNotFoundError("No SQLITE.db found in 'databases/' folder inside ZIP.")
        with tempfile.TemporaryDirectory() as temp_dir:
            extracted_db_path = zip_ref.extract(db_candidates[0], path=temp_dir)
            conn = sqlite3.connect(extracted_db_path)
            try:
                cursor = conn.execute("SELECT * FROM CITIES_TO_WATCH ORDER BY rank")
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                conn.close()
    if not rows:
        raise ValueError("No data found in CITIES_TO_WATCH table.")
    return rows


def array_from_app_plant(plant, name=None):
    return PanelArray(
        name=name or plant['city_name'],
        albedo=float(plant['albedo']),
        cellsMaxPower=float(plant['cells_max_pPower']),
        cellsArea=float(plant['cells_area']),
        cellsEfficiency=float(plant['cells_efficiency']),
        cellsTempCoeff=float(plant['cells_temp_coeff']),
        diffuseEfficiency=float(plant['diffuse_efficiency']),
        azimuthAngle=float(plant['azimuth_angle']),
        tiltAngle=float(plant['tilt_angle']),
        shadingElevation=[int(x) for x in str(plant['shading_elevation']).split(',')],
        shadingOpacity=[int(x) for x in str(plant['shading_opacity']).split(',')]
    )


def sites_from_app_plants(plants, beamMode="app"):
    # Plants at the same location form one site, as with the app's "summarize" option.
    # Plants without central inverter get their own inverter each. The central plants of a
    # location share one inverter whose limit is the sum of their limits, as in the app.
    # beamMode "app" keeps the app's calculation; "substep" uses the improved one.
    locations = {}
    for plant in plants:
        locations.setdefault((float(plant['latitude']), float(plant['longitude'])), []).append(plant)

    sites = []
    for (latitude, longitude), group in locations.items():
        inverters = []
        usedNames = set()
        central = [p for p in group if int(p['is_central_inverter'])]
        if central:
            arrayNames = set()
            efficiencies = {float(p['inverter_efficiency']) for p in central}
            efficiency = sum(efficiencies) / len(efficiencies)
            if len(efficiencies) > 1:
                logger.warning(f"Central plants at {latitude},{longitude} have different inverter "
                               f"efficiencies {sorted(efficiencies)}; using {efficiency:.2f} %")
            inverters.append(Inverter(
                name=CENTRAL_INVERTER_NAME,
                inverterEfficiency=efficiency,
                inverterPowerLimit=sum(float(p['inverter_power_limit']) for p in central),
                arrays=[array_from_app_plant(p, _uniqueName(p['city_name'], arrayNames)) for p in central]))
            usedNames.add(CENTRAL_INVERTER_NAME)
        for plant in group:
            if int(plant['is_central_inverter']):
                continue
            name = _uniqueName(plant['city_name'], usedNames)
            inverters.append(Inverter(
                name=name,
                inverterEfficiency=float(plant['inverter_efficiency']),
                inverterPowerLimit=float(plant['inverter_power_limit']),
                arrays=[array_from_app_plant(plant, name)]))
        sites.append(Site(latitude, longitude, inverters, name=group[0]['city_name'], beamMode=beamMode))
    return sites


def sites_from_app_backup(zip_path, beamMode="app"):
    return sites_from_app_plants(read_app_plants(zip_path), beamMode=beamMode)


def _uniqueName(name, usedNames):
    # name, or name with " 2", " 3", ... if it is already taken; remembers the result
    candidate, n = name, 2
    while candidate in usedNames:
        candidate, n = f"{name} {n}", n + 1
    usedNames.add(candidate)
    return candidate
