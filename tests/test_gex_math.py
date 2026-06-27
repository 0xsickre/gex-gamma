"""Unit tests for the pure dealer-GEX math (no network / DB)."""
from __future__ import annotations

import math

import pytest

from gex_gamma.core.gex_math import (
    OptionQuote,
    bs_gamma,
    bs_price,
    compute_gex_profile,
    gamma_flip,
    implied_vol,
    net_gex_at_spot,
    zscore,
)


def test_bs_gamma_matches_closed_form_atm():
    g = bs_gamma(100.0, 100.0, 0.0, 0.0, 0.2, 1.0)
    expected = math.exp(-0.5 * 0.1**2) / math.sqrt(2 * math.pi) / (100.0 * 0.2)
    assert g == pytest.approx(expected, rel=1e-9)


def test_bs_gamma_degenerate_inputs_zero():
    assert bs_gamma(0.0, 100.0, 0.0, 0.0, 0.2, 1.0) == 0.0
    assert bs_gamma(100.0, 100.0, 0.0, 0.0, 0.0, 1.0) == 0.0
    assert bs_gamma(100.0, 100.0, 0.0, 0.0, 0.2, 0.0) == 0.0


def test_implied_vol_round_trips():
    price = bs_price(100.0, 105.0, 0.03, 0.01, 0.25, 0.5, is_call=True)
    iv = implied_vol(price, 100.0, 105.0, 0.03, 0.01, 0.5, is_call=True)
    assert iv == pytest.approx(0.25, abs=1e-4)


def test_implied_vol_below_intrinsic_returns_none():
    assert implied_vol(0.5, 100.0, 50.0, 0.0, 0.0, 0.5, is_call=True) is None


def test_net_gex_sign_convention():
    call = [OptionQuote(strike=100.0, is_call=True, open_interest=1000, dte_years=0.1, iv=0.2)]
    put = [OptionQuote(strike=100.0, is_call=False, open_interest=1000, dte_years=0.1, iv=0.2)]
    assert net_gex_at_spot(call, 100.0, 0.0, 0.0) > 0
    assert net_gex_at_spot(put, 100.0, 0.0, 0.0) < 0


def test_gamma_flip_none_when_no_crossing():
    chain = [OptionQuote(strike=k, is_call=True, open_interest=500, dte_years=0.1, iv=0.2)
             for k in (90, 95, 100, 105, 110)]
    assert gamma_flip(chain, 100.0, 0.0, 0.0) is None


def test_gamma_flip_detects_crossing():
    chain = [
        OptionQuote(strike=90.0, is_call=False, open_interest=5000, dte_years=0.1, iv=0.2),
        OptionQuote(strike=95.0, is_call=False, open_interest=5000, dte_years=0.1, iv=0.2),
        OptionQuote(strike=105.0, is_call=True, open_interest=5000, dte_years=0.1, iv=0.2),
        OptionQuote(strike=110.0, is_call=True, open_interest=5000, dte_years=0.1, iv=0.2),
    ]
    flip = gamma_flip(chain, 100.0, 0.0, 0.0)
    assert flip is not None
    assert 85.0 <= flip <= 115.0
    assert net_gex_at_spot(chain, flip - 5.0, 0.0, 0.0) * net_gex_at_spot(chain, flip + 5.0, 0.0, 0.0) < 0


def test_compute_gex_profile_keys_and_regime():
    chain = [
        OptionQuote(strike=100.0, is_call=True, open_interest=2000, dte_years=0.05, iv=0.18),
        OptionQuote(strike=100.0, is_call=False, open_interest=500, dte_years=0.05, iv=0.18),
        OptionQuote(strike=110.0, is_call=True, open_interest=1500, dte_years=0.05, iv=0.20),
        OptionQuote(strike=90.0, is_call=False, open_interest=800, dte_years=0.05, iv=0.20),
    ]
    prof = compute_gex_profile(chain, spot=100.0, r=0.04, instrument="SPX")
    assert prof is not None
    for k in ("net_gex", "gamma_flip", "gamma_regime", "call_wall", "put_wall", "dte0_share", "n_contracts"):
        assert k in prof
    assert prof["gamma_regime"] in ("POSITIVE", "NEGATIVE")
    assert prof["n_contracts"] == 4


def test_compute_gex_profile_empty_returns_none():
    assert compute_gex_profile([], spot=100.0, r=0.04) is None
    bad = [OptionQuote(strike=100.0, is_call=True, open_interest=0, dte_years=0.1, iv=0.2)]
    assert compute_gex_profile(bad, spot=100.0, r=0.04) is None


def test_iv_inversion_used_when_iv_missing():
    mid = bs_price(100.0, 100.0, 0.04, 0.0, 0.2, 0.1, is_call=True)
    chain = [OptionQuote(strike=100.0, is_call=True, open_interest=1000, dte_years=0.1, iv=None, mid=mid)]
    prof = compute_gex_profile(chain, spot=100.0, r=0.04, q=0.0)
    assert prof is not None
    assert prof["net_gex"] > 0


def test_zscore():
    assert zscore(10.0, [0, 0, 0]) is None
    z = zscore(2.0, [0.0, 1.0, 2.0, 3.0, 4.0])
    assert z is not None and z == pytest.approx(0.0, abs=1e-9)
