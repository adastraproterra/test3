"""
smard.py — SMARD-Großhandelspreise einlesen und daraus Werte ableiten.

Reiner Rechenteil (nur pandas), damit er testbar bleibt und die
Streamlit-Caching-Schicht im UI liegt. Ausgelegt auf den deutschen
SMARD-CSV-Export (Semikolon-getrennt, Dezimalkomma, DD.MM.YYYY-Datum,
Preis in €/MWh). Der Parser erkennt Zeit- und Preisspalte heuristisch;
bei einem abweichenden Export lässt sich die Preisspalte explizit setzen.
"""

from __future__ import annotations
from dataclasses import dataclass

import pandas as pd


@dataclass
class SpotReihe:
    preise: pd.Series          # €/kWh, Index = Zeitstempel, native Auflösung
    aufloesung_min: int        # 15 oder 60
    quelle: str                # Dateiname/Hinweis

    @property
    def mittel(self) -> float:
        return float(self.preise.mean())

    @property
    def anteil_negativ(self) -> float:
        return float((self.preise < 0).mean())


def _erkenne_sep(pfad: str) -> str:
    with open(pfad, "r", encoding="utf-8-sig", errors="replace") as f:
        kopf = f.readline()
    return ";" if kopf.count(";") >= kopf.count(",") else ","


def parse_smard_csv(pfad: str, preis_spalte: str | None = None) -> SpotReihe:
    """Liest eine SMARD-CSV und gibt eine Preisreihe in €/kWh zurück."""
    sep = _erkenne_sep(pfad)
    df = pd.read_csv(pfad, sep=sep, dtype=str, encoding="utf-8-sig",
                     keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    # --- Zeitspalte: erste Spalte, die als Datum (dayfirst) parsebar ist ------
    zeit = None
    for c in df.columns:
        probe = pd.to_datetime(df[c].str.strip(), dayfirst=True, errors="coerce")
        if probe.notna().mean() > 0.9:
            zeit = probe
            break
    if zeit is None:
        raise ValueError("Keine Datums-/Zeitspalte erkannt.")

    # --- Preisspalte: bevorzugt DE/LU bzw. €/MWh, sonst beste numerische ------
    def to_num(s: pd.Series) -> pd.Series:
        s = (s.str.strip()
               .str.replace(".", "", regex=False)   # Tausenderpunkt
               .str.replace(",", ".", regex=False))  # Dezimalkomma
        s = s.replace({"-": None, "": None})
        return pd.to_numeric(s, errors="coerce")

    if preis_spalte and preis_spalte in df.columns:
        preise = to_num(df[preis_spalte])
    else:
        kandidaten = [c for c in df.columns
                      if any(k in c.lower() for k in
                             ("deutschland/luxemburg", "de/lu", "€/mwh", "eur/mwh"))]
        if not kandidaten:  # Fallback: numerischste Spalte
            kandidaten = sorted(
                (c for c in df.columns),
                key=lambda c: to_num(df[c]).notna().mean(), reverse=True)[:1]
        preise = to_num(df[kandidaten[0]])
        preis_spalte = kandidaten[0]

    s = pd.Series(preise.values, index=zeit).dropna().sort_index()
    if s.empty:
        raise ValueError("Preisspalte enthält keine gültigen Werte.")

    # €/MWh -> €/kWh, falls Größenordnung darauf hindeutet.
    if s.abs().median() > 5:
        s = s / 1000.0

    diffs = s.index.to_series().diff().dropna()
    aufl = int(round(diffs.median().total_seconds() / 60)) if not diffs.empty else 60
    return SpotReihe(preise=s, aufloesung_min=aufl, quelle=pfad.split("/")[-1])


# ---------------------------------------------------------------------------
# Aus Spot abgeleitete Werte
# ---------------------------------------------------------------------------

def marktwert_aus_spot(spot: SpotReihe, profilfaktor: float = 0.50) -> float:
    """Marktwert Solar (€/kWh) ≈ mittlerer Spotpreis × Profilfaktor.

    profilfaktor: FAKT-nah — Solar erzeugt v.a. zu Niedrigpreiszeiten;
    2025 lag der Profilfaktor bei ~0,505. SCHÄTZUNG/anpassbar. Wer ein
    PV-Erzeugungsprofil hat, sollte stattdessen erzeugungsgewichtet mitteln.
    """
    return spot.mittel * profilfaktor


@dataclass
class ArbitrageErgebnis:
    jahreswert: float          # €/a
    mittlerer_spread: float    # €/kWh (Entlade- minus Ladefenster, Tagesmittel)
    tage: int


def arbitrage_jahreswert(spot: SpotReihe,
                         nutzbar_kwh: float,
                         wirkungsgrad: float = 0.90,
                         lade_stunden: float = 3.0,
                         entlade_stunden: float = 3.0,
                         ausschoepfung: float = 0.80,
                         zyklen_pro_tag: int = 1) -> ArbitrageErgebnis:
    """Wert einer Netz-Arbitrage aus realem Spot: pro Tag die günstigsten
    Ladefenster gegen die teuersten Entladefenster, ein (oder mehr) Zyklus/Tag.

    Achtung: konkurriert mit PV-Eigenverbrauch (dieselben Zyklen können nicht
    doppelt genutzt werden) — hier als eigenständige Obergrenze zu verstehen.
    """
    pro_stunde = 60 / spot.aufloesung_min           # Slots je Stunde
    n_lade = max(int(round(lade_stunden * pro_stunde)), 1)
    n_entlade = max(int(round(entlade_stunden * pro_stunde)), 1)

    df = spot.preise.to_frame("p")
    df["tag"] = df.index.normalize()
    tages_spreads = []
    for _, g in df.groupby("tag"):
        p = g["p"].sort_values()
        if len(p) < n_lade + n_entlade:
            continue
        lade = p.iloc[:n_lade].mean()
        entlade = p.iloc[-n_entlade:].mean()
        tages_spreads.append(max(entlade - lade, 0.0))

    if not tages_spreads:
        return ArbitrageErgebnis(0.0, 0.0, 0)

    spread = sum(tages_spreads) / len(tages_spreads)
    # Gelieferte Energie/Tag = nutzbar × Ausschöpfung × Zyklen; Verlust über eta.
    energie_pro_tag = nutzbar_kwh * ausschoepfung * zyklen_pro_tag
    wert = sum(s * energie_pro_tag * wirkungsgrad for s in tages_spreads)
    return ArbitrageErgebnis(jahreswert=wert, mittlerer_spread=spread,
                             tage=len(tages_spreads))
