"""Official FPL DefCon labels. Do not invent thresholds."""

import pandas as pd

from fplbench.paths import DEFCON_DEF_THRESHOLD, DEFCON_OUTFIELD_THRESHOLD


def defcon_count(position: pd.Series, cbit: pd.Series, recoveries: pd.Series) -> pd.Series:
    pos = position.astype(str).str.upper()
    cbit = pd.to_numeric(cbit, errors="coerce")
    rec = pd.to_numeric(recoveries, errors="coerce").fillna(0)
    count = cbit.copy()
    outfield = pos.isin(["MID", "FWD"])
    count = count.where(~outfield, cbit + rec)
    count = count.where(~pos.eq("GK"), pd.NA)
    return count


def defcon_hit(position: pd.Series, cbit: pd.Series, recoveries: pd.Series) -> pd.Series:
    pos = position.astype(str).str.upper()
    count = defcon_count(position, cbit, recoveries)
    hit = pd.Series(pd.NA, index=position.index, dtype="Float64")
    def_mask = pos.eq("DEF") & count.notna()
    midfwd = pos.isin(["MID", "FWD"]) & count.notna()
    hit.loc[def_mask] = (count.loc[def_mask] >= DEFCON_DEF_THRESHOLD).astype(float)
    hit.loc[midfwd] = (count.loc[midfwd] >= DEFCON_OUTFIELD_THRESHOLD).astype(float)
    hit.loc[pos.eq("GK")] = 0.0
    return hit
