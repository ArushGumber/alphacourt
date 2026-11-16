"""Simulated markets with planted, known effects.

A world is a factor model: market factor + idiosyncratic noise (about 2% daily volatility) + planted effects
whose sizes are in `World.params["effects"]`. All noise is drawn up front from fixed streams, so a variant
(backfilled field, universe, effect scale) changes the effects only, never the noise.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

GEN_VERSION = 7
CRASH_HAZ = 0.0021
CACHE_DIR = Path(__file__).resolve().parent.parent / "results" / "cache" / "worlds"

# effect sizes: expected extra daily return per unit of the cross-sectionally standardised driver
BASE_EFFECTS = {
    "momentum": 4.4e-4,    # 12-1 return; calm days. In stressed regimes the sign flips (crash), see MOM_STRESS_MULT
    "reversal": 4.6e-4,    # previous-day return, reversed; very high turnover
    "pead": 1.3e-4,        # per-bar drift for PEAD_DAYS bars after an announcement, per unit of surprise
    "lowvol": 1.5e-4,        # low-volatility assets earn more
    "sentiment": 9e-5,     # sentiment[t] -> ret[t+1]
    "runup": 2.1e-4,       # pre-announcement run-up toward the (later restated) surprise
    "value": 1.4e-4,         # pull of log price back to a latent per-asset anchor (slow mean reversion)
    "crash": CRASH_HAZ,    # momentum winners delisting in stressed regimes
}
MOM_STRESS_MULT = -1.5
PEAD_DAYS = 40
ANN_JUMP = 0.01
SENT_K = 3.0               # sentiment_revised = sentiment + SENT_K * ret[t+1]
COST_BPS_TRUE = 10.0
DELIST_DD = 0.5            # log drawdown from the (slowly decaying) peak that makes delisting possible
DELIST_HAZ = 0.25
PEAK_DECAY = 0.007

LEAKY_OF = {"eps_reported": "eps_restated", "sentiment": "sentiment_revised", "index_member_pit": "index_member_now"}
ASOF_OF = {"eps_restated": "eps_reported", "sentiment_revised": "sentiment", "index_member_now": "index_member_pit"}

FIELD_INFO = {
    "close": {"description": "Closing price.", "documented_availability": "Available at the close of each bar. Point in time."},
    "ret": {"description": "Simple return from the previous close to this close. NaN after a delisting.",
            "documented_availability": "Available at the close of each bar. Point in time."},
    "volume": {"description": "Shares traded in the bar.", "documented_availability": "Available at the close of each bar. Point in time."},
    "eps_reported": {"description": "Standardised earnings surprise (reported minus expected, in units of its usual spread), "
                                    "held from each announcement bar until the next announcement. NaN before the first one.",
                     "documented_availability": "Published at the close of the announcement bar. Point in time."},
    "eps_restated": {"description": "Final restated earnings surprise for the fiscal period, shown from the first bar of the period.",
                     "documented_availability": "Final values; only known after the period closes and the filing is restated. Not point in time."},
    "sentiment": {"description": "News sentiment score for the asset, scaled to unit spread.",
                  "documented_availability": "Computed from news up to the close of each bar. Point in time."},
    "sentiment_revised": {"description": "Sentiment score after the vendor's later revision.",
                          "documented_availability": "Revised after the fact using later information. Not point in time."},
    "index_member_pit": {"description": "1 if the asset was in the index at that bar, else 0.",
                         "documented_availability": "Membership as of each bar. Point in time."},
    "index_member_now": {"description": "1 if the asset is in the index at the end of the research period, else 0, repeated for all bars.",
                         "documented_availability": "Membership as of today, applied to the past. Not point in time."},
}


@dataclass
class World:
    world_id: str
    seed: int
    T: int
    N: int
    research_end: int
    fields: dict
    field_info: dict
    asof: dict
    alive: np.ndarray
    universe_files: dict
    regime: np.ndarray
    cost_bps_true: float
    params: dict


def _world_id(seed, variant, T, N):
    wid = f"w{seed}"
    if variant:
        wid += "-" + hashlib.sha1(json.dumps(variant, sort_keys=True).encode()).hexdigest()[:6]
    if (T, N) != (3000, 300):
        wid += f"-T{T}N{N}"
    return wid


def _norm_variant(variant):
    v = dict(variant or {})
    bad = set(v) - {"backfilled", "default_universe", "effect_scale"}
    if bad:
        raise ValueError(f"unknown variant keys: {sorted(bad)}")
    for f in v.get("backfilled", []):
        if f not in LEAKY_OF:
            raise ValueError(f"cannot backfill '{f}'; choose from {sorted(LEAKY_OF)}")
    if v.get("default_universe", "all") not in ("all", "survivors"):
        raise ValueError("default_universe must be 'all' or 'survivors'")
    for k in v.get("effect_scale", {}):
        if k not in BASE_EFFECTS:
            raise ValueError(f"unknown effect '{k}'; effects are {sorted(BASE_EFFECTS)}")
    return v


def _std_rows(x, mask):
    """Cross-sectional z-score of one bar over assets where mask is True (others 0)."""
    n = max(mask.sum(), 1)
    xm = np.where(mask, x, 0.0)
    mu = xm.sum() / n
    d = np.where(mask, x - mu, 0.0)
    sd = np.sqrt((d * d).sum() / n)
    return d / sd if sd > 1e-12 else d


def _generate(seed, variant, T, N):
    ss = np.random.SeedSequence([seed, 7919])
    streams = [np.random.default_rng(s) for s in ss.spawn(10)]
    r_reg, r_mkt, r_idio, r_asset, r_ann, r_sent, r_del, r_vol, r_size, r_misc = streams
    scale = {k: 1.0 for k in BASE_EFFECTS}
    scale.update(variant.get("effect_scale", {}))
    eff = {k: BASE_EFFECTS[k] * scale[k] for k in BASE_EFFECTS}

    # regimes: stressed about 20% of days, episodes of about 12 days
    u = r_reg.random(T)
    reg = np.zeros(T, dtype=np.int8)
    for t in range(1, T):
        reg[t] = 1 if (reg[t - 1] == 1 and u[t] >= 0.08) or (reg[t - 1] == 0 and u[t] < 0.02) else 0
    sig_m = np.where(reg == 1, 0.020, 0.0085)
    sig_idio_mult = np.where(reg == 1, 1.35, 1.0)
    mkt = 0.0003 + sig_m * r_mkt.standard_normal(T)
    beta = np.clip(1.0 + 0.3 * r_asset.standard_normal(N), 0.2, 2.0)
    volmult = np.exp(0.3 * r_asset.standard_normal(N) - 0.045)
    sig_i = 0.017 * volmult
    size = r_size.standard_normal(N)
    e = r_idio.standard_t(5, size=(T, N)) / np.sqrt(5 / 3)
    anchor = 0.4 * r_asset.standard_normal(N)
    zvol = (volmult - volmult.mean()) / volmult.std()

    # earnings announcements: every 60-66 bars, staggered; surprises N(0,1)
    M = T // 60 + 3
    lens = r_ann.integers(60, 67, size=(N, M))
    offs = r_ann.integers(0, 63, size=N)
    ann_t = offs[:, None] + np.cumsum(lens, axis=1) - lens[:, :1]  # first announcement at offs
    surpr = r_ann.standard_normal((N, M))
    rest_noise = 0.15 * r_ann.standard_normal((N, M))
    S = np.zeros((T, N))
    flag = np.zeros((T, N), dtype=bool)
    idxn = np.broadcast_to(np.arange(N)[:, None], ann_t.shape)
    ok = ann_t < T
    S[ann_t[ok], idxn[ok]] = surpr[ok]
    flag[ann_t[ok], idxn[ok]] = True
    Rv = np.zeros((T, N))
    Rv[ann_t[ok], idxn[ok]] = surpr[ok] + rest_noise[ok]
    tgrid = np.arange(T)[:, None]
    last = np.maximum.accumulate(np.where(flag, tgrid, -1), axis=0)
    eps_rep = np.where(last >= 0, S[np.maximum(last, 0), np.arange(N)], np.nan)
    # next announcement at or after t (restated value of the period containing t)
    nxt_flag = flag.copy()
    big = T + 10
    nxt = np.minimum.accumulate(np.where(nxt_flag, tgrid, big)[::-1], axis=0)[::-1]
    # announcements beyond T: the period's surprise is still defined; build from the schedule
    after = np.where(ann_t >= T, np.arange(M)[None, :], M)
    first_after = after.min(axis=1)
    beyond_s = surpr[np.arange(N), np.minimum(first_after, M - 1)]
    beyond_r = beyond_s + rest_noise[np.arange(N), np.minimum(first_after, M - 1)]
    rest_vals = np.where(nxt < T, Rv[np.minimum(nxt, T - 1), np.arange(N)], beyond_r[None, :])
    surp_cur = np.where(nxt < T, S[np.minimum(nxt, T - 1), np.arange(N)], beyond_s[None, :])
    eps_rst = rest_vals.copy()
    cS = np.cumsum(S, axis=0)
    drift = np.zeros((T, N))
    drift[1:] = cS[:-1]
    drift[PEAD_DAYS + 1:] -= cS[: T - PEAD_DAYS - 1]
    static = eff["pead"] * drift + ANN_JUMP * scale["pead"] * S + eff["runup"] * surp_cur

    # sentiment: AR(1), unit variance; predicts the next bar
    q = np.zeros((T, N))
    eps_s = r_sent.standard_normal((T, N))
    q[0] = eps_s[0]
    for t in range(1, T):
        q[t] = 0.94 * q[t - 1] + np.sqrt(1 - 0.94**2) * eps_s[t]

    u_del = r_del.random((T, N))
    u_crash = r_del.random((T, N))
    fin = -(0.3 + 0.7 * r_del.random((T, N)))

    ret = np.full((T, N), np.nan)
    lp = np.zeros((T, N))
    alive = np.zeros((T, N), dtype=bool)
    alive_now = np.ones(N, dtype=bool)
    cs = np.zeros((T + 1, N))  # cs[k+1] = sum of ret[0..k]
    lpc = np.zeros(N)
    peak = np.zeros(N)
    zero = np.zeros(N)
    for t in range(T):
        e_t = eff
        x = static[t].copy()
        crash = False
        if t >= 1:
            prev = np.nan_to_num(ret[t - 1])
            x += -e_t["reversal"] * _std_rows(prev, alive_now)
            x += e_t["sentiment"] * q[t - 1]
            if t - 1 >= 252:
                m = cs[t - 1 - 21 + 1] - cs[t - 1 - 252]
                ms = 1.0 if reg[t] == 0 else MOM_STRESS_MULT
                zm = _std_rows(m, alive_now)
                x += e_t["momentum"] * ms * zm
                crash = (reg[t] == 1) & (zm > 0.84) & (u_crash[t] < eff["crash"])
            else:
                crash = False
        x += -e_t["lowvol"] * zvol - e_t["value"] * (lpc - anchor)
        r = beta * mkt[t] + sig_i * sig_idio_mult[t] * e[t] + x
        r = np.clip(r, -0.4, 0.8)
        lpn = lpc + np.log1p(r)
        peak = np.maximum(peak - PEAK_DECAY, lpn)
        trig = alive_now & ((((peak - lpn) > DELIST_DD) & (u_del[t] < DELIST_HAZ)) | crash)
        if trig.any():
            r = np.where(trig, fin[t], r)
            lpn = lpc + np.log1p(r)
        ret[t] = np.where(alive_now, r, np.nan)
        alive[t] = alive_now
        lpc = np.where(alive_now, lpn, lpc)
        lp[t] = np.where(alive_now, lpc, np.nan)
        cs[t + 1] = cs[t] + np.where(alive_now, r, 0.0)
        alive_now = alive_now & ~trig

    close = 100.0 * np.exp(lp)
    volume = np.exp(12 + 0.8 * size + 0.25 * r_vol.standard_normal((T, N))) * (1 + 25 * np.abs(np.nan_to_num(ret)))
    volume = np.where(alive, volume, np.nan)

    sent = np.where(alive, q, np.nan)
    ret_next = np.full((T, N), np.nan)
    ret_next[:-1] = ret[1:]
    sent_rev = np.where(np.isfinite(ret_next), q + SENT_K * ret_next, np.nan)
    sent_rev = np.where(alive, sent_rev, np.nan)
    eps_rep = np.where(alive, eps_rep, np.nan)
    eps_rst = np.where(alive, eps_rst, np.nan)

    research_end = int(0.75 * T)
    # index: top 70% by size + cumulative log price, rebuilt every 63 bars, alive assets only
    cap = size[None, :] * 0.5 + lp
    member = np.zeros((T, N))
    cur = np.zeros(N)
    for t in range(T):
        if t % 63 == 0:
            c = np.where(alive[t], cap[t], -np.inf)
            k = int(0.7 * alive[t].sum())
            cur = np.zeros(N)
            if k > 0:
                cur[np.argsort(-c)[:k]] = 1.0
        member[t] = cur * alive[t]
    pit = np.where(alive, member, np.nan)
    now_row = (member[research_end - 1] > 0) & alive[research_end - 1]
    now = np.where(alive, now_row[None, :].astype(float) * np.ones((T, 1)), np.nan)

    fields = {"close": close, "ret": ret, "volume": volume, "eps_reported": eps_rep, "eps_restated": eps_rst,
              "sentiment": sent, "sentiment_revised": sent_rev, "index_member_pit": pit, "index_member_now": now}
    fields = {k: v.astype(np.float32) for k, v in fields.items()}
    asof = {k: fields[ASOF_OF.get(k, k)] for k in fields}
    for f in variant.get("backfilled", []):
        fields[f] = fields[LEAKY_OF[f]]
    survivors = alive[research_end - 1].copy()
    uni = {"all": np.ones(N, dtype=bool), "survivors": survivors}
    uni["default"] = uni[variant.get("default_universe", "all")]
    params = {"variant": variant, "effects": eff, "effect_base": BASE_EFFECTS, "mom_stress_mult": MOM_STRESS_MULT,
              "pead_days": PEAD_DAYS, "announce_jump": ANN_JUMP, "sent_k": SENT_K, "gen_version": GEN_VERSION,
              "n_delisted_research": int((~alive[research_end - 1]).sum()), "n_delisted_total": int((~alive[-1]).sum()),
              "stressed_share": float(reg.mean())}
    return fields, asof, alive, uni, reg, params, research_end


def _save(path: Path, w: World):
    arrays, names = {}, {}
    seen = {}
    for grp, d in (("f", w.fields), ("a", w.asof)):
        for k, v in d.items():
            key = seen.setdefault(id(v), f"arr{len(seen)}")
            arrays[key] = v
            names[f"{grp}:{k}"] = key
    meta = {"world_id": w.world_id, "seed": w.seed, "T": w.T, "N": w.N, "research_end": w.research_end,
            "cost_bps_true": w.cost_bps_true, "params": w.params, "names": names, "gen_version": GEN_VERSION}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, alive=w.alive, regime=w.regime, uni_all=w.universe_files["all"], uni_surv=w.universe_files["survivors"],
             meta=np.array(json.dumps(meta)), **arrays)
    tmp.replace(path)


def _load(path: Path) -> World | None:
    try:
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        if meta.get("gen_version") != GEN_VERSION:
            return None
        names = meta["names"]
        fields = {k[2:]: z[v] for k, v in names.items() if k.startswith("f:")}
        asof = {k[2:]: z[v] for k, v in names.items() if k.startswith("a:")}
        cache = {}
        for d in (fields, asof):  # restore aliasing
            for k, v in d.items():
                d[k] = cache.setdefault(names[("f:" if d is fields else "a:") + k], v)
        uni = {"all": z["uni_all"], "survivors": z["uni_surv"]}
        uni["default"] = uni[meta["params"]["variant"].get("default_universe", "all")]
        return World(meta["world_id"], meta["seed"], meta["T"], meta["N"], meta["research_end"], fields,
                     {k: dict(v) for k, v in FIELD_INFO.items()}, asof, z["alive"], uni, z["regime"],
                     meta["cost_bps_true"], meta["params"])
    except Exception:
        return None


def make_world(seed: int, *, variant: dict | None = None, T: int = 3000, N: int = 300, cache: bool = True) -> World:
    """Build a world (deterministic in seed, variant, T, N), caching it under results/cache/worlds/{world_id}.npz.
    variant keys: "backfilled": [field names whose live values become the leaky counterpart, field_info unchanged],
    "default_universe": "all" | "survivors", "effect_scale": {effect: factor} (effects: momentum, reversal, pead,
    lowvol, sentiment, runup, value, crash)."""
    v = _norm_variant(variant)
    wid = _world_id(seed, v, T, N)
    path = CACHE_DIR / f"{wid}.npz"
    if cache and path.exists():
        w = _load(path)
        if w is not None:
            return w
    fields, asof, alive, uni, reg, params, rend = _generate(seed, v, T, N)
    w = World(wid, seed, T, N, rend, fields, {k: dict(x) for k, x in FIELD_INFO.items()}, asof, alive, uni, reg,
              COST_BPS_TRUE, params)
    if cache:
        try:
            _save(path, w)
        except OSError:
            pass
    return w


def true_edge(spec, world: World, *, seeds=(101, 102, 103), period: str = "sealed") -> dict:
    """Ground truth for a StrategySpec; see court.engine.true_edge."""
    from .engine import true_edge as _te
    return _te(spec, world, seeds=seeds, period=period)
