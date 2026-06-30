import io
import os
import re
import csv
import zipfile
import hashlib
import sqlite3
import datetime as dt
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
except Exception:
    canvas = None
    A4 = None
    cm = 28.3465

APP_TITLE = "FinancePlus Document Manager PRO"
BASE_DIR = Path("financeplus_document_data")
DB_PATH = BASE_DIR / "financeplus_documents.db"
LOCAL_ARCHIVE_DIR = BASE_DIR / "ArchivioLocale"

CATS = [
    "Bilancio", "Centrale Rischi", "Visura", "Report PDF", "Estratti conto", "Contratti",
    "Mandato", "Business Plan", "Email e allegati", "Documenti identita", "Richieste banca", "Altro"
]
REQUEST_STATUS = ["Bozza", "Documenti da integrare", "Pronta", "Inviata", "In istruttoria", "Deliberata", "Respinta", "Erogata", "Archiviata"]
REQUEST_TYPES = ["Chirografario", "MCC", "Ipotecario", "Factoring", "Leasing", "Anticipo fatture", "Fintech", "Altro"]

DEFAULT_SENDERS = """elibetty731@gmail.com
valentinaboratto82@gmail.com
stefano.faraone@eurofintechsrl.it
praticheBS@proton.me
sergio.pedolazzi@katudi.it
paolo.baldinelli@katudi.it
pratiche@katudi.it
niccolo.sovico@ener2crowd.com"""

st.set_page_config(page_title=APP_TITLE, page_icon="🗂️", layout="wide")
st.markdown(
    """
<style>
.block-container{padding-top:1.2rem; max-width:1500px;}
.fp-title{font-size:30px;font-weight:850;color:#0b2f5b;margin-bottom:0;}
.fp-sub{color:#667085;font-size:13px;margin-top:0;}
.fp-card{border:1px solid #e6edf7;border-radius:18px;padding:18px;background:#fff;box-shadow:0 6px 22px rgba(10,40,80,.055);}
.fp-warn{border:1px solid #f3c174;border-radius:14px;padding:12px;background:#fff7e8;color:#704500;}
.fp-ok{border:1px solid #95d5b2;border-radius:14px;padding:12px;background:#ecfff3;color:#14532d;}
.fp-pill{display:inline-block;background:#f4e4d0;color:#7a3f00;border-radius:99px;padding:4px 10px;font-size:12px;margin-right:5px;}
.small-muted{color:#667085;font-size:12px;}
hr{border:none;border-top:1px solid #edf2f7;margin:1rem 0;}
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

def init_db() -> None:
    BASE_DIR.mkdir(exist_ok=True)
    LOCAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clienti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ragione_sociale TEXT UNIQUE,
            piva TEXT,
            cf TEXT,
            pec TEXT,
            sede TEXT,
            rea TEXT,
            ateco TEXT,
            forma_giuridica TEXT,
            capitale_sociale TEXT,
            amministratore TEXT,
            amministratore_cf TEXT,
            fonte_estrazione TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS documenti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            categoria TEXT,
            data_doc TEXT,
            nome_file TEXT,
            estensione TEXT,
            dimensione INTEGER,
            md5 TEXT UNIQUE,
            percorso TEXT,
            descrizione TEXT,
            fonte TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS richieste(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            banca TEXT,
            tipo TEXT,
            importo REAL,
            durata_mesi INTEGER,
            stato TEXT,
            scadenza TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collaboratori(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            ruolo TEXT,
            email TEXT,
            telefono TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS valutazioni(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            importo_richiesto REAL,
            fatturato REAL,
            ebitda REAL,
            pfn REAL,
            patrimonio_netto REAL,
            dscr REAL,
            anomalie_cr INTEGER,
            score INTEGER,
            rating TEXT,
            giudizio TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    con.commit()
    con.close()


def con() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def ensure_columns() -> None:
    # Backward compatibility if an older database already exists.
    wanted = {
        "clienti": {
            "rea": "TEXT", "ateco": "TEXT", "forma_giuridica": "TEXT", "capitale_sociale": "TEXT",
            "amministratore": "TEXT", "amministratore_cf": "TEXT", "fonte_estrazione": "TEXT", "updated_at": "TEXT"
        },
        "richieste": {"durata_mesi": "INTEGER", "scadenza": "TEXT", "updated_at": "TEXT"},
    }
    c = con(); cur = c.cursor()
    for table, cols in wanted.items():
        cur.execute(f"PRAGMA table_info({table})")
        existing = {r[1] for r in cur.fetchall()}
        for name, typ in cols.items():
            if name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    c.commit(); c.close()


init_db()
ensure_columns()

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def clean_folder_name(value: str, fallback: str = "Senza nome") -> str:
    value = (value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|]+", "-", value)
    value = re.sub(r"\s+", " ", value)
    return value[:110] or fallback


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def read_table(sql: str, params: Tuple = ()) -> pd.DataFrame:
    c = con()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()


def get_clienti_df() -> pd.DataFrame:
    return read_table(
        """
        SELECT id, ragione_sociale, piva, cf, pec, sede, amministratore, rea, ateco, fonte_estrazione, updated_at
        FROM clienti ORDER BY ragione_sociale
        """
    )


def get_documenti_df(cliente: Optional[str] = None) -> pd.DataFrame:
    if cliente:
        return read_table(
            "SELECT * FROM documenti WHERE cliente=? ORDER BY created_at DESC",
            (cliente,),
        )
    return read_table("SELECT * FROM documenti ORDER BY created_at DESC")


def get_richieste_df(cliente: Optional[str] = None) -> pd.DataFrame:
    if cliente:
        return read_table("SELECT * FROM richieste WHERE cliente=? ORDER BY created_at DESC", (cliente,))
    return read_table("SELECT * FROM richieste ORDER BY created_at DESC")


def get_collaboratori_df() -> pd.DataFrame:
    return read_table("SELECT * FROM collaboratori ORDER BY nome")


def get_valutazioni_df(cliente: Optional[str] = None) -> pd.DataFrame:
    if cliente:
        return read_table("SELECT * FROM valutazioni WHERE cliente=? ORDER BY created_at DESC", (cliente,))
    return read_table("SELECT * FROM valutazioni ORDER BY created_at DESC")


def upsert_cliente(data: Dict[str, str]) -> None:
    ragione = clean_folder_name(data.get("ragione_sociale", ""), "Cliente senza nome")
    c = con(); cur = c.cursor()
    cur.execute(
        """
        INSERT INTO clienti(
            ragione_sociale,piva,cf,pec,sede,rea,ateco,forma_giuridica,capitale_sociale,
            amministratore,amministratore_cf,fonte_estrazione,note,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(ragione_sociale) DO UPDATE SET
            piva=excluded.piva,
            cf=excluded.cf,
            pec=excluded.pec,
            sede=excluded.sede,
            rea=excluded.rea,
            ateco=excluded.ateco,
            forma_giuridica=excluded.forma_giuridica,
            capitale_sociale=excluded.capitale_sociale,
            amministratore=excluded.amministratore,
            amministratore_cf=excluded.amministratore_cf,
            fonte_estrazione=excluded.fonte_estrazione,
            note=excluded.note,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            ragione,
            data.get("piva", ""), data.get("cf", ""), data.get("pec", ""), data.get("sede", ""),
            data.get("rea", ""), data.get("ateco", ""), data.get("forma_giuridica", ""),
            data.get("capitale_sociale", ""), data.get("amministratore", ""), data.get("amministratore_cf", ""),
            data.get("fonte_estrazione", "manuale"), data.get("note", ""),
        ),
    )
    c.commit(); c.close()


def get_setting(key: str, default: str = "") -> str:
    c = con(); cur = c.cursor(); cur.execute("SELECT value FROM settings WHERE key=?", (key,)); row = cur.fetchone(); c.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    c = con(); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value)); c.commit(); c.close()

# -----------------------------------------------------------------------------
# PDF extraction
# -----------------------------------------------------------------------------

def extract_pdf_text(uploaded_file) -> str:
    if PdfReader is None:
        return ""
    data = uploaded_file.getvalue()
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages[:25]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


def first_match(patterns: List[str], text: str, flags=re.IGNORECASE | re.MULTILINE) -> str:
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            return normalize_space(val).strip(" :-;,.\t")
    return ""


def detect_company_name(text: str, filename: str = "") -> str:
    raw = f"{text}\n{filename}"
    lines = [normalize_space(x) for x in raw.splitlines() if normalize_space(x)]
    patterns = [
        r"(?:denominazione|ragione\s+sociale|impresa|societ[aà]|azienda)\s*[:\-]?\s*([A-Z0-9À-Ù '&.,\-]{3,120})",
        r"([A-Z0-9À-Ù '&.,\-]{3,100}\s+(?:S\.R\.L\.|SRL|S\.P\.A\.|SPA|S\.A\.S\.|SAS|S\.N\.C\.|SNC|SRLS|S\.R\.L\.S\.))",
    ]
    found = first_match(patterns, raw)
    if found:
        return clean_company(found)
    # Fallback on uppercase lines containing legal form.
    for line in lines[:150]:
        if re.search(r"\b(SRL|S\.R\.L\.|SPA|S\.P\.A\.|SAS|SNC|SRLS)\b", line, re.I):
            if len(line) <= 130:
                return clean_company(line)
    return ""


def clean_company(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"\b(?:CODICE FISCALE|PARTITA IVA|P\.IVA|PEC|SEDE LEGALE|REA)\b.*$", "", value, flags=re.I)
    value = value.strip(" :-;,.\t")
    return clean_folder_name(value.upper(), "")


def detect_administrator(text: str) -> str:
    patterns = [
        r"(?:amministratore\s+unico|amministratore|legale\s+rappresentante|rappresentante\s+legale)\s*[:\-]?\s*([A-ZÀ-Ù][A-Za-zÀ-ÿ' ]{4,90})",
        r"(?:carica\s*[:\-]?\s*amministratore\s+unico[\s\S]{0,180}?nome\s*[:\-]?\s*)([A-ZÀ-Ù][A-Za-zÀ-ÿ' ]{4,90})",
        r"(?:nominato\s+amministratore[\s\S]{0,80}?)([A-ZÀ-Ù][A-Za-zÀ-ÿ' ]{4,90})",
    ]
    val = first_match(patterns, text)
    val = re.sub(r"\b(?:NATO|NATA|CODICE|FISCALE|RESIDENTE|CARICA|DAL|AL)\b.*$", "", val, flags=re.I).strip()
    return normalize_space(val).upper()


def extract_company_data(text: str, filename: str = "") -> Dict[str, str]:
    flat = normalize_space(text)
    data = {
        "ragione_sociale": detect_company_name(text, filename),
        "piva": first_match([
            r"(?:partita\s+iva|p\.\s*iva|iva)\s*[:\-]?\s*([0-9]{11})",
            r"\bP\.?IVA\s*([0-9]{11})",
        ], flat),
        "cf": first_match([
            r"(?:codice\s+fiscale|c\.\s*f\.)\s*[:\-]?\s*([A-Z0-9]{11,16})",
            r"\bCF\s*[:\-]?\s*([A-Z0-9]{11,16})",
        ], flat),
        "pec": first_match([
            r"(?:pec|posta\s+elettronica\s+certificata)\s*[:\-]?\s*([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})",
            r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]*pec[A-Z0-9.\-]*\.[A-Z]{2,})",
        ], flat),
        "sede": first_match([
            r"(?:sede\s+legale|sede)\s*[:\-]?\s*([A-Z0-9À-Ùa-zà-ù ,.'°\-/]{8,160}?)(?:\s+(?:PEC|P\.?IVA|Partita|Codice\s+fiscale|REA|Capitale|Oggetto)|$)",
        ], flat),
        "rea": first_match([
            r"\bREA\s*[:\-]?\s*([A-Z]{2}\s*[-/]?\s*[0-9]{3,8}|[0-9]{3,8})",
            r"Repertorio\s+Economico\s+Amministrativo\s*[:\-]?\s*([A-Z0-9\-/ ]{3,20})",
        ], flat),
        "ateco": first_match([
            r"(?:ateco|codice\s+attivit[aà])\s*[:\-]?\s*([0-9]{2}\.?[0-9]{0,2}\.?[0-9]{0,2})",
        ], flat),
        "forma_giuridica": first_match([
            r"(?:forma\s+giuridica)\s*[:\-]?\s*([A-ZÀ-Ùa-zà-ù .]{3,80})",
        ], flat),
        "capitale_sociale": first_match([
            r"(?:capitale\s+sociale)\s*[:\-]?\s*(?:euro|€)?\s*([0-9\.]+,[0-9]{2}|[0-9\.]+)",
        ], flat),
        "amministratore": detect_administrator(flat),
        "amministratore_cf": first_match([
            r"(?:codice\s+fiscale\s+(?:amministratore|legale\s+rappresentante)|cf\s+amministratore)\s*[:\-]?\s*([A-Z0-9]{16})",
        ], flat),
        "fonte_estrazione": filename,
        "note": "Dati estratti automaticamente da PDF. Verificare sempre prima del salvataggio definitivo.",
    }
    # If CF is empty and PIVA exists, for many SRL it coincides.
    if not data["cf"] and data["piva"]:
        data["cf"] = data["piva"]
    return data

# -----------------------------------------------------------------------------
# File/document storage
# -----------------------------------------------------------------------------

def archive_uploaded_file(cliente: str, categoria: str, descrizione: str, uploaded_file, fonte: str = "upload") -> Tuple[bool, str, str]:
    data = uploaded_file.getvalue()
    digest = md5_bytes(data)
    filename = clean_folder_name(uploaded_file.name, "documento")
    ext = Path(filename).suffix.lower()
    cliente_clean = clean_folder_name(cliente, "Da verificare")
    dest_dir = LOCAL_ARCHIVE_DIR / "Clienti" / cliente_clean / clean_folder_name(categoria)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    c = con(); cur = c.cursor()
    try:
        cur.execute(
            """
            INSERT INTO documenti(cliente,categoria,data_doc,nome_file,estensione,dimensione,md5,percorso,descrizione,fonte)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (cliente, categoria, dt.date.today().isoformat(), filename, ext, len(data), digest, str(dest_path), descrizione, fonte),
        )
        # Avoid overwriting an existing different file with the same name.
        if dest_path.exists():
            stem, suffix = dest_path.stem, dest_path.suffix
            dest_path = dest_dir / f"{stem}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
        dest_path.write_bytes(data)
        c.commit()
        return True, "Archiviato", str(dest_path)
    except sqlite3.IntegrityError:
        return False, "Duplicato: MD5 gia presente", ""
    finally:
        c.close()


def export_zip() -> io.BytesIO:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        if BASE_DIR.exists():
            for p in BASE_DIR.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(BASE_DIR.parent))
    mem.seek(0)
    return mem


def remove_duplicate_records_preview() -> pd.DataFrame:
    return read_table(
        """
        SELECT md5, COUNT(*) AS copie, GROUP_CONCAT(nome_file, ' | ') AS file, GROUP_CONCAT(percorso, ' | ') AS percorsi
        FROM documenti GROUP BY md5 HAVING COUNT(*) > 1
        """
    )

# -----------------------------------------------------------------------------
# Banking evaluation and PDF reports
# -----------------------------------------------------------------------------

def calculate_bank_score(importo: float, fatturato: float, ebitda: float, pfn: float, patrimonio: float, dscr: float, anomalie_cr: int) -> Tuple[int, str, str]:
    score = 50
    if fatturato > 0:
        incidenza = importo / fatturato
        if incidenza <= 0.15: score += 12
        elif incidenza <= 0.30: score += 6
        elif incidenza > 0.60: score -= 12
    if ebitda > 0:
        pfn_ebitda = pfn / ebitda
        if pfn_ebitda <= 2: score += 14
        elif pfn_ebitda <= 4: score += 6
        else: score -= 12
    else:
        score -= 16
    if patrimonio > 0: score += 7
    else: score -= 8
    if dscr >= 1.50: score += 14
    elif dscr >= 1.20: score += 8
    elif dscr >= 1.00: score += 2
    else: score -= 15
    score -= min(25, anomalie_cr * 5)
    score = max(0, min(100, int(score)))
    if score >= 85: return score, "A", "Molto finanziabile"
    if score >= 70: return score, "B", "Finanziabile con buona struttura"
    if score >= 55: return score, "C", "Finanziabile con integrazioni/garanzie"
    if score >= 40: return score, "D", "Critica, necessario intervento correttivo"
    return score, "E", "Non finanziabile allo stato"


def make_cliente_pdf(cliente: str) -> bytes:
    if canvas is None:
        raise RuntimeError("reportlab non installato")
    cdata = read_table("SELECT * FROM clienti WHERE ragione_sociale=?", (cliente,))
    dfd = get_documenti_df(cliente)
    dfr = get_richieste_df(cliente)
    dfv = get_valutazioni_df(cliente)
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def page_header(title: str):
        pdf.setFillColorRGB(0.04, 0.18, 0.36)
        pdf.rect(0, height - 2.2*cm, width, 2.2*cm, stroke=0, fill=1)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(1.5*cm, height - 1.35*cm, title)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(width - 1.5*cm, height - 1.35*cm, "FinancePlus Document Manager PRO")
        pdf.setFillColorRGB(0, 0, 0)

    def wrapped(text: str, x: float, y: float, max_chars: int = 105, leading: float = 12) -> float:
        text = str(text or "")
        words = text.split()
        line = ""
        pdf.setFont("Helvetica", 9)
        for w in words:
            if len(line + " " + w) > max_chars:
                pdf.drawString(x, y, line)
                y -= leading
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            pdf.drawString(x, y, line)
            y -= leading
        return y

    page_header(f"Fascicolo cliente - {cliente}")
    y = height - 3.1*cm
    pdf.setFont("Helvetica-Bold", 12); pdf.drawString(1.5*cm, y, "Anagrafica")
    y -= 0.55*cm
    if not cdata.empty:
        row = cdata.iloc[0].to_dict()
        for label, key in [("Ragione sociale", "ragione_sociale"), ("P.IVA", "piva"), ("Codice fiscale", "cf"), ("PEC", "pec"), ("Sede", "sede"), ("Amministratore", "amministratore"), ("REA", "rea"), ("ATECO", "ateco")]:
            pdf.setFont("Helvetica-Bold", 9); pdf.drawString(1.5*cm, y, f"{label}:")
            pdf.setFont("Helvetica", 9); pdf.drawString(4.6*cm, y, str(row.get(key, "") or ""))
            y -= 0.42*cm
    y -= 0.3*cm
    pdf.setFont("Helvetica-Bold", 12); pdf.drawString(1.5*cm, y, "Documenti archiviati")
    y -= 0.55*cm
    if dfd.empty:
        pdf.setFont("Helvetica", 9); pdf.drawString(1.5*cm, y, "Nessun documento archiviato.")
    else:
        for _, r in dfd.head(28).iterrows():
            if y < 2.3*cm:
                pdf.showPage(); page_header(f"Fascicolo cliente - {cliente}"); y = height - 3*cm
            line = f"{r.get('created_at','')[:10]} | {r.get('categoria','')} | {r.get('nome_file','')}"
            y = wrapped(line, 1.5*cm, y, 110, 11)
    pdf.showPage(); page_header(f"Pratiche e valutazioni - {cliente}")
    y = height - 3.1*cm
    pdf.setFont("Helvetica-Bold", 12); pdf.drawString(1.5*cm, y, "Richieste / pratiche")
    y -= 0.55*cm
    if dfr.empty:
        pdf.setFont("Helvetica", 9); pdf.drawString(1.5*cm, y, "Nessuna richiesta registrata.")
        y -= 0.5*cm
    else:
        for _, r in dfr.head(18).iterrows():
            line = f"{r.get('created_at','')[:10]} | {r.get('banca','')} | {r.get('tipo','')} | Euro {r.get('importo',0):,.2f} | {r.get('stato','')}"
            y = wrapped(line, 1.5*cm, y, 110, 11)
    y -= 0.6*cm
    pdf.setFont("Helvetica-Bold", 12); pdf.drawString(1.5*cm, y, "Valutazioni bancarie")
    y -= 0.55*cm
    if dfv.empty:
        pdf.setFont("Helvetica", 9); pdf.drawString(1.5*cm, y, "Nessuna valutazione registrata.")
    else:
        for _, r in dfv.head(12).iterrows():
            line = f"{r.get('created_at','')[:10]} | Richiesto Euro {r.get('importo_richiesto',0):,.2f} | Score {r.get('score','')} | Rating {r.get('rating','')} | {r.get('giudizio','')}"
            y = wrapped(line, 1.5*cm, y, 105, 11)
    pdf.save(); buf.seek(0)
    return buf.getvalue()

# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("<div class='fp-title'>FinancePlus.Tech</div><div class='fp-sub'>Document Manager PRO</div>", unsafe_allow_html=True)
    st.divider()
    st.download_button("⬇️ Esporta archivio ZIP", export_zip(), "FinancePlus_Document_Manager_export.zip", "application/zip", use_container_width=True)
    st.caption(f"Database locale: `{DB_PATH}`")
    st.caption(f"Archivio locale: `{LOCAL_ARCHIVE_DIR}`")
    st.divider()
    st.markdown("<span class='fp-pill'>PRO</span><span class='fp-pill'>SQLite</span><span class='fp-pill'>PDF</span>", unsafe_allow_html=True)

st.markdown("<div class='fp-title'>🗂️ FinancePlus Document Manager PRO</div>", unsafe_allow_html=True)
st.markdown("<p class='fp-sub'>Clienti, visure/report PDF, documenti, richieste, mail, valutazione bancaria, archivio locale e predisposizione cloud.</p>", unsafe_allow_html=True)

MENU = [
    "Dashboard", "Nuovo Cliente", "Elenco Clienti", "Collaboratori", "Inserisci Report PDF", "Gestione Documenti",
    "Gestione Richieste", "Mail", "Valutazione bancaria", "Report PDF", "Archivio locale", "Google Drive", "pCloud"
]
section = st.sidebar.radio("Menu", MENU, label_visibility="collapsed")

# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------

if section == "Dashboard":
    dfc, dfd, dfr, dfv = get_clienti_df(), get_documenti_df(), get_richieste_df(), get_valutazioni_df()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Clienti", len(dfc))
    c2.metric("Documenti", len(dfd))
    c3.metric("Richieste", len(dfr))
    c4.metric("Valutazioni", len(dfv))
    c5.metric("Archivio", "Locale + Cloud ready")
    st.subheader("Ultimi documenti")
    st.dataframe(dfd[["cliente", "categoria", "nome_file", "dimensione", "created_at"]].head(30) if not dfd.empty else dfd, use_container_width=True)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Documenti per categoria")
        if not dfd.empty:
            st.bar_chart(dfd.groupby("categoria").size())
        else:
            st.info("Nessun documento archiviato.")
    with col_b:
        st.subheader("Richieste per stato")
        if not dfr.empty:
            st.bar_chart(dfr.groupby("stato").size())
        else:
            st.info("Nessuna richiesta registrata.")

elif section == "Nuovo Cliente":
    st.subheader("Nuovo Cliente")
    st.markdown("<div class='fp-warn'>Puoi compilare a mano oppure caricare una visura/report PDF: la web app estrae ragione sociale, P.IVA, CF, PEC, sede e amministratore. I dati restano modificabili prima del salvataggio.</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Carica visura camerale o report PDF per compilazione automatica", type=["pdf"], key="new_cliente_pdf")
    extracted = {}
    if uploaded:
        if PdfReader is None:
            st.error("Installa pypdf: aggiungi `pypdf>=4.0` in requirements.txt")
        else:
            with st.spinner("Lettura PDF e riconoscimento dati..."):
                text = extract_pdf_text(uploaded)
                extracted = extract_company_data(text, uploaded.name)
            with st.expander("Testo PDF estratto / controllo tecnico", expanded=False):
                st.text_area("Estratto", text[:12000], height=250)
            st.success("Dati estratti. Controllali e poi premi Salva cliente.")

    c1, c2 = st.columns(2)
    rag = c1.text_input("Ragione sociale", value=extracted.get("ragione_sociale", ""))
    piva = c2.text_input("Partita IVA", value=extracted.get("piva", ""))
    cf = c1.text_input("Codice fiscale", value=extracted.get("cf", ""))
    pec = c2.text_input("PEC", value=extracted.get("pec", ""))
    sede = st.text_input("Sede legale", value=extracted.get("sede", ""))
    c3, c4, c5 = st.columns(3)
    rea = c3.text_input("REA", value=extracted.get("rea", ""))
    ateco = c4.text_input("ATECO", value=extracted.get("ateco", ""))
    forma = c5.text_input("Forma giuridica", value=extracted.get("forma_giuridica", ""))
    c6, c7 = st.columns(2)
    capitale = c6.text_input("Capitale sociale", value=extracted.get("capitale_sociale", ""))
    amministratore = c7.text_input("Amministratore / legale rappresentante", value=extracted.get("amministratore", ""))
    amministratore_cf = st.text_input("Codice fiscale amministratore", value=extracted.get("amministratore_cf", ""))
    note = st.text_area("Note", value=extracted.get("note", ""))

    col1, col2 = st.columns([1, 3])
    if col1.button("💾 Salva cliente", type="primary", use_container_width=True):
        if not rag:
            st.error("Inserisci o estrai la ragione sociale.")
        else:
            upsert_cliente({
                "ragione_sociale": rag, "piva": piva, "cf": cf, "pec": pec, "sede": sede, "rea": rea,
                "ateco": ateco, "forma_giuridica": forma, "capitale_sociale": capitale,
                "amministratore": amministratore, "amministratore_cf": amministratore_cf,
                "fonte_estrazione": uploaded.name if uploaded else "manuale", "note": note,
            })
            if uploaded:
                archive_uploaded_file(rag, "Visura" if "visura" in uploaded.name.lower() else "Report PDF", "Documento usato per compilazione automatica anagrafica", uploaded, "estrazione_anagrafica")
            st.success("Cliente salvato e fascicolo aggiornato.")
    col2.info("Dopo il salvataggio il cliente appare in Elenco Clienti e diventa disponibile per documenti, richieste e report.")

elif section == "Elenco Clienti":
    st.subheader("Elenco Clienti")
    dfc = get_clienti_df()
    st.dataframe(dfc, use_container_width=True, hide_index=True)
    if not dfc.empty:
        cliente = st.selectbox("Apri scheda cliente", dfc["ragione_sociale"].tolist())
        cdata = read_table("SELECT * FROM clienti WHERE ragione_sociale=?", (cliente,))
        if not cdata.empty:
            row = cdata.iloc[0]
            st.markdown("### Scheda anagrafica")
            a, b, c = st.columns(3)
            a.write(f"**Ragione sociale:** {row.get('ragione_sociale','')}")
            a.write(f"**P.IVA:** {row.get('piva','')}")
            a.write(f"**CF:** {row.get('cf','')}")
            b.write(f"**PEC:** {row.get('pec','')}")
            b.write(f"**Sede:** {row.get('sede','')}")
            b.write(f"**Amministratore:** {row.get('amministratore','')}")
            c.write(f"**REA:** {row.get('rea','')}")
            c.write(f"**ATECO:** {row.get('ateco','')}")
            c.write(f"**Fonte:** {row.get('fonte_estrazione','')}")
        st.markdown("### Documenti cliente")
        st.dataframe(get_documenti_df(cliente), use_container_width=True)
        st.markdown("### Richieste cliente")
        st.dataframe(get_richieste_df(cliente), use_container_width=True)

elif section == "Collaboratori":
    st.subheader("Collaboratori")
    c1, c2 = st.columns(2)
    nome = c1.text_input("Nome collaboratore")
    ruolo = c2.text_input("Ruolo / funzione")
    email = c1.text_input("Email")
    telefono = c2.text_input("Telefono")
    note = st.text_area("Note collaboratore")
    if st.button("💾 Salva collaboratore", type="primary"):
        if not nome:
            st.error("Inserisci il nome.")
        else:
            cc = con(); cc.execute("INSERT INTO collaboratori(nome,ruolo,email,telefono,note) VALUES(?,?,?,?,?)", (nome, ruolo, email, telefono, note)); cc.commit(); cc.close()
            st.success("Collaboratore salvato.")
    st.dataframe(get_collaboratori_df(), use_container_width=True, hide_index=True)

elif section == "Inserisci Report PDF":
    st.subheader("Inserisci Report PDF / Visura")
    st.write("Carica un PDF: il sistema legge il contenuto e compila automaticamente anagrafica azienda e amministratore. Poi archivia il file nel fascicolo cliente.")
    pdf_file = st.file_uploader("Report PDF o visura camerale", type=["pdf"], key="report_pdf")
    if pdf_file:
        if PdfReader is None:
            st.error("pypdf non installato. Aggiungi `pypdf>=4.0` in requirements.txt")
        else:
            text = extract_pdf_text(pdf_file)
            extracted = extract_company_data(text, pdf_file.name)
            st.markdown("### Dati riconosciuti")
            e1, e2 = st.columns(2)
            rag = e1.text_input("Ragione sociale riconosciuta", value=extracted.get("ragione_sociale", ""), key="ins_rag")
            piva = e2.text_input("P.IVA", value=extracted.get("piva", ""), key="ins_piva")
            cf = e1.text_input("CF", value=extracted.get("cf", ""), key="ins_cf")
            pec = e2.text_input("PEC", value=extracted.get("pec", ""), key="ins_pec")
            sede = st.text_input("Sede legale", value=extracted.get("sede", ""), key="ins_sede")
            admin = st.text_input("Amministratore / legale rappresentante", value=extracted.get("amministratore", ""), key="ins_admin")
            categoria = st.selectbox("Categoria con cui archiviare il PDF", ["Report PDF", "Visura", "Bilancio", "Centrale Rischi", "Altro"])
            descr = st.text_input("Descrizione", value="Documento inserito da modulo Inserisci Report PDF")
            if st.button("✅ Salva anagrafica + archivia PDF", type="primary"):
                if not rag:
                    st.error("Ragione sociale non riconosciuta. Inseriscila manualmente.")
                else:
                    upsert_cliente({
                        "ragione_sociale": rag, "piva": piva, "cf": cf, "pec": pec, "sede": sede,
                        "rea": extracted.get("rea", ""), "ateco": extracted.get("ateco", ""),
                        "forma_giuridica": extracted.get("forma_giuridica", ""), "capitale_sociale": extracted.get("capitale_sociale", ""),
                        "amministratore": admin, "amministratore_cf": extracted.get("amministratore_cf", ""),
                        "fonte_estrazione": pdf_file.name, "note": "Anagrafica generata da Inserisci Report PDF",
                    })
                    ok, msg, path = archive_uploaded_file(rag, categoria, descr, pdf_file, "report_pdf_visura")
                    if ok:
                        st.success(f"Salvato. Percorso: {path}")
                    else:
                        st.warning(msg)
            with st.expander("Controllo testo PDF estratto"):
                st.text_area("Testo", text[:15000], height=300)

elif section == "Gestione Documenti":
    st.subheader("Gestione Documenti")
    dfc = get_clienti_df()
    if dfc.empty:
        st.warning("Crea prima un cliente oppure usa Inserisci Report PDF/Visura per crearlo automaticamente.")
    else:
        c1, c2 = st.columns(2)
        cliente = c1.selectbox("Cliente", dfc["ragione_sociale"].tolist())
        categoria = c2.selectbox("Categoria", CATS)
        descrizione = st.text_input("Descrizione documento")
        uploads = st.file_uploader("Carica uno o piu documenti", accept_multiple_files=True)
        if st.button("📎 Inserisci e salva documenti", type="primary"):
            if not uploads:
                st.error("Carica almeno un file.")
            else:
                results = []
                for f in uploads:
                    ok, msg, path = archive_uploaded_file(cliente, categoria, descrizione, f, "gestione_documenti")
                    results.append({"file": f.name, "esito": msg, "percorso": path})
                st.dataframe(pd.DataFrame(results), use_container_width=True)
        st.markdown("### Archivio documenti")
        docs_df = get_documenti_df(cliente)
        q = st.text_input("Filtra documenti", key="filter_docs")
        if q and not docs_df.empty:
            docs_df = docs_df[docs_df.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(), axis=1)]
        st.dataframe(docs_df, use_container_width=True, hide_index=True)

elif section == "Gestione Richieste":
    st.subheader("Gestione Richieste / Pratiche")
    dfc = get_clienti_df()
    if dfc.empty:
        st.warning("Crea prima un cliente.")
    else:
        c1, c2, c3 = st.columns(3)
        cliente = c1.selectbox("Cliente", dfc["ragione_sociale"].tolist(), key="rich_cliente")
        banca = c2.text_input("Banca / Istituto")
        tipo = c3.selectbox("Tipo richiesta", REQUEST_TYPES)
        c4, c5, c6 = st.columns(3)
        importo = c4.number_input("Importo richiesto", min_value=0.0, step=1000.0, format="%.2f")
        durata = c5.number_input("Durata mesi", min_value=0, max_value=360, step=1)
        stato = c6.selectbox("Stato", REQUEST_STATUS)
        scadenza = st.date_input("Scadenza / promemoria", value=None)
        note = st.text_area("Note pratica")
        if st.button("💾 Salva richiesta", type="primary"):
            cc = con(); cc.execute(
                "INSERT INTO richieste(cliente,banca,tipo,importo,durata_mesi,stato,scadenza,note,updated_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (cliente, banca, tipo, importo, int(durata), stato, scadenza.isoformat() if scadenza else "", note),
            ); cc.commit(); cc.close()
            st.success("Richiesta salvata.")
        st.markdown("### Elenco pratiche")
        st.dataframe(get_richieste_df(), use_container_width=True, hide_index=True)

elif section == "Mail":
    st.subheader("Mail")
    st.markdown("<div class='fp-card'>Modulo predisposto per collegamento con <b>Archivio Mail Clienti PRO</b>. Qui puoi impostare periodo, mittenti e cartella archivio; gli allegati importati potranno essere archiviati nei fascicoli cliente.</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    start = c1.date_input("Da data", value=dt.date(2026, 5, 1))
    end = c2.date_input("A data", value=dt.date(2026, 6, 30))
    senders = st.text_area("Mittenti da monitorare", value=get_setting("mail_senders", DEFAULT_SENDERS), height=180)
    local_mail_dir = st.text_input("Cartella locale archivio mail", value=get_setting("mail_archive_dir", str(LOCAL_ARCHIVE_DIR / "Mail")))
    if st.button("💾 Salva impostazioni Mail"):
        set_setting("mail_senders", senders); set_setting("mail_archive_dir", local_mail_dir); set_setting("mail_start", start.isoformat()); set_setting("mail_end", end.isoformat())
        st.success("Impostazioni mail salvate.")
    st.info("Per scaricare realmente da Gmail su Streamlit Cloud serve OAuth Google. Il modulo Archivio Mail Clienti PRO gia predisposto gestisce il flusso di autorizzazione; questo Document Manager importa e organizza i file per cliente.")

elif section == "Valutazione bancaria":
    st.subheader("Valutazione bancaria")
    dfc = get_clienti_df()
    if dfc.empty:
        st.warning("Crea prima un cliente.")
    else:
        cliente = st.selectbox("Cliente", dfc["ragione_sociale"].tolist(), key="val_cliente")
        c1, c2, c3 = st.columns(3)
        importo = c1.number_input("Importo richiesto", min_value=0.0, step=10000.0, format="%.2f")
        fatturato = c2.number_input("Fatturato ultimo anno", min_value=0.0, step=10000.0, format="%.2f")
        ebitda = c3.number_input("EBITDA", step=10000.0, format="%.2f")
        c4, c5, c6 = st.columns(3)
        pfn = c4.number_input("PFN", step=10000.0, format="%.2f")
        patrimonio = c5.number_input("Patrimonio netto", step=10000.0, format="%.2f")
        dscr = c6.number_input("DSCR stimato", min_value=0.0, step=0.05, format="%.2f")
        anomalie = st.number_input("Anomalie Centrale Rischi / sconfinamenti rilevanti", min_value=0, max_value=99, step=1)
        score, rating, giudizio = calculate_bank_score(importo, fatturato, ebitda, pfn, patrimonio, dscr, int(anomalie))
        m1, m2, m3 = st.columns(3)
        m1.metric("Score", score)
        m2.metric("Rating", rating)
        m3.metric("Giudizio", giudizio)
        if st.button("💾 Salva valutazione", type="primary"):
            cc = con(); cc.execute(
                """
                INSERT INTO valutazioni(cliente,importo_richiesto,fatturato,ebitda,pfn,patrimonio_netto,dscr,anomalie_cr,score,rating,giudizio)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (cliente, importo, fatturato, ebitda, pfn, patrimonio, dscr, int(anomalie), score, rating, giudizio),
            ); cc.commit(); cc.close()
            st.success("Valutazione salvata.")
        st.markdown("### Storico valutazioni")
        st.dataframe(get_valutazioni_df(cliente), use_container_width=True, hide_index=True)

elif section == "Report PDF":
    st.subheader("Report PDF")
    dfc = get_clienti_df()
    if dfc.empty:
        st.warning("Nessun cliente disponibile.")
    else:
        cliente = st.selectbox("Cliente", dfc["ragione_sociale"].tolist(), key="pdf_cliente")
        st.write("Genera un fascicolo PDF con anagrafica, documenti, richieste e valutazioni bancarie.")
        if canvas is None:
            st.error("reportlab non installato. Aggiungi `reportlab>=4.0` in requirements.txt")
        else:
            pdf_bytes = make_cliente_pdf(cliente)
            st.download_button("📄 Scarica report PDF cliente", pdf_bytes, f"Report_{clean_folder_name(cliente)}.pdf", "application/pdf", type="primary")
        st.markdown("### Dati inclusi")
        st.dataframe(get_documenti_df(cliente), use_container_width=True)

elif section == "Archivio locale":
    st.subheader("Archivio locale")
    st.write("Questa sezione gestisce il fascicolo sul file system locale della web app. In Streamlit Cloud lo storage puo essere temporaneo; su PC/server aziendale diventa archivio stabile.")
    st.code(str(LOCAL_ARCHIVE_DIR))
    st.download_button("⬇️ Scarica ZIP completo archivio", export_zip(), "FinancePlus_Document_Manager_export.zip", "application/zip", type="primary")
    st.markdown("### Struttura prevista")
    st.code("""financeplus_document_data/
├── ArchivioLocale/
│   ├── Clienti/
│   │   ├── NOME AZIENDA/
│   │   │   ├── Visura/
│   │   │   ├── Report PDF/
│   │   │   ├── Bilancio/
│   │   │   └── Email e allegati/
│   └── Mail/
└── financeplus_documents.db""")
    st.markdown("### Duplicati")
    dup = remove_duplicate_records_preview()
    if dup.empty:
        st.success("Non risultano duplicati nel database documentale.")
    else:
        st.warning("Duplicati rilevati nel database.")
        st.dataframe(dup, use_container_width=True)

elif section == "Google Drive":
    st.subheader("Predisposizione Google Drive")
    st.write("Qui imposti i parametri per la futura sincronizzazione Drive. La versione attuale conserva le credenziali/ID cartella nel database locale; l'attivazione API richiede client OAuth Google.")
    folder_id = st.text_input("Google Drive Folder ID", value=get_setting("gdrive_folder_id", ""))
    client_json_info = st.text_area("Nota credenziali OAuth / Service Account", value=get_setting("gdrive_note", ""), height=120)
    sync_mode = st.selectbox("Modalita sincronizzazione", ["Disattivata", "Upload documenti", "Download documenti", "Bidirezionale"], index=["Disattivata", "Upload documenti", "Download documenti", "Bidirezionale"].index(get_setting("gdrive_mode", "Disattivata")))
    if st.button("💾 Salva predisposizione Google Drive"):
        set_setting("gdrive_folder_id", folder_id); set_setting("gdrive_note", client_json_info); set_setting("gdrive_mode", sync_mode)
        st.success("Predisposizione Google Drive salvata.")
    st.info("Per renderla operativa: Google Cloud Console > Gmail/Drive API > OAuth consent screen > Client ID > inserimento secrets su Streamlit Cloud.")

elif section == "pCloud":
    st.subheader("Predisposizione pCloud")
    st.write("Predisposizione per sincronizzazione con pCloud tramite API/WebDAV o cartella sincronizzata del PC.")
    pcloud_path = st.text_input("Cartella pCloud o mount locale", value=get_setting("pcloud_path", ""))
    pcloud_mode = st.selectbox("Modalita pCloud", ["Disattivata", "Cartella sincronizzata", "API pCloud", "WebDAV"], index=["Disattivata", "Cartella sincronizzata", "API pCloud", "WebDAV"].index(get_setting("pcloud_mode", "Disattivata")))
    token_note = st.text_area("Note token/API", value=get_setting("pcloud_note", ""), height=120)
    if st.button("💾 Salva predisposizione pCloud"):
        set_setting("pcloud_path", pcloud_path); set_setting("pcloud_mode", pcloud_mode); set_setting("pcloud_note", token_note)
        st.success("Predisposizione pCloud salvata.")
    st.info("Soluzione piu semplice su PC: installa pCloud Drive, scegli la cartella sincronizzata e imposta qui quel percorso come archivio stabile.")
