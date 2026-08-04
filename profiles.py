"""
profiles.py — Zeitaufgelöste PV- und Lastprofile (SCHÄTZUNG).

Für die Co-Optimierung braucht man PV und Last je Zeitschritt, nicht nur
Jahressummen. Beide Profile sind synthetisch (typisierte Tages-/Saisonform)
und auf die Jahressumme skaliert. Wer echte Profile hat (PVGIS für PV,
gemessenes Lastprofil), sollte sie hier einspeisen — die Form ist der einzige
Schätzanteil, die Skalierung ist exakt.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def pv_profil(index: pd.DatetimeIndex, jahres_kwh: float) -> pd.Series:
    """Normiertes PV-Erzeugungsprofil (kWh je Zeitschritt), Summe = jahres_kwh."""
    h = index.hour + index.minute / 60.0
    doy = index.dayofyear.values
    # Tageslichtlänge saisonal (Winter ~8 h, Sommer ~16 h)
    taglicht = 12 - 4 * np.cos(2 * np.pi * (doy - 172) / 365)  # Max um Sommersonnenwende
    sonnenaufgang = 12 - taglicht / 2
    sonnenuntergang = 12 + taglicht / 2
    # Halbwellen-Sinus während Tageslicht
    x = (h - sonnenaufgang) / np.maximum(sonnenuntergang - sonnenaufgang, 1e-6)
    form = np.where((x > 0) & (x < 1), np.sin(np.pi * x), 0.0)
    # Saisonale Amplitude (Sommer ergiebiger)
    amp = 0.6 + 0.4 * (1 - np.cos(2 * np.pi * (doy - 172) / 365)) / 2
    roh = form * amp
    s = pd.Series(roh, index=index)
    total = s.sum()
    return s * (jahres_kwh / total) if total > 0 else s


def last_profil(index: pd.DatetimeIndex, jahres_kwh: float) -> pd.Series:
    """H0-ähnliches Haushalts-Lastprofil (kWh je Zeitschritt), Summe = jahres_kwh."""
    h = index.hour + index.minute / 60.0
    # Grundlast + Morgen- und Abendspitze
    grund = 0.35
    morgen = 0.5 * np.exp(-((h - 7.5) ** 2) / 3)
    abend = 1.0 * np.exp(-((h - 19.5) ** 2) / 6)
    mittag = 0.25 * np.exp(-((h - 13) ** 2) / 4)
    roh = grund + morgen + abend + mittag
    # Wochenende etwas flacher/höher tagsüber
    we = index.dayofweek.values >= 5
    roh = np.where(we, roh * 1.05, roh)
    s = pd.Series(roh, index=index)
    total = s.sum()
    return s * (jahres_kwh / total) if total > 0 else s
