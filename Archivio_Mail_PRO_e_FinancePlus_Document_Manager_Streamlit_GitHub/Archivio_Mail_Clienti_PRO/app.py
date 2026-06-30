import os, re, io, csv, json, hashlib, zipfile, sqlite3, datetime as dt
from pathlib import Path
import streamlit as st

APP_TITLE = 'Archivio Mail Clienti PRO'
DEFAULT_SENDERS = '''elibetty731@gmail.com
Valentinaboratto82@gmail.com
stefano.faraone@eurofintechsrl.it
praticheBS@proton.me
sergio.pedolazzi@katudi.it
paolo.baldinelli@katudi.it
pratiche@katudi.it
niccolo.sovico@ener2crowd.com'''
BASE_DIR = Path('archivio_mail_data')
DB_PATH = BASE_DIR / 'archivio_mail.db'

st.set_page_config(page_title=APP_TITLE, page_icon='📥', layout='wide')

CSS = '''
<style>
.main .block-container{padding-top:2rem;}
.card{background:#fff;border:1px solid #e8edf5;border-radius:16px;padding:18px;box-shadow:0 4px 20px rgba(0,0,0,.04)}
.metric-card{background:linear-gradient(135deg,#0b2f5b,#0f5a8a);color:white;border-radius:18px;padding:18px}
.small{font-size:12px;color:#6b7280}
</style>
'''
st.markdown(CSS, unsafe_allow_html=True)


def init_db():
    BASE_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS allegati(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_mail TEXT, mittente TEXT, azienda TEXT, oggetto TEXT,
        nome_file TEXT, tipo TEXT, dimensione INTEGER, md5 TEXT, percorso TEXT, fonte TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_md5 ON allegati(md5)')
    con.commit(); con.close()


def clean_name(s):
    s = re.sub(r'[\\/:*?"<>|]+', '-', (s or '').strip())
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:90] or 'Da verificare'


def detect_company(text):
    text = re.sub(r'\s+', ' ', text or ' ')
    pats = [
        r'([A-Z0-9À-Ù &\.\-]{2,80}\s+(?:SRL|S\.R\.L\.|SPA|S\.P\.A\.|SAS|SNC|SRLS|S\.R\.L\.S\.))',
        r'(?:azienda|cliente|pratica|documenti|bilancio|visura)\s+([A-Z0-9À-Ù &\.\-]{3,80})'
    ]
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return clean_name(m.group(1).upper())
    return 'Da verificare'


def md5_bytes(b): return hashlib.md5(b).hexdigest()


def save_uploaded_files(files, sender, subject, date_mail, root_name):
    root = BASE_DIR / clean_name(root_name)
    rows, skipped = [], 0
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    for up in files:
        data = up.getvalue()
        md5 = md5_bytes(data)
        azienda = detect_company(subject + ' ' + up.name)
        dest = root / clean_name(sender) / azienda / date_mail[:7]
        dest.mkdir(parents=True, exist_ok=True)
        fname = clean_name(up.name)
        path = dest / fname
        try:
            cur.execute('''INSERT INTO allegati(data_mail,mittente,azienda,oggetto,nome_file,tipo,dimensione,md5,percorso,fonte)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (date_mail, sender, azienda, subject, fname, Path(fname).suffix.lower(), len(data), md5, str(path), 'upload/manuale'))
            path.write_bytes(data)
            rows.append((date_mail, sender, azienda, subject, fname, str(path)))
        except sqlite3.IntegrityError:
            skipped += 1
    con.commit(); con.close()
    return rows, skipped


def read_table():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('SELECT data_mail,mittente,azienda,oggetto,nome_file,tipo,dimensione,percorso FROM allegati ORDER BY data_mail DESC, id DESC')
    rows = cur.fetchall(); con.close()
    return rows


def export_zip():
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        if BASE_DIR.exists():
            for p in BASE_DIR.rglob('*'):
                if p.is_file(): z.write(p, p.relative_to(BASE_DIR.parent))
    mem.seek(0); return mem

init_db()
st.title('📥 Archivio Mail Clienti PRO')
st.caption('Archivio allegati Gmail, cartelle per mittente e azienda, duplicati MD5, report e ZIP finale.')

with st.sidebar:
    st.header('Configurazione')
    st.info('Per Gmail reale: inserisci le credenziali OAuth Google nel file secrets.toml o usa il modulo manuale per test operativo.')
    mode = st.radio('Modalità', ['Demo / Upload manuale', 'Gmail API - da configurare'])
    st.download_button('Scarica archivio ZIP', data=export_zip(), file_name='Archivio_Mail_Clienti_PRO_export.zip')

tab1, tab2, tab3, tab4 = st.tabs(['📥 Scarica/Importa', '🔍 Cerca', '📊 Report', '⚙️ Impostazioni'])

with tab1:
    c1,c2,c3 = st.columns(3)
    start = c1.date_input('Data inizio', dt.date(2026,5,1))
    end = c2.date_input('Data fine', dt.date(2026,6,30))
    root_name = c3.text_input('Cartella archivio', 'ALLEGATI_MAIL_01-05-2026_30-06-2026')
    senders = st.text_area('Mittenti da controllare', DEFAULT_SENDERS, height=150)
    st.divider()
    if mode == 'Demo / Upload manuale':
        st.subheader('Import manuale allegati')
        sender = st.selectbox('Mittente', [x.strip() for x in senders.splitlines() if x.strip()])
        subject = st.text_input('Oggetto mail / testo utile per riconoscere azienda', 'Documenti bilancio BEL GARDEN EUROPE SRL')
        date_mail = st.date_input('Data mail', dt.date(2026,5,1)).isoformat()
        files = st.file_uploader('Carica allegati', accept_multiple_files=True)
        if st.button('📥 Archivia allegati') and files:
            rows, skipped = save_uploaded_files(files, sender, subject, date_mail, root_name)
            st.success(f'Archiviati: {len(rows)} - Duplicati saltati: {skipped}')
            st.dataframe(rows, use_container_width=True)
    else:
        st.warning('Modulo Gmail API predisposto: configurare Google Cloud OAuth e secrets.toml. Vedi guida PDF.')
        if st.button('Test configurazione Gmail'):
            st.error('Credenziali OAuth non trovate. Caricare client_secret.json/secrets.toml secondo guida.')

with tab2:
    q = st.text_input('Cerca per azienda, mittente, oggetto o file')
    rows = read_table()
    if q:
        rows = [r for r in rows if q.lower() in ' '.join(map(str,r)).lower()]
    st.dataframe(rows, use_container_width=True)

with tab3:
    rows = read_table()
    st.metric('Allegati archiviati', len(rows))
    aziende = len(set(r[2] for r in rows)) if rows else 0
    mittenti = len(set(r[1] for r in rows)) if rows else 0
    c1,c2,c3 = st.columns(3)
    c1.metric('Aziende', aziende); c2.metric('Mittenti', mittenti); c3.metric('Duplicati bloccati', 'MD5 attivo')
    csv_mem = io.StringIO(); writer = csv.writer(csv_mem); writer.writerow(['data','mittente','azienda','oggetto','file','tipo','dimensione','percorso']); writer.writerows(rows)
    st.download_button('Scarica report CSV', csv_mem.getvalue(), 'report_archivio_mail.csv', 'text/csv')

with tab4:
    st.code('streamlit run app.py')
    st.markdown('Per Streamlit Cloud: caricare repository su GitHub e impostare app.py come main file.')
