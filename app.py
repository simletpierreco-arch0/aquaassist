"""
AquaAssist — Streamlit UI (Territory login, blue/white wave theme, multi-chat
history, widget-optimized layout for embedding on the NAWASA website)
NAWASA (National Water and Sewerage Authority, Grenada) AI customer support platform.

Run with:
    pip install -r requirements.txt
    streamlit run app.py

Folder layout expected:
    app.py
    assets/aquaassist_logo.png
    assets/nawasa_logo.png    (the official NAWASA authority logo, shown on
                                the login screen, header, and dashboard.)
    .streamlit/config.toml
    data/reports.csv          (auto-created, and auto-migrated if its schema
                                is missing a column added in a later update)
    data/notifications.csv    (auto-created)
    attachments/              (auto-created, uploaded report files + chat attachments)

BEFORE DEPLOYING:
    STAFF_PASSCODE -> replace "changeme123" below, or set as env var / Streamlit secret

LANGUAGE: the interface and every AI reply are always Standard English. The
AI still fully understands Grenadian Creole/patois if a customer types in
it — see build_system_instruction() — it simply never replies in it.

TERRITORY: replaces the old language picker on the login screen. Selecting
Grenada / Carriacou / Petit Martinique controls which WhatsApp number the
app uses throughout (contact card, floating button, sidebar, and what the
AI tells customers) — see TERRITORY_WHATSAPP.

EMBEDDING AS A WEBSITE WIDGET: this app's layout (compact width, hidden
Streamlit chrome, fade-in animation) is tuned to look like a purpose-built
chat widget when embedded in an iframe on the NAWASA website. The actual
floating "open/close" button behavior on nawasa.gd itself is NOT part of
this codebase — that lives in the website's own HTML/JS as a small iframe
embed snippet (ask for this separately if you need it).
"""

import os
import csv
import io
import uuid
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

# Optional upgrades — used automatically if installed, safely skipped if not.
try:
    from audio_recorder_streamlit import audio_recorder
    HAS_MIC_RECORDER = True
except ImportError:
    HAS_MIC_RECORDER = False

try:
    from streamlit_geolocation import streamlit_geolocation
    HAS_GEOLOCATION = True
except ImportError:
    HAS_GEOLOCATION = False

try:
    from gtts import gTTS
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

try:
    import folium
    from streamlit_folium import st_folium
    HAS_MAP = True
except ImportError:
    HAS_MAP = False

# ---------------------------------------------------------------------------
# NAWASA contact details
# ---------------------------------------------------------------------------
NAWASA_PHONE = "(473) 440-2155"
NAWASA_WEBSITE = "https://nawasa.gd/"
STAFF_PASSCODE = os.environ.get("STAFF_PASSCODE", "changeme123")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
LOGO_PATH = os.path.join("assets", "aquaassist_logo.png")
# Official NAWASA authority logo — shown on the login screen, chatbot
# header, and welcome dashboard. Resolved relative to this file's own
# folder (Path(__file__).parent) rather than the process's current working
# directory, so the logo still loads correctly no matter where `streamlit
# run` is launched from. Falls back to a styled text badge if the file
# isn't present at this path.
logo_path = Path(__file__).parent / "nawasa_logo.png"
REPORTS_PATH = os.path.join("data", "reports.csv")
NOTIFY_PATH = os.path.join("data", "notifications.csv")
OUTAGES_PATH = os.path.join("data", "outages.csv")
ATTACHMENTS_DIR = "attachments"
REPORTS_FIELDS = ["reference", "timestamp", "name", "phone", "location", "issue_type",
                   "description", "attachment", "status", "severity"]
NOTIFY_FIELDS = ["timestamp", "contact", "categories"]
OUTAGE_FIELDS = ["id", "parish", "message", "start_date", "end_date", "created_at"]
STATUS_STAGES = ["Received", "Assigned", "Crew Dispatched", "In Progress", "Resolved"]
SEVERITY_LEVELS = ["Unknown", "Low", "Medium", "High"]
USAGE_PATH = os.path.join("data", "usage.csv")

# ---------------------------------------------------------------------------
# Business hours — NAWASA Customer Service.
# Monday–Saturday, 8:00 AM–4:00 PM, Grenada local time. Only Sunday is
# always closed. NAWASA_HOLIDAYS lists official closure dates (YYYY-MM-DD)
# that are also treated as closed even if they fall on a business day —
# add/edit this list each year as NAWASA publishes its holiday schedule.
# ---------------------------------------------------------------------------
BUSINESS_HOURS_START = 8   # 8:00 AM
BUSINESS_HOURS_END = 16    # 4:00 PM
NAWASA_HOLIDAYS = [
    # "2026-01-01",  # New Year's Day
    # "2026-12-25",  # Christmas Day
]
# Grenada is on Atlantic Standard Time (UTC-4) year-round — it does not
# observe daylight saving — so a fixed offset is used rather than a named
# timezone (this also avoids depending on the host machine having the IANA
# tzdata package installed, which some minimal server images lack).
GRENADA_TZ = timezone(timedelta(hours=-4))
_WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def get_business_hours_status():
    """Computes whether NAWASA Customer Service is open right now, entirely
    server-side in Python (using the server clock — reliable on every
    browser/device, unlike a client-side JS check). Returns a dict with
    `is_open` plus a human-readable `closed_reason` and `reopens_label` for
    display when closed."""
    now = datetime.now(GRENADA_TZ)
    today_str = now.strftime("%Y-%m-%d")
    weekday_idx = now.weekday()  # Monday=0 ... Sunday=6
    is_weekend = weekday_idx == 6  # Sunday only — Saturday is a business day
    is_holiday = today_str in NAWASA_HOLIDAYS
    is_open_hour = BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END

    is_open = (not is_weekend) and (not is_holiday) and is_open_hour

    # Figure out the next business day (skipping Sundays/holidays) for the
    # "reopens" message shown when closed.
    next_day = now
    if is_weekend or is_holiday or now.hour >= BUSINESS_HOURS_END:
        next_day = next_day + timedelta(days=1)
    while next_day.weekday() == 6 or next_day.strftime("%Y-%m-%d") in NAWASA_HOLIDAYS:
        next_day = next_day + timedelta(days=1)

    if is_weekend:
        closed_reason = "It's Sunday"
    elif is_holiday:
        closed_reason = "Today is a NAWASA holiday"
    elif now.hour < BUSINESS_HOURS_START:
        closed_reason = "We open later this morning"
    else:
        closed_reason = "We've closed for the day"

    same_day = next_day.strftime("%Y-%m-%d") == today_str
    reopens_label = ("today" if same_day else _WEEKDAY_LABELS[next_day.weekday()]) + f" at {BUSINESS_HOURS_START}:00 AM"

    return {"is_open": is_open, "closed_reason": closed_reason, "reopens_label": reopens_label}

# ---------------------------------------------------------------------------
# Rate limiting / cost control. Two independent caps:
#   - SESSION_MESSAGE_LIMIT: max AI messages one browser session can send —
#     stops a single runaway/abusive session from looping indefinitely.
#   - DAILY_MESSAGE_LIMIT: max AI messages across ALL customers, all
#     sessions, per calendar day — a hard ceiling on total API spend if this
#     app is shared publicly with one API key. Both are overridable via
#     environment variables without touching code.
# ---------------------------------------------------------------------------
SESSION_MESSAGE_LIMIT = int(os.environ.get("SESSION_MESSAGE_LIMIT", "40"))
DAILY_MESSAGE_LIMIT = int(os.environ.get("DAILY_MESSAGE_LIMIT", "500"))

st.set_page_config(
    page_title="AquaAssist",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "💧",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
defaults = {
    "auth_done": False,            # True once the customer submits territory + API key
    "territory": "Grenada",
    "customer_name": "",
    "api_key": os.environ.get("GEMINI_API_KEY", ""),
    "dark_mode": False,
    "high_contrast": False,
    "large_text": False,
    "voice_replies": False,
    "chat_sessions": {},           # id -> {"name": str, "messages": [...]}
    "current_session_id": None,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

if not st.session_state.current_session_id:
    _sid = str(uuid.uuid4())
    st.session_state.chat_sessions[_sid] = {"name": "New chat", "messages": []}
    st.session_state.current_session_id = _sid

# Convenience alias — `messages` is the SAME list object stored inside
# chat_sessions[current_session_id], so appending here also updates history.
st.session_state.messages = st.session_state.chat_sessions[st.session_state.current_session_id]["messages"]

# ---------------------------------------------------------------------------
# Territories — replaces the old language selector. The chatbot's output
# language is now always Standard English (it still UNDERSTANDS Grenadian
# Creole input — see build_system_instruction() — it just never replies in
# it). Territory instead controls which WhatsApp number the app points to.
# ---------------------------------------------------------------------------
TERRITORIES = ["Grenada", "Carriacou", "Petit Martinique"]
TERRITORY_WHATSAPP = {
    "Grenada": "https://wa.link/rt9dj1",
    "Carriacou": "https://wa.link/wp6vfj",
    "Petit Martinique": "https://wa.link/3dpbnj",
}

def get_whatsapp_link():
    return TERRITORY_WHATSAPP.get(st.session_state.get("territory", "Grenada"), TERRITORY_WHATSAPP["Grenada"])

# Recomputed every script run (Streamlit reruns top-to-bottom on every
# interaction), so changing territory anywhere immediately updates every
# WhatsApp button/link/reference throughout the app.
WHATSAPP_LINK = get_whatsapp_link()

# ---------------------------------------------------------------------------
# Grenada geography — for the report location picker
# ---------------------------------------------------------------------------
GRENADA_PARISHES = [
    "St. George's (Capital area)", "St. Andrew's", "St. David's",
    "St. John's", "St. Mark's", "St. Patrick's", "Carriacou and Petite Martinique",
]
GRENADA_CENTER = (12.1165, -61.6790)

# UI text — Standard English only (per client requirement, the interface and
# all AI replies are always English; the app no longer offers a language
# picker or auto-translation).
UI_TEXT = {
    "welcome": (
        "👋 **Welcome to AquaAssist**\n\n"
        "I'm NAWASA's official virtual assistant.\n\n"
        "I'm available **24 hours a day, 7 days a week** to help answer your questions about NAWASA's services.\n\n"
        "I can help you with:\n\n"
        "- 🚰 Water outages\n"
        "- 📄 Billing\n"
        "- 📍 New connections\n"
        "- 👷 Reporting leaks\n"
        "- 🏢 Office locations\n"
        "- ❓ Frequently asked questions\n"
        "- 💬 General customer support\n\n"
        "**How may I assist you today?**"
    ),
    "tab_chat": "💬 Chat", "tab_faq": "❓ FAQ", "tab_report": "📋 Report & Track",
    "tab_history": "🕘 History", "tab_settings": "⚙️ Settings",
    "report_issue": "🚿 Report an issue",
    "quick_actions": "💧 Quick actions", "ask_placeholder": "Ask about your water service...",
    "your_name": "Your name", "continue": "Continue",
    "call_us": "Call Us", "whatsapp_label": "WhatsApp", "chat_now": "Chat now",
    "website_label": "Website",
    "qa_report_label": "👷 Report a Leak", "qa_report_prompt": "I'd like to report a water leak.",
    "qa_maint_label": "🚰 Water Supply & Outages", "qa_maint_prompt": "Are there any scheduled outages or planned maintenance in my area?",
    "qa_bill_label": "💳 Pay My Bill", "qa_bill_prompt": "What are my options for paying my NAWASA bill?",
    "qa_checkbill_label": "📄 Check My Bill", "qa_checkbill_prompt": "How can I check my current NAWASA bill balance and consumption?",
    "qa_locations_label": "📍 Office Locations", "qa_locations_prompt": "Where are NAWASA's office locations?",
    "qa_rep_label": "👤 Speak to an Agent", "qa_rep_prompt": "I'd like to speak with a customer service representative.",
    "settings_preferences": "⚙️ Preferences",
    "dark_mode": "🌙 Dark mode", "high_contrast": "🔲 High contrast mode", "large_text": "🔠 Larger text",
    "accessibility_note": "Accessibility: this app supports keyboard navigation and screen readers natively through Streamlit's standard components.",
    "settings_conversation": "💬 Conversation",
    "conversation_note": "messages in this session. Go to the History tab to search or clear your conversation.",
    "field_name": "Your name", "field_phone": "Phone number",
    "field_location": "Location / address of the issue", "field_description": "Describe the issue",
    "field_issue_type": "Issue type", "field_attachment": "Attach a photo, video, or document (optional)",
    "submit_report": "Submit report", "report_form_expander": "Fill out a report — goes straight to NAWASA staff",
    "track_report_label": "📍 Track a report", "track_report_placeholder": "Enter your reference number (e.g. NW-A1B2C3D)",
    "get_notified": "🔔 Get notified", "notify_contact_label": "Email or phone number",
    "notify_categories_label": "Notify me about", "subscribe_button": "Subscribe",
    "voice_toggle_label": "🔊 Speak replies aloud", "voice_popover_label": "🎤",
    "voice_help_on": "Uses text-to-speech to read the bot's replies aloud, in the warmest Caribbean-leaning voice available.",
    "voice_help_off": "Install gTTS to enable this.",
    "issue_leak": "Leak", "issue_no_water": "No water supply", "issue_low_pressure": "Low pressure",
    "issue_billing": "Billing issue", "issue_burst": "Burst main", "issue_hydrant": "Damaged hydrant",
    "issue_quality": "Water quality concern", "issue_other": "Other",
    "new_chat": "＋ New chat", "chat_history": "Recent chats", "no_history": "No previous chats yet.",
    "login_title": "Welcome to AquaAssist", "login_subtitle": "Your smart water support assistant",
    "login_territory": "Select your NAWASA territory",
    "login_key": "Google AI Studio API key", "login_key_help": "Get a key at https://aistudio.google.com/",
    "login_start": "Start chatting",
    "login_missing": "Please select your territory and enter your API key first.",
    "map_section_label": "📍 Pin location on map",
    "map_parish_label": "Parish / Territory",
    "map_address_label": "Street / Landmark Address",
    "map_gps_button": "📡 Use My GPS Location",
    "map_not_installed": "Interactive map isn't installed on this server — add `folium` and `streamlit-folium` to requirements.txt to enable it. Enter your parish and address manually for now.",
    "map_pinned_caption": "Pinned location",
    "map_click_hint": "Click or drag the pin to set the exact spot.",
    "severity_label": "Severity",
    "severity_analyze_button": "Analyze severity from photo",
    "outage_banner_prefix": "⚠️ Service notice for",
    "your_parish_label": "Your parish (for outage alerts)",
    "staff_map_label": "🗺️ Reports map",
    "staff_map_empty": "No reports with a pinned location yet.",
    "outage_section_label": "📢 Outage announcements",
    "outage_parish_label": "Parish / Territory",
    "outage_message_label": "Message to customers",
    "outage_start_label": "Start date",
    "outage_end_label": "End date",
    "outage_create_button": "Post announcement",
    "outage_active_label": "Active / upcoming announcements",
    "outage_none": "No announcements posted.",
    "outage_delete_button": "Remove",
    "limit_session_reached": "You've reached the message limit for this conversation. Please start a new chat, or reach us directly by phone at (473) 440-2155 or WhatsApp.",
    "limit_daily_reached": "AquaAssist has reached its message limit for today. Please contact NAWASA directly by phone at (473) 440-2155 or WhatsApp, or try again tomorrow.",
}

def t(key):
    return UI_TEXT.get(key, key)

# ---------------------------------------------------------------------------
# Official NAWASA FAQs (pulled from nawasa.gd/nawasa-faqs, customer-facing subset)
# ---------------------------------------------------------------------------
FAQS = [
    {"category": "New Connections", "q": "How do I apply for a new connection?",
     "a": "Fill out the application for a new service connection. Review the Requirements for Private Water Service and the Terms and Conditions for Water Service on nawasa.gd."},
    {"category": "New Connections", "q": "What is the cost of a new connection?",
     "a": "Connection to ½\" main: $75. ¾\" main: $125. 1\" main: $175. 1¼\"/1½\"/2\" main: $420. 4\" main: $1000. Plus variable costs (transportation, pipes & fittings, VAT) — an estimate is prepared to determine the total."},
    {"category": "New Connections", "q": "How long does it take NAWASA to install a new service?",
     "a": "Per the customer service charter, a new service should be installed within 10 working days after payment of the connection fee."},
    {"category": "New Connections", "q": "I don't own the property — can I still get a connection in my name?",
     "a": "Yes, with written permission from the property owner plus the owner's ID. A security deposit is also required: $240 (Domestic), $340 (Commercial), or $2,000 (Projects) — refundable if you later become the owner or the service is permanently terminated."},
    {"category": "Billing", "q": "How may I change my account name or billing/mailing address?",
     "a": "To change the account name, fill out the application for change of name and provide one of: Title Deed/Conveyance, Death Certificate, Letter from Lawyer, Will, or Court Judgement. To change the mailing address, fill out the Change of Mailing Address Form. A valid picture ID is required for all account changes."},
    {"category": "Billing", "q": "I've been paying my bills, why does my bill show arrears?",
     "a": "Your current bill may have already been issued prior to processing your previous payment."},
    {"category": "Billing", "q": "How are estimated bills calculated?",
     "a": "Estimated bills use an average of your last three months' consumption."},
    {"category": "Water Usage & Leaks", "q": "My water consumption is unusually high — what could be the problem?",
     "a": "High consumption can come from estimated bills, leaks, unsecured taps, or a faulty meter. To check for a leak: turn off all taps and watch the meter dial — if it's still turning, there's a leak. If not, contact Customer Services."},
    {"category": "Disconnection", "q": "Under what circumstances does NAWASA disconnect service?",
     "a": "At the customer's request, for non-payment of arrears, for wastage/abuse, or for illegal tampering of meters and fittings."},
    {"category": "Disconnection", "q": "How do I request a disconnection?",
     "a": "Request in writing or in person using a 'Request for Disconnection' form. Only the account owner or an authorized person (with documentation) can request this, and valid ID is required."},
    {"category": "Disconnection", "q": "What is the minimum balance for disconnection?",
     "a": "A customer can be disconnected once arrears reach at least $50.00 and are at least 30 days overdue."},
    {"category": "Disconnection", "q": "After paying the reconnection fee, how long until reconnection?",
     "a": "Reconnection is not guaranteed within 48 hours after payment of the reconnection fee."},
    {"category": "General", "q": "What does NAWASA mean?",
     "a": "National Water & Sewerage Authority."},
    {"category": "General", "q": "Where is NAWASA's main office?",
     "a": "The main office is on the Carenage, St. George's, with sub-offices in Gouyave, Grenville, Sauteurs, St. David's, and Grand Anse."},
]


def search_faqs(query, faq_list=None):
    faq_list = faq_list if faq_list is not None else FAQS
    if not query:
        return faq_list
    q = query.lower()
    return [f for f in faq_list if q in f["q"].lower() or q in f["a"].lower() or q in f["category"].lower()]

MODEL_NAME = "gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# Report storage helpers
# ---------------------------------------------------------------------------
def _migrate_reports_schema():
    """Self-heals data/reports.csv if its header is missing a column that
    the current REPORTS_FIELDS expects (e.g. "severity", added after some
    reports.csv files already existed). Without this, save_report() writes
    rows with MORE values than the file's existing header has columns for,
    which misaligns every row and breaks both Track a Report and the Staff
    Portal when the file is read back. Existing data is preserved — this
    only adds the missing column(s) with a safe default, it never deletes
    rows or columns."""
    import pandas as pd
    if not os.path.exists(REPORTS_PATH):
        return
    try:
        df = pd.read_csv(REPORTS_PATH)
    except Exception:
        # File is unreadable/corrupted in some other way — leave it alone
        # here; load_reports() has its own fallback for this case.
        return
    changed = False
    for col in REPORTS_FIELDS:
        if col not in df.columns:
            df[col] = "Unknown" if col == "severity" else ""
            changed = True
    ordered_cols = [c for c in REPORTS_FIELDS if c in df.columns] + [c for c in df.columns if c not in REPORTS_FIELDS]
    if changed or list(df.columns) != ordered_cols:
        df = df[ordered_cols]
        df.to_csv(REPORTS_PATH, index=False)

def ensure_files():
    os.makedirs(os.path.dirname(REPORTS_PATH), exist_ok=True)
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    if not os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writeheader()
    else:
        _migrate_reports_schema()
    if not os.path.exists(NOTIFY_PATH):
        with open(NOTIFY_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=NOTIFY_FIELDS).writeheader()
    if not os.path.exists(OUTAGES_PATH):
        with open(OUTAGES_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTAGE_FIELDS).writeheader()

def new_reference():
    return "NW-" + uuid.uuid4().hex[:7].upper()

def save_report(name, phone, location, issue_type, description, attachment_name="", severity="Unknown"):
    ensure_files()
    reference = new_reference()
    with open(REPORTS_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writerow({
            "reference": reference,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name, "phone": phone, "location": location,
            "issue_type": issue_type, "description": description,
            "attachment": attachment_name, "status": "Received",
            "severity": severity,
        })
    return reference

def load_reports():
    ensure_files()
    import pandas as pd
    try:
        df = pd.read_csv(REPORTS_PATH)
    except Exception:
        # Still broken after migration (e.g. genuinely corrupted file) —
        # rebuild a clean, empty, correctly-columned file rather than
        # crashing Track a Report / the Staff Portal on every load.
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writeheader()
        df = pd.read_csv(REPORTS_PATH)
    # Guarantee every expected column exists even if something upstream
    # still slipped through, so callers can always safely do df["severity"] etc.
    for col in REPORTS_FIELDS:
        if col not in df.columns:
            df[col] = "Unknown" if col == "severity" else ""
    return df

def update_report_status(reference, new_status):
    import pandas as pd
    df = load_reports()
    df.loc[df["reference"] == reference, "status"] = new_status
    df.to_csv(REPORTS_PATH, index=False)

def track_report(reference):
    df = load_reports()
    match = df[df["reference"].astype(str).str.upper() == reference.strip().upper()]
    return match.iloc[0] if not match.empty else None

def save_notification_signup(contact, categories):
    ensure_files()
    with open(NOTIFY_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=NOTIFY_FIELDS).writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contact": contact, "categories": ", ".join(categories),
        })

def parse_report_coords(location_text):
    """Pulls (lat, lng) out of a location string like '... (GPS: 12.11650,
    -61.67900)', which is how both the map picker and the geolocation button
    write coordinates into the location field. Returns None if not found."""
    import re
    if not isinstance(location_text, str):
        return None
    match = re.search(r"GPS:\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)", location_text)
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError:
        return None

# ---------------------------------------------------------------------------
# Outage announcements — staff creates these; the customer portal shows a
# banner to anyone whose parish matches an announcement whose date range
# covers today. This is an in-app "proactive" notice: it surfaces the next
# time a customer opens (or already has open) the app, since actually
# pushing a message to someone's phone/email requires wiring up an SMS or
# email provider (e.g. Twilio, SendGrid) with its own API key, which isn't
# configured here.
# ---------------------------------------------------------------------------
def save_outage(parish, message, start_date, end_date):
    ensure_files()
    outage_id = uuid.uuid4().hex[:8]
    with open(OUTAGES_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=OUTAGE_FIELDS).writerow({
            "id": outage_id, "parish": parish, "message": message,
            "start_date": start_date, "end_date": end_date,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return outage_id

def load_outages():
    ensure_files()
    import pandas as pd
    try:
        return pd.read_csv(OUTAGES_PATH)
    except Exception:
        with open(OUTAGES_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUTAGE_FIELDS).writeheader()
        return pd.read_csv(OUTAGES_PATH)

def delete_outage(outage_id):
    import pandas as pd
    df = load_outages()
    df = df[df["id"] != outage_id]
    df.to_csv(OUTAGES_PATH, index=False)

def get_active_outages_for_parish(parish):
    import pandas as pd
    df = load_outages()
    if df.empty:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    matches = df[
        (df["parish"] == parish)
        & (df["start_date"].astype(str) <= today)
        & (df["end_date"].astype(str) >= today)
    ]
    return matches.to_dict("records")

# ---------------------------------------------------------------------------
# Usage tracking — a single-row-per-day counter file backing the daily cap.
# Best-effort, not perfectly atomic under heavy concurrent writes (a plain
# CSV isn't built for that), but for a small utility's customer-support
# volume this is a simple, dependency-free way to put a hard ceiling on
# total daily AI spend without standing up a real database.
# ---------------------------------------------------------------------------
def _ensure_usage_file():
    os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)
    if not os.path.exists(USAGE_PATH):
        with open(USAGE_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["date", "count"])

def _today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_daily_usage_count():
    import pandas as pd
    _ensure_usage_file()
    try:
        df = pd.read_csv(USAGE_PATH)
    except Exception:
        return 0
    today_rows = df[df["date"].astype(str) == _today_str()]
    return int(today_rows["count"].sum()) if not today_rows.empty else 0

def increment_daily_usage():
    import pandas as pd
    _ensure_usage_file()
    today = _today_str()
    try:
        df = pd.read_csv(USAGE_PATH)
    except Exception:
        df = pd.DataFrame(columns=["date", "count"])
    if today in df["date"].astype(str).values:
        df.loc[df["date"].astype(str) == today, "count"] += 1
    else:
        df = pd.concat([df, pd.DataFrame([{"date": today, "count": 1}])], ignore_index=True)
    # Keep the file small — only the last 30 days of counts are needed.
    df = df.tail(30)
    df.to_csv(USAGE_PATH, index=False)

def check_and_record_usage():
    """Call this immediately before every AI message send. Returns
    (allowed: bool, reason: str|None). If allowed, also records the usage
    so the caps stay accurate for the NEXT call."""
    session_count = st.session_state.get("_session_message_count", 0)
    if session_count >= SESSION_MESSAGE_LIMIT:
        return False, "session"

    daily_count = get_daily_usage_count()
    if daily_count >= DAILY_MESSAGE_LIMIT:
        return False, "daily"

    st.session_state["_session_message_count"] = session_count + 1
    increment_daily_usage()
    return True, None

def usage_limit_message(reason):
    if reason == "session":
        return t("limit_session_reached")
    return t("limit_daily_reached")

# ---------------------------------------------------------------------------
# Tool the AI can call directly during conversation to log a report
# ---------------------------------------------------------------------------
def log_water_report(location: str, issue_type: str, description: str,
                      name: str = "Not provided", phone: str = "Not provided",
                      severity: str = "Unknown") -> str:
    """Logs a customer's water service issue into the NAWASA staff system so a
    technician can follow up on it. Call this as soon as the customer has
    described their problem and given at least a location — even in normal
    conversation, without requiring them to fill out a separate form.

    Args:
        location: The location or address where the issue is happening.
        issue_type: One of "Leak", "No water supply", "Low pressure", "Billing issue", "Other".
        description: A short description of the issue in the customer's own words.
        name: The customer's name, if given.
        phone: The customer's phone number, if given.
        severity: One of "Unknown", "Low", "Medium", "High". If the customer
            attached a photo of the issue, assess how serious it looks (e.g.
            a small drip vs. a burst main flooding a street) and set this
            accordingly; otherwise leave it "Unknown" rather than guessing
            from text alone.

    Returns:
        A confirmation message including the reference number for tracking.
    """
    reference = save_report(name, phone, location, issue_type, description, severity=severity)
    return f"Report logged successfully. Reference number: {reference}. A technician will follow up."

# ---------------------------------------------------------------------------
# Voice helpers — Caribbean-leaning English text-to-speech
#
# gTTS (Google Translate TTS) does not offer a dedicated "Grenadian" or
# "Caribbean English" voice model — its `lang`/`tld` options only select
# from Google's existing regional English accents. There is no tld that
# reproduces a Grenadian accent specifically. Per the brief's own fallback
# instructions ("if a Grenadian voice is unavailable, use the closest
# high-quality Caribbean English voice; if none is available, fall back to
# a warm Standard English voice"), this tries the accents below in order
# and keeps the first one that actually renders audio successfully:
#   1. en / tld=com.jm  — Jamaican English (closest Caribbean-region accent
#      gTTS exposes; not Grenadian, but the nearest available approximation)
#   2. en / tld=co.uk   — a neutral, warm Standard English fallback
#   3. en / tld=us      — final fallback if the above are unreachable
# If a fully Caribbean/Grenadian voice becomes available through whichever
# speech provider is ultimately selected for production (e.g. a premium
# TTS API with regional accent packs), swap the implementation here.
# ---------------------------------------------------------------------------
VOICE_ACCENT_CHAIN = [
    {"tld": "com.jm", "label": "Caribbean (Jamaican English — closest available to Grenadian)"},
    {"tld": "co.uk", "label": "Warm Standard English"},
    {"tld": "us", "label": "Standard English"},
]

def speak_text(text, lang_code="en"):
    if not HAS_TTS:
        return None
    for accent in VOICE_ACCENT_CHAIN:
        try:
            buf = io.BytesIO()
            gTTS(text=text, lang=lang_code, tld=accent["tld"]).write_to_fp(buf)
            buf.seek(0)
            return buf.read()
        except Exception:
            continue
    return None

# ---------------------------------------------------------------------------
# Chat session helpers (multi-chat history, like a typical AI chat app)
# ---------------------------------------------------------------------------
def _auto_name_from(text, limit=42):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"

def start_new_chat():
    cur = st.session_state.chat_sessions[st.session_state.current_session_id]
    if cur["messages"] and cur["name"] == "New chat":
        first_user = next((m["content"] for m in cur["messages"] if m["role"] == "user"), None)
        if first_user:
            cur["name"] = _auto_name_from(first_user)
    new_id = str(uuid.uuid4())
    st.session_state.chat_sessions[new_id] = {"name": "New chat", "messages": []}
    st.session_state.current_session_id = new_id
    st.session_state.pop("chat", None)  # force a fresh Gemini chat session

def switch_to_chat(session_id):
    if session_id != st.session_state.current_session_id:
        st.session_state.current_session_id = session_id
        st.session_state.pop("chat", None)  # reseed Gemini session from this chat's transcript

def ordered_session_ids():
    # Current session first if it's brand new/empty; otherwise most-recently-touched first.
    ids = list(st.session_state.chat_sessions.keys())
    ids.remove(st.session_state.current_session_id)
    ids.reverse()
    return [st.session_state.current_session_id] + ids

# ---------------------------------------------------------------------------
# System instruction — tone rules per the Communications team's brief:
# understand Grenadian Creole, always reply in Standard English, sound like
# a warm and experienced NAWASA representative rather than a generic bot.
# ---------------------------------------------------------------------------
def build_system_instruction(territory):
    territory_whatsapp = TERRITORY_WHATSAPP.get(territory, TERRITORY_WHATSAPP["Grenada"])
    return f"""
You are AquaAssist, a friendly virtual customer assistant for the National Water and Sewerage Authority (NAWASA) of Grenada, serving the {territory} territory.

LANGUAGE RULE:
Always reply in clear, professional Standard English, regardless of what language or dialect the customer writes in. You must still fully UNDERSTAND Grenadian Creole (patois) if a customer writes in it — correctly interpret their meaning and intent — but your reply itself must always be in Standard English. Never reply in Creole, patois, or any other language, even if asked to.

CONVERSATION STYLE:
Sound like an experienced, caring NAWASA customer service representative — not a generic AI chatbot. Be warm, natural, and conversational, never robotic or overly formal.
- Prefer natural phrasing over stiff, templated wording. For example, say "I've received your request and I'm here to help — let's get this sorted out" rather than "Your request has been processed." Say "I'm sorry, I didn't quite understand that — could you try asking your question another way?" rather than "Invalid input."
- Vary your wording across a conversation; avoid repeating the same stock phrases turn after turn.
- Greet customers naturally and maintain a friendly, professional tone throughout.
- Keep track of what's already been said in the conversation and don't ask the customer to repeat information they've already given you.
- When a customer reports a problem — no water, a leak, a burst main, a billing concern — show empathy first: acknowledge how frustrating or inconvenient it is, reassure them you're there to help, and then guide them calmly through the next steps.
- Keep responses concise, clear, and easy to understand, while still sounding like a real person who cares about getting the customer's problem solved.

Use the following facts to answer user questions:
- Help customers report water leaks by collecting the location and relevant details.
- Provide information about water supply issues and service interruptions.
- Help customers check for planned maintenance and scheduled outages.
- Explain the available methods for paying NAWASA bills.
- Provide NAWASA customer service contact information and transfer users to a representative when requested.
- If the issue is an emergency, advise the user to contact NAWASA immediately at (473) 440-2155.
- NAWASA's official contact details: Phone (473) 440-2155, WhatsApp via {territory_whatsapp} (this is the number for {territory}), Website https://nawasa.gd/. Share these when a customer asks how to reach NAWASA directly.
- When a customer describes a specific problem (a leak, no water, low pressure, a billing issue) and gives at least a location, log it immediately using the log_water_report tool — do not tell the customer to fill out a separate form themselves. After logging it, tell the customer their reference number so they can track it, and let them know NAWASA staff will follow up. If you don't have their name or phone number yet, ask for it after logging so staff can reach them, but don't block logging the report on that.
- If the customer attaches a photo or video of the issue, look at it before calling log_water_report and set the tool's severity argument based on what you actually see (e.g. a small drip is "Low", a steady leak is "Medium", a burst main or flooding is "High"). If there's no photo, leave severity as "Unknown" — never guess severity from text description alone.
- The "Report a Leak" form, voice messages, and the WhatsApp button are alternative ways to reach NAWASA, but you should always try to log the report yourself first if the customer is describing it in chat.
- Use natural understanding, not keyword matching — "I have no water", "my bill is wrong", "I smell chlorine", "my meter is leaking" should all be recognized as reportable issues even without exact keywords.

If a question is unrelated to NAWASA services, politely explain that you can only assist with NAWASA-related topics and invite the user to ask another water service question.
"""

# ---------------------------------------------------------------------------
# Brand palette — official NAWASA colour system, with dark mode / high
# contrast swaps. Base (light) values follow the official NAWASA brief:
#   Primary #005A9C · Secondary/Accent #00AEEF · Hover #0077CC
#   Background #F6FBFF · Cards #FFFFFF · Text #33414F
# If your exact brand hex differs, swap the BRAND_* values below and every
# gradient/card/button/bubble in the app follows.
# ---------------------------------------------------------------------------
if st.session_state.high_contrast:
    BRAND_PRIMARY = "#00385E"
    BRAND_HOVER = "#00243D"
    BRAND_ACCENT = "#0077CC"
    BRAND_BG = "#FFFFFF"
    BRAND_BG_SOFT = "#F0F0F0"
    BRAND_CARD = "#FFFFFF"
    BRAND_TEXT = "#000000"
elif st.session_state.dark_mode:
    BRAND_PRIMARY = "#2E86C6"
    BRAND_HOVER = "#3D97D9"
    BRAND_ACCENT = "#00AEEF"
    BRAND_BG = "#0B121C"
    BRAND_BG_SOFT = "#141E2C"
    BRAND_CARD = "#141E2C"
    BRAND_TEXT = "#E8F0FA"
else:
    BRAND_PRIMARY = "#005A9C"
    BRAND_HOVER = "#0077CC"
    BRAND_ACCENT = "#00AEEF"
    BRAND_BG = "#F6FBFF"
    BRAND_BG_SOFT = "#EAF6FF"
    BRAND_CARD = "#FFFFFF"
    BRAND_TEXT = "#33414F"

# Dedicated chat-bubble colors (spec-exact, independent of dark/high-contrast
# so the conversation stays legible even if those toggles are on).
USER_BUBBLE_BG = "#D9F3FF"
USER_BUBBLE_TEXT = "#003B5C"
ASSISTANT_BUBBLE_BORDER = "#D6EAF8"
ASSISTANT_BUBBLE_TEXT = "#3A4550"
HOURS_BANNER_BG = "#EAF6FF"
HOURS_BANNER_BORDER = "#B8DDF7"
HOURS_BANNER_TEXT = "#003B5C"

# Kept for any lingering references — old names now alias to the new palette.
BRAND_BLUE = BRAND_PRIMARY
BRAND_BLUE_LIGHT = BRAND_ACCENT
BRAND_BLUE_DARK = BRAND_TEXT
BRAND_CREAM = BRAND_BG
BRAND_CREAM_SOFT = BRAND_BG_SOFT
BRAND_WHITE = BRAND_CARD

WHATSAPP_GREEN = "#25D366"
BASE_FONT_SIZE = "1.15rem" if st.session_state.large_text else "0.95rem"

logo_b64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()

nawasa_logo_b64 = ""
if logo_path.exists():
    with open(logo_path, "rb") as f:
        nawasa_logo_b64 = base64.b64encode(f.read()).decode()

def nawasa_logo_tag(size_px=56, css_class=""):
    """Official NAWASA logo <img>, centered, or a styled text-badge
    fallback if the asset isn't present next to app.py as nawasa_logo.png."""
    classes = f"aqua-nawasa-logo {css_class}".strip()
    if nawasa_logo_b64:
        return f'<img class="{classes}" src="data:image/png;base64,{nawasa_logo_b64}" style="width:{size_px}px;height:{size_px}px;" />'
    return f'<span class="aqua-login-nawasa-fallback {classes}" style="width:{size_px}px;height:{size_px}px;">NAWASA</span>'

# A soft repeating wave pattern used as a fixed backdrop behind the whole app.
_WAVE_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%201200%20200'%20preserveAspectRatio='none'%3E"
    "%3Cpath%20d='M0,80%20C200,140%20400,20%20600,80%20C800,140%201000,20%201200,80%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.06'/%3E"
    "%3Cpath%20d='M0,120%20C220,60%20420,180%20620,120%20C820,60%201020,180%201200,120%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.10'/%3E"
    "%3C/svg%3E"
)

# A subtle concentric-ripple pattern used behind hero/dashboard panels.
_RIPPLE_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%20300%20300'%3E"
    "%3Ccircle%20cx='150'%20cy='150'%20r='40'%20fill='none'%20"
    f"stroke='{BRAND_ACCENT.replace('#', '%23')}'%20stroke-opacity='0.14'%20stroke-width='2'/%3E"
    "%3Ccircle%20cx='150'%20cy='150'%20r='80'%20fill='none'%20"
    f"stroke='{BRAND_ACCENT.replace('#', '%23')}'%20stroke-opacity='0.10'%20stroke-width='2'/%3E"
    "%3Ccircle%20cx='150'%20cy='150'%20r='120'%20fill='none'%20"
    f"stroke='{BRAND_ACCENT.replace('#', '%23')}'%20stroke-opacity='0.06'%20stroke-width='2'/%3E"
    "%3C/svg%3E"
)

# ---------------------------------------------------------------------------
# Custom CSS — every line flush-left (Markdown treats 4+ space indents as a
# literal code block and refuses to render it as HTML, even with
# unsafe_allow_html=True — keep every line here starting at column 0).
# ---------------------------------------------------------------------------
CSS_BLOCK = f"""<style>
html, body, [class*="css"] {{
font-family: 'Poppins', 'Inter', sans-serif;
font-size: {BASE_FONT_SIZE};
}}
.stApp {{
background-color: {BRAND_BG};
background-image: linear-gradient(180deg, {BRAND_BG_SOFT} 0%, {BRAND_BG} 45%), url("{_WAVE_BG_SVG}");
background-repeat: no-repeat, repeat-x;
background-position: top, bottom;
background-size: 100% 420px, 1200px 200px;
background-attachment: fixed, fixed;
}}
::-webkit-scrollbar {{
width: 8px;
height: 8px;
}}
::-webkit-scrollbar-track {{
background: {BRAND_BG};
}}
::-webkit-scrollbar-thumb {{
background: {BRAND_PRIMARY}55;
border-radius: 10px;
}}
::-webkit-scrollbar-thumb:hover {{
background: {BRAND_PRIMARY}88;
}}
@keyframes aquaFadeUp {{
from {{ opacity: 0; transform: translateY(10px); }}
to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes aquaPulseRing {{
0% {{ box-shadow: 0 0 0 0 rgba(37, 211, 102, 0.55); }}
70% {{ box-shadow: 0 0 0 14px rgba(37, 211, 102, 0); }}
100% {{ box-shadow: 0 0 0 0 rgba(37, 211, 102, 0); }}
}}
@keyframes aquaShimmer {{
0% {{ background-position: 0% 50%; }}
50% {{ background-position: 100% 50%; }}
100% {{ background-position: 0% 50%; }}
}}
@keyframes aquaRipple {{
0% {{ transform: scale(0.85); opacity: 0.35; }}
100% {{ transform: scale(1.35); opacity: 0; }}
}}
@keyframes aquaPop {{
0% {{ opacity: 0; transform: scale(0.92) translateY(8px); }}
60% {{ opacity: 1; transform: scale(1.01) translateY(0); }}
100% {{ opacity: 1; transform: scale(1) translateY(0); }}
}}
@keyframes aquaDotBounce {{
0%, 80%, 100% {{ transform: translateY(0); opacity: 0.5; }}
40% {{ transform: translateY(-5px); opacity: 1; }}
}}
* {{
scroll-behavior: smooth;
}}
.aqua-page {{
animation: aquaFadeUp 0.35s ease-out;
}}
.aqua-hero {{
position: relative;
background:
radial-gradient(circle at 15% 15%, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 40%),
radial-gradient(circle at 88% 110%, {BRAND_ACCENT}45 0%, rgba(255,255,255,0) 55%),
linear-gradient(135deg, {BRAND_PRIMARY} 0%, {BRAND_HOVER} 100%);
background-size: 100% 100%, 100% 100%, 100% 100%;
border-radius: 24px 24px 0 0;
padding: 1.6rem 1.6rem 3.4rem 1.6rem;
margin-bottom: -1px;
overflow: hidden;
box-shadow: inset 0 1px 0 rgba(255,255,255,0.14);
}}
.aqua-hero::before {{
content: "";
position: absolute;
inset: 0;
background-image: radial-gradient(rgba(255,255,255,0.10) 1.4px, transparent 1.4px);
background-size: 18px 18px;
opacity: 0.5;
z-index: 1;
pointer-events: none;
}}
.aqua-hero-content {{
display: flex;
align-items: center;
justify-content: space-between;
gap: 1rem;
position: relative;
z-index: 2;
animation: aquaFadeUp 0.5s ease-out;
}}
.aqua-hero-brand {{
display: flex;
align-items: center;
gap: 0.85rem;
min-width: 0;
}}
.aqua-hero img {{
width: 60px;
height: 60px;
border-radius: 50%;
background: #FFFFFF;
padding: 5px;
box-shadow: 0 4px 14px rgba(0,0,0,0.22);
flex-shrink: 0;
}}
.aqua-hero-nawasa-badge {{
width: 52px;
height: 52px;
border-radius: 50%;
background: #FFFFFF;
display: flex;
align-items: center;
justify-content: center;
box-shadow: 0 4px 14px rgba(0,0,0,0.22);
flex-shrink: 0;
overflow: hidden;
padding: 4px;
box-sizing: border-box;
}}
.aqua-hero-nawasa-badge img {{
width: 100%;
height: 100%;
object-fit: contain;
}}
.aqua-hero-title {{
font-size: 1.7rem;
font-weight: 800;
color: #FFFFFF;
line-height: 1.15;
letter-spacing: -0.02em;
}}
.aqua-hero-subtitle {{
font-size: 0.92rem;
color: rgba(255,255,255,0.9);
font-weight: 500;
}}
.aqua-hero-status {{
display: inline-flex;
align-items: center;
gap: 0.35rem;
margin-top: 0.45rem;
padding: 0.2rem 0.65rem;
border-radius: 999px;
font-size: 0.68rem;
font-weight: 700;
letter-spacing: 0.02em;
background: rgba(255,255,255,0.16);
border: 1px solid rgba(255,255,255,0.28);
color: #FFFFFF;
}}
.aqua-hero-status-dot {{
width: 7px;
height: 7px;
border-radius: 50%;
flex-shrink: 0;
}}
.aqua-hero-status-open .aqua-hero-status-dot {{
background: #34D399;
box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.35);
}}
.aqua-hero-status-closed .aqua-hero-status-dot {{
background: #FBBF6B;
box-shadow: 0 0 0 3px rgba(251, 191, 107, 0.3);
}}
.aqua-wave {{
position: absolute;
bottom: -2px;
left: 0;
width: 100%;
line-height: 0;
z-index: 1;
}}
.aqua-wave-fill {{
fill: {BRAND_BG};
}}
.aqua-glass {{
background: rgba(255, 255, 255, 0.55);
backdrop-filter: blur(14px) saturate(160%);
-webkit-backdrop-filter: blur(14px) saturate(160%);
border: 1px solid rgba(255, 255, 255, 0.6);
box-shadow: 0 8px 28px rgba(0, 114, 188, 0.12);
}}
.aqua-card {{
background: {BRAND_CARD};
border-radius: 18px;
padding: 1.1rem 1.3rem;
margin-bottom: 1rem;
box-shadow: 0 2px 12px rgba(0, 114, 188, 0.08);
border: 1px solid {BRAND_PRIMARY}22;
animation: aquaFadeUp 0.4s ease-out;
color: {BRAND_TEXT};
}}
.aqua-section-label {{
display: flex;
align-items: center;
gap: 0.4rem;
font-size: 0.8rem;
font-weight: 700;
color: {BRAND_PRIMARY};
text-transform: uppercase;
letter-spacing: 0.06em;
margin: 1.4rem 0 0.6rem 0;
}}
.aqua-contact-row {{
display: flex;
gap: 0.7rem;
margin-bottom: 0.5rem;
}}
.aqua-contact-card {{
flex: 1;
background: {BRAND_CARD};
border: 1px solid {BRAND_PRIMARY}22;
border-radius: 16px;
padding: 0.7rem 0.6rem;
min-height: 44px;
text-align: center;
text-decoration: none !important;
box-shadow: 0 2px 8px rgba(0, 90, 156, 0.06);
transition: all 0.18s ease-in-out;
}}
.aqua-contact-card:hover {{
transform: translateY(-3px);
box-shadow: 0 6px 16px rgba(0, 90, 156, 0.18);
border-color: {BRAND_ACCENT}88;
}}
.aqua-contact-icon {{
font-size: 1.3rem;
display: block;
margin-bottom: 0.2rem;
}}
.aqua-contact-label {{
font-size: 0.72rem;
font-weight: 700;
color: {BRAND_TEXT};
text-transform: uppercase;
letter-spacing: 0.04em;
display: block;
}}
.aqua-contact-value {{
font-size: 0.7rem;
color: {BRAND_PRIMARY};
font-weight: 600;
}}
.aqua-status-badge {{
display: inline-block;
padding: 0.2rem 0.7rem;
border-radius: 999px;
font-size: 0.75rem;
font-weight: 700;
background: {BRAND_PRIMARY}18;
color: {BRAND_PRIMARY};
}}
.aqua-faq-item {{
background: {BRAND_CARD};
border: 1px solid {BRAND_PRIMARY}22;
border-radius: 14px;
padding: 0.8rem 1rem;
margin-bottom: 0.6rem;
color: {BRAND_TEXT};
transition: box-shadow 0.15s ease-in-out;
}}
.aqua-faq-item:hover {{
box-shadow: 0 4px 14px rgba(0, 114, 188, 0.1);
}}
.aqua-faq-cat {{
font-size: 0.68rem;
font-weight: 700;
color: {BRAND_ACCENT};
text-transform: uppercase;
letter-spacing: 0.05em;
}}
/* Dashboard hero — ripple-textured panel behind the welcome + quick links */
.aqua-dash-hero {{
position: relative;
border-radius: 26px;
overflow: hidden;
background: linear-gradient(145deg, {BRAND_PRIMARY} 0%, {BRAND_HOVER} 100%);
background-image: linear-gradient(145deg, {BRAND_PRIMARY} 0%, {BRAND_HOVER} 100%), url("{_RIPPLE_BG_SVG}");
background-repeat: no-repeat, no-repeat;
background-position: 0 0, right -40px top -40px;
background-size: 100% 100%, 340px 340px;
padding: 2rem 1.6rem 2.4rem 1.6rem;
margin-bottom: 1.2rem;
animation: aquaPop 0.5s ease-out;
box-shadow: 0 10px 32px rgba(0, 114, 188, 0.22);
}}
.aqua-dash-hero-top {{
display: flex;
align-items: center;
justify-content: space-between;
gap: 0.8rem;
margin-bottom: 1.1rem;
}}
.aqua-dash-hero-top img, .aqua-login-nawasa-fallback {{
border-radius: 50%;
background: #FFFFFF;
box-shadow: 0 4px 14px rgba(0,0,0,0.18);
object-fit: contain;
}}
.aqua-login-nawasa-fallback {{
display: flex;
align-items: center;
justify-content: center;
color: {BRAND_HOVER};
font-size: 0.62rem;
font-weight: 800;
letter-spacing: 0.03em;
text-align: center;
padding: 3px;
box-sizing: border-box;
}}
.aqua-dash-greeting {{
font-size: 1.55rem;
font-weight: 800;
color: #FFFFFF;
letter-spacing: -0.02em;
line-height: 1.2;
}}
.aqua-dash-subtitle {{
font-size: 0.92rem;
color: rgba(255,255,255,0.92);
font-weight: 500;
margin-top: 0.15rem;
}}
.aqua-dash-badge {{
display: inline-flex;
align-items: center;
gap: 0.35rem;
background: rgba(255,255,255,0.16);
border: 1px solid rgba(255,255,255,0.3);
color: #FFFFFF;
font-size: 0.72rem;
font-weight: 600;
padding: 0.28rem 0.7rem;
border-radius: 999px;
margin-top: 0.7rem;
}}
/* Quick action tiles — icon-led glass cards instead of plain buttons */
.aqua-tile-grid {{
display: grid;
grid-template-columns: 1fr 1fr;
gap: 0.7rem;
margin-bottom: 0.3rem;
}}
.aqua-tile {{
background: {BRAND_CARD};
border: 1px solid {BRAND_PRIMARY}1f;
border-radius: 18px;
padding: 0.85rem 0.7rem 0.7rem 0.7rem;
box-shadow: 0 2px 10px rgba(0, 114, 188, 0.07);
transition: all 0.15s ease-in-out;
animation: aquaFadeUp 0.4s ease-out;
}}
.aqua-tile:hover {{
transform: translateY(-3px);
box-shadow: 0 8px 20px rgba(0, 114, 188, 0.16);
border-color: {BRAND_ACCENT}66;
}}
.aqua-tile-icon-wrap {{
width: 38px;
height: 38px;
border-radius: 12px;
background: linear-gradient(135deg, {BRAND_PRIMARY}22, {BRAND_ACCENT}22);
display: flex;
align-items: center;
justify-content: center;
font-size: 1.15rem;
margin-bottom: 0.5rem;
}}
.aqua-tile-title {{
font-weight: 700;
font-size: 0.85rem;
color: {BRAND_TEXT};
margin-bottom: 0.15rem;
}}
.aqua-tile-desc {{
font-size: 0.72rem;
color: {BRAND_TEXT}99;
line-height: 1.3;
}}
.aqua-tile-btn button {{
margin-top: 0.55rem;
width: 100%;
}}
/* Chat bubbles — clear customer vs. AI distinction (spec-exact colors) */
[data-testid="stChatMessage"] {{
border-radius: 18px;
padding: 0.75rem 1rem;
margin-bottom: 0.75rem;
box-shadow: 0 2px 10px rgba(0, 90, 156, 0.07);
animation: aquaFadeUp 0.3s ease-out;
border: 1px solid transparent;
gap: 0.65rem;
transition: box-shadow 0.15s ease-in-out;
}}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"],
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] {{
box-shadow: 0 0 0 2px {BRAND_CARD}, 0 0 0 3px {BRAND_PRIMARY}30;
}}
[data-testid="stChatMessage"]:has(img[alt="assistant avatar"]),
[data-testid="stChatMessageAvatarAssistant"] ~ div,
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {{
background: {BRAND_CARD};
border: 1px solid {ASSISTANT_BUBBLE_BORDER};
border-radius: 6px 18px 18px 18px;
color: {ASSISTANT_BUBBLE_TEXT};
}}
[data-testid="stChatMessage"]:has(img[alt="assistant avatar"]) p,
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) p {{
color: {ASSISTANT_BUBBLE_TEXT};
}}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
background: {USER_BUBBLE_BG};
border: 1px solid {USER_BUBBLE_BG};
border-radius: 18px 6px 18px 18px;
flex-direction: row-reverse;
text-align: right;
}}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p {{
color: {USER_BUBBLE_TEXT};
}}
.aqua-typing-dots {{
display: inline-flex;
gap: 4px;
padding: 0.2rem 0;
}}
.aqua-typing-dots span {{
width: 6px;
height: 6px;
border-radius: 50%;
background: {BRAND_PRIMARY};
animation: aquaDotBounce 1.2s infinite ease-in-out;
}}
.aqua-typing-dots span:nth-child(2) {{ animation-delay: 0.15s; }}
.aqua-typing-dots span:nth-child(3) {{ animation-delay: 0.3s; }}
/* Loading state — three animated dots instead of Streamlit's default spinner icon */
[data-testid="stSpinner"] > div {{
display: flex;
align-items: center;
gap: 0.5rem;
color: {BRAND_PRIMARY};
font-weight: 600;
}}
[data-testid="stSpinner"] svg {{
display: none;
}}
[data-testid="stSpinner"] > div::before {{
content: "";
display: inline-flex;
width: 34px;
height: 8px;
background-image:
radial-gradient({BRAND_PRIMARY} 40%, transparent 41%),
radial-gradient({BRAND_PRIMARY} 40%, transparent 41%),
radial-gradient({BRAND_PRIMARY} 40%, transparent 41%);
background-size: 8px 8px;
background-repeat: no-repeat;
background-position: 0 center, 13px center, 26px center;
animation: aquaDotBounce 1.2s infinite ease-in-out;
}}
div.stButton > button {{
border-radius: 12px;
border: 1px solid {BRAND_PRIMARY}30;
background-color: {BRAND_CARD};
color: {BRAND_PRIMARY};
font-weight: 600;
padding: 0.7rem 0.6rem;
min-height: 44px;
box-shadow: 0 2px 6px rgba(0, 90, 156, 0.06);
transition: all 0.18s ease-in-out;
}}
div.stButton > button:hover {{
border-color: {BRAND_HOVER};
color: {BRAND_HOVER};
background-color: {BRAND_BG_SOFT};
box-shadow: 0 6px 16px rgba(0, 90, 156, 0.16);
transform: translateY(-2px);
}}
div.stButton > button:focus-visible {{
outline: 2px solid {BRAND_ACCENT};
outline-offset: 2px;
}}
div.stButton > button:active {{
transform: translateY(0px) scale(0.98);
}}
.aqua-primary-btn button {{
background-color: {BRAND_PRIMARY} !important;
color: #FFFFFF !important;
border: none !important;
}}
.aqua-primary-btn button:hover {{
background-color: {BRAND_HOVER} !important;
color: #FFFFFF !important;
}}
section[data-testid="stSidebar"] {{
background-color: {BRAND_CARD};
background-image: url("{_WAVE_BG_SVG}");
background-repeat: repeat-x;
background-position: bottom;
background-size: 900px 150px;
border-right: 1px solid {BRAND_PRIMARY}22;
}}
.aqua-sidebar-newchat button {{
background-color: {BRAND_PRIMARY} !important;
color: #FFFFFF !important;
border: none !important;
width: 100%;
font-weight: 700;
}}
.aqua-sidebar-newchat button:hover {{
background-color: {BRAND_HOVER} !important;
transform: none;
}}
.aqua-history-btn button {{
text-align: left !important;
justify-content: flex-start !important;
background: transparent !important;
box-shadow: none !important;
border: none !important;
padding: 0.4rem 0.3rem !important;
font-weight: 500 !important;
color: {BRAND_TEXT} !important;
}}
.aqua-history-btn button:hover {{
background: {BRAND_BG_SOFT} !important;
transform: none !important;
box-shadow: none !important;
color: {BRAND_PRIMARY} !important;
}}
.aqua-history-active button {{
background: {BRAND_PRIMARY}14 !important;
color: {BRAND_PRIMARY} !important;
font-weight: 700 !important;
}}
.whatsapp-float {{
position: fixed;
bottom: 24px;
right: 24px;
z-index: 9999;
background-color: {WHATSAPP_GREEN};
color: white !important;
text-decoration: none !important;
width: 56px;
height: 56px;
border-radius: 50%;
display: flex;
align-items: center;
justify-content: center;
font-size: 1.6rem;
box-shadow: 0 4px 16px rgba(37, 211, 102, 0.45);
transition: transform 0.15s ease-in-out;
animation: aquaPulseRing 2.5s infinite;
}}
.whatsapp-float:hover {{
transform: scale(1.1);
animation: none;
}}
.whatsapp-btn {{
display: inline-flex;
align-items: center;
gap: 0.5rem;
background-color: {WHATSAPP_GREEN};
color: white !important;
text-decoration: none !important;
padding: 0.55rem 1rem;
border-radius: 999px;
font-weight: 700;
font-size: 0.9rem;
width: 100%;
justify-content: center;
box-sizing: border-box;
}}
.whatsapp-btn:hover {{
opacity: 0.9;
}}
.aqua-login-wrap {{
max-width: 460px;
margin: 0 auto;
animation: aquaFadeUp 0.4s ease-out;
}}
.aqua-login-header {{
display: flex;
align-items: center;
justify-content: center;
gap: 0.6rem;
padding: 1.6rem 0.5rem 1rem 0.5rem;
text-align: center;
}}
.aqua-login-header-left, .aqua-login-header-right {{
display: none;
}}
.aqua-login-header-left img, .aqua-login-header-right img {{
width: 56px;
height: 56px;
border-radius: 50%;
background: #FFFFFF;
padding: 5px;
box-shadow: 0 4px 14px rgba(0, 114, 188, 0.18);
object-fit: contain;
}}
.aqua-login-drop-fallback {{
font-size: 2rem;
}}
.aqua-login-header-center {{
flex: 1 1 auto;
text-align: center;
display: flex;
flex-direction: column;
align-items: center;
}}
.aqua-nawasa-logo {{
display: block;
margin: 0 auto 0.6rem auto;
}}
.aqua-login-title {{
font-size: 1.6rem;
font-weight: 800;
color: {BRAND_TEXT};
letter-spacing: -0.02em;
line-height: 1.1;
}}
.aqua-login-subtitle {{
font-size: 0.85rem;
color: {BRAND_PRIMARY};
font-weight: 500;
}}
.aqua-login-card {{
margin-top: 0.3rem;
}}
.aqua-mic-btn button {{
border-radius: 50% !important;
width: 2.75rem !important;
height: 2.75rem !important;
min-height: 2.75rem !important;
padding: 0 !important;
font-size: 1.1rem !important;
}}

/* Chat input — larger rounded field, brand focus ring, droplet-accented send button */
[data-testid="stChatInput"] {{
border-radius: 20px;
}}
[data-testid="stChatInput"] textarea {{
font-size: 0.95rem;
padding-top: 0.65rem;
padding-bottom: 0.65rem;
}}
[data-testid="stChatInputContainer"] {{
border-radius: 20px !important;
border: 1px solid {BRAND_PRIMARY}30 !important;
box-shadow: 0 2px 10px rgba(0, 90, 156, 0.06);
transition: box-shadow 0.15s ease-in-out, border-color 0.15s ease-in-out;
}}
[data-testid="stChatInputContainer"]:focus-within {{
border-color: {BRAND_ACCENT} !important;
box-shadow: 0 0 0 3px {BRAND_ACCENT}22;
}}
button[data-testid="stChatInputSubmitButton"] {{
background-color: {BRAND_PRIMARY} !important;
border-radius: 50% !important;
color: #FFFFFF !important;
position: relative;
transition: background-color 0.15s ease-in-out, transform 0.15s ease-in-out;
}}
button[data-testid="stChatInputSubmitButton"]:hover {{
background-color: {BRAND_HOVER} !important;
transform: scale(1.06);
}}
button[data-testid="stChatInputSubmitButton"] svg {{
fill: #FFFFFF !important;
}}
button[data-testid="stChatInputSubmitButton"]::after {{
content: "💧";
position: absolute;
top: -6px;
right: -4px;
font-size: 0.6rem;
line-height: 1;
filter: drop-shadow(0 1px 1px rgba(0,0,0,0.25));
}}

/* Footer */
.aqua-footer {{
text-align: center;
font-size: 0.72rem;
color: {BRAND_TEXT}99;
padding: 0.9rem 0 0.3rem 0;
letter-spacing: 0.02em;
}}
.aqua-footer strong {{
color: {BRAND_PRIMARY};
font-weight: 700;
}}

/* Business hours banner — shown above the quick-contact buttons; not a chat message */
.aqua-hours-banner {{
display: flex;
align-items: flex-start;
gap: 0.55rem;
background: {HOURS_BANNER_BG};
border: 1px solid {HOURS_BANNER_BORDER};
border-radius: 14px;
padding: 0.65rem 0.9rem;
margin-bottom: 0.85rem;
color: {HOURS_BANNER_TEXT};
font-size: 0.8rem;
line-height: 1.45;
animation: aquaFadeUp 0.3s ease-out;
}}
.aqua-hours-banner-icon {{
flex-shrink: 0;
font-size: 0.95rem;
line-height: 1.4;
}}

/* --- Widget-embed optimization ---------------------------------------- */
/* This app is designed to be embedded as a compact popup chat widget on
the NAWASA website (via iframe). These rules hide Streamlit's default
page chrome and tighten spacing so it reads as a purpose-built widget
rather than a generic web app. */
#MainMenu, header[data-testid="stHeader"], footer {{
visibility: hidden;
height: 0;
}}
.block-container {{
padding-top: 1.2rem;
padding-bottom: 1rem;
max-width: 480px;
}}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
gap: 4px;
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
border-radius: 12px 12px 0 0;
font-weight: 600;
}}
@media (max-width: 480px) {{
.block-container {{
padding-left: 0.6rem;
padding-right: 0.6rem;
max-width: 100%;
}}
.aqua-hero-title, .aqua-dash-greeting {{
font-size: 1.4rem;
}}
.aqua-tile-grid {{
grid-template-columns: 1fr 1fr;
}}
}}
</style>"""

st.markdown(
    '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">',
    unsafe_allow_html=True,
)
st.markdown(CSS_BLOCK, unsafe_allow_html=True)
st.markdown(
    f'<div class="whatsapp-float-wrap"><a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-float" title="Chat on WhatsApp">💬</a></div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# LOGIN / WELCOME GATE — first screen on a fresh session.
# Only two inputs required: territory and API key, per client spec. There is
# no user-account system (no passwords, no database) — see the note at the
# top of this file about what "log in" does and doesn't mean here.
# ---------------------------------------------------------------------------
if not st.session_state.auth_done:
    st.markdown('<div class="aqua-login-wrap">', unsafe_allow_html=True)

    # Centered NAWASA logo (falls back to a styled text badge if
    # nawasa_logo.png isn't found next to app.py).
    st.markdown(f"""<div class="aqua-login-header">
<div class="aqua-login-header-center">
{nawasa_logo_tag(72)}
<div class="aqua-login-title">AquaAssist</div>
<div class="aqua-login-subtitle">Your smart water support assistant</div>
</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="aqua-card aqua-login-card">', unsafe_allow_html=True)

    st.session_state.territory = st.selectbox(
        f"📍 {t('login_territory')}", TERRITORIES,
        index=TERRITORIES.index(st.session_state.territory) if st.session_state.territory in TERRITORIES else 0,
    )

    st.session_state.api_key = st.text_input(
        f"🔑 {t('login_key')}", value=st.session_state.api_key, type="password",
        help=t("login_key_help"),
    )

    st.markdown('<div class="aqua-primary-btn">', unsafe_allow_html=True)
    start_clicked = st.button(f"💧 {t('login_start')}", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if start_clicked:
        if not st.session_state.territory or not st.session_state.api_key:
            st.error(t("login_missing"))
        else:
            st.session_state.auth_done = True
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)  # aqua-card
    st.markdown('</div>', unsafe_allow_html=True)  # aqua-login-wrap
    st.stop()

api_key = st.session_state.api_key

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
    elif nawasa_logo_b64:
        st.image(str(logo_path), width=90)

    mode = st.radio("View", ["💬 Customer Portal", "🔐 Staff Portal"], label_visibility="collapsed")

    if mode == "💬 Customer Portal":
        st.markdown('<div class="aqua-sidebar-newchat">', unsafe_allow_html=True)
        if st.button(t("new_chat"), use_container_width=True):
            start_new_chat()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.caption(t("chat_history"))
        session_ids = ordered_session_ids()
        if len(session_ids) == 1 and not st.session_state.chat_sessions[session_ids[0]]["messages"]:
            st.caption(t("no_history"))
        else:
            for sid in session_ids:
                sess = st.session_state.chat_sessions[sid]
                label = sess["name"] if sess["messages"] or sess["name"] != "New chat" else t("new_chat")
                is_active = sid == st.session_state.current_session_id
                wrap_class = "aqua-history-btn aqua-history-active" if is_active else "aqua-history-btn"
                st.markdown(f'<div class="{wrap_class}">', unsafe_allow_html=True)
                if st.button(label, key=f"hist_{sid}", use_container_width=True):
                    switch_to_chat(sid)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        st.divider()

    st.markdown(
        f'<a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-btn">📱 Chat on WhatsApp</a>',
        unsafe_allow_html=True,
    )
    st.caption(f"📞 {NAWASA_PHONE}")
    st.caption(f"🌐 [nawasa.gd]({NAWASA_WEBSITE})")
    st.caption(f"📍 Territory: {st.session_state.territory}")
    _sidebar_hours = get_business_hours_status()
    if _sidebar_hours["is_open"]:
        st.caption("🟢 Open now · Mon–Sat, 8:00 AM – 4:00 PM")
    else:
        st.caption(f"🟠 Closed — reopens {_sidebar_hours['reopens_label']} · Mon–Sat, 8:00 AM – 4:00 PM")

    with st.expander("⚙️ Territory & API key"):
        new_territory = st.selectbox(
            "NAWASA territory", TERRITORIES,
            index=TERRITORIES.index(st.session_state.territory) if st.session_state.territory in TERRITORIES else 0,
            key="sidebar_territory_select",
        )
        if new_territory != st.session_state.territory:
            st.session_state.territory = new_territory
            st.session_state.pop("chat", None)
            st.rerun()

        new_key = st.text_input("Google AI Studio API key", value=api_key, type="password",
                                 help="Get a key at https://aistudio.google.com/")
        if new_key != api_key:
            st.session_state.api_key = new_key
            st.rerun()
        api_key = st.session_state.api_key

        if st.button("Sign out"):
            st.session_state.auth_done = False
            st.rerun()

    if st.button("🔄 Reset conversation"):
        st.session_state.pop("chat", None)
        st.session_state.pop("client", None)
        st.session_state.pop("_key_used", None)
        st.session_state.chat_sessions[st.session_state.current_session_id]["messages"] = []
        st.rerun()

    with st.expander("📜 View system instruction"):
        st.text(build_system_instruction(st.session_state.territory))

    if HAS_MIC_RECORDER:
        st.caption("🎤 Live mic recording: enabled")
    else:
        st.caption("🎤 Live mic recording: not installed (voice notes via upload still work)")
    if HAS_GEOLOCATION:
        st.caption("📍 One-tap GPS: enabled")
    else:
        st.caption("📍 One-tap GPS: not installed (manual location entry still works)")
    if HAS_MAP:
        st.caption("🗺️ Interactive Grenada map: enabled")
    else:
        st.caption("🗺️ Interactive Grenada map: not installed (manual lat/lng entry still works)")
    if HAS_TTS:
        st.caption("🔊 Voice replies: enabled (Caribbean-leaning voice, Standard English fallback)")
    else:
        st.caption("🔊 Voice replies: not installed (add `gtts` to requirements.txt to enable)")

# ===========================================================================
# STAFF PORTAL
# ===========================================================================
if mode == "🔐 Staff Portal":
    staff_hero = f"""<div class="aqua-hero">
<div class="aqua-hero-content">
<div>
<div class="aqua-hero-title">🔐 Staff Portal</div>
<div class="aqua-hero-subtitle">Reports submitted by customers</div>
</div>
</div>
<svg class="aqua-wave" viewBox="0 0 500 40" preserveAspectRatio="none">
<path class="aqua-wave-fill" d="M0,20 C150,45 350,-5 500,20 L500,40 L0,40 Z"></path>
</svg>
</div>"""
    st.markdown(staff_hero, unsafe_allow_html=True)

    if "staff_authed" not in st.session_state:
        st.session_state.staff_authed = False

    if not st.session_state.staff_authed:
        st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
        entered = st.text_input("Enter staff passcode", type="password")
        if st.button("Log in"):
            if entered == STAFF_PASSCODE:
                st.session_state.staff_authed = True
                st.rerun()
            else:
                st.error("Incorrect passcode.")
        st.markdown('</div>', unsafe_allow_html=True)
        st.stop()

    st.success("Logged in as staff.")
    if st.button("Log out"):
        st.session_state.staff_authed = False
        st.rerun()

    daily_used = get_daily_usage_count()
    usage_pct = daily_used / DAILY_MESSAGE_LIMIT if DAILY_MESSAGE_LIMIT else 0
    st.caption(f"🤖 AI messages today: {daily_used} / {DAILY_MESSAGE_LIMIT}")
    st.progress(min(usage_pct, 1.0))
    if usage_pct >= 0.9:
        st.warning("Approaching today's AI message limit — customers will be redirected to phone/WhatsApp once it's reached. Adjust DAILY_MESSAGE_LIMIT if this happens often.")

    reports_df = load_reports()

    if reports_df.empty:
        st.info("No reports submitted yet.")
    else:
        st.metric("Total reports", len(reports_df))

        # --- Incident map: every report with a pinned GPS location, color-coded by status ---
        st.markdown(f'<div class="aqua-section-label">{t("staff_map_label")}</div>', unsafe_allow_html=True)
        if HAS_MAP:
            STATUS_COLORS = {
                "Received": "red", "Assigned": "orange", "Crew Dispatched": "orange",
                "In Progress": "blue", "Resolved": "green",
            }
            pinned_rows = []
            for _, row in reports_df.iterrows():
                coords = parse_report_coords(row.get("location", ""))
                if coords:
                    pinned_rows.append((row, coords))

            if not pinned_rows:
                st.caption(t("staff_map_empty"))
            else:
                avg_lat = sum(c[0] for _, c in pinned_rows) / len(pinned_rows)
                avg_lng = sum(c[1] for _, c in pinned_rows) / len(pinned_rows)
                incident_map = folium.Map(
                    location=[avg_lat, avg_lng], zoom_start=11,
                    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                    attr="Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
                )
                for row, (lat, lng) in pinned_rows:
                    status = row.get("status", "Received")
                    severity = row.get("severity", "Unknown")
                    popup = (f"<b>{row.get('reference', '')}</b><br>"
                             f"{row.get('issue_type', '')} — {status}<br>"
                             f"Severity: {severity}")
                    folium.CircleMarker(
                        location=[lat, lng], radius=8,
                        color=STATUS_COLORS.get(status, "gray"),
                        fill=True, fill_color=STATUS_COLORS.get(status, "gray"), fill_opacity=0.8,
                        popup=folium.Popup(popup, max_width=220),
                        tooltip=row.get("reference", ""),
                    ).add_to(incident_map)
                st_folium(incident_map, height=380, use_container_width=True, key="staff_incident_map")
                st.caption("🔴 Received · 🟠 Assigned/Dispatched · 🔵 In Progress · 🟢 Resolved")
        else:
            st.caption(t("map_not_installed"))

        edited_df = st.data_editor(
            reports_df,
            use_container_width=True,
            column_config={
                "status": st.column_config.SelectboxColumn("status", options=STATUS_STAGES),
            },
            disabled=[c for c in REPORTS_FIELDS if c != "status" and c in reports_df.columns],
            key="staff_editor",
        )
        if st.button("💾 Save status changes"):
            edited_df.to_csv(REPORTS_PATH, index=False)
            st.success("Statuses updated.")

        csv_bytes = reports_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download reports as CSV", data=csv_bytes,
                            file_name="nawasa_reports.csv", mime="text/csv")

        notif_df = None
        if os.path.exists(NOTIFY_PATH):
            import pandas as pd
            notif_df = pd.read_csv(NOTIFY_PATH)
        with st.expander(f"🔔 Notification subscribers ({0 if notif_df is None else len(notif_df)})"):
            if notif_df is not None and not notif_df.empty:
                st.dataframe(notif_df, use_container_width=True)
            else:
                st.caption("No subscribers yet.")

    # --- Outage announcements: staff posts these; matching customers see a
    # banner in-app for their selected parish while the date range is active. ---
    st.markdown(f'<div class="aqua-section-label">{t("outage_section_label")}</div>', unsafe_allow_html=True)
    with st.form("outage_form", clear_on_submit=True):
        outage_parish = st.selectbox(t("outage_parish_label"), GRENADA_PARISHES, key="outage_parish_select")
        outage_message = st.text_area(t("outage_message_label"), key="outage_message_input")
        outage_col1, outage_col2 = st.columns(2)
        with outage_col1:
            outage_start = st.date_input(t("outage_start_label"), key="outage_start_input")
        with outage_col2:
            outage_end = st.date_input(t("outage_end_label"), key="outage_end_input")
        if st.form_submit_button(t("outage_create_button")):
            if outage_message.strip():
                save_outage(outage_parish, outage_message.strip(),
                            outage_start.strftime("%Y-%m-%d"), outage_end.strftime("%Y-%m-%d"))
                st.success("Announcement posted.")
                st.rerun()
            else:
                st.error("Please enter a message.")

    st.caption(t("outage_active_label"))
    outages_df = load_outages()
    if outages_df.empty:
        st.caption(t("outage_none"))
    else:
        for _, row in outages_df.iterrows():
            oc1, oc2 = st.columns([5, 1])
            with oc1:
                st.write(f"**{row['parish']}** ({row['start_date']} – {row['end_date']}): {row['message']}")
            with oc2:
                if st.button(t("outage_delete_button"), key=f"del_outage_{row['id']}"):
                    delete_outage(row["id"])
                    st.rerun()

    st.stop()

# ===========================================================================
# CUSTOMER PORTAL
# ===========================================================================
if "active_portal_tab" not in st.session_state:
    st.session_state.active_portal_tab = "chat"

def go_to(portal_tab):
    st.session_state.active_portal_tab = portal_tab

logo_html = f'<img src="data:image/png;base64,{logo_b64}" />' if logo_b64 else "💧"

if not api_key:
    st.info("👈 Enter your Google AI Studio API key in the sidebar (Territory & API key) to start chatting.")
    st.stop()

# ---------------------------------------------------------------------------
# Initialize client + chat session (recreated when key, territory, or the
# active chat session changes)
# ---------------------------------------------------------------------------
if ("chat" not in st.session_state
        or st.session_state.get("_key_used") != api_key
        or st.session_state.get("_chat_territory") != st.session_state.territory
        or st.session_state.get("_chat_session_ref") != st.session_state.current_session_id):
    try:
        client = genai.Client(api_key=api_key)
        st.session_state.client = client

        # Reseed history from the active chat session's transcript, if any,
        # so switching back to an older chat can still be continued.
        seed_history = []
        for m in st.session_state.messages:
            if m["role"] in ("user", "assistant") and isinstance(m.get("content"), str):
                role = "user" if m["role"] == "user" else "model"
                seed_history.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))

        chat_kwargs = dict(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=build_system_instruction(st.session_state.territory),
                temperature=0.7,
                tools=[log_water_report],
            ),
        )
        try:
            st.session_state.chat = client.chats.create(history=seed_history, **chat_kwargs)
        except TypeError:
            # Older SDK versions may not accept `history=` — fall back to a
            # fresh session; the displayed transcript is unaffected either way.
            st.session_state.chat = client.chats.create(**chat_kwargs)

        st.session_state._key_used = api_key
        st.session_state._chat_territory = st.session_state.territory
        st.session_state._chat_session_ref = st.session_state.current_session_id
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()

quick_actions = {
    t("qa_report_label"): {"prompt": t("qa_report_prompt"), "icon": "👷",
                            "desc": "Log a leak, burst main, or drip in seconds."},
    t("qa_maint_label"): {"prompt": t("qa_maint_prompt"), "icon": "🚰",
                           "desc": "Check for planned works or outages near you."},
    t("qa_bill_label"): {"prompt": t("qa_bill_prompt"), "icon": "💳",
                          "desc": "See how to pay your NAWASA bill."},
    t("qa_checkbill_label"): {"prompt": t("qa_checkbill_prompt"), "icon": "📄",
                               "desc": "View your balance and billing details."},
    t("qa_locations_label"): {"prompt": t("qa_locations_prompt"), "icon": "📍",
                               "desc": "Find a NAWASA office near you."},
    t("qa_rep_label"): {"prompt": t("qa_rep_prompt"), "icon": "👤",
                         "desc": "Get connected to a live representative."},
}

contact_row_html = f"""<div class="aqua-contact-row">
<a href="tel:{NAWASA_PHONE.replace(' ', '').replace('(', '').replace(')', '').replace('-', '')}" class="aqua-contact-card">
<span class="aqua-contact-icon">📞</span>
<span class="aqua-contact-label">{t('call_us')}</span>
<span class="aqua-contact-value">{NAWASA_PHONE}</span>
</a>
<a href="{WHATSAPP_LINK}" target="_blank" class="aqua-contact-card">
<span class="aqua-contact-icon">💬</span>
<span class="aqua-contact-label">{t('whatsapp_label')}</span>
<span class="aqua-contact-value">{t('chat_now')}</span>
</a>
<a href="{NAWASA_WEBSITE}" target="_blank" class="aqua-contact-card">
<span class="aqua-contact-icon">🌐</span>
<span class="aqua-contact-label">{t('website_label')}</span>
<span class="aqua-contact-value">nawasa.gd</span>
</a>
</div>"""

# ===========================================================================
# PORTAL — Chat / FAQ / Report & Track / History / Settings
# This is a compact popup widget embedded on the NAWASA website, so the
# customer lands directly in the tabbed portal — there's no separate Home
# dashboard screen to pass through first.
# ===========================================================================
st.markdown('<div class="aqua-page">', unsafe_allow_html=True)

hours_status = get_business_hours_status()
if hours_status["is_open"]:
    status_pill_html = '<div class="aqua-hero-status aqua-hero-status-open"><span class="aqua-hero-status-dot"></span>Open now</div>'
else:
    status_pill_html = f'<div class="aqua-hero-status aqua-hero-status-closed"><span class="aqua-hero-status-dot"></span>Closed — reopens {hours_status["reopens_label"]}</div>'

nawasa_badge_inner = (f'<img src="data:image/png;base64,{nawasa_logo_b64}" />' if nawasa_logo_b64
                      else '<span style="font-size:0.55rem;font-weight:800;color:{0};text-align:center;">NAWASA</span>'.format(BRAND_HOVER))

chat_hero = f"""<div class="aqua-hero">
<div class="aqua-hero-content">
<div class="aqua-hero-brand">
{logo_html}
<div>
<div class="aqua-hero-title">AquaAssist</div>
<div class="aqua-hero-subtitle">Official Virtual Assistant</div>
{status_pill_html}
</div>
</div>
<div class="aqua-hero-nawasa-badge">{nawasa_badge_inner}</div>
</div>
<svg class="aqua-wave" viewBox="0 0 500 40" preserveAspectRatio="none">
<path class="aqua-wave-fill" d="M0,20 C150,45 350,-5 500,20 L500,40 L0,40 Z"></path>
</svg>
</div>"""
st.markdown(chat_hero, unsafe_allow_html=True)

NAV_ITEMS = [
    ("chat", t("tab_chat")), ("faq", t("tab_faq")), ("report", t("tab_report")),
    ("history", t("tab_history")), ("settings", t("tab_settings")),
]
nav_cols = st.columns(len(NAV_ITEMS))
for col, (key, label) in zip(nav_cols, NAV_ITEMS):
    with col:
        wrap_class = "aqua-primary-btn" if st.session_state.active_portal_tab == key else ""
        if wrap_class:
            st.markdown(f'<div class="{wrap_class}">', unsafe_allow_html=True)
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state.active_portal_tab = key
            st.rerun()
        if wrap_class:
            st.markdown('</div>', unsafe_allow_html=True)

st.divider()

active_tab = st.session_state.active_portal_tab

if st.session_state.get("customer_parish") and active_tab == "chat":
    for outage in get_active_outages_for_parish(st.session_state.customer_parish):
        st.warning(f"{t('outage_banner_prefix')} {outage['parish']}: {outage['message']} "
                   f"({outage['start_date']} – {outage['end_date']})")

# ===================== CHAT =====================
if active_tab == "chat":
    if not hours_status["is_open"]:
        st.markdown(
            f'<div class="aqua-hours-banner">'
            f'<span class="aqua-hours-banner-icon">🕒</span>'
            f'<span><strong>Our Customer Service team has closed for the day and will reopen '
            f'{hours_status["reopens_label"]}.</strong> AquaAssist remains available 24/7 to answer your questions. '
            f"You're welcome to leave a message here, call, or WhatsApp us at any time—we'll follow up as soon as our team is back in the office.</span>"
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown(contact_row_html, unsafe_allow_html=True)

    ASSISTANT_AVATAR = LOGO_PATH if os.path.exists(LOGO_PATH) else "💧"
    USER_AVATAR = "🧑"

    for msg in st.session_state.messages:
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else USER_AVATAR
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("audio"):
                st.audio(msg["audio"])
            if msg.get("attachment_name"):
                st.caption(f"📎 {msg['attachment_name']}")

    if not st.session_state.messages:
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.markdown(t("welcome"))

    input_row = st.columns([0.09, 0.08, 0.83])
    with input_row[0]:
        st.markdown('<div class="aqua-mic-btn">', unsafe_allow_html=True)
        mic_clicked = st.button("🎤", key="mic_toggle_btn", help=t("voice_popover_label"))
        st.markdown('</div>', unsafe_allow_html=True)
    with input_row[1]:
        st.session_state.voice_replies = st.toggle(
            "🔊", value=st.session_state.voice_replies, disabled=not HAS_TTS,
            help=t("voice_help_on") if HAS_TTS else t("voice_help_off"), label_visibility="visible",
        )

    voice_text_input = None
    if mic_clicked:
        st.session_state["_mic_open"] = not st.session_state.get("_mic_open", False)
    if st.session_state.get("_mic_open"):
        with st.container(border=True):
            if HAS_MIC_RECORDER:
                audio_bytes = audio_recorder(text="Tap to record", icon_size="2x", key="mic_recorder")
                if audio_bytes:
                    st.audio(audio_bytes)
                    if st.button("Send recording", key="send_recording_btn"):
                        voice_text_input = ("__AUDIO__", audio_bytes, "audio/wav")
                        st.session_state["_mic_open"] = False
            else:
                st.caption("Live mic recording isn't installed. Upload a voice note instead:")
                uploaded_audio = st.file_uploader("Voice note", type=["mp3", "wav", "m4a", "ogg"], key="voice_upload")
                if uploaded_audio and st.button("Send this voice note", key="send_upload_btn"):
                    voice_text_input = ("__AUDIO__", uploaded_audio.read(), uploaded_audio.type or "audio/mpeg")
                    st.session_state["_mic_open"] = False

    try:
        chat_submission = st.chat_input(
            t("ask_placeholder"), accept_file=True,
            file_type=["jpg", "jpeg", "png", "pdf", "doc", "docx", "mp3", "wav", "m4a"],
        )
        typed_input = chat_submission.text if chat_submission else None
        uploaded_files = chat_submission.files if chat_submission else []
    except TypeError:
        typed_input = st.chat_input(t("ask_placeholder"))
        uploaded_files = []

    st.markdown(f'<div class="aqua-section-label">{t("quick_actions")}</div>', unsafe_allow_html=True)
    qa_items = list(quick_actions.items())
    queued_prompt = None
    for row_start in range(0, len(qa_items), 2):
        row_items = qa_items[row_start:row_start + 2]
        qa_cols = st.columns(len(row_items))
        for qa_idx, (col, (label, info)) in enumerate(zip(qa_cols, row_items), start=row_start):
            with col:
                if st.button(label, use_container_width=True, key=f"qa_{qa_idx}", help=info["desc"]):
                    queued_prompt = info["prompt"]

    user_turn = None
    is_audio_turn = False
    if voice_text_input:
        user_turn = voice_text_input
        is_audio_turn = True
    elif queued_prompt:
        user_turn = queued_prompt
    elif typed_input:
        user_turn = typed_input.strip()

    if user_turn:
        if is_audio_turn:
            _, audio_bytes, mime_type = user_turn
            st.session_state.messages.append({"role": "user", "content": "🎤 (voice message)"})

            allowed, limit_reason = check_and_record_usage()
            if not allowed:
                reply_text = usage_limit_message(limit_reason)
            else:
                with st.spinner("Listening..."):
                    try:
                        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
                        bot_response = st.session_state.chat.send_message([
                            audio_part,
                            "Please respond to this voice message from a NAWASA customer.",
                        ])
                        reply_text = bot_response.text
                    except Exception as e:
                        reply_text = f"⚠️ Error processing voice message: {e}"

            reply_audio = None
            if st.session_state.voice_replies:
                reply_audio = speak_text(reply_text, "en")

            st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": reply_audio})
            st.rerun()
        else:
            cleaned_input = user_turn.strip()
            if cleaned_input or uploaded_files:
                attachment_name = ""
                message_parts = []
                if cleaned_input:
                    message_parts.append(cleaned_input)
                    display_text = cleaned_input
                else:
                    display_text = "📎 Sent an attachment"

                for uf in (uploaded_files or []):
                    ensure_files()
                    file_bytes = uf.read()
                    attachment_name = f"{uuid.uuid4().hex[:8]}_{uf.name}"
                    with open(os.path.join(ATTACHMENTS_DIR, attachment_name), "wb") as out:
                        out.write(file_bytes)
                    message_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=uf.type or "application/octet-stream"))

                st.session_state.messages.append({
                    "role": "user", "content": display_text,
                    "attachment_name": attachment_name if uploaded_files else None,
                })

                allowed, limit_reason = check_and_record_usage()
                if not allowed:
                    reply_text = usage_limit_message(limit_reason)
                else:
                    with st.spinner("Thinking..."):
                        try:
                            bot_response = st.session_state.chat.send_message(message_parts if message_parts else cleaned_input)
                            reply_text = bot_response.text
                        except Exception as e:
                            reply_text = f"⚠️ Error: {e}"

                reply_audio = None
                if st.session_state.voice_replies:
                    reply_audio = speak_text(reply_text, "en")

                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": reply_audio})
                st.rerun()

# ===================== HISTORY =====================
elif active_tab == "history":
    st.markdown(f'<div class="aqua-section-label">{t("tab_history")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    history_search = st.text_input("Search this conversation", key="history_search_main")
    shown_messages = st.session_state.messages
    if history_search:
        shown_messages = [m for m in shown_messages if history_search.lower() in m["content"].lower()]

    if not shown_messages:
        st.caption("No messages to show yet." if not history_search else "No matches found.")
    else:
        for m in shown_messages:
            role_label = "🧑 You" if m["role"] == "user" else "💧 AquaAssist"
            st.markdown(f"**{role_label}:** {m['content']}")

    st.caption(f"{len(st.session_state.messages)} messages in this session.")
    if st.button("🗑️ Clear chat history", key="clear_history_main"):
        st.session_state.chat_sessions[st.session_state.current_session_id]["messages"] = []
        st.rerun()
    st.caption("Tip: use “+ New chat” in the sidebar to start a fresh conversation without losing this one — it's saved automatically under Recent chats.")
    st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("🕵️ Raw Gemini session (technical/debug view)"):
        if "chat" in st.session_state:
            try:
                for message in st.session_state.chat.get_history():
                    role = message.role.upper()
                    text = message.parts[0].text
                    st.markdown(f"**[{role}]:** {text}")
            except Exception as e:
                st.caption(f"No history yet ({e})")

# ===================== FAQ =====================
elif active_tab == "faq":
    st.markdown('<div class="aqua-section-label">❓ Frequently Asked Questions</div>', unsafe_allow_html=True)
    st.caption("Sourced from the official NAWASA FAQ page (nawasa.gd).")

    faq_query = st.text_input("Search FAQs", placeholder="e.g. billing, leak, disconnection...")
    results = search_faqs(faq_query, FAQS)
    if not results:
        st.info("No matching FAQ found. Try the Chat tab to ask the AI directly, or contact a representative.")
    else:
        categories = sorted(set(f["category"] for f in results))
        for cat in categories:
            st.markdown(f"**{cat}**")
            for faq_idx, f in enumerate([x for x in results if x["category"] == cat]):
                faq_html = f"""<div class="aqua-faq-item">
<div class="aqua-faq-cat">{f['category']}</div>
<b>{f['q']}</b><br>{f['a']}
</div>"""
                st.markdown(faq_html, unsafe_allow_html=True)
                # Key is index-based (not sliced question text) — two FAQ
                # items with the same first ~20 characters, especially after
                # translation, previously collided on the same widget key
                # and crashed the app with StreamlitDuplicateElementKey.
                if HAS_TTS and st.button(f"🔊 Read aloud", key=f"faq_audio_{cat}_{faq_idx}"):
                    audio = speak_text(f["a"], "en")
                    if audio:
                        st.audio(audio)

# ===================== REPORT & TRACK =====================
elif active_tab == "report":
    st.markdown(f'<div class="aqua-section-label">{t("report_issue")}</div>', unsafe_allow_html=True)

    # --- Grenada location picker: parish + landmark + physical (terrain) map pin ---
    st.markdown(f'<div class="aqua-section-label">{t("map_section_label")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)

    pick_col1, pick_col2 = st.columns(2)
    with pick_col1:
        default_parish_idx = (
            GRENADA_PARISHES.index(st.session_state.get("report_parish"))
            if st.session_state.get("report_parish") in GRENADA_PARISHES else 0
        )
        st.session_state.report_parish = st.selectbox(
            t("map_parish_label"), GRENADA_PARISHES, index=default_parish_idx, key="report_parish_select",
        )
    with pick_col2:
        st.session_state.report_landmark = st.text_input(
            t("map_address_label"), value=st.session_state.get("report_landmark", ""),
            key="report_landmark_input", placeholder="e.g. New Life Grocery, Main road",
        )

    if "report_pin" not in st.session_state:
        st.session_state.report_pin = {"lat": GRENADA_CENTER[0], "lng": GRENADA_CENTER[1]}

    gps_col, hint_col = st.columns([1, 2])
    with gps_col:
        if HAS_GEOLOCATION:
            if st.button(t("map_gps_button"), key="map_gps_btn", use_container_width=True):
                coords = streamlit_geolocation()
                if coords and coords.get("latitude"):
                    st.session_state.report_pin = {"lat": coords["latitude"], "lng": coords["longitude"]}
                    st.rerun()
    with hint_col:
        if HAS_MAP:
            st.caption(t("map_click_hint"))

    if HAS_MAP:
        m = folium.Map(
            location=[st.session_state.report_pin["lat"], st.session_state.report_pin["lng"]],
            zoom_start=12,
            tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            attr="Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
        )
        folium.Marker(
            [st.session_state.report_pin["lat"], st.session_state.report_pin["lng"]],
            draggable=True,
            tooltip=t("map_click_hint"),
        ).add_to(m)
        map_result = st_folium(m, height=340, use_container_width=True, key="grenada_pin_map")
        if map_result and map_result.get("last_clicked"):
            new_lat = map_result["last_clicked"]["lat"]
            new_lng = map_result["last_clicked"]["lng"]
            if (round(new_lat, 6), round(new_lng, 6)) != (
                round(st.session_state.report_pin["lat"], 6), round(st.session_state.report_pin["lng"], 6)
            ):
                st.session_state.report_pin = {"lat": new_lat, "lng": new_lng}
                st.rerun()
        st.caption(f"📍 {t('map_pinned_caption')}: {st.session_state.report_pin['lat']:.4f}, {st.session_state.report_pin['lng']:.4f}")
    else:
        st.caption(t("map_not_installed"))
        manual_col1, manual_col2 = st.columns(2)
        with manual_col1:
            st.session_state.report_pin["lat"] = st.number_input(
                "Latitude", value=float(st.session_state.report_pin["lat"]), format="%.5f", key="manual_lat",
            )
        with manual_col2:
            st.session_state.report_pin["lng"] = st.number_input(
                "Longitude", value=float(st.session_state.report_pin["lng"]), format="%.5f", key="manual_lng",
            )

    st.markdown('</div>', unsafe_allow_html=True)

    _composed_location_parts = [
        st.session_state.report_landmark.strip() if st.session_state.report_landmark else "",
        st.session_state.report_parish,
    ]
    composed_location = ", ".join([p for p in _composed_location_parts if p])
    composed_location += f" (GPS: {st.session_state.report_pin['lat']:.5f}, {st.session_state.report_pin['lng']:.5f})"

    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.expander(t("report_form_expander"), expanded=True):
        # Photo upload lives OUTSIDE the form so the "Analyze severity" button
        # can call Gemini vision and rerun immediately — widgets inside a
        # st.form only take effect when the form itself is submitted.
        r_attachment = st.file_uploader(t("field_attachment"),
                                          type=["jpg", "jpeg", "png", "mp4", "mov", "pdf", "doc", "docx"],
                                          key="report_attachment_uploader")
        if "report_severity" not in st.session_state:
            st.session_state.report_severity = "Unknown"

        if r_attachment is not None and r_attachment.type and r_attachment.type.startswith("image/"):
            if st.button(f"🔍 {t('severity_analyze_button')}", key="analyze_severity_btn"):
                img_bytes = r_attachment.getvalue()
                try:
                    client = genai.Client(api_key=api_key)
                    with st.spinner("Analyzing photo..."):
                        vision_response = client.models.generate_content(
                            model=MODEL_NAME,
                            contents=[
                                types.Part.from_bytes(data=img_bytes, mime_type=r_attachment.type),
                                "This is a photo of a water utility issue (leak, burst pipe, "
                                "damaged hydrant, etc.) reported by a NAWASA customer in Grenada. "
                                "Reply with exactly one word describing the severity: Low, Medium, "
                                "or High. Low = minor drip/no visible water loss. Medium = a steady "
                                "leak or moderate water loss. High = a burst pipe, major flooding, "
                                "or a safety hazard.",
                            ],
                        )
                        guess = vision_response.text.strip().split()[0].capitalize()
                    st.session_state.report_severity = guess if guess in SEVERITY_LEVELS else "Unknown"
                except Exception:
                    st.session_state.report_severity = "Unknown"
                    st.warning("Couldn't analyze the photo right now — set severity manually below.")

        with st.form("leak_report_form", clear_on_submit=True):
            r_name = st.text_input(t("field_name"), value=st.session_state.customer_name)
            r_phone = st.text_input(t("field_phone"))
            r_location = st.text_input(t("field_location"), value=composed_location)

            issue_type_keys = ["issue_leak", "issue_no_water", "issue_low_pressure", "issue_billing",
                                "issue_burst", "issue_hydrant", "issue_quality", "issue_other"]
            issue_type_values = ["Leak", "No water supply", "Low pressure", "Billing issue",
                                  "Burst main", "Damaged hydrant", "Water quality concern", "Other"]
            r_issue_type = st.selectbox(t("field_issue_type"), issue_type_values,
                                          format_func=lambda v: t(issue_type_keys[issue_type_values.index(v)]))
            r_description = st.text_area(t("field_description"))
            r_severity = st.selectbox(
                t("severity_label"), SEVERITY_LEVELS,
                index=SEVERITY_LEVELS.index(st.session_state.report_severity),
            )
            submitted = st.form_submit_button(t("submit_report"))

            if submitted:
                if not r_name or not r_phone or not r_location:
                    st.error("Please fill in your name, phone number, and location.")
                else:
                    attachment_name = ""
                    if r_attachment is not None:
                        ensure_files()
                        attachment_name = f"{uuid.uuid4().hex[:8]}_{r_attachment.name}"
                        with open(os.path.join(ATTACHMENTS_DIR, attachment_name), "wb") as out:
                            out.write(r_attachment.getvalue())
                    reference = save_report(r_name, r_phone, r_location, r_issue_type,
                                             r_description, attachment_name, severity=r_severity)
                    st.session_state.report_severity = "Unknown"
                    st.success(f"✅ Report submitted! Your reference number is **{reference}** — save this to track your report below.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("track_report_label")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    track_ref = st.text_input(t("track_report_placeholder"))
    if track_ref:
        result = track_report(track_ref)
        if result is None:
            st.warning("No report found with that reference number.")
        else:
            stage_idx = STATUS_STAGES.index(result["status"]) if result["status"] in STATUS_STAGES else 0
            st.markdown(f"**Status:** <span class='aqua-status-badge'>{result['status']}</span>", unsafe_allow_html=True)
            st.progress((stage_idx + 1) / len(STATUS_STAGES))
            st.caption(" → ".join(STATUS_STAGES))
            st.write(f"**Issue:** {result['issue_type']} — {result['description']}")
            st.write(f"**Location:** {result['location']}")
            st.write(f"**Submitted:** {result['timestamp']}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("get_notified")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.form("notify_form", clear_on_submit=True):
        notify_contact = st.text_input(t("notify_contact_label"))
        notify_categories = st.multiselect(t("notify_categories_label"), [
            "Planned maintenance", "Water outages", "Emergency repairs", "Service updates",
        ])
        if st.form_submit_button(t("subscribe_button")):
            if notify_contact and notify_categories:
                save_notification_signup(notify_contact, notify_categories)
                st.success("You're subscribed to notifications.")
            else:
                st.error("Please enter a contact and select at least one category.")
    st.markdown('</div>', unsafe_allow_html=True)

# ===================== SETTINGS =====================
elif active_tab == "settings":
    st.markdown(f'<div class="aqua-section-label">{t("settings_preferences")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)

    new_territory = st.selectbox(
        "NAWASA territory", TERRITORIES,
        index=TERRITORIES.index(st.session_state.territory) if st.session_state.territory in TERRITORIES else 0,
        key="settings_territory_select",
    )
    if new_territory != st.session_state.territory:
        st.session_state.territory = new_territory
        st.session_state.pop("chat", None)
        st.rerun()

    st.session_state.dark_mode = st.toggle(t("dark_mode"), value=st.session_state.dark_mode)
    st.session_state.high_contrast = st.toggle(t("high_contrast"), value=st.session_state.high_contrast)
    st.session_state.large_text = st.toggle(t("large_text"), value=st.session_state.large_text)
    st.caption(t("accessibility_note"))

    parish_options = [""] + GRENADA_PARISHES
    current_parish = st.session_state.get("customer_parish", "")
    st.session_state.customer_parish = st.selectbox(
        t("your_parish_label"), parish_options,
        index=parish_options.index(current_parish) if current_parish in parish_options else 0,
        key="settings_customer_parish",
    )

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("settings_conversation")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.caption(f"{len(st.session_state.messages)} {t('conversation_note')}")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)  # aqua-page

st.markdown('<div class="aqua-footer">Powered by <strong>NAWASA</strong></div>', unsafe_allow_html=True)


