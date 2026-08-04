from einspeise_calc import *

def euro(x): return f"{x:8.0f} €"
def ct(x):  return f"{x*100:5.2f} ct"

print("="*70)
print("FALL A — Ü20-Anlage, niedriger Einspeisewert (Speicher lohnt?)")
print("="*70)
a = Anlage(kwp=6, spez_ertrag=950, verbrauch_kwh=4000, basis_ev_quote=0.28, strompreis_bezug=0.34)
s = Speicher(nutzbar_kwh=7.2, wirkungsgrad=0.90, nutzungsfaktor=0.70, capex=5000)
b = jahresbilanz(a, Speicher(), Modus.ANSCHLUSS_UE20)
print(f"Erzeugung {a.erzeugung_kwh:.0f} kWh | Verbrauch {a.verbrauch_kwh:.0f} kWh")
print(f"OHNE Speicher: EV {b.eigenverbrauch:.0f} kWh ({b.ev_quote:.0%}), eingespeist {b.eingespeist:.0f} kWh")
print(f"  Einspeisesatz {ct(b.einspeisesatz)} | Nutzen {euro(b.nutzen_gesamt)}")
k = speicher_kennzahlen(a, s, Modus.ANSCHLUSS_UE20)
print(f"MIT 7,2 kWh Speicher ({s.capex:.0f} €):")
print(f"  verschoben {k.verschobene_kwh:.0f} kWh | Delta {ct(k.delta_je_kwh)}/kWh (Strompreis - Einspeisung)")
print(f"  Jahresnutzen {euro(k.jahresnutzen)} | Amort {k.amortisation_jahre:.1f} J | NPV {euro(k.npv)} -> lohnt: {k.lohnt}")

print()
print("="*70)
print("FALL B — GLEICHE Anlage, aber hoher Alttarif 40 ct (Kipp-Test)")
print("="*70)
k2 = speicher_kennzahlen(a, s, Modus.ALTTARIF, alttarif=0.40)
b2 = jahresbilanz(a, Speicher(), Modus.ALTTARIF, alttarif=0.40)
print(f"Einspeisesatz {ct(b2.einspeisesatz)} | Delta {ct(k2.delta_je_kwh)}/kWh")
print(f"  Jahresnutzen Speicher {euro(k2.jahresnutzen)} | NPV {euro(k2.npv)} -> lohnt: {k2.lohnt}")
print("  (erwartet: negativ — eingespeiste kWh sind mehr wert als vermiedener Bezug)")

print()
print("="*70)
print("FALL C — Modi-Vergleich für dieselbe Ü20-Anlage OHNE Speicher")
print("="*70)
for m, bb in vergleich_modi(a, Speicher(), alttarif=0.40).items():
    print(f"  {m.value:42s} Einspeisung {ct(bb.einspeisesatz)} -> {euro(bb.wert_einspeisung)} Einspeiseerlös")

print()
print("="*70)
print("FALL D — Direktvermarktung: Gebühr frisst Erlös (Fraunhofer)")
print("="*70)
for anteil in (0.30, 0.50, 0.69):
    ss = einspeisesatz(Modus.DIREKTVERMARKTUNG, dv_gebuehr_anteil=anteil)
    print(f"  Gebühr {anteil:.0%} -> Netto {ct(ss)}/kWh (vs. Anschluss {ct(einspeisesatz(Modus.ANSCHLUSS_UE20))})")
