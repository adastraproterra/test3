"""
app_einspeise.py — Streamlit-Frontend für einspeise_calc.

Start:  streamlit run app_einspeise.py
Deploy: als zweite Seite/App neben deinem bestehenden Rechner auf
        Streamlit Community Cloud. Nutzt nur streamlit + pandas.
"""

import pandas as pd
import streamlit as st

from einspeise_calc import (
    Anlage, Speicher, Modus, jahresbilanz, speicher_kennzahlen,
    vergleich_modi, einspeisesatz,
    JAHRESMARKTWERT_SOLAR_2025, ANSCHLUSS_PAUSCHALE_2026, UEBERGANG_SATZ_2027,
)
from technologie import LFP, NATRIUM, PRESETS

st.set_page_config(page_title="PV-Überschuss: was noch lohnt", layout="wide")
st.title("PV-Überschuss — was ist er noch wert?")
st.caption(
    "Wenn die Einspeisung marginal wird, entscheidet Eigenverbrauch + Speicher. "
    "Dieses Tool rechnet die vier Einspeise-Modi mit derselben Engine."
)

# ---------------------------------------------------------------- Eingaben ---
with st.sidebar:
    st.header("Anlage & Verbrauch")
    kwp = st.number_input("PV-Leistung (kWp)", 1.0, 100.0, 6.0, 0.5)
    ertrag = st.number_input("Spez. Ertrag (kWh/kWp·a)", 700.0, 1200.0, 950.0, 10.0,
                             help="Schätzung. Westerwald ~950.")
    verbrauch = st.number_input("Jahresverbrauch (kWh)", 500.0, 200000.0, 4000.0, 100.0)
    basis_ev = st.slider("Eigenverbrauchsquote ohne Speicher", 0.10, 0.60, 0.28, 0.01,
                         help="Schätzung. Haushalt typ. 0,20–0,35.")
    strompreis = st.number_input("Netzbezugspreis (€/kWh)", 0.10, 0.80, 0.34, 0.01,
                                 help="Der eigentliche Hebel: Wert des vermiedenen Bezugs.")

    st.header("Einspeise-Modus")
    modus = st.selectbox("Modus", list(Modus), format_func=lambda m: m.value)
    alttarif = 0.0
    marktwert = JAHRESMARKTWERT_SOLAR_2025
    dv_geb = 0.30
    clip = 0.0
    if modus == Modus.ALTTARIF:
        alttarif = st.number_input("Fixe EEG-Vergütung (€/kWh)", 0.0, 0.60, 0.08, 0.01,
                                   help="Der Satz aus deinem EEG-Bescheid.")
    if modus in (Modus.ANSCHLUSS_UE20, Modus.DIREKTVERMARKTUNG):
        marktwert = st.number_input("Jahresmarktwert Solar (€/kWh)", 0.0, 0.20,
                                    JAHRESMARKTWERT_SOLAR_2025, 0.001, format="%.3f")
    if modus == Modus.DIREKTVERMARKTUNG:
        dv_geb = st.slider("Vermarkter-Gebühr (Anteil vom Marktwert)", 0.0, 0.80, 0.30, 0.01,
                           help="Fraunhofer: bei Kleinanlagen bis ~0,69.")
    if modus == Modus.UEBERGANG_2027:
        st.info(f"Übergangszahlung {UEBERGANG_SATZ_2027*100:.1f} ct/kWh für 36 Monate, "
                "danach Direktvermarktung. **Entwurf**, kein geltendes Recht.")
        clip = st.slider("Einspeise-Verlust durch 50 %-Deckel (Anteil)", 0.0, 0.50, 0.0, 0.01,
                         help="Schätzung. Nur Neuanlagen ab 2027.")

    st.header("Speicher")
    tech_name = st.radio("Zellchemie", [LFP.name, NATRIUM.name], horizontal=True)
    tech = PRESETS[tech_name]
    nutzbar = st.number_input("Nutzbare Kapazität (kWh)", 0.0, 100.0, 7.2, 0.5)
    capex_kwh = st.number_input("Kosten (€/kWh)", 100.0, 1500.0, tech.capex_eur_kwh, 10.0,
                                key=f"capex_{tech_name}")
    capex = capex_kwh * nutzbar
    eta = st.slider("Round-Trip-Wirkungsgrad", 0.70, 0.98, tech.wirkungsgrad, 0.01,
                    key=f"eta_{tech_name}")
    st.caption(f"{tech_name}: η {tech.wirkungsgrad:.0%}, ~{tech.capex_eur_kwh:.0f} €/kWh, "
               f"{tech.zyklen_lebensdauer:,} Zyklen — Werte anpassbar.")
    nutzfaktor = st.slider("Zyklen-Ausnutzung übers Jahr", 0.40, 1.00, 0.70, 0.05,
                           help="Schätzung. Winter liefert wenig Überschuss.")

    with st.expander("Wirtschaftlichkeits-Parameter"):
        horizont = st.slider("Betrachtungshorizont (Jahre)", 5, 25, 15)
        diskont = st.slider("Diskontsatz", 0.0, 0.10, 0.03, 0.005)
        degr = st.slider("Speicher-Degradation p.a.", 0.0, 0.03, 0.01, 0.005)
        preissteig = st.slider("Strompreis-Steigerung p.a.", 0.0, 0.06, 0.02, 0.005)

anlage = Anlage(kwp=kwp, spez_ertrag=ertrag, verbrauch_kwh=verbrauch,
                basis_ev_quote=basis_ev, strompreis_bezug=strompreis,
                einspeise_clip_anteil=clip)
speicher = Speicher(nutzbar_kwh=nutzbar, wirkungsgrad=eta,
                    nutzungsfaktor=nutzfaktor, capex=capex)

b_ohne = jahresbilanz(anlage, Speicher(), modus, alttarif, marktwert, dv_geb)
b_mit = jahresbilanz(anlage, speicher, modus, alttarif, marktwert, dv_geb)
k = speicher_kennzahlen(anlage, speicher, modus, alttarif, marktwert, dv_geb,
                        horizont, diskont, degr, preissteig)

# ---------------------------------------------------------------- Ausgabe ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("Erzeugung", f"{anlage.erzeugung_kwh:,.0f} kWh")
c2.metric("Einspeisesatz (netto)", f"{b_ohne.einspeisesatz*100:.2f} ct/kWh")
c3.metric("Eigenverbrauch ohne Speicher", f"{b_ohne.ev_quote:.0%}")
c4.metric("Eigenverbrauch mit Speicher", f"{b_mit.ev_quote:.0%}",
          delta=f"+{(b_mit.ev_quote-b_ohne.ev_quote)*100:.0f} pp")

st.divider()
st.subheader("Der entscheidende Hebel")
delta = k.delta_je_kwh
st.markdown(
    f"Jede kWh, die der Speicher vom Einspeisen ins **Eigenverbrauchen** verschiebt, "
    f"ist wert: **Netzbezug − Einspeisung = {strompreis*100:.1f} − "
    f"{b_ohne.einspeisesatz*100:.1f} = `{delta*100:.1f} ct/kWh`**."
)
if delta <= 0:
    st.error(
        f"Delta ist **negativ** ({delta*100:.1f} ct/kWh): Deine eingespeisten kWh sind "
        "mehr wert als der vermiedene Bezug. Ein Speicher zur Eigenverbrauchssteigerung "
        "**vernichtet hier Wert** — der klassische Fall der alten Hochtarif-Anlage."
    )
elif delta < 0.10:
    st.warning(f"Delta klein ({delta*100:.1f} ct/kWh) — Speicher rechnet sich nur bei "
               "niedrigen Speicherkosten.")
else:
    st.success(f"Delta groß ({delta*100:.1f} ct/kWh) — Eigenverbrauch/Speicher ist "
               "der dominante Werttreiber.")

st.divider()
st.subheader("Lohnt der Speicher?")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Verschobene Energie", f"{k.verschobene_kwh:,.0f} kWh/a")
s2.metric("Jahresnutzen", f"{k.jahresnutzen:,.0f} €")
amort = "—" if k.amortisation_jahre == float("inf") else f"{k.amortisation_jahre:.1f} J"
s3.metric("Einf. Amortisation", amort)
s4.metric(f"NPV ({horizont} J)", f"{k.npv:,.0f} €")
if k.lohnt:
    st.success("Bei diesen Annahmen positiv — der Speicher lohnt sich.")
else:
    st.error("Bei diesen Annahmen negativ — der Speicher lohnt sich nicht.")

st.divider()
st.subheader("Einspeise-Modi im Vergleich (mit gewähltem Speicher)")
vgl = vergleich_modi(anlage, speicher, alttarif, marktwert, dv_geb)
df = pd.DataFrame([{
    "Modus": m.value,
    "Einspeisesatz (ct/kWh)": round(bz.einspeisesatz*100, 2),
    "Einspeiseerlös (€/a)": int(round(bz.wert_einspeisung)),
    "Eigenverbrauchswert (€/a)": int(round(bz.wert_eigenverbrauch)),
    "Nutzen gesamt (€/a)": int(round(bz.nutzen_gesamt)),
} for m, bz in vgl.items()])
st.table(df.set_index("Modus"))
st.bar_chart(df.set_index("Modus")["Einspeiseerlös (€/a)"])
st.caption(
    "Kernaussage: Der Einspeiseerlös kollabiert von Bestands-Alttarif zu allen "
    "Neuregime-Modi — der Wert wandert vollständig in den Eigenverbrauch."
)

with st.expander("Fakten vs. Schätzungen (bitte lesen)"):
    st.markdown(
        f"""
**Fakten (Regulatorik, Stand 2026):**
- Ü20-Anschlussvergütung = Jahresmarktwert Solar − Pauschale
  ({ANSCHLUSS_PAUSCHALE_2026*100:.2f} ct/kWh 2026), garantiert bis 31.12.2032.
- Jahresmarktwert Solar 2025 ≈ {JAHRESMARKTWERT_SOLAR_2025*100:.2f} ct/kWh.
- Übergangszahlung Neuanlage 2027 ≈ {UEBERGANG_SATZ_2027*100:.1f} ct/kWh, 36 Monate — **Kabinettsentwurf**, EU-Beihilfe + Bundestag/Bundesrat offen.
- Direktvermarktung: Gebühr laut Fraunhofer bei Kleinanlagen bis ~69 % des Marktwerts.

**Schätzungen (von dir wählbar, hier nicht als Wahrheit gesetzt):**
- Spez. Ertrag, Eigenverbrauchsquote, Zyklen-Ausnutzung, Netzbezugspreis,
  Speicher-Capex/-Wirkungsgrad, Diskont/Degradation/Preissteigerung,
  50 %-Deckel-Verlust.

Das Modell rechnet Jahresmittel, keine Viertelstunden-Simulation. Für die
Direktvermarktungs-/Arbitrage-Feinheiten (realer Spot-Spread) ist dein
SMARD-basierter Rechner die genauere Quelle.
"""
    )
