"""Tests for the A9 hourly typical-day profile modeler."""

from __future__ import annotations

import pytest

from app.matching import hourly_profile as hp


def test_wind_shape_has_24_points_summing_to_one():
    shape = hp.wind_shape()
    assert len(shape) == hp.HOURS == 24
    assert sum(shape) == pytest.approx(1.0)


def test_wind_is_night_strong_day_weak():
    # Taiwan wind: pre-dawn hours carry more than the midday trough.
    shape = hp.wind_shape()
    night = shape[2]  # 02:00
    midday = shape[11]  # 11:00
    assert night > midday


def test_load_shape_sums_to_one_for_every_industry():
    for industry in ["半導體", "面板", "電子", "電源管理", "生技", None, "未知產業"]:
        shape = hp.load_shape(industry)
        assert len(shape) == 24
        assert sum(shape) == pytest.approx(1.0)


def test_semiconductor_is_flatter_than_office():
    # A 24h fab is a high baseload; an office/biotech load swings far more.
    fab = hp.load_shape("半導體")
    office = hp.load_shape("生技")
    fab_swing = max(fab) - min(fab)
    office_swing = max(office) - min(office)
    assert fab_swing < office_swing


def test_to_hourly_preserves_the_period_total():
    shape = hp.load_shape("半導體")
    hourly = hp.to_hourly(1200.0, shape)
    assert len(hourly) == 24
    assert sum(hourly) == pytest.approx(1200.0)


def test_unknown_industry_falls_back_to_a_valid_shape():
    shape = hp.load_shape("something-else")
    assert sum(shape) == pytest.approx(1.0)
