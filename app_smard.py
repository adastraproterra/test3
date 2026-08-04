"""
app_smard.py — Separate App: Direktvermarktung & Arbitrage aus realem SMARD-Spot
+ 2027-Zeitpfad (36 Monate Übergang -> danach Direktvermarktung).

Start:  streamlit run app_smard.py

CSV serverseitig: Die App liest standardmäßig ./data/smard_de_lu.csv aus dem
Repo — kein Kunden-Upload nötig. Zum Aktualisieren einfach diese Datei im
Repo ersetzen (echte SMARD-Viertelstundenwerte). Der Upload unten ist nur ein
optionaler Override zum Testen.
"""

import os
import numpy as np
import pandas as pd
import streamlit as st

from smard import parse_smard_csv, marktwert_aus_spot, arbitrage_jahreswert
from profiles import pv_profil, last_profil
from dispatch import co_optimiere_jahr
from technologie import LFP, NATRIUM, REVOLTA, npv_speicher
from einspeise_calc import (
    Anlage, Speicher, Modus, speicher_kennzahlen,
    zeitpfad_2027_saetze, wirtschaftlichkeit_zeitpfad,
    UEBERGANG_SATZ_2027,
)

HIER = os.path.dirname(os.path.abspath(__file__))
CSV_DEFAULT = os.path.join(HIER, "data", "smard_de_lu.csv")

st.set_page_config(page_title="Spot-Direktvermarktung & 2027-Pfad", layout="wide")
st.title("Direktvermarktung & Arbitrage aus realem Spot")
st.caption("Marktwert Solar, DV-Erlös und Speicher-Arbitrage aus SMARD-Großhandelspreisen "
           "— plus der 2027-Zeitpfad (36 Monate Übergang, danach DV).")


@st.cache_data(show_spinner="Lade Spotpreise …")
def lade_spot_von_pfad(pfad: str, mtime: float, preis_spalte: str | None):
    # mtime ist Teil des Cache-Keys -> neue Datei => neu geladen.
    return parse_smard_csv(pfad, preis_spalte or None)


@st.cache_data(show_spinner="Lade Spotpreise …")
def lade_spot_von_bytes(inhalt: bytes, preis_spalte: str | None):
    tmp = os.path.join(HIER, "_upload_tmp.csv")
    with open(tmp, "wb") as f:
        f.write(inhalt)
    return parse_smard_csv(tmp, preis_spalte or None)


with st.sidebar:
    st.header("Datenquelle")
    override = st.file_uploader("Optional: andere SMARD-CSV (Test-Override)", type=["csv"])
    preis_spalte = st.text_input("Preisspalte (leer = auto)", "")

    st.header("Direktvermarktung")
    profilfaktor = st.slider("Profilfaktor Solar", 0.30, 0.80, 0.50, 0.01,
                             help="Marktwert Solar ≈ Mittel-Spot × Profilfaktor. 2025 ~0,50.")
    dv_geb = st.slider("Vermarkter-Gebühr (Anteil)", 0.0, 0.80, 0.30, 0.01,
                       help="Fraunhofer: bei Kleinanlagen bis ~0,69.")

    st.header("Anlage & Speicher")
    kwp = st.number_input("PV-Leistung (kWp)", 1.0, 100.0, 6.0, 0.5)
    ertrag = st.number_input("Spez. Ertrag (kWh/kWp·a)", 700.0, 1200.0, 950.0, 10.0)
    verbrauch = st.number_input("Jahresverbrauch (kWh)", 500.0, 200000.0, 4000.0, 100.0)
    basis_ev = st.slider("Eigenverbrauchsquote ohne Speicher", 0.10, 0.60, 0.28, 0.01)
    strompreis = st.number_input("Netzbezugspreis (€/kWh)", 0.10, 0.80, 0.34, 0.01)
    nutzbar = st.number_input("Nutzbare Speicherkapazität (kWh)", 0.0, 100.0, 7.2, 0.5)
    capex = st.number_input("Speicher-Investition (€)", 0.0, 100000.0, 5000.0, 100.0)
    eta = st.slider("Round-Trip-Wirkungsgrad", 0.70, 0.98, 0.90, 0.01)
    nutzfaktor = st.slider("Zyklen-Ausnutzung (PV)", 0.40, 1.00, 0.70, 0.05)

    st.header("Arbitrage (Netzladung)")
    arb_an = st.checkbox("Arbitrage-Erlös berücksichtigen", value=False,
                         help="Konkurriert mit PV-Eigenverbrauch — als Obergrenze lesen.")
    lade_h = st.slider("Ladefenster (h/Tag)", 1.0, 6.0, 3.0, 0.5)
    entlade_h = st.slider("Entladefenster (h/Tag)", 1.0, 6.0, 3.0, 0.5)
    aussch = st.slider("Ausschöpfung", 0.3, 1.0, 0.80, 0.05)

    st.header("Wirtschaftlichkeit")
    horizont = st.slider("Horizont (Jahre)", 5, 25, 15)
    diskont = st.slider("Diskontsatz", 0.0, 0.10, 0.03, 0.005)
    degr = st.slider("Speicher-Degradation p.a.", 0.0, 0.03, 0.01, 0.005)
    preissteig = st.slider("Strompreis-Steigerung p.a.", 0.0, 0.06, 0.02, 0.005)

# ------------------------------------------------------------- Daten laden ---
try:
    if override is not None:
        spot = lade_spot_von_bytes(override.getvalue(), preis_spalte)
        quelle = f"Upload: {override.name}"
    else:
        if not os.path.exists(CSV_DEFAULT):
            st.error(f"Server-CSV nicht gefunden: {CSV_DEFAULT}. Bitte data/smard_de_lu.csv "
                     "im Repo hinterlegen oder oben eine Datei hochladen.")
            st.stop()
        spot = lade_spot_von_pfad(CSV_DEFAULT, os.path.getmtime(CSV_DEFAULT), preis_spalte)
        quelle = f"Server: data/{spot.quelle}"
except Exception as e:  # Parser-Fehler dem Nutzer zeigen, nicht verschlucken
    st.error(f"CSV konnte nicht gelesen werden: {e}")
    st.stop()

# ------------------------------------------------------------- Kennzahlen ----
mw = marktwert_aus_spot(spot, profilfaktor)
dv_net = max(mw * (1 - dv_geb), 0.0)
arb = arbitrage_jahreswert(spot, nutzbar, eta, lade_h, entlade_h, aussch)
arb_wert = arb.jahreswert if arb_an else 0.0

st.info(f"Quelle: {quelle} · {len(spot.preise):,} Werte · Auflösung {spot.aufloesung_min} min")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Mittlerer Spotpreis", f"{spot.mittel*100:.2f} ct/kWh")
c2.metric("Negative Preise", f"{spot.anteil_negativ:.1%} der Zeit")
c3.metric("Marktwert Solar", f"{mw*100:.2f} ct/kWh")
c4.metric("DV netto (nach Gebühr)", f"{dv_net*100:.2f} ct/kWh")

st.divider()
st.subheader("Speicher-Arbitrage aus realem Spot")
a1, a2, a3 = st.columns(3)
a1.metric("Mittlerer Tages-Spread", f"{arb.mittlerer_spread*100:.2f} ct/kWh")
a2.metric("Erlös p.a.", f"{arb.jahreswert:,.0f} €")
a3.metric("Ausgewertete Tage", f"{arb.tage}")
if not arb_an:
    st.caption("Arbitrage ist aktuell **nicht** in die NPV eingerechnet (Checkbox links). "
               "Sie konkurriert mit den PV-Ladezyklen.")

st.divider()
st.subheader("2027-Zeitpfad: 36 Monate Übergang → danach Direktvermarktung")
anlage = Anlage(kwp=kwp, spez_ertrag=ertrag, verbrauch_kwh=verbrauch,
                basis_ev_quote=basis_ev, strompreis_bezug=strompreis)
speicher = Speicher(nutzbar_kwh=nutzbar, wirkungsgrad=eta,
                    nutzungsfaktor=nutzfaktor, capex=capex)
saetze = zeitpfad_2027_saetze(horizont, dv_net)
z = wirtschaftlichkeit_zeitpfad(anlage, speicher, saetze, diskont, degr,
                                preissteig, arbitrage_jahreswert=arb_wert)

z1, z2, z3 = st.columns(3)
z1.metric("NPV Speicher", f"{z.npv_speicher:,.0f} €",
          help="inkl. Arbitrage" if arb_an else "ohne Arbitrage")
z2.metric("NPV Gesamtnutzen ohne Speicher", f"{z.npv_gesamtnutzen_ohne_speicher:,.0f} €")
z3.metric("NPV Gesamtnutzen mit Speicher", f"{z.npv_gesamtnutzen_mit_speicher:,.0f} €")

pfad_df = pd.DataFrame({
    "Jahr": list(range(1, horizont + 1)),
    "Einspeisesatz (ct/kWh)": [round(s * 100, 2) for s in z.einspeisesatz_pro_jahr],
    "Jahresnutzen Speicher (€)": [round(x, 0) for x in z.jahresnutzen_speicher],
}).set_index("Jahr")
cc1, cc2 = st.columns(2)
cc1.caption("Einspeisesatz je Jahr")
cc1.bar_chart(pfad_df["Einspeisesatz (ct/kWh)"])
cc2.caption("Jahresnutzen des Speichers")
cc2.bar_chart(pfad_df["Jahresnutzen Speicher (€)"])

st.divider()
st.subheader("Belastbare Co-Optimierung + Technologievergleich")
st.caption("Tägliche LP teilt EINEN Speicher zwischen PV-Eigenverbrauch und "
           "dyn.-Tarif-Arbitrage (keine Doppelzählung). Der co-optimierte "
           "Jahreswert geht in NPV/Amortisation je Technologie — inkl. Ersatz, "
           "wenn die Lebensdauer den Horizont unterschreitet. Synthetische "
           "PV-/Lastprofile (durch echte PVGIS-/Lastdaten ersetzbar).")

co1, co2, co3 = st.columns(3)
tarif = co1.radio("Bezugstarif", ["Fixer Tarif", "Dynamisch (Spot + Aufschlag)"])
aufschlag = co2.number_input("Aufschlag dyn. Tarif (€/kWh)", 0.0, 0.40, 0.18, 0.01,
                             help="Netzentgelte + Steuern + Umlagen + Marge über Spot.",
                             disabled=(tarif == "Fixer Tarif"))
p_max = co3.number_input("Speicher-Leistung (kW)", 0.5, 30.0, 3.0, 0.5)

t1, t2, t3 = st.columns(3)
capex_lfp = t1.number_input("LFP: Kosten (€/kWh)", 100.0, 1500.0,
                            LFP.capex_eur_kwh, 10.0)
capex_na = t2.number_input("Na-Ion: Kosten (€/kWh)", 100.0, 1500.0,
                           NATRIUM.capex_eur_kwh, 10.0)
capex_rev = t3.number_input("Revolta: Kosten (€/kWh)", 100.0, 1500.0,
                            REVOLTA.capex_eur_kwh, 10.0,
                            help="Preis nicht veröffentlicht — Platzhalter.")


@st.cache_data(show_spinner="Optimiere 365 Tage …")
def _dispatch(fingerprint, kwp, ertrag, verbrauch, cap, p_max, eta,
              einspeise, verkauf, dyn, aufschlag, retail):
    pvp = pv_profil(spot.preise.index, kwp * ertrag)
    lp = last_profil(spot.preise.index, verbrauch)
    imp = (spot.preise + aufschlag) if dyn else retail
    return co_optimiere_jahr(pvp, lp, spot.preise, imp, einspeise, verkauf,
                             cap, p_max, eta)


if st.button("Co-Optimierung + Technologievergleich rechnen (~6 s)"):
    dyn = tarif != "Fixer Tarif"
    fp = (quelle, len(spot.preise), round(spot.mittel, 5))
    ergebnisse = {}
    for tech, cpx in ((LFP, capex_lfp), (NATRIUM, capex_na), (REVOLTA, capex_rev)):
        r = _dispatch(fp, kwp, ertrag, verbrauch, nutzbar, p_max, tech.wirkungsgrad,
                      dv_net, dv_net, dyn, aufschlag, strompreis)
        t = tech.__class__(**{**tech.__dict__, "capex_eur_kwh": cpx})
        inv = npv_speicher(r.batteriewert, r.entladung_kwh, nutzbar, t,
                           horizont, diskont, preissteig)
        ergebnisse[tech.name] = (r, t, inv)
    st.session_state["tech"] = ergebnisse

if "tech" in st.session_state:
    erg = st.session_state["tech"]
    rows = []
    for name, (r, t, inv) in erg.items():
        rows.append({
            "Technologie": name,
            "η": f"{t.wirkungsgrad:.0%}",
            "Wert (€/a)": round(r.batteriewert, 0),
            "Zyklen/a": round(inv.zyklen_pro_jahr, 0),
            "Lebensdauer (J)": round(inv.lebensdauer_jahre, 1),
            "Ersatz (Jahr)": ", ".join(map(str, inv.ersatz_jahre)) or "—",
            "Capex (€)": round(t.capex_eur_kwh * nutzbar, 0),
            "Amort. (J)": ("—" if inv.amortisation_jahre == float("inf")
                           else round(inv.amortisation_jahre, 1)),
            f"NPV {horizont}J (€)": round(inv.npv, 0),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    beste = max(erg.items(), key=lambda kv: kv[1][2].npv)
    st.success(f"Höchster NPV: **{beste[0]}** mit {beste[1][2].npv:,.0f} € "
               f"über {horizont} Jahre.")
    for name, (r, t, inv) in erg.items():
        st.caption(f"**{name}:** {t.hinweis}")

    # Doppelzählungs-Gegenüberstellung (Referenz: LFP)
    rL, tL, _ = erg[LFP.name]
    from einspeise_calc import Anlage, Speicher, Modus, speicher_kennzahlen
    from smard import arbitrage_jahreswert as _arb
    a = Anlage(kwp=kwp, spez_ertrag=ertrag, verbrauch_kwh=verbrauch,
               basis_ev_quote=basis_ev, strompreis_bezug=strompreis)
    s = Speicher(nutzbar_kwh=nutzbar, wirkungsgrad=tL.wirkungsgrad,
                 nutzungsfaktor=nutzfaktor, capex=capex_lfp * nutzbar)
    k = speicher_kennzahlen(a, s, Modus.ALTTARIF, alttarif=dv_net)
    getrennt = k.jahresnutzen + (arb.jahreswert if arb_an else 0.0)
    st.markdown(
        f"*Kontrolle Doppelzählung (LFP): getrennt geschätzt "
        f"`{getrennt:,.0f} €/a` vs. co-optimiert `{rL.batteriewert:,.0f} €/a` — "
        f"Differenz `{getrennt - rL.batteriewert:,.0f} €`, weil sich Eigenverbrauch "
        f"und Arbitrage dieselben Zyklen teilen.*"
    )
else:
    st.caption("Noch nicht gerechnet — Button oben.")

with st.expander("Fakten vs. Schätzungen"):
    st.markdown(
        f"""
**Fakten / datengetrieben:**
- Spotpreise, Spread, Negativpreis-Anteil direkt aus der SMARD-CSV.
- Übergangszahlung {UEBERGANG_SATZ_2027*100:.1f} ct/kWh, 36 Monate — **Kabinettsentwurf**.
- Technologie-*Richtung* (Stand 2026): LFP mehr Zyklen & ausgereift; Na-Ion
  kältefester (-30/-40 °C), materialunabhängig, Kostenvorteil noch prospektiv.

**Schätzungen (überschreibbar):**
- Profilfaktor, Vermarkter-Gebühr, PV-/Lastprofil-Form, dyn.-Tarif-Aufschlag,
  Technologie-Kennzahlen (η, Capex €/kWh, Zyklen-/Kalenderlebensdauer, Degradation),
  Diskont/Preissteigerung.

**Modellgrenzen:** ein Speicher, tägliche LP mit perfekter Tagesvoraussicht
(= Obergrenze, keine reale Steuerung); Tageszyklus-Reset (kein saisonaler
Übertrag); Technologiezahlen streuen je Quelle/Zelle stark.
"""
    )
