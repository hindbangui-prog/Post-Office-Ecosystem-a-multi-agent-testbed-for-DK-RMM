from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Sequence

#: Fewer points than this and every statistic below is noise with a decimal
#: point. The monitor reports "not enough yet" rather than a number, because a
#: confident figure from four samples is worse than no figure.
MIN_POINTS = 12

#: How far above the fitted tail the largest point has to sit before it is
#: called a dragon king. A factor rather than a percentage: the claim is that
#: it is of a different order, not that it is somewhat bigger.
DRAGON_FACTOR = 2.0

#: How many of the largest points the fit uses. Enough to describe a tail,
#: few enough that the body of the distribution does not drag the line.
TAIL_POINTS = 12


@dataclass
class Precursors:
    """The critical-slowing-down reading of one series."""

    points: int = 0
    variance: float = 0.0
    autocorrelation: float = 0.0
    skewness: float = 0.0
    #: Whether each of the three is higher in the recent half than the earlier
    #: half. The warning is about all three rising, not about their levels.
    variance_rising: bool = False
    autocorrelation_rising: bool = False
    skewness_rising: bool = False
    enough: bool = False

    @property
    def rising(self) -> int:
        """How many of the three are rising. Three is the classical warning."""
        return sum((self.variance_rising, self.autocorrelation_rising,
                    self.skewness_rising))

    @property
    def slowing_down(self) -> bool:
        """
        The early warning proper: variance and memory both climbing.

        Skewness is counted towards `rising` but not required here. It is the
        least robust of the three on short series, and demanding all three
        would mean the warning almost never fires on a run short enough to
        watch.
        """
        return self.enough and self.variance_rising and self.autocorrelation_rising

    def as_dict(self) -> Dict[str, Any]:
        return {"points": self.points, "enough": self.enough,
                "variance": round(self.variance, 5),
                "autocorrelation": round(self.autocorrelation, 4),
                "skewness": round(self.skewness, 4),
                "variance_rising": self.variance_rising,
                "autocorrelation_rising": self.autocorrelation_rising,
                "skewness_rising": self.skewness_rising,
                "rising": self.rising, "slowing_down": self.slowing_down}


@dataclass
class DragonKing:
    """The rank-ordering reading of one series."""

    points: int = 0
    observed: float = 0.0
    #: What the tail, fitted without this point, says the largest should be.
    expected: float = 0.0
    #: observed / expected. One means the tail explained it.
    ratio: float = 0.0
    #: The slope of the fitted tail, kept because a tail that is not a
    #: straight line at all is a reason to distrust the verdict above it.
    slope: float = 0.0
    fit_quality: float = 0.0
    is_dragon: bool = False
    enough: bool = False
    #: log-rank, log-value pairs, so the page can draw what was fitted rather
    #: than redo the arithmetic in another language.
    plot: List[List[float]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"points": self.points, "enough": self.enough,
                "observed": round(self.observed, 5),
                "expected": round(self.expected, 5),
                "ratio": round(self.ratio, 3),
                "slope": round(self.slope, 4),
                "fit_quality": round(self.fit_quality, 3),
                "is_dragon": self.is_dragon,
                "plot": [[round(x, 4), round(y, 4)] for x, y in self.plot]}


def _autocorrelation(series: Sequence[float], lag: int = 1) -> float:
    """Lag-1 autocorrelation. Zero for a series with no variance to speak of."""
    if len(series) <= lag + 1:
        return 0.0
    average = mean(series)
    deviations = [value - average for value in series]
    bottom = sum(d * d for d in deviations)
    if bottom <= 1e-12:
        return 0.0
    top = sum(deviations[i] * deviations[i + lag]
              for i in range(len(deviations) - lag))
    return max(-1.0, min(1.0, top / bottom))


def _skewness(series: Sequence[float]) -> float:
    if len(series) < 3:
        return 0.0
    average = mean(series)
    spread = pstdev(series)
    if spread <= 1e-12:
        return 0.0
    return sum(((value - average) / spread) ** 3
               for value in series) / len(series)


def _variance(series: Sequence[float]) -> float:
    return pstdev(series) ** 2 if len(series) >= 2 else 0.0


def precursors(series: Sequence[float],
               min_points: int = MIN_POINTS) -> Precursors:
    """
    Whether this series looks like one approaching a critical point.

    Each statistic is computed over the whole series and then over its two
    halves, because the level of a variance says little on its own -- a busy
    facility is noisier than a quiet one all day long -- and a variance that
    has doubled in the last few minutes says a great deal.
    """
    values = [float(v) for v in series]
    if len(values) < min_points:
        return Precursors(points=len(values), enough=False,
                          variance=_variance(values),
                          autocorrelation=_autocorrelation(values),
                          skewness=_skewness(values))

    half = len(values) // 2
    early, late = values[:half], values[half:]
    return Precursors(
        points=len(values), enough=True,
        variance=_variance(values),
        autocorrelation=_autocorrelation(values),
        skewness=_skewness(values),
        variance_rising=_variance(late) > _variance(early),
        autocorrelation_rising=_autocorrelation(late) > _autocorrelation(early),
        skewness_rising=_skewness(late) > _skewness(early),
    )


def dragon_king(series: Sequence[float], factor: float = DRAGON_FACTOR,
                tail_points: int = TAIL_POINTS,
                min_points: int = MIN_POINTS) -> DragonKing:
    """
    Whether the largest value in this series belongs to its own tail.

    The fit deliberately excludes the point it is judging. Including it would
    let a big enough outlier drag the line up to meet itself, which is how a
    test for outliers quietly becomes a test for nothing.
    """
    values = sorted((float(v) for v in series if float(v) > 0.0), reverse=True)
    if len(values) < min_points:
        return DragonKing(points=len(values), enough=False,
                          observed=values[0] if values else 0.0)

    tail = values[:max(4, min(tail_points, len(values)))]
    # Ranks from 1. The largest point is rank 1 and is held out of the fit.
    xs = [math.log(rank) for rank in range(2, len(tail) + 1)]
    ys = [math.log(value) for value in tail[1:]]
    plot = [[math.log(rank), math.log(value)]
            for rank, value in enumerate(tail, start=1)]

    n = len(xs)
    if n < 3:
        return DragonKing(points=len(values), enough=False,
                          observed=tail[0], plot=plot)

    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return DragonKing(points=len(values), enough=False,
                          observed=tail[0], plot=plot)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx

    # How straight the held-out tail actually was. A curved tail makes the
    # extrapolation to rank 1 an opinion rather than a prediction, and the
    # page says so rather than hiding it behind a verdict.
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    spread = sum((y - my) ** 2 for y in ys)
    if spread > 1e-12:
        quality = 1.0 - (residual / spread)
    else:
        # A tail with no spread at all is a flat one, and a flat line is fitted
        # perfectly by a flat line. Scoring that as a bad fit -- which the
        # ratio above does, since it is zero over zero -- threw away the
        # clearest dragon king there is: a quiet series with one spike in it.
        quality = 1.0 if residual <= 1e-12 else 0.0

    expected = math.exp(intercept)          # rank 1: log(1) is zero
    observed = tail[0]
    ratio = observed / expected if expected > 1e-12 else 0.0
    return DragonKing(
        points=len(values), enough=True, observed=observed, expected=expected,
        ratio=ratio, slope=slope, fit_quality=quality,
        is_dragon=bool(ratio >= factor and quality > 0.5), plot=plot,
    )


def zscore(value: float, history: Sequence[float]) -> float:
    """
    How far off its own baseline one indicator is.

    The baseline is the indicator's own recent past, not a number anybody set:
    a facility under stress and a facility at three in the morning have
    different normal message rates, and a fixed threshold would call one of
    them abnormal all day.
    """
    values = [float(v) for v in history]
    if len(values) < 4:
        return 0.0
    spread = pstdev(values)
    if spread <= 1e-9:
        # A dead-flat baseline that has just moved is a real signal, but its
        # size cannot be expressed in standard deviations of nothing.
        return 0.0 if abs(value - mean(values)) <= 1e-9 else 3.0
    return (float(value) - mean(values)) / spread
