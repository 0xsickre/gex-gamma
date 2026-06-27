"""Smoke tests for the gex_signal service (no network / DB)."""
from __future__ import annotations

from gex_gamma.services import build_gex_signal as svc


_FAKE_PROFILE = {
    "instrument": "SPX",
    "underlying": "I:SPX",
    "spot": 5000.0,
    "q": 0.013,
    "net_gex": 1.23e9,
    "net_gex_norm": 0.5,
    "gamma_flip": 4950.0,
    "spot_vs_flip": 0.0101,
    "gamma_regime": "POSITIVE",
    "call_wall": 5100.0,
    "put_wall": 4900.0,
    "near_term_gex": 8.0e8,
    "dte0_share": 0.25,
    "n_contracts": 120,
}


def test_build_gex_signal_assembles_doc(monkeypatch):
    def fake_compute(code):
        return {**_FAKE_PROFILE, "instrument": code} if code in ("SPX", "NDX") else None

    monkeypatch.setattr(svc, "compute_gex_for_instrument", fake_compute)

    row = svc.build_gex_signal(["SPX", "NDX"])
    assert set(row.keys()) == {"as_of", "computed_at", "instruments"}
    assert set(row["instruments"].keys()) == {"SPX", "NDX"}
    assert row["instruments"]["SPX"]["gamma_regime"] == "POSITIVE"


def test_build_gex_signal_skips_failures(monkeypatch):
    monkeypatch.setattr(svc, "compute_gex_for_instrument", lambda code: None)
    row = svc.build_gex_signal(["SPX"])
    assert row["instruments"] == {}


def test_public_gex_signal_thin_contract():
    row = {
        "as_of": "2026-06-27",
        "computed_at": "2026-06-27T20:00:00+00:00",
        "instruments": {"SPX": dict(_FAKE_PROFILE)},
    }
    pub = svc.public_gex_signal(row)
    assert pub["as_of"] == "2026-06-27"
    spx = pub["instruments"]["SPX"]
    assert set(spx.keys()) == {
        "gamma_regime",
        "net_gex_norm",
        "spot_vs_flip",
        "gamma_flip",
        "call_wall",
        "put_wall",
    }
    # full-only keys must not leak into the thin contract
    assert "net_gex" not in spx
    assert "n_contracts" not in spx
