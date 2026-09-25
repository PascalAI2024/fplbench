"""Bench order from simulated FPL autosubs.

The bench only scores through automatic substitutions, and FPL applies those
by fixed rules: each starter who plays no minutes is replaced, in pitch order,
by the first bench player (in bench order) who did play and whose arrival
keeps the formation legal. The goalkeeper slot is separate — bench slot 1 is
always the backup GK and only ever replaces the starting GK.

So ordering the three outfield subs by raw expected points is wrong in two
ways. A bench player who doesn't play is skipped at no cost, so what matters is
his points *when he plays*. And a sub who cannot legally replace the starter
most likely to miss out (a 3-at-the-back XI can only lose a defender to a
defender) is worth less than his projection says. This module scores all six
outfield orderings against the same sampled scenarios and keeps the best.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import numpy as np
import pandas as pd

from fplbench.squad import XI_DEF, XI_FWD, XI_MID

# Observed share of players who got any minutes, by projected minutes, on the
# 2025-26 holdout (outputs/predictions/val_2025-26.csv, 29.7k rows, binned).
# Even an 88-minute projection misses 3% of games.
PLAY_CURVE_MINUTES = (0.0, 10.0, 22.0, 38.0, 52.0, 65.0, 75.0, 82.0, 88.0)
PLAY_CURVE_PROB = (0.0, 0.28, 0.53, 0.73, 0.84, 0.88, 0.93, 0.94, 0.97)
# Below this a player is treated as not playing: dividing a near-zero
# expectation by a near-zero probability would invent a huge per-game score.
MIN_PLAY_PROB = 0.05
N_SAMPLES = 4000
SEED = 20260925

_BANDS = {"DEF": XI_DEF, "MID": XI_MID, "FWD": XI_FWD}


@dataclass
class BenchOrder:
    gk_id: int
    outfield_ids: list[int]
    expected_sub_points: float
    naive_sub_points: float

    @property
    def ids(self) -> list[int]:
        """Bench slots 12-15 in FPL order."""
        return [self.gk_id, *self.outfield_ids]


def play_probability(df: pd.DataFrame) -> pd.Series:
    """P(plays any minutes), from projected minutes and flagged availability."""
    if "pred_minutes" in df.columns:
        minutes = pd.to_numeric(df["pred_minutes"], errors="coerce").fillna(0.0)
        p = pd.Series(
            np.interp(minutes, PLAY_CURVE_MINUTES, PLAY_CURVE_PROB), index=df.index
        )
    else:
        p = pd.Series(1.0, index=df.index)
    if "chance_of_playing_next_round" in df.columns:
        chance = pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce")
        p = np.minimum(p, (chance.fillna(100.0) / 100.0).clip(0.0, 1.0))
    return p.where(p >= MIN_PLAY_PROB, 0.0).astype(float)


def _formation_ok(counts: dict[str, int]) -> bool:
    return all(lo <= counts.get(pos, 0) <= hi for pos, (lo, hi) in _BANDS.items())


def _autosub_points(
    xi: list[int],
    bench_outfield: list[int],
    bench_gk: int,
    played: dict[int, bool],
    pts: dict[int, float],
    position: dict[int, str],
) -> float:
    """Points the bench adds in one scenario, following FPL's autosub rules."""
    counts: dict[str, int] = {}
    for i in xi:
        counts[position[i]] = counts.get(position[i], 0) + 1
    used: set[int] = set()
    total = 0.0
    for starter in xi:
        if played[starter]:
            continue
        if position[starter] == "GK":
            if played[bench_gk]:
                total += pts[bench_gk]
            continue
        for sub in bench_outfield:
            if sub in used or not played[sub]:
                continue
            trial = dict(counts)
            trial[position[starter]] -= 1
            trial[position[sub]] = trial.get(position[sub], 0) + 1
            if _formation_ok(trial):
                counts = trial
                used.add(sub)
                total += pts[sub]
                break
    return total


def order_bench(
    squad: pd.DataFrame,
    xi_ids: list[int],
    *,
    n_samples: int = N_SAMPLES,
    seed: int = SEED,
) -> BenchOrder:
    """Best FPL bench order for a fixed XI.

    `squad` holds the 15 with `id`, `position`, `e_points_final` and,
    optionally, `pred_minutes` and `chance_of_playing_next_round`.
    """
    df = squad.set_index(squad["id"].astype(int))
    xi = [int(i) for i in xi_ids]
    bench = [int(i) for i in df.index if int(i) not in set(xi)]
    position = df["position"].astype(str).to_dict()
    gks = [i for i in bench if position[i] == "GK"]
    if len(bench) != 4 or len(gks) != 1:
        raise ValueError("bench must be 4 players including exactly one GK")
    gk = gks[0]
    outfield = [i for i in bench if i != gk]

    p = play_probability(df)
    e_pts = df["e_points_final"].astype(float)
    # Points when he plays, so each player's unconditional mean stays
    # e_points_final — the number the rest of the pipeline ranks on.
    pts = (e_pts / p.where(p > 0, 1.0)).where(p > 0, 0.0)
    if {"pred_points", "pred_defcon"} <= set(df.columns):
        # Low projected minutes are partly short cameos, not only missed
        # games, so e/p overstates a bench-warmer. A full 90 is the ceiling.
        full_game = pd.to_numeric(
            df["pred_points"], errors="coerce"
        ) + 2 * pd.to_numeric(df["pred_defcon"], errors="coerce")
        pts = np.minimum(pts, full_game.fillna(np.inf).clip(lower=e_pts))
    pts = pts.to_dict()

    ids = list(df.index)
    draws = np.random.default_rng(seed).random((n_samples, len(ids)))
    probs = p.reindex(ids).to_numpy()
    scenarios = [dict(zip(ids, row < probs, strict=True)) for row in draws]

    def score(order: list[int]) -> float:
        return float(
            np.mean(
                [_autosub_points(xi, order, gk, s, pts, position) for s in scenarios]
            )
        )

    # Points order, with anyone ruled out last: his slot is worth nothing
    # either way, but a late fitness call should not jump him up the queue.
    naive = sorted(outfield, key=lambda i: (p[i] == 0, -e_pts[i]))
    naive_score = score(naive)
    best, best_score = naive, naive_score
    for order in permutations(outfield):
        order = list(order)
        if order == naive:
            continue
        s = score(order)
        # Strictly better only: ties keep the familiar points order.
        if s > best_score + 1e-9:
            best, best_score = order, s

    return BenchOrder(
        gk_id=gk,
        outfield_ids=best,
        expected_sub_points=best_score,
        naive_sub_points=naive_score,
    )
