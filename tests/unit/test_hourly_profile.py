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


def test_solar_shape_has_24_points_summing_to_one():
    shape = hp.solar_shape()
    assert len(shape) == hp.HOURS == 24
    assert sum(shape) == pytest.approx(1.0)


def test_solar_generates_nothing_at_night():
    shape = hp.solar_shape()
    for hour in [0, 1, 2, 3, 4, 5, 19, 20, 21, 22, 23]:
        assert shape[hour] == 0.0


def test_solar_peaks_around_noon():
    shape = hp.solar_shape()
    assert shape.index(max(shape)) in (11, 12, 13)


def test_solar_and_wind_are_time_complementary():
    # 風光互補的核心：太陽能白天強、風電夜間強。
    wind, solar = hp.wind_shape(), hp.solar_shape()
    assert solar[12] > wind[12]
    assert wind[2] > solar[2]


def test_technology_classifies_solar_apart_from_wind():
    assert hp.technology("solar") == "solar"
    assert hp.technology("offshore") == "wind"
    assert hp.technology("onshore") == "wind"
    assert hp.technology(None) == "wind"


def test_generation_shape_dispatches_on_technology():
    assert hp.generation_shape("solar") == hp.solar_shape()
    assert hp.generation_shape("wind") == hp.wind_shape()
