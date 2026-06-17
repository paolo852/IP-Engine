"""Small, deterministic analysis helpers for stream sub-signals. No ML."""

from __future__ import annotations


def linear_slope(points: list[tuple[float, float]]) -> float:
    """Ordinary least-squares slope of y over x. 0.0 if undefined (<2 pts / flat x)."""
    n = len(points)
    if n < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom == 0:
        return 0.0
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return num / denom


def coverage(found: int, expected: int) -> float:
    """Fraction in [0, 1] of expected data points actually present."""
    if expected <= 0:
        return 0.0
    return min(1.0, max(0.0, found / expected))


def clamp_unit(value: float) -> float:
    """Clamp to [0, 1] (evidence match_strength must satisfy the DB check)."""
    return min(1.0, max(0.0, value))
