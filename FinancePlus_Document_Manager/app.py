import os, re, io, csv, json, hashlib, zipfile, sqlite3, datetime as dt
from pathlib import Path
import streamlit as st
import pandas as pd

APP_TITLE = 'FinancePlus Document Manager'
BASE_DIR = Path('financeplus_document_data')
DB_PATH = BASE_DIR / 'financeplus_documents.db'

st.set_page_config(page_title=APP_TITLE, page_icon='🗂️', layout='wide')
st.markdown('''<style>
.block-container{padding-top:1.4rem}.fp-card{border:1px solid #e6edf7;border-radius:18px;padding:18px;background:#fff;box-shadow:0 6px 22px rgba(10,40,80,.05)}
.big{font-size:28px;font-weight:800;color:#0b2f5b}.muted{color:#667085;font-size:13px}.pill{background:#f4e4d0;color:#7a3f00;border-radius:99px;padding:4px 10px;font-size:12px}
</style>''', unsafe_allow_html=True)

CATS = ['Bilanci','Centrale Rischi','Visure','Estratti conto','Contratti','Mandati','Business Plan','Report banca','Email e allegati','Altro']


def init_db():
    BASE_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS clienti(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ragione_sociale TEXT UNIQUE, piva TEXT, cf TEXT, pec TEXT, sede TEXT, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS documenti(
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, categoria TEXT, data_doc TEXT, nome_file TEXT, estensione TEXT,
        dimensione INTEGER, md5 TEXT UNIQUE, percorso TEXT, descrizione TEXT, fonte TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS pratiche(
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, banca TEXT, importo REAL, stato TEXT, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    con.commit(); con.close()


def clean(s):
    s = re.sub(r'[\\/:*?"<>|]+','-',(s or '').strip())
    return re.sub(r'\s+',' ',s)[:100] or 'Senza nome'

def md5b(b): return hashlib.md5(b).hexdigest()

def add_cliente(ragione, piva='', cf='', pec='', sede='', note=''):
    con=sqlite3.connect(DB_PATH); cur=con.cursor()
    cur.execute('INSERT OR IGNORE INTO clienti(ragione_sociale,piva,cf,pec,sede,note) VALUES(?,?,?,?,?,?)',(ragione,piva,cf,pec,sede,note))
    con.commit(); con.close()

def clienti():
    con=sqlite3.connect(DB_PATH); df=pd.read_sql_query('SELECT ragione_sociale,piva,pec,sede,created_at FROM clienti ORDER BY ragione_sociale',con); con.close(); return df

def docs():
    con=sqlite3.connect(DB_PATH); df=pd.read_sql_query('SELECT cliente,categoria,data_doc,nome_file,estensione,dimensione,percorso,descrizione,created_at FROM documenti ORDER BY created_at DESC',con); con.close(); return df

def save_docs(cliente,categoria,desc,files):
    rows=[]; con=sqlite3.connect(DB_PATH); cur=con.cursor()
    for up in files:
        data=up.getvalue(); md5=md5b(data); name=clean(up.name); ext=Path(name).suffix.lower()
        dest=BASE_DIR/'Clienti'/clean(cliente)/clean(categoria); dest.mkdir(parents=True,exist_ok=True); path=dest/name
        try:
            cur.execute('INSERT INTO documenti(cliente,categoria,data_doc,nome_file,estensione,dimensione,md5,percorso,descrizione,fonte) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (cliente,categoria,dt.date.today().isoformat(),name,ext,len(data),md5,str(path),desc,'upload'))
            path.write_bytes(data); rows.append((cliente,categoria,name,str(path)))
        except sqlite3.IntegrityError: pass
    con.commit(); con.close(); return rows

def export_zip():
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        if BASE_DIR.exists():
            for p in BASE_DIR.rglob('*'):
                if p.is_file(): z.write(p,p.relative_to(BASE_DIR.parent))
    mem.seek(0); return mem

init_db()
with st.sidebar:
    st.image('https://dummyimage.com/300x80/0b2f5b/ffffff&text=FinancePlus.Tech', use_container_width=True)
    st.caption('Document Manager - modulo archivio documentale')
    st.download_button('⬇️ Export ZIP archivio', export_zip(), 'FinancePlus_Document_Manager_export.zip')

st.title('🗂️ FinancePlus Document Manager')
st.caption('Anagrafica clienti, fascicoli documentali, pratiche bancarie, ricerca e collegamento con Archivio Mail Clienti PRO.')

tabs=st.tabs(['🏠 Dashboard','👥 Clienti','📎 Documenti','🏦 Pratiche','🔍 Ricerca','📊 Report','⚙️ Integrazione Mail'])

with tabs[0]:
    dfc=clienti(); dfd=docs()
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Clienti', len(dfc)); c2.metric('Documenti', len(dfd)); c3.metric('Categorie', dfd.categoria.nunique() if not dfd.empty else 0); c4.metric('Archivio', 'SQLite + file')
    st.subheader('Ultimi documenti')
    st.dataframe(dfd.head(20), use_container_width=True)

with tabs[1]:
    st.subheader('Nuovo cliente')
    c1,c2=st.columns(2)
    rag=c1.text_input('Ragione sociale')
    piva=c2.text_input('Partita IVA')
    cf=c1.text_input('Codice fiscale')
    pec=c2.text_input('PEC')
    sede=st.text_input('Sede legale')
    note=st.text_area('Note')
    if st.button('Salva cliente') and rag:
        add_cliente(rag,piva,cf,pec,sede,note); st.success('Cliente salvato')
    st.dataframe(clienti(), use_container_width=True)

with tabs[2]:
    dfc=clienti()
    if dfc.empty: st.warning('Crea prima almeno un cliente.')
    else:
        cliente=st.selectbox('Cliente', dfc.ragione_sociale.tolist())
        categoria=st.selectbox('Categoria documento', CATS)
        desc=st.text_input('Descrizione documento')
        files=st.file_uploader('Carica documenti', accept_multiple_files=True)
        if st.button('Archivia documenti') and files:
            rows=save_docs(cliente,categoria,desc,files); st.success(f'Documenti archiviati: {len(rows)}'); st.dataframe(rows)
    st.dataframe(docs(), use_container_width=True)

with tabs[3]:
    st.subheader('Nuova pratica bancaria')
    dfc=clienti()
    if not dfc.empty:
        cliente=st.selectbox('Cliente pratica', dfc.ragione_sociale.tolist(), key='prac_cliente')
        banca=st.text_input('Banca / Istituto')
        importo=st.number_input('Importo richiesto', min_value=0.0, step=1000.0)
        stato=st.selectbox('Stato', ['Bozza','Documenti richiesti','In istruttoria','Deliberata','Respinta','Erogata'])
        note=st.text_area('Note pratica')
        if st.button('Salva pratica'):
            con=sqlite3.connect(DB_PATH); con.execute('INSERT INTO pratiche(cliente,banca,importo,stato,note) VALUES(?,?,?,?,?)',(cliente,banca,importo,stato,note)); con.commit(); con.close(); st.success('Pratica salvata')
    con=sqlite3.connect(DB_PATH); st.dataframe(pd.read_sql_query('SELECT * FROM pratiche ORDER BY created_at DESC',con), use_container_width=True); con.close()

with tabs[4]:
    q=st.text_input('Ricerca full archive')
    dfd=docs()
    if q and not dfd.empty:
        mask=dfd.apply(lambda r: q.lower() in ' '.join(map(str,r.values)).lower(), axis=1)
        dfd=dfd[mask]
    st.dataframe(dfd, use_container_width=True)

with tabs[5]:
    dfd=docs()
    if not dfd.empty:
        st.bar_chart(dfd.groupby('categoria').size())
        csv=dfd.to_csv(index=False).encode('utf-8')
        st.download_button('Scarica report documenti CSV', csv, 'report_documenti_financeplus.csv','text/csv')
    else: st.info('Nessun documento ancora archiviato.')

with tabs[6]:
    st.subheader('Collegamento con Archivio Mail Clienti PRO')
    st.write('Workflow consigliato: Archivio Mail Clienti PRO scarica allegati da Gmail; FinancePlus Document Manager li importa nel fascicolo cliente.')
    st.code('Archivio Mail Clienti PRO -> export ZIP/Cartella -> FinancePlus Document Manager -> categoria Email e allegati')
    st.info('Nella versione Enterprise si può unificare il database e sincronizzare automaticamente gli allegati nel fascicolo del cliente.')
