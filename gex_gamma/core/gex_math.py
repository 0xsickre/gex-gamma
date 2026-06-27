"""Dealer Gamma Exposure (GEX) mathematics — pure, no I/O, no framework imports.

The free Massive Basic tier ships option *prices* and open interest but **no
Greeks**, so this module recomputes everything from first principles:

1. Black-Scholes gamma for European index options (SPX/NDX are European, cash
   settled).
2. Implied volatility by inverting the BS price (when the feed omits IV).
3. Implied forward / dividend yield from put-call parity at the money.
4. Per-strike dollar gamma, net dealer GEX, the gamma-flip (zero-gamma) level,
   and call/put gamma walls.

Sign convention (the widely used "naive" dealer assumption): dealers are **long
call gamma** and **short put gamma**. So a positive net GEX means dealers hedge
counter-trend (volatility suppression / pinning); negative means pro-trend
hedging (volatility amplification / momentum).

Dollar gamma per strike (M = contract multiplier, S = spot):

    DollarGamma = Gamma * OI * M * S**2 * 0.01

Depends only on :mod:`math` and the stdlib — importable from any layer and
testable without network, filesystem, or DataFrames.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

# Index option contract multiplier (SPX, NDX, ... = $100 per point).
CONTRACT_MULTIPLIER = 100.0

# Fallback continuous dividend yields when put-call parity cannot resolve q.
DEFAULT_DIVIDEND_YIELD = {
    "SPX": 0.013,
    "NDX": 0.008,
}
_DEFAULT_Q = 0.01

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_MIN_TAU = 1.0 / (365.0 * 24.0)  # ~1 hour, guards division by zero near expiry
_MIN_SIGMA = 1e-4
_MAX_SIGMA = 5.0


@dataclass(frozen=True)
class OptionQuote:
    """One option contract snapshot. ``iv`` is optional (inverted from ``mid`` if absent)."""

    strike: float
    is_call: bool
    open_interest: float
    dte_years: float
    iv: Optional[float] = None
    mid: Optional[float] = None


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(spot: float, strike: float, r: float, q: float, sigma: float, tau: float) -> float:
    return (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * tau) / (sigma * math.sqrt(tau))


def bs_gamma(spot: float, strike: float, r: float, q: float, sigma: float, tau: float) -> float:
    """Black-Scholes gamma (per 1 unit of spot). Returns 0 on degenerate inputs."""
    if spot <= 0 or strike <= 0 or sigma <= 0 or tau <= 0:
        return 0.0
    d1 = _d1(spot, strike, r, q, sigma, tau)
    return math.exp(-q * tau) * norm_pdf(d1) / (spot * sigma * math.sqrt(tau))


def bs_price(spot: float, strike: float, r: float, q: float, sigma: float, tau: float, is_call: bool) -> float:
    """Black-Scholes price for a European option."""
    if tau <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        intrinsic = (spot - strike) if is_call else (strike - spot)
        return max(0.0, intrinsic)
    d1 = _d1(spot, strike, r, q, sigma, tau)
    d2 = d1 - sigma * math.sqrt(tau)
    disc_q = math.exp(-q * tau)
    disc_r = math.exp(-r * tau)
    if is_call:
        return spot * disc_q * norm_cdf(d1) - strike * disc_r * norm_cdf(d2)
    return strike * disc_r * norm_cdf(-d2) - spot * disc_q * norm_cdf(-d1)


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    r: float,
    q: float,
    tau: float,
    is_call: bool,
) -> Optional[float]:
    """Invert the BS price for sigma. Bisection (robust) on a bounded bracket.

    Returns ``None`` when the price is below intrinsic or no root exists in
    ``[_MIN_SIGMA, _MAX_SIGMA]`` (deep ITM / stale quotes).
    """
    if price is None or spot <= 0 or strike <= 0 or tau <= 0:
        return None
    p = float(price)
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot)) * math.exp(-q * tau)
    if p < intrinsic - 1e-6 or p <= 0:
        return None

    def f(sig: float) -> float:
        return bs_price(spot, strike, r, q, sig, tau, is_call) - p

    lo, hi = _MIN_SIGMA, _MAX_SIGMA
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < 1e-8:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def implied_dividend_yield(
    call_mid: float,
    put_mid: float,
    spot: float,
    strike: float,
    r: float,
    tau: float,
) -> Optional[float]:
    """Continuous dividend yield from put-call parity at one (near-ATM) strike.

    Parity: ``C - P = S e^{-q tau} - K e^{-r tau}`` ->
    ``q = -ln((C - P + K e^{-r tau}) / S) / tau``.
    """
    if spot <= 0 or strike <= 0 or tau <= 0:
        return None
    try:
        rhs = call_mid - put_mid + strike * math.exp(-r * tau)
        if rhs <= 0:
            return None
        q = -math.log(rhs / spot) / tau
    except (ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(q) or abs(q) > 0.2:
        return None
    return q


def resolve_dividend_yield(
    options: Sequence[OptionQuote],
    spot: float,
    r: float,
    instrument: Optional[str] = None,
) -> float:
    """Estimate q from the nearest-ATM call/put parity; fall back to a constant."""
    fallback = DEFAULT_DIVIDEND_YIELD.get(str(instrument or "").upper(), _DEFAULT_Q)
    calls = {round(o.strike, 4): o for o in options if o.is_call and (o.mid or 0) > 0 and o.dte_years > 0}
    puts = {round(o.strike, 4): o for o in options if not o.is_call and (o.mid or 0) > 0 and o.dte_years > 0}
    common = set(calls) & set(puts)
    if not common:
        return fallback
    atm_strike = min(common, key=lambda k: abs(k - spot))
    c, p = calls[atm_strike], puts[atm_strike]
    tau = max(_MIN_TAU, min(c.dte_years, p.dte_years))
    q = implied_dividend_yield(float(c.mid), float(p.mid), spot, atm_strike, r, tau)
    return q if q is not None else fallback


def _ensure_iv(o: OptionQuote, spot: float, r: float, q: float) -> Optional[float]:
    if o.iv is not None and o.iv > 0:
        return float(o.iv)
    if o.mid is None or o.mid <= 0:
        return None
    tau = max(_MIN_TAU, o.dte_years)
    return implied_vol(float(o.mid), spot, o.strike, r, q, tau, o.is_call)


def dollar_gamma(gamma: float, open_interest: float, spot: float, multiplier: float = CONTRACT_MULTIPLIER) -> float:
    """Dealer dollar gamma per strike: change in $ delta per 1% spot move."""
    return gamma * open_interest * multiplier * spot * spot * 0.01


def net_gex_at_spot(
    options: Iterable[OptionQuote],
    spot: float,
    r: float,
    q: float,
    *,
    multiplier: float = CONTRACT_MULTIPLIER,
) -> float:
    """Net dealer GEX (long call gamma, short put gamma) evaluated at ``spot``.

    IV and OI are held fixed; gamma is recomputed at the hypothetical ``spot`` —
    this is what makes the gamma-flip search meaningful.
    """
    total = 0.0
    for o in options:
        iv = _ensure_iv(o, spot, r, q)
        if iv is None or iv <= 0:
            continue
        tau = max(_MIN_TAU, o.dte_years)
        g = bs_gamma(spot, o.strike, r, q, iv, tau)
        dg = dollar_gamma(g, o.open_interest, spot, multiplier)
        total += dg if o.is_call else -dg
    return total


def gamma_flip(
    options: Sequence[OptionQuote],
    spot: float,
    r: float,
    q: float,
    *,
    multiplier: float = CONTRACT_MULTIPLIER,
    grid: int = 41,
    lo_frac: float = 0.85,
    hi_frac: float = 1.15,
) -> Optional[float]:
    """Spot level where net GEX crosses zero (grid scan + bisection on first crossing).

    Returns ``None`` when net GEX keeps one sign across the whole grid.
    """
    if spot <= 0 or not options:
        return None
    lo, hi = spot * lo_frac, spot * hi_frac
    n = max(5, int(grid))
    step = (hi - lo) / (n - 1)
    prev_s = lo
    prev_v = net_gex_at_spot(options, prev_s, r, q, multiplier=multiplier)
    for i in range(1, n):
        cur_s = lo + i * step
        cur_v = net_gex_at_spot(options, cur_s, r, q, multiplier=multiplier)
        if prev_v == 0.0:
            return prev_s
        if prev_v * cur_v < 0:
            a, fa, b = prev_s, prev_v, cur_s
            for _ in range(60):
                mid = 0.5 * (a + b)
                fm = net_gex_at_spot(options, mid, r, q, multiplier=multiplier)
                if abs(fm) < 1e-3 or (b - a) < 1e-4:
                    return mid
                if fa * fm < 0:
                    b = mid
                else:
                    a, fa = mid, fm
            return 0.5 * (a + b)
        prev_s, prev_v = cur_s, cur_v
    return None


def gamma_walls(
    options: Iterable[OptionQuote],
    spot: float,
    r: float,
    q: float,
    *,
    multiplier: float = CONTRACT_MULTIPLIER,
) -> tuple[Optional[float], Optional[float]]:
    """(call_wall, put_wall): strikes with peak dealer dollar gamma above / below spot."""
    call_by_strike: dict[float, float] = {}
    put_by_strike: dict[float, float] = {}
    for o in options:
        iv = _ensure_iv(o, spot, r, q)
        if iv is None or iv <= 0:
            continue
        tau = max(_MIN_TAU, o.dte_years)
        g = bs_gamma(spot, o.strike, r, q, iv, tau)
        dg = abs(dollar_gamma(g, o.open_interest, spot, multiplier))
        if o.is_call:
            call_by_strike[o.strike] = call_by_strike.get(o.strike, 0.0) + dg
        else:
            put_by_strike[o.strike] = put_by_strike.get(o.strike, 0.0) + dg
    call_above = {k: v for k, v in call_by_strike.items() if k >= spot}
    put_below = {k: v for k, v in put_by_strike.items() if k <= spot}
    call_wall = max(call_above, key=call_above.get) if call_above else None
    put_wall = max(put_below, key=put_below.get) if put_below else None
    return call_wall, put_wall


def zscore(value: float, history: Sequence[float]) -> Optional[float]:
    """Z-score of ``value`` against a history sample (population std). None if degenerate."""
    vals = [float(x) for x in history if x is not None and math.isfinite(float(x))]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / len(vals)
    std = math.sqrt(var)
    if std <= 1e-12:
        return None
    return (float(value) - mean) / std


def compute_gex_profile(
    options: Sequence[OptionQuote],
    spot: float,
    r: float,
    *,
    instrument: Optional[str] = None,
    q: Optional[float] = None,
    multiplier: float = CONTRACT_MULTIPLIER,
    near_term_days: float = 30.0,
    history: Optional[Sequence[float]] = None,
) -> Optional[dict]:
    """Aggregate a full chain into GEX features. Returns ``None`` on empty/degenerate input.

    Output keys: ``net_gex`` ($), ``net_gex_norm`` (z-score vs history or None),
    ``gamma_flip``, ``spot_vs_flip`` (fraction), ``gamma_regime``
    (POSITIVE/NEGATIVE), ``call_wall``, ``put_wall``, ``near_term_gex``,
    ``dte0_share`` (fraction of |GEX| from 0DTE), ``spot``, ``q``, ``n_contracts``.
    """
    usable = [
        o
        for o in options
        if o.strike > 0 and o.dte_years > 0 and o.open_interest and o.open_interest > 0
    ]
    if not usable or spot <= 0:
        return None

    if q is None:
        q = resolve_dividend_yield(usable, spot, r, instrument)

    net = 0.0
    near_term = 0.0
    dte0_abs = 0.0
    total_abs = 0.0
    for o in usable:
        iv = _ensure_iv(o, spot, r, q)
        if iv is None or iv <= 0:
            continue
        tau = max(_MIN_TAU, o.dte_years)
        g = bs_gamma(spot, o.strike, r, q, iv, tau)
        dg = dollar_gamma(g, o.open_interest, spot, multiplier)
        signed = dg if o.is_call else -dg
        net += signed
        total_abs += abs(dg)
        if o.dte_years * 365.0 <= near_term_days:
            near_term += signed
        if o.dte_years * 365.0 <= 1.0:
            dte0_abs += abs(dg)

    flip = gamma_flip(usable, spot, r, q, multiplier=multiplier)
    call_wall, put_wall = gamma_walls(usable, spot, r, q, multiplier=multiplier)
    spot_vs_flip = ((spot - flip) / flip) if (flip and flip > 0) else None
    net_norm = zscore(net, history) if history else None

    return {
        "spot": float(spot),
        "q": float(q),
        "net_gex": float(net),
        "net_gex_norm": net_norm,
        "gamma_flip": float(flip) if flip is not None else None,
        "spot_vs_flip": float(spot_vs_flip) if spot_vs_flip is not None else None,
        "gamma_regime": "POSITIVE" if net >= 0 else "NEGATIVE",
        "call_wall": float(call_wall) if call_wall is not None else None,
        "put_wall": float(put_wall) if put_wall is not None else None,
        "near_term_gex": float(near_term),
        "dte0_share": float(dte0_abs / total_abs) if total_abs > 0 else 0.0,
        "n_contracts": int(len(usable)),
    }
