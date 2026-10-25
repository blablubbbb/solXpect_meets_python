"""Tests for calcs/forecast.py without network access."""
from datetime import datetime, timezone

import pandas as pd

from calcs import forecast


def test_fetch_requests_the_given_hour_range(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"hourly": {"time": ["2026-10-25T10:00"], "shortwave_radiation": [0.0]}}

    def fake_get(url, params=None, **kwargs):
        captured.update(params)
        return Response()

    monkeypatch.setattr(forecast.requests, "get", fake_get)
    start = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
    end = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)
    forecast.fetch_open_meteo_data(50.0, 8.0, start, end)

    assert captured["start_hour"] == "2026-10-25T10:00"
    assert captured["end_hour"] == "2026-10-26T10:00"
    assert "start" not in captured and "end" not in captured


def test_missing_hour_returns_none_instead_of_crashing():
    meteo_df = pd.DataFrame({
        "time": pd.to_datetime(["2026-10-25T10:00"], utc=True),
        "direct_normal_irradiance": [100.0],
        "diffuse_radiation": [50.0],
        "shortwave_radiation": [120.0],
        "temperature_2m": [12.0],
    })
    missing = datetime(2026, 10, 25, 11, tzinfo=timezone.utc)
    assert forecast.prepare_weather(missing, meteo_df) is None
