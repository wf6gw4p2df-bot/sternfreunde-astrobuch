import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
import uuid
import re
import html
import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload


# ------------------------------------------------------------
# Grundkonfiguration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Faszination Nachthimmel",
    page_icon="🌌",
    layout="wide",
)

MAX_UPLOAD_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

KATEGORIEN = [
    "Deep Sky",
    "Milchstraße",
    "Planeten",
    "Mond",
    "Sonne",
    "Nightscape / Landschaft mit Nachthimmel",
    "Sternspuren",
    "Polarlicht",
    "Kometen",
    "Sternschnuppen / Meteore",
    "Sonnen- und Mondfinsternisse",
    "Panorama- und Spezialtechniken",
    "Sonstiges",
]

COLUMNS = [
    "Zeitpunkt",
    "Dein Name",
    "Deine E-Mail",
    "Name deines Bildes",
    "Kategorie",
    "Bilddatei",
]

SCOPES = ["https://www.googleapis.com/auth/drive"]


# ------------------------------------------------------------
# Google Drive
# ------------------------------------------------------------
@st.cache_resource
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gdrive"]),
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def drive_folder_id():
    return st.secrets["gdrive"]["drive_folder_id"]


def find_drive_file(filename):
    service = get_drive_service()
    query = (
        f"name='{filename}' and "
        f"'{drive_folder_id()}' in parents and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0] if files else None


def upload_bytes_to_drive(filename, data, mimetype):
    service = get_drive_service()
    existing = find_drive_file(filename)

    media = MediaIoBaseUpload(
        io.BytesIO(data),
        mimetype=mimetype,
        resumable=True,
    )

    if existing:
        uploaded = service.files().update(
            fileId=existing["id"],
            media_body=media,
            fields="id,name",
        ).execute()
    else:
        metadata = {
            "name": filename,
            "parents": [drive_folder_id()],
        }
        uploaded = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name",
        ).execute()

    return uploaded


def download_drive_file(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    return buffer.getvalue()


def delete_drive_file(file_id: str) -> None:
    if not file_id:
        return
    try:
        service = get_drive_service()
        service.files().delete(fileId=file_id).execute()
    except Exception:
        pass


# ------------------------------------------------------------
# Hilfsfunktionen
# ------------------------------------------------------------
def safe_filename(filename: str) -> str:
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_")
    return f"{stem}_{uuid.uuid4().hex[:8]}{ext}"


def load_data() -> pd.DataFrame:
    csv_file = find_drive_file("beitraege.csv")

    if csv_file:
        data = download_drive_file(csv_file["id"])
        df = pd.read_csv(io.BytesIO(data))
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNS]

    return pd.DataFrame(columns=COLUMNS)


def save_data(df: pd.DataFrame) -> None:
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    upload_bytes_to_drive(
        "beitraege.csv",
        csv_bytes,
        "text/csv",
    )


def save_upload(uploaded_file) -> str:
    filename = safe_filename(uploaded_file.name)
    uploaded = upload_bytes_to_drive(
        filename,
        uploaded_file.getvalue(),
        uploaded_file.type or "application/octet-stream",
    )
    return uploaded["id"]


def delete_image_file(img_id: str) -> None:
    delete_drive_file(img_id)


def delete_entry(original_index: int) -> None:
    df_all = load_data()

    if original_index not in df_all.index:
        return

    delete_image_file(str(df_all.loc[original_index, "Bilddatei"]))
    df_all = df_all.drop(index=original_index).reset_index(drop=True)
    save_data(df_all)


def csv_without_images(df_all: pd.DataFrame) -> bytes:
    export_df = df_all.copy()

    if "Bilddatei" in export_df.columns:
        export_df["Bilddatei_ID"] = export_df["Bilddatei"]
        export_df = export_df.drop(columns=["Bilddatei"])

    ordered_cols = [
        "Zeitpunkt",
        "Dein Name",
        "Deine E-Mail",
        "Name deines Bildes",
        "Kategorie",
        "Bilddatei_ID",
    ]
    export_df = export_df[[c for c in ordered_cols if c in export_df.columns]]
    return export_df.to_csv(index=False).encode("utf-8-sig")


def esc(value) -> str:
    return html.escape(str(value)) if pd.notna(value) else ""


def get_edit_defaults(df_all: pd.DataFrame):
    edit_index = st.session_state.get("edit_index")

    if edit_index is None or edit_index not in df_all.index:
        return None

    row = df_all.loc[edit_index]
    return {
        "index": int(edit_index),
        "name": str(row.get("Dein Name", "")),
        "email": str(row.get("Deine E-Mail", "")),
        "bildtitel": str(row.get("Name deines Bildes", "")),
        "kategorie": str(row.get("Kategorie", KATEGORIEN[0])),
        "bilddatei": str(row.get("Bilddatei", "")),
    }


# ------------------------------------------------------------
# Design / CSS
# ------------------------------------------------------------
st.markdown(
    """
<style>
.stApp {
    background:
        radial-gradient(circle at top left, rgba(68, 81, 166, 0.35), transparent 34rem),
        radial-gradient(circle at top right, rgba(212, 175, 55, 0.12), transparent 30rem),
        linear-gradient(180deg, #050816 0%, #0b1020 48%, #05070d 100%);
    color: #e5edf7;
}

.block-container {
    padding-top: 2.2rem;
    padding-bottom: 4rem;
    max-width: 1180px;
}

h1, h2, h3 {
    color: #ffffff !important;
}

h1 {
    font-size: clamp(2.1rem, 4vw, 3.6rem) !important;
    letter-spacing: -0.04em;
    margin-bottom: 1.4rem !important;
}

h2, h3 {
    letter-spacing: -0.02em;
}

p, li, label, span {
    color: #dbe4f0 !important;
}

.form-title,
.gallery-title {
    color: #ffffff !important;
    font-size: 1.75rem !important;
    font-weight: 900 !important;
    margin-top: 0.4rem !important;
    margin-bottom: 1.1rem !important;
    text-shadow: 0 2px 14px rgba(0,0,0,0.45);
}

.info-box {
    background: rgba(15, 23, 42, 0.82);
    border: 1px solid rgba(212, 175, 55, 0.28);
    border-radius: 24px;
    padding: 1.6rem 1.8rem;
    margin-bottom: 1.8rem;
    line-height: 1.65;
    box-shadow: 0 18px 60px rgba(0,0,0,0.28);
}

.info-box p {
    color: #dbe4f0 !important;
    font-size: 1.02rem;
}

.info-box strong,
.info-box b {
    color: #dbe4f0 !important;
    font-weight: 700 !important;
}

div[data-testid="stForm"] {
    background: rgba(15, 23, 42, 0.90);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 24px;
    padding: 1.6rem 1.8rem;
    box-shadow: 0 16px 54px rgba(0,0,0,0.32);
}

.stTextInput input,
.stSelectbox div[data-baseweb="select"] > div,
.stTextArea textarea {
    background-color: #ffffff !important;
    color: #111827 !important;
    border-radius: 12px !important;
}

.stTextInput input::placeholder {
    color: #6b7280 !important;
}

.stTextInput label,
.stSelectbox label,
.stFileUploader label {
    color: #ffffff !important;
    font-weight: 800 !important;
    font-size: 1.0rem !important;
}

.stSelectbox div[data-baseweb="select"] span,
.stSelectbox div[data-baseweb="select"] div {
    color: #111827 !important;
}

div[data-baseweb="popover"] div,
div[data-baseweb="popover"] span,
ul[role="listbox"] li,
ul[role="listbox"] div,
ul[role="listbox"] span {
    color: #111827 !important;
    background-color: #ffffff !important;
}

.stFileUploader section {
    background: #ffffff !important;
    border: 2px dashed rgba(212, 175, 55, 0.95) !important;
    border-radius: 16px !important;
}

.stFileUploader section div,
.stFileUploader section span,
.stFileUploader section p {
    color: #111827 !important;
}

.stFileUploader small {
    display: none !important;
}

.stFileUploader button {
    background: #d4af37 !important;
    color: #111827 !important;
    border-radius: 10px !important;
    border: none !important;
    font-weight: 800 !important;
}

.stFileUploader button p,
.stFileUploader button span {
    color: #111827 !important;
}

div[data-testid="stFormSubmitButton"] button,
.stDownloadButton > button {
    background: linear-gradient(135deg, #f6d67a, #d4af37 55%, #b8860b) !important;
    color: #111827 !important;
    font-weight: 900 !important;
    border: none !important;
    border-radius: 14px !important;
    padding: 0.72rem 1.25rem !important;
    box-shadow: 0 12px 28px rgba(212,175,55,0.22) !important;
    opacity: 1 !important;
}

div[data-testid="stFormSubmitButton"] button p,
div[data-testid="stFormSubmitButton"] button span,
.stDownloadButton > button p,
.stDownloadButton > button span {
    color: #111827 !important;
    font-weight: 900 !important;
}

div[data-testid="stFormSubmitButton"] button:hover,
.stDownloadButton > button:hover {
    filter: brightness(1.06) !important;
    transform: translateY(-1px);
}

div[data-testid="stFormSubmitButton"] button:disabled,
div[data-testid="stFormSubmitButton"] button[disabled] {
    background: linear-gradient(135deg, #e7c75e, #b99428) !important;
    color: #111827 !important;
    opacity: 0.74 !important;
}

.stButton > button {
    background: transparent !important;
    color: #f6d67a !important;
    font-weight: 850 !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0.15rem 0.05rem !important;
    box-shadow: none !important;
    text-decoration: underline !important;
    text-underline-offset: 0.18rem !important;
}

.stButton > button:hover {
    background: transparent !important;
    color: #ffe59a !important;
}

.stButton > button p,
.stButton > button span {
    color: #f6d67a !important;
    font-weight: 850 !important;
}

.card-wide {
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 22px;
    padding: 1rem;
    margin-bottom: 1.35rem;
    box-shadow: 0 16px 44px rgba(0,0,0,0.24);
}

.card-wide h3 {
    margin-top: 0.15rem;
    margin-bottom: 0.45rem;
    font-size: 1.45rem;
    color: #ffffff !important;
}

.card-wide .meta {
    color: #cbd5e1 !important;
    font-size: 1rem;
    margin-bottom: 0.35rem;
}

.edit-notice {
    background: rgba(212, 175, 55, 0.12);
    border: 1px solid rgba(212,175,55,0.34);
    border-radius: 16px;
    padding: 0.85rem 1rem;
    margin-bottom: 1rem;
    color: #f6d67a !important;
    font-weight: 750;
}

.csv-box {
    margin-top: 2.2rem;
    margin-bottom: 1.2rem;
    padding: 1.05rem 1.2rem;
    border-radius: 18px;
    background: rgba(15, 23, 42, 0.86);
    border: 1px solid rgba(255,255,255,0.18);
}

.csv-box p,
.csv-box span,
.csv-box div {
    color: #dbe4f0 !important;
}

div[data-testid="stAlert"] p,
div[data-testid="stAlert"] span,
div[data-testid="stAlert"] div {
    color: #111827 !important;
}

.streamlit-expanderHeader {
    color: #ffffff !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Kopfbereich
# ------------------------------------------------------------
st.title("Faszination Nachthimmel – Fotografien der Sternfreunde Münster")

st.markdown(
    """
<div class="info-box">
<p><strong>Hallo zusammen,</strong></p>

<p>wir wollen ein gemeinsames Astrobuch der Sternenfreunde Münster im Format <b>21 × 21 cm</b> erstellen,
das die Vielfalt und Schönheit der Astrofotografie unserer Mitglieder zeigt.</p>

<p>Geplant sind beeindruckende Bilder aus unterschiedlichen Bereichen der Astronomie- und Nachtfotografie –
beispielsweise <b>Deep Sky, Mond und Planeten, Sternspuren, Nightscape/Landschaft mit Nachthimmel,
Milchstraße, Polarlichter, Sonnen- und Mondfinsternisse, Sternschnuppen, Kometen</b> und vieles mehr.</p>

<p>Zu jedem ausgewählten Bild soll auf einer begleitenden Seite etwas über das <b>Motiv</b>,
die <b>verwendete Technik</b>, den <b>Aufnahmezeitpunkt</b>, den <b>Ort der Aufnahme</b> sowie die
<b>Bildbearbeitung</b> erzählt werden – also auch die Geschichte hinter dem Bild.</p>

<p><b>Jeder kann mitmachen!</b></p>

<p>Mit dieser unverbindlichen Interessensabfrage möchten wir zunächst eine Idee davon bekommen,
welche Motive vorhanden sind, wie vielfältig die Beiträge sein könnten und welchen Umfang das Projekt haben kann.
Eine Eintragung ist daher <b>noch keine Verpflichtung</b>, sondern zunächst eine Möglichkeit, Interesse und mögliche
Bildideen zu teilen.</p>

<p>Wir freuen uns auf eure Beiträge und darauf, gemeinsam die Faszination des Nachthimmels in einem besonderen
Buchprojekt sichtbar zu machen!</p>
</div>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Formular mit Neu-/Ändern-Modus
# ------------------------------------------------------------
df_all = load_data()
edit_defaults = get_edit_defaults(df_all)

if edit_defaults:
    st.markdown(
        f'<div class="edit-notice">Änderungsmodus: Der Eintrag „{esc(edit_defaults["bildtitel"])}“ wird bearbeitet.</div>',
        unsafe_allow_html=True,
    )

with st.form("upload_form", clear_on_submit=(edit_defaults is None)):
    if edit_defaults:
        st.markdown('<div class="form-title">Bildvorschlag ändern</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="form-title">Bildvorschlag einreichen</div>', unsafe_allow_html=True)

    name = st.text_input("Dein Name *", value=edit_defaults["name"] if edit_defaults else "")
    email = st.text_input("Deine E-Mail *", value=edit_defaults["email"] if edit_defaults else "")
    bildtitel = st.text_input(
        "Name deines Bildes *",
        value=edit_defaults["bildtitel"] if edit_defaults else "",
    )

    current_category = edit_defaults["kategorie"] if edit_defaults else KATEGORIEN[0]
    if current_category not in KATEGORIEN:
        current_category = KATEGORIEN[0]

    kategorie = st.selectbox(
        "Kategorie *",
        KATEGORIEN,
        index=KATEGORIEN.index(current_category),
    )

    if edit_defaults:
        st.caption("Wenn kein neues Bild hochgeladen wird, bleibt das bisherige Bild erhalten.")

    uploaded = st.file_uploader(
        "Bildvorschlag hochladen *" if not edit_defaults else "Neues Bild hochladen (optional)",
        type=["jpg", "jpeg", "png", "webp", "tif", "tiff"],
        help=f"Maximale Dateigröße: {MAX_UPLOAD_MB} MB",
    )
    st.caption(f"Maximale Dateigröße: {MAX_UPLOAD_MB} MB · JPG, PNG, WEBP oder TIF")

    submit_label = "Änderungen speichern" if edit_defaults else "Bildvorschlag speichern"
    submitted = st.form_submit_button(submit_label)

    if submitted:
        if not name.strip() or not email.strip() or not bildtitel.strip():
            st.error("Bitte Name, E-Mail und Bildname ausfüllen.")
        elif not edit_defaults and uploaded is None:
            st.error("Bitte eine Bilddatei hochladen.")
        elif uploaded is not None and uploaded.size > MAX_UPLOAD_BYTES:
            st.error(f"Die Bilddatei ist zu groß. Bitte maximal {MAX_UPLOAD_MB} MB hochladen.")
        else:
            df_all = load_data()

            if edit_defaults:
                old_img = str(df_all.loc[edit_defaults["index"], "Bilddatei"])
                if uploaded is not None:
                    delete_image_file(old_img)
                    img_id = save_upload(uploaded)
                else:
                    img_id = old_img

                df_all.loc[edit_defaults["index"], "Zeitpunkt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                df_all.loc[edit_defaults["index"], "Dein Name"] = name.strip()
                df_all.loc[edit_defaults["index"], "Deine E-Mail"] = email.strip()
                df_all.loc[edit_defaults["index"], "Name deines Bildes"] = bildtitel.strip()
                df_all.loc[edit_defaults["index"], "Kategorie"] = kategorie
                df_all.loc[edit_defaults["index"], "Bilddatei"] = img_id
                save_data(df_all)

                st.session_state.pop("edit_index", None)
                st.success("Änderungen gespeichert.")
                st.rerun()
            else:
                img_id = save_upload(uploaded)
                new_row = {
                    "Zeitpunkt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Dein Name": name.strip(),
                    "Deine E-Mail": email.strip(),
                    "Name deines Bildes": bildtitel.strip(),
                    "Kategorie": kategorie,
                    "Bilddatei": img_id,
                }
                df_all = pd.concat([df_all, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df_all)
                st.success("Danke! Dein Bildvorschlag wurde gespeichert.")
                st.rerun()

if edit_defaults:
    if st.button("Bearbeitung abbrechen"):
        st.session_state.pop("edit_index", None)
        st.rerun()


# ------------------------------------------------------------
# Galerie
# ------------------------------------------------------------
st.divider()
st.markdown('<div class="gallery-title">Eingereichte Bildvorschläge</div>', unsafe_allow_html=True)

df_all = load_data()
df = df_all[df_all["Bilddatei"].fillna("").astype(str).str.strip() != ""].copy()

if df.empty:
    st.info("Noch keine Bildvorschläge mit Bild vorhanden.")
else:
    sort_by = st.selectbox(
        "Sortieren nach",
        [
            "Kategorie",
            "Name des Einreichers",
            "Name des Bildes",
            "Neueste zuerst",
        ],
    )

    if sort_by == "Kategorie":
        df = df.sort_values(["Kategorie", "Name deines Bildes", "Dein Name"], ascending=True)
    elif sort_by == "Name des Einreichers":
        df = df.sort_values(["Dein Name", "Name deines Bildes"], ascending=True)
    elif sort_by == "Name des Bildes":
        df = df.sort_values(["Name deines Bildes", "Dein Name"], ascending=True)
    else:
        df = df.sort_values("Zeitpunkt", ascending=False)

    for original_index, row in df.iterrows():
        img_id = str(row["Bilddatei"])

        st.markdown('<div class="card-wide">', unsafe_allow_html=True)
        img_col, text_col = st.columns([1.25, 1.75])

        with img_col:
            try:
                st.image(download_drive_file(img_id), use_container_width=True)
            except Exception:
                st.warning("Bild konnte nicht geladen werden.")

        with text_col:
            st.markdown(
                f"""
<h3>Name des Bildes: {esc(row["Name deines Bildes"])}</h3>
<p class="meta">Eingereicht von: <b>{esc(row["Dein Name"])}</b></p>
<p class="meta">Kategorie: <b>{esc(row["Kategorie"])}</b></p>
""",
                unsafe_allow_html=True,
            )

            action_col_1, action_col_2, action_col_3, _ = st.columns([1, 1, 1, 3])

            with action_col_1:
                if st.button("Groß anzeigen", key=f"open_{original_index}_{img_id}"):
                    st.session_state["modal_image"] = img_id
                    st.session_state["modal_title"] = row["Name deines Bildes"]

            with action_col_2:
                if st.button("Ändern", key=f"edit_{original_index}_{img_id}"):
                    st.session_state["edit_index"] = int(original_index)
                    st.rerun()

            with action_col_3:
                if st.button("Löschen", key=f"delete_{original_index}_{img_id}"):
                    st.session_state["pending_delete"] = int(original_index)

            if st.session_state.get("pending_delete") == int(original_index):
                st.warning(f"Eintrag „{row['Name deines Bildes']}“ wirklich löschen?")
                confirm_col, cancel_col, _ = st.columns([1.1, 1.1, 3])

                with confirm_col:
                    if st.button("Ja, löschen", key=f"confirm_delete_{original_index}"):
                        delete_entry(int(original_index))
                        if st.session_state.get("modal_image") == img_id:
                            st.session_state.pop("modal_image", None)
                            st.session_state.pop("modal_title", None)
                        if st.session_state.get("edit_index") == int(original_index):
                            st.session_state.pop("edit_index", None)
                        st.session_state.pop("pending_delete", None)
                        st.success("Eintrag gelöscht.")
                        st.rerun()

                with cancel_col:
                    if st.button("Abbrechen", key=f"cancel_delete_{original_index}"):
                        st.session_state.pop("pending_delete", None)
                        st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------------------------------------
# Große Bildansicht als echte Dialogbox
# ------------------------------------------------------------
if "modal_image" in st.session_state:
    if hasattr(st, "dialog"):
        @st.dialog(st.session_state.get("modal_title", "Große Ansicht"), width="large")
        def show_image_dialog():
            try:
                st.image(download_drive_file(st.session_state["modal_image"]), use_container_width=True)
            except Exception:
                st.warning("Bild konnte nicht geladen werden.")
            if st.button("Schließen", key="close_dialog"):
                st.session_state.pop("modal_image", None)
                st.session_state.pop("modal_title", None)
                st.rerun()

        show_image_dialog()
    else:
        st.divider()
        st.subheader(f"Große Ansicht: {st.session_state.get('modal_title', '')}")
        try:
            st.image(download_drive_file(st.session_state["modal_image"]), use_container_width=True)
        except Exception:
            st.warning("Bild konnte nicht geladen werden.")
        if st.button("Große Ansicht schließen", key="close_fallback"):
            st.session_state.pop("modal_image", None)
            st.session_state.pop("modal_title", None)
            st.rerun()


# ------------------------------------------------------------
# CSV-Download ganz am Seitenende
# ------------------------------------------------------------
st.divider()
st.markdown('<div class="csv-box">', unsafe_allow_html=True)
st.markdown("### CSV-Export")
st.markdown("Hier können die Eintragsdaten ohne Bilddateien als CSV-Datei heruntergeladen werden.")
st.download_button(
    label="CSV-Datei herunterladen",
    data=csv_without_images(load_data()),
    file_name="astrobuch_bildbeitraege.csv",
    mime="text/csv",
)
st.markdown("</div>", unsafe_allow_html=True)
