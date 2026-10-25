"""Read the plants from a solXpect backup ZIP and turn them into Site objects."""
import logging
import sqlite3
import tempfile
import zipfile

import numpy as np

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
        name=name or _plantName(plant),
        albedo=_num(plant['albedo']),
        cellsMaxPower=_num(plant['cells_max_pPower']),
        cellsArea=_num(plant['cells_area']),
        cellsEfficiency=_num(plant['cells_efficiency']),
        cellsTempCoeff=_num(plant['cells_temp_coeff']),
        diffuseEfficiency=_num(plant['diffuse_efficiency']),
        azimuthAngle=_num(plant['azimuth_angle']),
        tiltAngle=_num(plant['tilt_angle']),
        shadingElevation=[int(x) for x in str(plant['shading_elevation']).split(',')],
        shadingOpacity=[int(x) for x in str(plant['shading_opacity']).split(',')]
    )


def sites_from_app_plants(plants, beamMode="app", select=None, combine=True):
    # select: ranks (int) or names (str) of the plants to import; None imports all.
    # combine=True: plants at the same location form one site, as with the app's "summarize"
    #   option. Plants without central inverter get their own inverter each. The central plants
    #   of a location share one inverter whose limit is the sum of their limits, as in the app.
    # combine=False: every plant becomes its own site with its own inverter (e.g. when the
    #   plants are alternative variants of the same installation).
    # beamMode "app" keeps the app's calculation; "substep" uses the improved one.
    if select is not None:
        wanted = {s.strip() if isinstance(s, str) else int(s) for s in select}
        plants = [p for p in plants if int(p['rank']) in wanted or _plantName(p) in wanted]
        if not plants:
            raise ValueError(f"none of the plants {sorted(map(str, wanted))} found")

    if not combine:
        return [Site(_num(p['latitude']), _num(p['longitude']), [Inverter(
                    name=_plantName(p),
                    inverterEfficiency=_num(p['inverter_efficiency']),
                    inverterPowerLimit=_num(p['inverter_power_limit']),
                    arrays=[array_from_app_plant(p)])],
                    name=_plantName(p), beamMode=beamMode)
                for p in plants]

    locations = {}
    for plant in plants:
        locations.setdefault((_num(plant['latitude']), _num(plant['longitude'])), []).append(plant)

    sites = []
    for (latitude, longitude), group in locations.items():
        inverters = []
        usedNames = set()
        central = [p for p in group if int(p['is_central_inverter'])]
        if central:
            arrayNames = set()
            efficiencies = {_num(p['inverter_efficiency']) for p in central}
            efficiency = sum(efficiencies) / len(efficiencies)
            if len(efficiencies) > 1:
                logger.warning(f"Central plants at {latitude},{longitude} have different inverter "
                               f"efficiencies {sorted(efficiencies)}; using {efficiency:.2f} %")
            inverters.append(Inverter(
                name=CENTRAL_INVERTER_NAME,
                inverterEfficiency=efficiency,
                inverterPowerLimit=sum(_num(p['inverter_power_limit']) for p in central),
                arrays=[array_from_app_plant(p, _uniqueName(_plantName(p), arrayNames)) for p in central]))
            usedNames.add(CENTRAL_INVERTER_NAME)
        for plant in group:
            if int(plant['is_central_inverter']):
                continue
            name = _uniqueName(_plantName(plant), usedNames)
            inverters.append(Inverter(
                name=name,
                inverterEfficiency=_num(plant['inverter_efficiency']),
                inverterPowerLimit=_num(plant['inverter_power_limit']),
                arrays=[array_from_app_plant(plant, name)]))
        sites.append(Site(latitude, longitude, inverters, name=_plantName(group[0]), beamMode=beamMode))
    return sites


def sites_from_app_backup(zip_path, beamMode="app", select=None, combine=True):
    return sites_from_app_plants(read_app_plants(zip_path), beamMode=beamMode, select=select, combine=combine)


def _num(value):
    # The app stores Java floats (32 bit), so 22.53 comes back as 22.530000686645508;
    # the shortest text of the 32-bit value gives 22.53 again
    return float(str(np.float32(value)))


def _plantName(plant):
    return str(plant['city_name']).strip()


def _uniqueName(name, usedNames):
    # name, or name with " 2", " 3", ... if it is already taken; remembers the result
    candidate, n = name, 2
    while candidate in usedNames:
        candidate, n = f"{name} {n}", n + 1
    usedNames.add(candidate)
    return candidate
