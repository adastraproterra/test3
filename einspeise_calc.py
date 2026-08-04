"""
einspeise_calc.py — Rechenkern für die "Einspeisung-ist-marginal"-Entscheidung.

Beantwortet für eine PV-Anlage (+ optional Speicher) die Frage, was der
Überschussstrom noch wert ist und ob sich ein Speicher lohnt — über vier
Einspeise-Modi, die dieselbe Engine bedienen:

    ALTTARIF        fixe EEG-Vergütung einer Bestandsanlage (Nutzer trägt ct/kWh ein)
    UEBERGANG_2027  3-Jahres-Übergangszahlung für Neuanlagen ab 2027 (ENTWURF)
    ANSCHLUSS_UE20  Ü20-Anschlussvergütung: Jahresmarktwert Solar minus Pauschale
    DIREKTVERMARKTUNG  sonstige Direktvermarktung: Marktwert minus Vermarkter-Gebühr

FAKTEN (Regulatorik, Stand 2026) sind als Defaults hinterlegt und
kommentiert; MODELL-SCHÄTZUNGEN (Ertrag, Eigenverbrauchsquote, Speicher-
nutzung, Preise, Kapitalkosten) sind Eingaben und klar als solche markiert.
Alle Fakten sind Planungs-/Rechtsstand und können sich ändern — der
UEBERGANG_2027-Modus beruht auf einem Kabinettsentwurf, nicht auf geltendem Recht.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# FAKTEN — Regulatorik-Defaults (Stand 2026). Quelle in Kommentar.
# ---------------------------------------------------------------------------

class Modus(str, Enum):
    ALTTARIF = "Fixer Alttarif (Bestandsanlage)"
    UEBERGANG_2027 = "Übergangszahlung Neuanlage ab 2027 (Entwurf)"
    ANSCHLUSS_UE20 = "Ü20-Anschlussvergütung"
    DIREKTVERMARKTUNG = "Sonstige Direktvermarktung"


# Jahresmarktwert Solar (€/kWh). FAKT: 2024 ~0,0462 / 2025 ~0,0451.
JAHRESMARKTWERT_SOLAR_2025 = 0.0451
# Vermarktungspauschale Anschlussvergütung (€/kWh). FAKT: 2026 = 0,0023.
ANSCHLUSS_PAUSCHALE_2026 = 0.0023
# Deckel Anschlussvergütung (€/kWh). FAKT: max. 0,10.
ANSCHLUSS_DECKEL = 0.10
# Übergangszahlung Neuanlage ab 2027 (€/kWh) — ENTWURF, Quellen streuen
# (5,2–6,2 ct netto). Default konservativ. Dauer: 36 Monate.
UEBERGANG_SATZ_2027 = 0.052
UEBERGANG_MONATE = 36
# 50%-Einspeisedeckel auf Nennleistung für Neuanlagen ab 2027 (ENTWURF):
# hier als optionaler, vom Nutzer schätzbarer Energie-Clip modelliert
# (Default 0 = nicht angesetzt), NICHT als exakte Leistungssimulation.


def einspeisesatz(modus: Modus,
                  alttarif: float = 0.0,
                  marktwert_solar: float = JAHRESMARKTWERT_SOLAR_2025,
                  dv_gebuehr_anteil: float = 0.30) -> float:
    """Netto-Erlös je eingespeiste kWh (€/kWh) für den gewählten Modus.

    alttarif            : nur ALTTARIF — die fixe EEG-Vergütung des Nutzers.
    marktwert_solar     : Jahresmarktwert Solar (SCHÄTZUNG/aktueller Wert).
    dv_gebuehr_anteil   : Anteil, den der Direktvermarkter vom Marktwert
                          einbehält (SCHÄTZUNG; laut Fraunhofer bei Klein-
                          anlagen bis ~0,69).
    """
    if modus == Modus.ALTTARIF:
        return alttarif
    if modus == Modus.UEBERGANG_2027:
        return UEBERGANG_SATZ_2027
    if modus == Modus.ANSCHLUSS_UE20:
        return min(max(marktwert_solar - ANSCHLUSS_PAUSCHALE_2026, 0.0),
                   ANSCHLUSS_DECKEL)
    if modus == Modus.DIREKTVERMARKTUNG:
        return max(marktwert_solar * (1.0 - dv_gebuehr_anteil), 0.0)
    raise ValueError(modus)


# ---------------------------------------------------------------------------
# EINGABEN (Modell-Schätzungen, vom Nutzer wählbar)
# ---------------------------------------------------------------------------

@dataclass
class Anlage:
    kwp: float = 6.0                    # installierte Leistung
    spez_ertrag: float = 950.0         # kWh/kWp/a (Westerwald ~950; SCHÄTZUNG)
    verbrauch_kwh: float = 4000.0      # Jahresverbrauch
    basis_ev_quote: float = 0.28       # Eigenverbrauchsquote OHNE Speicher (SCHÄTZUNG)
    strompreis_bezug: float = 0.34     # €/kWh Netzbezug (der eigentliche Hebel)
    einspeise_clip_anteil: float = 0.0 # Anteil Überschuss, der durch 50%-Deckel
                                       # verloren geht (nur Neuanlage 2027+; SCHÄTZUNG)
    ev_direkt_kwh: float | None = None # optional: exakter direkter Eigenverbrauch
                                       # (kWh, aus Profil-Simulation) — überschreibt
                                       # basis_ev_quote, wenn gesetzt.

    @property
    def erzeugung_kwh(self) -> float:
        return self.kwp * self.spez_ertrag


@dataclass
class Speicher:
    nutzbar_kwh: float = 0.0           # nutzbare Kapazität (nach DoD)
    wirkungsgrad: float = 0.90         # Round-Trip
    nutzungsfaktor: float = 0.70       # mittlere Zyklen-Ausnutzung übers Jahr (SCHÄTZUNG)
    capex: float = 0.0                 # Investition inkl. Einbau
    zyklen_pro_jahr: int = 300         # nur informativ
    geliefert_kwh: float | None = None # optional: exakte Speicher-Lieferung an die
                                       # Last (kWh, aus Profil-Simulation) — überschreibt
                                       # das Nutzungsfaktor-Modell, wenn gesetzt.

    @property
    def aktiv(self) -> bool:
        return self.nutzbar_kwh > 0


# ---------------------------------------------------------------------------
# JAHRESBILANZ
# ---------------------------------------------------------------------------

@dataclass
class Bilanz:
    erzeugung: float
    eigenverbrauch: float
    eingespeist: float
    ev_quote: float
    wert_eigenverbrauch: float
    wert_einspeisung: float
    nutzen_gesamt: float
    einspeisesatz: float


def jahresbilanz(anlage: Anlage, speicher: Speicher, modus: Modus,
                 alttarif: float = 0.0,
                 marktwert_solar: float = JAHRESMARKTWERT_SOLAR_2025,
                 dv_gebuehr_anteil: float = 0.30) -> Bilanz:
    """Energie- und Geldbilanz für ein Jahr (Jahr 1, ohne Degradation)."""
    G = anlage.erzeugung_kwh
    C = anlage.verbrauch_kwh
    satz = einspeisesatz(modus, alttarif, marktwert_solar, dv_gebuehr_anteil)

    # Direkter Eigenverbrauch (ohne Speicher). Exakt aus Profil-Simulation,
    # falls gesetzt — sonst über die geschätzte Quote.
    if anlage.ev_direkt_kwh is not None:
        direkt = min(anlage.ev_direkt_kwh, C, G)
    else:
        direkt = min(anlage.basis_ev_quote * G, C)
    ueberschuss = max(G - direkt, 0.0)
    rest_verbrauch = max(C - direkt, 0.0)

    # Speicher: exakte Lieferung aus Simulation, sonst Nutzungsfaktor-Modell.
    if speicher.aktiv:
        if speicher.geliefert_kwh is not None:
            geliefert = min(speicher.geliefert_kwh, ueberschuss * speicher.wirkungsgrad,
                            rest_verbrauch)
        else:
            potenzial = speicher.nutzbar_kwh * 365 * speicher.nutzungsfaktor
            geliefert = min(potenzial,
                            ueberschuss * speicher.wirkungsgrad,
                            rest_verbrauch)
        ladeenergie = geliefert / speicher.wirkungsgrad
    else:
        geliefert = 0.0
        ladeenergie = 0.0

    eigenverbrauch = direkt + geliefert
    eingespeist = max(ueberschuss - ladeenergie, 0.0)

    # Optionaler 50%-Einspeisedeckel (Neuanlage 2027+): Teil des Überschusses
    # wird abgeregelt und bringt keinen Erlös.
    eingespeist *= (1.0 - anlage.einspeise_clip_anteil)

    wert_ev = eigenverbrauch * anlage.strompreis_bezug   # vermiedener Netzbezug
    wert_ein = eingespeist * satz
    return Bilanz(
        erzeugung=G,
        eigenverbrauch=eigenverbrauch,
        eingespeist=eingespeist,
        ev_quote=eigenverbrauch / G if G else 0.0,
        wert_eigenverbrauch=wert_ev,
        wert_einspeisung=wert_ein,
        nutzen_gesamt=wert_ev + wert_ein,
        einspeisesatz=satz,
    )


# ---------------------------------------------------------------------------
# SPEICHER-ENTSCHEIDUNG
# ---------------------------------------------------------------------------

@dataclass
class SpeicherKennzahlen:
    jahresnutzen: float          # €/a Mehrwert des Speichers (Jahr 1)
    delta_je_kwh: float          # €/kWh: Strompreis - Einspeisesatz (der Kern)
    verschobene_kwh: float       # kWh/a, die vom Einspeisen ins Eigen wandern
    amortisation_jahre: float    # einfache Amortisation (inf, wenn <=0)
    npv: float                   # Kapitalwert über Horizont
    lohnt: bool


def speicher_kennzahlen(anlage: Anlage, speicher: Speicher, modus: Modus,
                        alttarif: float = 0.0,
                        marktwert_solar: float = JAHRESMARKTWERT_SOLAR_2025,
                        dv_gebuehr_anteil: float = 0.30,
                        horizont_jahre: int = 15,
                        diskont: float = 0.03,
                        degradation: float = 0.01,
                        strompreis_steigerung: float = 0.02) -> SpeicherKennzahlen:
    ohne = jahresbilanz(anlage, Speicher(), modus, alttarif, marktwert_solar, dv_gebuehr_anteil)
    mit = jahresbilanz(anlage, speicher, modus, alttarif, marktwert_solar, dv_gebuehr_anteil)

    jahresnutzen = mit.nutzen_gesamt - ohne.nutzen_gesamt
    verschobene = mit.eigenverbrauch - ohne.eigenverbrauch
    delta_je_kwh = anlage.strompreis_bezug - ohne.einspeisesatz

    amort = speicher.capex / jahresnutzen if jahresnutzen > 0 else float("inf")

    # NPV: Nutzen wächst mit Strompreis, sinkt mit Speicher-Degradation.
    npv = -speicher.capex
    for jahr in range(1, horizont_jahre + 1):
        faktor = ((1 + strompreis_steigerung) ** (jahr - 1)) * ((1 - degradation) ** (jahr - 1))
        npv += (jahresnutzen * faktor) / ((1 + diskont) ** jahr)

    return SpeicherKennzahlen(
        jahresnutzen=jahresnutzen,
        delta_je_kwh=delta_je_kwh,
        verschobene_kwh=verschobene,
        amortisation_jahre=amort,
        npv=npv,
        lohnt=npv > 0,
    )


# ---------------------------------------------------------------------------
# VERGLEICH ÜBER MODI
# ---------------------------------------------------------------------------

def vergleich_modi(anlage: Anlage, speicher: Speicher,
                   alttarif: float = 0.0,
                   marktwert_solar: float = JAHRESMARKTWERT_SOLAR_2025,
                   dv_gebuehr_anteil: float = 0.30) -> dict[Modus, Bilanz]:
    """Jahresbilanz je Einspeise-Modus (mit dem gewählten Speicher)."""
    return {
        m: jahresbilanz(anlage, speicher, m, alttarif, marktwert_solar, dv_gebuehr_anteil)
        for m in Modus
    }


# ---------------------------------------------------------------------------
# ZEITPFAD (Neuanlage 2027: 36 Monate Übergang -> danach Direktvermarktung)
# ---------------------------------------------------------------------------
# Trick: jahresbilanz akzeptiert über Modus.ALTTARIF einen beliebigen festen
# Einspeisesatz. Damit lässt sich jeder Jahressatz einspeisen, ohne die Engine
# zu ändern.

def zeitpfad_2027_saetze(horizont_jahre: int, dv_satz: float,
                         uebergang_satz: float = UEBERGANG_SATZ_2027) -> list[float]:
    """Einspeisesatz je Jahr: Jahre 1-3 Übergangszahlung, ab Jahr 4 DV-Satz."""
    monate_uebergang = UEBERGANG_MONATE
    saetze = []
    for j in range(1, horizont_jahre + 1):
        voll_uebergang = j * 12 <= monate_uebergang
        if voll_uebergang:
            saetze.append(uebergang_satz)
        elif (j - 1) * 12 < monate_uebergang:      # Mischjahr
            anteil = (monate_uebergang - (j - 1) * 12) / 12.0
            saetze.append(anteil * uebergang_satz + (1 - anteil) * dv_satz)
        else:
            saetze.append(dv_satz)
    return saetze


@dataclass
class ZeitpfadErgebnis:
    npv_speicher: float
    npv_gesamtnutzen_ohne_speicher: float
    npv_gesamtnutzen_mit_speicher: float
    jahresnutzen_speicher: list[float]
    einspeisesatz_pro_jahr: list[float]
    saetze: list[float]


def wirtschaftlichkeit_zeitpfad(anlage: Anlage, speicher: Speicher,
                                saetze_pro_jahr: list[float],
                                diskont: float = 0.03,
                                degradation: float = 0.01,
                                strompreis_steigerung: float = 0.02,
                                arbitrage_jahreswert: float = 0.0) -> ZeitpfadErgebnis:
    """NPV mit jahresweise variierendem Einspeisesatz (z. B. 2027-Pfad).

    arbitrage_jahreswert: optionaler zusätzlicher €/a-Strom aus Netz-Arbitrage
    (nur mit Speicher), degradiert wie der Speichernutzen.
    """
    npv_sp = -speicher.capex
    npv_ohne = 0.0
    npv_mit = 0.0
    jn, esatz = [], []

    for i, satz in enumerate(saetze_pro_jahr, start=1):
        preis_faktor = (1 + strompreis_steigerung) ** (i - 1)
        degr_faktor = (1 - degradation) ** (i - 1)
        disk = (1 + diskont) ** i

        a = Anlage(kwp=anlage.kwp, spez_ertrag=anlage.spez_ertrag,
                   verbrauch_kwh=anlage.verbrauch_kwh,
                   basis_ev_quote=anlage.basis_ev_quote,
                   strompreis_bezug=anlage.strompreis_bezug * preis_faktor,
                   einspeise_clip_anteil=anlage.einspeise_clip_anteil)

        ohne = jahresbilanz(a, Speicher(), Modus.ALTTARIF, alttarif=satz)
        # Speicherbeitrag mit Degradation über reduzierte Kapazität abbilden.
        sp = Speicher(nutzbar_kwh=speicher.nutzbar_kwh * degr_faktor,
                      wirkungsgrad=speicher.wirkungsgrad,
                      nutzungsfaktor=speicher.nutzungsfaktor, capex=0.0)
        mit = jahresbilanz(a, sp, Modus.ALTTARIF, alttarif=satz)

        arb = arbitrage_jahreswert * degr_faktor if speicher.aktiv else 0.0
        nutzen_speicher = (mit.nutzen_gesamt - ohne.nutzen_gesamt) + arb

        npv_ohne += ohne.nutzen_gesamt / disk
        npv_mit += (mit.nutzen_gesamt + arb) / disk
        npv_sp += nutzen_speicher / disk
        jn.append(nutzen_speicher)
        esatz.append(satz)

    return ZeitpfadErgebnis(
        npv_speicher=npv_sp,
        npv_gesamtnutzen_ohne_speicher=npv_ohne,
        npv_gesamtnutzen_mit_speicher=npv_mit,
        jahresnutzen_speicher=jn,
        einspeisesatz_pro_jahr=esatz,
        saetze=saetze_pro_jahr,
    )
