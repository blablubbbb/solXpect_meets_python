"""Tests for calcs/forecast.py without network access."""
from datetime import datetime, timezone

import numpy as np

from calcs import forecast


def _fake_response(monkeypatch, payload, captured):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    def fake_get(url, params=None, **kwargs):
        captured.update(params)
        return Response()

    monkeypatch.setattr(forecast.requests, "get", fake_get)


def test_fetch_requests_the_given_hour_range(monkeypatch):
    captured = {}
    _fake_response(monkeypatch, {"hourly": {"time": ["2026-10-25T10:00"], "shortwave_radiation": [0.0]}}, captured)
    start = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
    end = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)
    forecast.fetch_open_meteo_data(50.0, 8.0, start, end)

    assert captured["start_hour"] == "2026-10-25T10:00"
    assert captured["end_hour"] == "2026-10-26T10:00"
    assert "start" not in captured and "end" not in captured


def test_fetch_returns_numpy_arrays_with_unix_times(monkeypatch):
    payload = {"hourly": {
        "time": ["2026-10-25T10:00", "2026-10-25T11:00"],
        "direct_normal_irradiance": [100.0, None],      # Open-Meteo sends null for missing values
        "diffuse_radiation": [50.0, 60.0],
        "shortwave_radiation": [120.0, 130.0],
        "temperature_2m": [12.0, 13.0],
    }}
    _fake_response(monkeypatch, payload, {})
    start = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
    weather = forecast.fetch_open_meteo_data(50.0, 8.0, start, start)

    assert weather["time"].tolist() == [int(start.timestamp()), int(start.timestamp()) + 3600]
    assert weather["diffuse_radiation"].tolist() == [50.0, 60.0]
    assert np.isnan(weather["direct_normal_irradiance"][1])


def test_missing_hour_returns_none_instead_of_crashing():
    present = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
    weather = {
        "time": np.array([int(present.timestamp())]),
        "direct_normal_irradiance": np.array([100.0]),
        "diffuse_radiation": np.array([50.0]),
        "shortwave_radiation": np.array([120.0]),
        "temperature_2m": np.array([12.0]),
    }
    assert forecast.prepare_weather(present, weather)["solar_power_diffuse"] == 50.0
    missing = datetime(2026, 10, 25, 11, tzinfo=timezone.utc)
    assert forecast.prepare_weather(missing, weather) is None
