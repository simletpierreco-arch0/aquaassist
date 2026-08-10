"""
sheets_storage.py — Google Sheets-backed persistence for AquaAssist.

WHY THIS EXISTS:
Streamlit Community Cloud's filesystem is EPHEMERAL — every redeploy, app
sleep/wake cycle, or container restart wipes local files like
data/reports.csv. That means customer reports and notification signups
collected during a demo (or in production) can silently disappear. This
module persists that same data to a Google Sheet instead, which survives
restarts and lets you (or judges) watch it fill up live in a browser tab.

SETUP (5 minutes):
1. Create a Google Cloud project (or reuse one) and enable the
   "Google Sheets API" and "Google Drive API".
2. Create a Service Account, then create a JSON key for it and download it.
3. Create a new Google Sheet. Share it with the service account's email
   address (looks like xxxx@xxxx.iam.gserviceaccount.com) as an Editor.
4. Copy the Sheet's ID from its URL:
   https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
5. Set two secrets (in .streamlit/secrets.toml locally, or the Streamlit
   Cloud Settings -> Secrets panel):

     GOOGLE_SHEETS_ID = "your-sheet-id-here"
     GOOGLE_SHEETS_CREDENTIALS = '''
     {"type": "service_account", "project_id": "...", ... the whole JSON key file ...}
     '''

   (Paste the entire downloaded JSON key file as-is, wrapped in triple
   quotes since it contains its own quotes.)

If those two secrets aren't set, or the `gspread` package isn't installed,
HAS_SHEETS_BACKEND is False and every function below returns None so the
caller can fall back to local CSV storage — same optional-dependency
pattern as the Pinecone knowledge-base retrieval in app.py.

ATTACHMENTS (photos/videos on reports) use the same service account to
upload to Google Drive instead of local disk — see sheets_upload_attachment()
below. This needs ONE extra piece of setup beyond the Sheet itself:

6. In Google Drive, create a folder for AquaAssist attachments and share
   IT (not just the Sheet) with the same service account email as an
   Editor. Copy the folder's ID from its URL:
   https://drive.google.com/drive/folders/<THIS_PART>
7. Set one more secret:

     GOOGLE_DRIVE_FOLDER_ID = "your-folder-id-here"

IMPORTANT — personal (non-Workspace) Google accounts: service accounts get
0 bytes of their own storage quota. Uploads will fail with a quota error
UNLESS the shared folder lives inside a Shared Drive (needs Google
Workspace), or you're on a Workspace account where the folder owner's
quota is used instead. If you don't have that available, uploads will
fail every time and the app automatically falls back to saving the photo
to local disk (see the fallback logic in app.py) — nothing breaks, you
just won't get cross-restart persistence for photos until Drive is set
up correctly. Test one upload before your demo to confirm it's working.

Uploaded files are set to "anyone with the link can view" so they can be
opened directly from the Reports sheet or Staff Portal without each staff
member needing their own Drive access — reasonable for a demo, but worth
tightening (e.g. share with specific staff emails instead) before real
customer photos go through this in production.

pip install gspread google-auth google-api-python-client
"""

import os
import io
import json
import uuid
import mimetypes
from datetime import datetime

import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    HAS_DRIVE_LIBS = True
except ImportError:
    HAS_DRIVE_LIBS = False

REPORTS_FIELDS = ["reference", "timestamp", "name", "phone", "location", "issue_type",
                   "description", "attachment", "status", "severity"]
NOTIFY_FIELDS = ["timestamp", "contact", "categories"]

REPORTS_SHEET_NAME = "reports"
NOTIFY_SHEET_NAME = "notifications"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_config(key, default=""):
    val = os.environ.get(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


GOOGLE_SHEETS_ID = _get_config("GOOGLE_SHEETS_ID", "")
GOOGLE_SHEETS_CREDENTIALS = _get_config("GOOGLE_SHEETS_CREDENTIALS", "")
GOOGLE_DRIVE_FOLDER_ID = _get_config("GOOGLE_DRIVE_FOLDER_ID", "")

HAS_SHEETS_BACKEND = bool(HAS_GSPREAD and GOOGLE_SHEETS_ID and GOOGLE_SHEETS_CREDENTIALS)
HAS_DRIVE_BACKEND = bool(HAS_DRIVE_LIBS and GOOGLE_DRIVE_FOLDER_ID and GOOGLE_SHEETS_CREDENTIALS)


@st.cache_resource
def _get_client():
    """Returns an authorized gspread client, or None on any failure. Cached
    per-process so we don't re-authenticate on every rerun."""
    if not HAS_GSPREAD or not GOOGLE_SHEETS_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
        return gspread.authorize(creds)
    except Exception:
        return None


@st.cache_resource
def _get_drive_service():
    """Returns an authorized Drive v3 API client, or None on any failure.
    Reuses the same service account credentials as the Sheets client."""
    if not HAS_DRIVE_LIBS or not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def _get_worksheet(sheet_name, headers):
    """Opens (or creates) the given worksheet tab inside the configured
    spreadsheet, ensuring the header row matches `headers`. Returns None on
    any failure so callers can fall back to CSV."""
    client = _get_client()
    if client is None:
        return None
    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)
    except Exception:
        return None
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except Exception:
        try:
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
            worksheet.append_row(headers)
        except Exception:
            return None
    # Auto-migrate: if the sheet is brand new / header row is empty, write it.
    try:
        first_row = worksheet.row_values(1)
        if not first_row:
            worksheet.append_row(headers)
    except Exception:
        pass
    return worksheet


def sheets_status_caption():
    """A one-line status string for the sidebar diagnostics panel, matching
    the style of the existing HAS_TTS / HAS_MAP captions in app.py."""
    if not HAS_GSPREAD:
        return "📊 Google Sheets storage: not installed (add `gspread` and `google-auth` to requirements.txt)"
    if not GOOGLE_SHEETS_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return "📊 Google Sheets storage: installed, but GOOGLE_SHEETS_ID / GOOGLE_SHEETS_CREDENTIALS not set"
    if _get_client() is None:
        return "📊 Google Sheets storage: configured, but couldn't authenticate — check credentials/sharing"
    return "📊 Google Sheets storage: enabled (reports & signups persist across restarts)"


def drive_status_caption():
    """A one-line status string for attachment (photo) storage, for the
    same sidebar diagnostics panel."""
    if not HAS_DRIVE_LIBS:
        return "📎 Photo storage (Drive): not installed (add `google-api-python-client` to requirements.txt)"
    if not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return "📎 Photo storage (Drive): installed, but GOOGLE_DRIVE_FOLDER_ID not set"
    if _get_drive_service() is None:
        return "📎 Photo storage (Drive): configured, but couldn't authenticate — check credentials/sharing"
    return "📎 Photo storage (Drive): enabled (photos persist across restarts)"


def new_reference():
    return "NW-" + uuid.uuid4().hex[:7].upper()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def sheets_save_report(name, phone, location, issue_type, description,
                        attachment_name="", severity="Unknown"):
    """Appends a new report row to the Sheet. Returns the reference number
    on success, or None if the Sheets backend isn't available/working —
    callers should fall back to the local CSV path on None."""
    worksheet = _get_worksheet(REPORTS_SHEET_NAME, REPORTS_FIELDS)
    if worksheet is None:
        return None
    reference = new_reference()
    row = {
        "reference": reference,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name, "phone": phone, "location": location,
        "issue_type": issue_type, "description": description,
        "attachment": attachment_name, "status": "Received",
        "severity": severity,
    }
    try:
        worksheet.append_row([row[field] for field in REPORTS_FIELDS])
        return reference
    except Exception:
        return None


def sheets_load_reports():
    """Returns all reports as a pandas DataFrame, or None on any failure."""
    import pandas as pd
    worksheet = _get_worksheet(REPORTS_SHEET_NAME, REPORTS_FIELDS)
    if worksheet is None:
        return None
    try:
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        for col in REPORTS_FIELDS:
            if col not in df.columns:
                df[col] = "Unknown" if col == "severity" else ""
        return df[REPORTS_FIELDS] if not df.empty else df
    except Exception:
        return None


def sheets_update_report_status(reference, new_status):
    """Finds the row with the given reference and updates its status
    column. Returns True on success, False otherwise."""
    worksheet = _get_worksheet(REPORTS_SHEET_NAME, REPORTS_FIELDS)
    if worksheet is None:
        return False
    try:
        cell = worksheet.find(reference)
        if cell is None:
            return False
        status_col = REPORTS_FIELDS.index("status") + 1  # 1-indexed for gspread
        worksheet.update_cell(cell.row, status_col, new_status)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Notification signups
# ---------------------------------------------------------------------------
def sheets_save_notification_signup(contact, categories):
    worksheet = _get_worksheet(NOTIFY_SHEET_NAME, NOTIFY_FIELDS)
    if worksheet is None:
        return False
    try:
        worksheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            contact,
            ", ".join(categories),
        ])
        return True
    except Exception:
        return False


def sheets_load_notifications():
    import pandas as pd
    worksheet = _get_worksheet(NOTIFY_SHEET_NAME, NOTIFY_FIELDS)
    if worksheet is None:
        return None
    try:
        records = worksheet.get_all_records()
        return pd.DataFrame(records)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Attachments (photos/videos) — uploaded to Google Drive instead of local
# disk, so they survive redeploys/restarts the same way reports do.
# ---------------------------------------------------------------------------
def sheets_upload_attachment(file_bytes, filename, mime_type=None):
    """Uploads a file to the configured Drive folder and returns a viewable
    URL on success, or None on any failure (quota errors, auth issues,
    Drive not configured, etc.) — callers should fall back to saving the
    file to local disk on None, exactly as the app already does today.

    Args:
        file_bytes: raw bytes of the file.
        filename: display filename to give the uploaded file.
        mime_type: e.g. "image/jpeg" — guessed from the filename if omitted.
    """
    service = _get_drive_service()
    if service is None:
        return None
    if not mime_type:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        # A short random prefix avoids collisions between customers who
        # happen to upload files with the same name (e.g. "photo.jpg").
        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_metadata = {"name": safe_name, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
        uploaded = service.files().create(
            body=file_metadata, media_body=media, fields="id, webViewLink",
        ).execute()
        file_id = uploaded.get("id")
        # Make the file viewable via link so it can be opened straight from
        # the Sheet or Staff Portal without per-user Drive access. See the
        # module docstring for the privacy trade-off this makes.
        service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"},
        ).execute()
        return uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
    except Exception:
        return None
