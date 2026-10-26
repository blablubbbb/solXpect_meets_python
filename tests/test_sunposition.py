"""The NOAA solar position must agree with pvlib's NREL SPA (pvlib is only needed for this test)."""
import numpy as np
import pytest

from calcs.sunposition import sunPosition

pvlib = pytest.importorskip("pvlib")
pd = pytest.importorskip("pandas")


@pytest.mark.parametrize("latitude,longitude", [(53.6, 10.0), (0.0, 0.0), (-33.9, 151.2), (64.1, -21.9)])
def test_matches_pvlib(latitude, longitude):
    rng = np.random.default_rng(1)
    start = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp())
    end = int(pd.Timestamp("2035-01-01", tz="UTC").timestamp())
    epochs = rng.integers(start, end, 5000)
    azimuth, elevation = sunPosition(latitude, longitude, epochs)
    ref = pvlib.solarposition.get_solarposition(pd.to_datetime(epochs, unit="s", utc=True), latitude, longitude)
    ref_elevation = ref["elevation"].to_numpy()
    assert np.abs(elevation - ref_elevation).max() < 0.03
    # azimuth changes fast near the zenith, so compare it where the sun is not almost overhead
    usable = (ref_elevation > 1) & (ref_elevation < 85)
    azimuth_error = np.abs((azimuth - ref["azimuth"].to_numpy() + 180) % 360 - 180)[usable]
    assert azimuth_error.max() < 0.1


def test_keeps_the_shape():
    epochs = np.array([[1782043200, 1782046800], [1782050400, 1782054000]])
    azimuth, elevation = sunPosition(50.0, 8.0, epochs)
    assert azimuth.shape == elevation.shape == (2, 2)
