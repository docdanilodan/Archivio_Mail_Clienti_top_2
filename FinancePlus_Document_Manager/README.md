# FinancePlus Document Manager PRO

Web app Streamlit per gestione clienti, fascicoli documentali, richieste bancarie e report PDF.

## Menu inclusi

- Dashboard
- Nuovo Cliente
- Elenco Clienti
- Collaboratori
- Inserisci Report PDF
- Gestione Documenti
- Gestione Richieste
- Mail
- Valutazione bancaria
- Report PDF
- Archivio locale
- Predisposizione Google Drive
- Predisposizione pCloud

## Funzione principale nuova

Caricando una **visura camerale PDF** o un **report PDF**, la web app prova a estrarre automaticamente:

- ragione sociale
- partita IVA
- codice fiscale
- PEC
- sede legale
- REA
- ATECO
- forma giuridica
- capitale sociale
- amministratore / legale rappresentante

I dati vengono mostrati in maschera, restano modificabili e poi si salvano nel database clienti.
Il PDF caricato viene archiviato automaticamente nel fascicolo del cliente.

## Avvio locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud

Main file path:

```text
FinancePlus_Document_Manager/app.py
```

## Archivio

I dati sono salvati in:

```text
financeplus_document_data/
├── financeplus_documents.db
└── ArchivioLocale/
    └── Clienti/
```

Su Streamlit Cloud lo storage può essere temporaneo. Per uso professionale stabile usare server/PC locale o collegare Google Drive/pCloud.
