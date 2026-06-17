"""Deterministic analysis helpers."""

from __future__ import annotations

from forge.streams.analysis import clamp_unit, coverage, linear_slope


def test_linear_slope_rising_series():
    assert linear_slope([(2021, 10), (2022, 12), (2023, 14)]) == 2.0


def test_linear_slope_falling_series_is_negative():
    assert linear_slope([(2021, 20), (2022, 10)]) == -10.0


def test_linear_slope_degenerate_cases():
    assert linear_slope([]) == 0.0
    assert linear_slope([(2023, 5)]) == 0.0  # single point
    assert linear_slope([(2023, 5), (2023, 9)]) == 0.0  # zero x-variance


def test_coverage_is_a_unit_fraction():
    assert coverage(5, 5) == 1.0
    assert coverage(2, 5) == 0.4
    assert coverage(9, 5) == 1.0  # capped
    assert coverage(1, 0) == 0.0


def test_clamp_unit():
    assert clamp_unit(-0.2) == 0.0
    assert clamp_unit(1.5) == 1.0
    assert clamp_unit(0.3) == 0.3
