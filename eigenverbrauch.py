"""
eigenverbrauch.py — Präzise Eigenverbrauchs-Simulation aus PV-/Lastprofil.

Regelbasierte Stundensimulation (kein LP, kein scipy): PV deckt zuerst die
Last, Überschuss lädt den Speicher, der Speicher deckt zeitversetzt die
Restlast. Liefert den exakten Eigenverbrauch mit/ohne Speicher aus der
tatsächlichen zeitlichen Überlappung — statt aus einer geschätzten Quote.

Das ist die genauere Alternative zur pauschalen Eigenverbrauchsquote: Die
Quote hängt real an der Deckung von Erzeugungs- und Lastprofil und an der
Speichergröße, was ein einzelner Jahreswert nicht abbildet.
"""

from __future__ import annotations
from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

from profiles import pv_profil, last_profil


@dataclass
class EVErgebnis:
    erzeugung_kwh: float
    ev_direkt_kwh: float          # PV direkt in die Last (ohne Speicher)
    ev_speicher_kwh: float        # zusätzlich über den Speicher
    einspeisung_kwh: float        # Rest ins Netz
    entladung_kwh: float          # Speicher-Durchsatz (= ev_speicher_kwh)
    ev_quote_ohne: float
    ev_quote_mit: float


def simuliere(pv: pd.Series, load: pd.Series, nutzbar_kwh: float,
              wirkungsgrad: float = 0.90, p_max_kw: float = 3.0) -> EVErgebnis:
    """Stundenweise Regel-Simulation über die gegebenen Profile."""
    dt = (pv.index.to_series().diff().median().total_seconds() / 3600) or 1.0
    eta = sqrt(wirkungsgrad)
    p_step = p_max_kw * dt                     # max. Energie je Schritt

    pv_v = pv.values
    load_v = load.reindex(pv.index).fillna(0).values

    soc = 0.0
    ev_direkt = ev_batt = einspeisung = 0.0
    for pv_t, load_t in zip(pv_v, load_v):
        direkt = min(pv_t, load_t)
        ev_direkt += direkt
        surplus = pv_t - direkt
        rest = load_t - direkt
        # Laden aus Überschuss (Leistungs- und Kapazitätsgrenze)
        if nutzbar_kwh > 0 and surplus > 0:
            laden = min(surplus, p_step, (nutzbar_kwh - soc) / eta)
            soc += laden * eta
            surplus -= laden
        einspeisung += max(surplus, 0.0)
        # Entladen in die Restlast
        if nutzbar_kwh > 0 and rest > 0 and soc > 0:
            entladen = min(rest, p_step, soc * eta)
            soc -= entladen / eta
            ev_batt += entladen

    G = float(pv_v.sum())
    return EVErgebnis(
        erzeugung_kwh=G,
        ev_direkt_kwh=ev_direkt,
        ev_speicher_kwh=ev_batt,
        einspeisung_kwh=einspeisung,
        entladung_kwh=ev_batt,
        ev_quote_ohne=ev_direkt / G if G else 0.0,
        ev_quote_mit=(ev_direkt + ev_batt) / G if G else 0.0,
    )


def simuliere_aus_jahreswerten(kwp: float, spez_ertrag: float, verbrauch_kwh: float,
                               nutzbar_kwh: float, wirkungsgrad: float = 0.90,
                               p_max_kw: float = 3.0,
                               stunden_index: pd.DatetimeIndex | None = None) -> EVErgebnis:
    """Baut synthetische Stundenprofile aus Jahreswerten und simuliert.

    Ohne echten Zeitindex wird ein Standard-Jahr (stündlich) erzeugt. Echte
    PVGIS-/Lastprofile lassen sich über simuliere() direkt einspeisen.
    """
    if stunden_index is None:
        stunden_index = pd.date_range("2024-01-01 00:00", periods=8760, freq="h")
    pv = pv_profil(stunden_index, kwp * spez_ertrag)
    load = last_profil(stunden_index, verbrauch_kwh)
    return simuliere(pv, load, nutzbar_kwh, wirkungsgrad, p_max_kw)
