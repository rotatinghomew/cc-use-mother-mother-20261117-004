from __future__ import annotations

import math
from collections.abc import Iterable


def mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        raise ValueError("mean requires at least one value")
    return math.fsum(items) / len(items)


def sample_variance(values: Iterable[float]) -> float:
    items = list(values)
    if len(items) < 2:
        raise ValueError("sample variance requires at least two values")
    center = mean(items)
    return math.fsum((value - center) ** 2 for value in items) / (len(items) - 1)


def standard_deviation(values: Iterable[float]) -> float:
    return math.sqrt(sample_variance(values))


def coefficient_of_variation(values: Iterable[float]) -> float:
    items = list(values)
    center = mean(items)
    if center == 0:
        raise ValueError("coefficient of variation is undefined at zero mean")
    return standard_deviation(items) / abs(center)


def quantile(values: Iterable[float], probability: float) -> float:
    items = sorted(values)
    if not items or not 0 <= probability <= 1:
        raise ValueError("quantile needs values and probability in [0, 1]")
    position = (len(items) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return items[lower] * (1 - fraction) + items[upper] * fraction


def percentile_summary(values: Iterable[float]) -> dict[str, float]:
    items = list(values)
    if not items:
        raise ValueError("summary requires at least one value")
    result = {"n": float(len(items)), "mean": mean(items), "min": min(items), "max": max(items),
              "p25": quantile(items, .25), "median": quantile(items, .5), "p75": quantile(items, .75)}
    result["sample_sd"] = standard_deviation(items) if len(items) > 1 else 0.0
    result["cv"] = coefficient_of_variation(items) if len(items) > 1 and result["mean"] != 0 else 0.0
    return result
