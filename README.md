# PV-Überschuss-Tools

Zwei Streamlit-Apps auf einer gemeinsamen Engine:

- **app_einspeise.py** — Entscheidung Eigenverbrauch/Speicher über vier
  Einspeise-Modi (Alttarif / Übergang 2027 / Ü20-Anschluss / Direktvermarktung).
- **app_smard.py** — Direktvermarktung & Arbitrage aus realem SMARD-Spot
  + 2027-Zeitpfad (36 Monate Übergang → danach DV).

## Struktur
- `einspeise_calc.py` — reiner Rechenkern (keine UI).
- `smard.py` — SMARD-CSV-Parser + spot-abgeleitete Werte.
- `profiles.py` — synthetische PV-/Lastprofile (durch echte Daten ersetzbar).
- `dispatch.py` — Co-Optimierung: tägliche LP, ein geteilter Speicher
  (Eigenverbrauch + Arbitrage ohne Doppelzählung; Bezugspreis fix oder dynamisch).
- `technologie.py` — Speichertechnologien (LFP / Na-Ion / Revolta) + NPV/Amortisation
  aus dem co-optimierten Jahreswert, inkl. Ersatz-Capex bei kurzer Lebensdauer.
- `data/smard_de_lu.csv` — **serverseitige** Preisdatei (im Repo). Wird von
  app_smard.py automatisch geladen, kein Kunden-Upload nötig.
- `test_einspeise_calc.py` — Verifikation der Kernfälle.

## SMARD-CSV serverseitig aktualisieren
Die aktuell beiliegende `data/smard_de_lu.csv` ist ein **synthetisches
Beispieljahr** (stündlich), nur damit die App sofort läuft. Ersetze sie durch
deinen echten SMARD-Export (DE/LU, Viertelstunde) — gleiche Struktur:
Semikolon-getrennt, Dezimalkomma, Datum `DD.MM.YYYY HH:MM`, Preis in €/MWh.
Der Parser erkennt Zeit-/Preisspalte automatisch; bei abweichendem Export die
Preisspalte in der Sidebar explizit angeben.

## Start
```
pip install -r requirements.txt
streamlit run app_smard.py      # oder app_einspeise.py
```
Auf Streamlit Community Cloud: Repo mit `data/` committen, App-Datei als
Entry-Point wählen — die CSV liegt dann serverseitig vor.
