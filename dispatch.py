"""
dispatch.py — Co-Optimierung von PV-Eigenverbrauch und dynamischer Last-
verschiebung/Arbitrage mit EINEM geteilten Speicher.

Tägliche lineare Optimierung (scipy/HiGHS). Die LP entscheidet je Zeitschritt,
wofür jede kWh Speicher genutzt wird — Eigenverbrauch oder Netz-Arbitrage —,
sodass sich beide Nutzungen die realen Zyklen teilen (keine Doppelzählung).

WICHTIG zum Preis: Hinter dem Zähler kostet auch das Laden aus dem Netz den
Bezugspreis (nicht den nackten Börsen-Spot). Deshalb ist `import_preis` je
Zeitschritt anzugeben:
    - fixer Tarif  -> konstanter Wert (dann lohnt Netzladen praktisch nie)
    - dyn. Tarif   -> Spot + Aufschlag (Netzentgelte/Steuern/Umlagen)
Nur unter dynamischem Tarif entsteht echter Last-Shift-Wert.

Variablen je Tag (Energie kWh/Schritt, >=0):
    pv_load, pv_batt, pv_grid, grid_batt, batt_load, batt_grid, grid_load, soc
Ziel (min): grid_load*import + grid_batt*import − pv_grid*einspeise − batt_grid*verkauf
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linprog


@dataclass
class DispatchErgebnis:
    eigenverbrauch_kwh: float
    einspeisung_kwh: float
    netzbezug_kwh: float
    batt_zu_netz_kwh: float
    netz_zu_batt_kwh: float
    entladung_kwh: float            # Speicher-Durchsatz (Entladung) für Zyklen/Lebensdauer
    kosten_ohne_speicher: float     # €/a Netto-Netzkosten Basisfall
    kosten_mit_speicher: float      # €/a Netto-Netzkosten optimiert
    batteriewert: float             # €/a = Basis − optimiert (der belastbare Wert)
    ev_quote: float
    tage: int


def _tages_lp(pv, load, spot, imp, einspeise, verkauf,
              cap, p_max, dt, eta_c, eta_d):
    T = len(pv)
    idx = {name: i * T for i, name in enumerate(
        ["pv_load", "pv_batt", "pv_grid", "grid_batt",
         "batt_load", "batt_grid", "grid_load", "soc"])}
    n = 8 * T
    c = np.zeros(n)
    for t in range(T):
        c[idx["grid_load"] + t] = imp[t]
        c[idx["grid_batt"] + t] = imp[t]
        c[idx["pv_grid"] + t] = -einspeise
        c[idx["batt_grid"] + t] = -verkauf

    A_eq, b_eq = [], []
    for t in range(T):                       # PV-Bilanz
        row = np.zeros(n)
        row[idx["pv_load"] + t] = 1
        row[idx["pv_batt"] + t] = 1
        row[idx["pv_grid"] + t] = 1
        A_eq.append(row); b_eq.append(pv[t])
    for t in range(T):                       # Last-Bilanz
        row = np.zeros(n)
        row[idx["pv_load"] + t] = 1
        row[idx["batt_load"] + t] = 1
        row[idx["grid_load"] + t] = 1
        A_eq.append(row); b_eq.append(load[t])
    for t in range(T):                       # SoC-Dynamik (Start-SoC = 0)
        row = np.zeros(n)
        row[idx["soc"] + t] = 1
        if t > 0:
            row[idx["soc"] + t - 1] = -1
        row[idx["pv_batt"] + t] = -eta_c * dt
        row[idx["grid_batt"] + t] = -eta_c * dt
        row[idx["batt_load"] + t] = dt / eta_d
        row[idx["batt_grid"] + t] = dt / eta_d
        A_eq.append(row); b_eq.append(0.0)

    A_ub, b_ub = [], []                      # Leistungsgrenzen
    for t in range(T):
        r1 = np.zeros(n); r1[idx["pv_batt"] + t] = 1; r1[idx["grid_batt"] + t] = 1
        A_ub.append(r1); b_ub.append(p_max * dt)
        r2 = np.zeros(n); r2[idx["batt_load"] + t] = 1; r2[idx["batt_grid"] + t] = 1
        A_ub.append(r2); b_ub.append(p_max * dt)

    bounds = [(0, None)] * n
    for t in range(T):
        bounds[idx["soc"] + t] = (0, cap)
    bounds[idx["soc"] + T - 1] = (0, 0)      # Tagesende leer

    res = linprog(c, A_ub=np.array(A_ub), b_ub=np.array(b_ub),
                  A_eq=np.array(A_eq), b_eq=np.array(b_eq),
                  bounds=bounds, method="highs")
    if not res.success:
        pvl = np.minimum(pv, load)
        kosten = float(np.sum((load - pvl) * imp - (pv - pvl) * einspeise))
        return dict(pv_load=pvl, batt_load=np.zeros(T), pv_grid=pv - pvl,
                    grid_load=load - pvl, grid_batt=np.zeros(T),
                    batt_grid=np.zeros(T), kosten=kosten)
    x = res.x
    sl = lambda k: x[idx[k]:idx[k] + T]
    return dict(pv_load=sl("pv_load"), batt_load=sl("batt_load"),
                pv_grid=sl("pv_grid"), grid_load=sl("grid_load"),
                grid_batt=sl("grid_batt"), batt_grid=sl("batt_grid"),
                kosten=res.fun)


def co_optimiere_jahr(pv: pd.Series, load: pd.Series, spot: pd.Series,
                      import_preis, einspeise: float, verkauf: float,
                      cap_kwh: float, p_max_kw: float,
                      wirkungsgrad: float = 0.90) -> DispatchErgebnis:
    """import_preis: Series (je Zeitschritt) ODER Skalar (fixer Tarif)."""
    df = pd.concat({"pv": pv, "load": load, "spot": spot}, axis=1).dropna()
    if np.isscalar(import_preis):
        df["imp"] = float(import_preis)
    else:
        df["imp"] = pd.Series(import_preis).reindex(df.index)
    df = df.dropna()
    dt = (df.index.to_series().diff().median().total_seconds() / 3600) or 1.0
    eta = np.sqrt(wirkungsgrad)

    agg = dict(ev=0.0, ein=0.0, bez=0.0, b2n=0.0, n2b=0.0, bl=0.0, kosten=0.0, tage=0)
    for _, g in df.groupby(df.index.normalize()):
        if len(g) < 2:
            continue
        r = _tages_lp(g["pv"].values, g["load"].values, g["spot"].values,
                      g["imp"].values, einspeise, verkauf,
                      cap_kwh, p_max_kw, dt, eta, eta)
        agg["ev"] += float(np.sum(r["pv_load"]) + np.sum(r["batt_load"]))
        agg["ein"] += float(np.sum(r["pv_grid"]))
        agg["bez"] += float(np.sum(r["grid_load"]))
        agg["b2n"] += float(np.sum(r["batt_grid"]))
        agg["bl"] += float(np.sum(r["batt_load"]))
        agg["n2b"] += float(np.sum(r["grid_batt"]))
        agg["kosten"] += float(r["kosten"])
        agg["tage"] += 1

    pvl = np.minimum(df["pv"].values, df["load"].values)
    kosten_basis = float(np.sum((df["load"].values - pvl) * df["imp"].values
                                - (df["pv"].values - pvl) * einspeise))
    erzeugung = float(df["pv"].sum())
    return DispatchErgebnis(
        eigenverbrauch_kwh=agg["ev"], einspeisung_kwh=agg["ein"],
        netzbezug_kwh=agg["bez"], batt_zu_netz_kwh=agg["b2n"],
        netz_zu_batt_kwh=agg["n2b"],
        entladung_kwh=agg["bl"] + agg["b2n"],
        kosten_ohne_speicher=kosten_basis, kosten_mit_speicher=agg["kosten"],
        batteriewert=kosten_basis - agg["kosten"],
        ev_quote=agg["ev"] / erzeugung if erzeugung else 0.0, tage=agg["tage"])
