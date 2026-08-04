"""
technologie.py — Speichertechnologien (LFP / Natrium-Ionen) und die Über-
führung des co-optimierten Jahreswerts in NPV / Amortisation.

Die Technologie-Defaults sind der Stand 2026 — mit klarer Trennung:
FAKT-nah ist die *Richtung* der Unterschiede (LFP mehr Zyklen & ausgereift;
Na-Ion kältefester, materialunabhängig, Kostenvorteil noch prospektiv).
Die konkreten Zahlen streuen je Quelle/Zelle stark und sind SCHÄTZUNGEN —
alle Felder sind überschreibbar.

Der wirtschaftlich entscheidende Hebel im Vergleich ist die Lebensdauer:
Aus dem Dispatch-Durchsatz folgt die Zyklenzahl/Jahr; unterschreitet die
resultierende Lebensdauer den Horizont, fällt ein Ersatz-Capex an.
"""

from __future__ import annotations
from dataclasses import dataclass
from math import ceil


@dataclass
class Technologie:
    name: str
    wirkungsgrad: float          # Round-Trip (SCHÄTZUNG)
    capex_eur_kwh: float         # installierte Kosten je kWh nutzbar (SCHÄTZUNG)
    zyklen_lebensdauer: int      # Vollzyklen bis EoL (SCHÄTZUNG)
    kalender_jahre: int          # kalendarische Lebensdauer (SCHÄTZUNG)
    degradation_pa: float        # jährlicher Kapazitätsverlust (SCHÄTZUNG)
    hinweis: str                 # qualitative, FAKT-nahe Einordnung


# Stand 2026 — Defaults konservativ, bewusst überschreibbar.
LFP = Technologie(
    name="Lithium (LFP)",
    wirkungsgrad=0.92,
    capex_eur_kwh=450.0,
    zyklen_lebensdauer=6000,
    kalender_jahre=15,
    degradation_pa=0.01,
    hinweis="Ausgereift, tiefe Lieferkette, viele zertifizierte Heimspeicher. "
            "Hohe Zyklenzahl -> stark bei täglichem Zyklen. Schwächelt < -10 °C.",
)

NATRIUM = Technologie(
    name="Natrium-Ionen (Na-Ion)",
    wirkungsgrad=0.90,
    capex_eur_kwh=440.0,
    zyklen_lebensdauer=4000,       # Standardzellen; Premium (Naxtra) bis ~10000
    kalender_jahre=13,
    degradation_pa=0.012,
    hinweis="Kältefest (-30/-40 °C), ohne Lithium/Kobalt/Nickel, 0-V-transportfähig. "
            "Kostenvorteil noch prospektiv (2027+), heute Preis ~parität. "
            "Wohn-Segment noch dünn (wenige zertifizierte Produkte).",
)

REVOLTA = Technologie(
    name="Na-Ion HV (Revolta)",
    wirkungsgrad=0.91,             # Herstellerclaim „geringe Umwandlungsverluste" — SCHÄTZUNG
    capex_eur_kwh=460.0,           # NICHT veröffentlicht — Platzhalter, SCHÄTZUNG
    zyklen_lebensdauer=4000,       # nicht veröffentlicht — Na-Ion-typisch angenommen
    kalender_jahre=13,
    degradation_pa=0.012,
    hinweis="Na-Ionen-Produkt (Startup Frankfurt), Hochvolt 450 V, modular 2–20 kWh, "
            "Spannungsmultiplikator (wenige großformatige Zellen), hohe thermische "
            "Stabilität. VORMARKTLICH (Warteliste/Piloten) — η, Zyklen, Preis sind "
            "Herstellerangaben/Schätzungen ohne Feldstand.",
)

PRESETS = {LFP.name: LFP, NATRIUM.name: NATRIUM, REVOLTA.name: REVOLTA}


@dataclass
class InvestErgebnis:
    npv: float
    amortisation_jahre: float
    zyklen_pro_jahr: float
    lebensdauer_jahre: float
    ersatz_jahre: list[int]
    capex_gesamt_barwert: float


def npv_speicher(jahreswert: float,
                 entladung_kwh: float,
                 nutzbar_kwh: float,
                 tech: Technologie,
                 horizont_jahre: int = 15,
                 diskont: float = 0.03,
                 strompreis_steigerung: float = 0.02,
                 capex_ruckgang_pa: float = 0.03) -> InvestErgebnis:
    """Wandelt den (co-optimierten) Jahreswert in NPV/Amortisation.

    entladung_kwh : jährlicher Speicher-Durchsatz aus dem Dispatch.
    capex_ruckgang_pa : erwarteter Preisrückgang für Ersatzbeschaffung.
    """
    capex0 = tech.capex_eur_kwh * nutzbar_kwh
    zyklen_pa = entladung_kwh / nutzbar_kwh if nutzbar_kwh else 0.0
    lebensdauer = min(tech.kalender_jahre,
                      tech.zyklen_lebensdauer / zyklen_pa) if zyklen_pa else tech.kalender_jahre

    # Ersatzzeitpunkte innerhalb des Horizonts
    ersatz_jahre, t = [], lebensdauer
    while t < horizont_jahre:
        ersatz_jahre.append(int(ceil(t)))
        t += lebensdauer

    npv = -capex0
    capex_barwert = capex0
    for jahr in range(1, horizont_jahre + 1):
        faktor = ((1 + strompreis_steigerung) ** (jahr - 1)
                  * (1 - tech.degradation_pa) ** ((jahr - 1) % max(lebensdauer, 1)))
        npv += (jahreswert * faktor) / ((1 + diskont) ** jahr)
        if jahr in ersatz_jahre:
            ersatz_capex = capex0 * (1 - capex_ruckgang_pa) ** jahr
            npv -= ersatz_capex / ((1 + diskont) ** jahr)
            capex_barwert += ersatz_capex / ((1 + diskont) ** jahr)

    amort = capex0 / jahreswert if jahreswert > 0 else float("inf")
    return InvestErgebnis(
        npv=npv,
        amortisation_jahre=amort,
        zyklen_pro_jahr=zyklen_pa,
        lebensdauer_jahre=lebensdauer,
        ersatz_jahre=ersatz_jahre,
        capex_gesamt_barwert=capex_barwert,
    )
