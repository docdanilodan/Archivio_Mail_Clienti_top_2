# Archivio Mail Clienti PRO

Web app Streamlit per archiviare allegati email in struttura mittente/azienda, con deduplica MD5, ricerca, report CSV e export ZIP.

## Avvio locale
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy GitHub + Streamlit Cloud
1. Crea repository GitHub.
2. Carica i file.
3. Vai su Streamlit Community Cloud.
4. New app > repository > branch main > app.py > Deploy.

## Gmail API
La schermata è predisposta. Per accesso Gmail reale configurare OAuth Google Cloud secondo guida PDF inclusa.
