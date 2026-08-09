import os
import csv
import io
import uuid
import base64
import smtplib
from email.mime.text import MIMEText
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

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

try:
    from pinecone import Pinecone
    HAS_PINECONE = True
except Exception:
    HAS_PINECONE = False

# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------
def get_config(key, default=""):
    val = os.environ.get(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

# ---------------------------------------------------------------------------
# NAWASA contact details
# ---------------------------------------------------------------------------
NAWASA_PHONE = "(473) 440-2155"
NAWASA_WEBSITE = "https://nawasa.gd/"
STAFF_PASSCODE = get_config("STAFF_PASSCODE", "changeme123")

PINECONE_API_KEY = get_config("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = get_config("PINECONE_INDEX_NAME", "")
PINECONE_NAMESPACE = get_config("PINECONE_NAMESPACE", "")

@st.cache_resource
def get_pinecone_index():
    if not HAS_PINECONE or not PINECONE_API_KEY or not PINECONE_INDEX_NAME:
        return None
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        return pc.Index(PINECONE_INDEX_NAME)
    except Exception:
        return None

def retrieve_nawasa_knowledge(query_text, top_k=4):
    index = get_pinecone_index()
    if index is None or not query_text:
        return ""
    try:
        results = index.search(
            namespace=PINECONE_NAMESPACE,
            query={"top_k": top_k, "inputs": {"text": query_text}},
        )
        hits = (results.get("result", {}) or {}).get("hits", [])
        snippets = []
        for hit in hits:
            fields = hit.get("fields", {}) or {}
            text = fields.get("text") or fields.get("chunk_text") or fields.get("content") or ""
            if text:
                snippets.append(text)
        if snippets:
            return "\n\n".join(snippets)
    except Exception:
        pass
    try:
        embed_client = genai.Client(api_key=st.session_state.get("api_key", ""))
        embed_response = embed_client.models.embed_content(
            model="text-embedding-004", contents=query_text,
        )
        query_vector = embed_response.embeddings[0].values
        results = index.query(
            namespace=PINECONE_NAMESPACE, vector=query_vector,
            top_k=top_k, include_metadata=True,
        )
        matches = results.get("matches", []) if isinstance(results, dict) else results.matches
        snippets = []
        for match in matches:
            meta = (match.get("metadata", {}) if isinstance(match, dict) else match.metadata) or {}
            text = meta.get("text") or meta.get("chunk_text") or meta.get("content") or ""
            if text:
                snippets.append(text)
        return "\n\n".join(snippets)
    except Exception:
        return ""

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
LOGO_PATH = os.path.join("assets", "aquaassist_logo.png")
AVATAR_PATH = os.path.join("assets", "aquaassist_avatar.png")
USER_AVATAR_PATH = os.path.join("assets", "user_avatar.png.jpg")
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

BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END = 16
CLOSING_SOON_WINDOW_MINUTES = 60
NAWASA_HOLIDAYS = []
GRENADA_TZ = timezone(timedelta(hours=-4))
_WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def get_business_hours_status():
    now = datetime.now(GRENADA_TZ)
    today_str = now.strftime("%Y-%m-%d")
    weekday_idx = now.weekday()
    is_weekend = weekday_idx >= 5
    is_holiday = today_str in NAWASA_HOLIDAYS
    is_open_hour = BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END
    is_open = (not is_weekend) and (not is_holiday) and is_open_hour
    next_day = now
    if is_weekend or is_holiday or now.hour >= BUSINESS_HOURS_END:
        next_day = next_day + timedelta(days=1)
    while next_day.weekday() >= 5 or next_day.strftime("%Y-%m-%d") in NAWASA_HOLIDAYS:
        next_day = next_day + timedelta(days=1)
    if is_weekend:
        closed_reason = "It's the weekend"
    elif is_holiday:
        closed_reason = "Today is a NAWASA holiday"
    elif now.hour < BUSINESS_HOURS_START:
        closed_reason = "We open later this morning"
    else:
        closed_reason = "We've closed for the day"
    same_day = next_day.strftime("%Y-%m-%d") == today_str
    reopens_label = ("today" if same_day else _WEEKDAY_LABELS[next_day.weekday()]) + f" at {BUSINESS_HOURS_START}:00 AM"
    minutes_until_close = None
    closing_soon = False
    if is_open:
        close_time = now.replace(hour=BUSINESS_HOURS_END, minute=0, second=0, microsecond=0)
        minutes_until_close = max(0, int((close_time - now).total_seconds() // 60))
        closing_soon = minutes_until_close <= CLOSING_SOON_WINDOW_MINUTES
    return {
        "is_open": is_open,
        "closed_reason": closed_reason,
        "reopens_label": reopens_label,
        "closing_soon": closing_soon,
        "minutes_until_close": minutes_until_close,
    }

st.set_page_config(
    page_title="AquaAssist",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

defaults = {
    "auth_done": False,
    "territory": "Grenada",
    "customer_name": "",
    "api_key": get_config("GEMINI_API_KEY", ""),
    "dark_mode": False,
    "high_contrast": False,
    "large_text": False,
    "voice_replies": HAS_TTS,
    "chat_sessions": {},
    "current_session_id": None,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

if not st.session_state.current_session_id:
    _sid = str(uuid.uuid4())
    st.session_state.chat_sessions[_sid] = {"name": "New chat", "messages": []}
    st.session_state.current_session_id = _sid

st.session_state.messages = st.session_state.chat_sessions[st.session_state.current_session_id]["messages"]

TERRITORIES = ["Grenada", "Carriacou", "Petit Martinique"]
TERRITORY_WHATSAPP = {
    "Grenada": "https://wa.link/rt9dj1",
    "Carriacou": "https://wa.link/wp6vfj",
    "Petit Martinique": "https://wa.link/3dpbnj",
}

def get_whatsapp_link():
    return TERRITORY_WHATSAPP.get(st.session_state.get("territory", "Grenada"), TERRITORY_WHATSAPP["Grenada"])

WHATSAPP_LINK = get_whatsapp_link()

def _sync_territory(source_key, other_key):
    new_value = st.session_state[source_key]
    st.session_state.territory = new_value
    st.session_state[other_key] = new_value
    st.session_state.pop("chat", None)

GRENADA_PARISHES = [
    "St. George's (Capital area)", "St. Andrew's", "St. David's",
    "St. John's", "St. Mark's", "St. Patrick's", "Carriacou and Petite Martinique",
]
GRENADA_CENTER = (12.1165, -61.6790)

PARISH_CENTERS = {
    "St. George's (Capital area)": (12.0561, -61.7488),
    "St. Andrew's": (12.1500, -61.6500),
    "St. David's": (12.0333, -61.6500),
    "St. John's": (12.1667, -61.7167),
    "St. Mark's": (12.2167, -61.6833),
    "St. Patrick's": (12.2333, -61.6167),
    "Carriacou and Petite Martinique": (12.4747, -61.4487),
}

def _nearest_parish(lat, lng):
    best_parish, best_dist = None, None
    for parish, (p_lat, p_lng) in PARISH_CENTERS.items():
        dist = (lat - p_lat) ** 2 + (lng - p_lng) ** 2
        if best_dist is None or dist < best_dist:
            best_parish, best_dist = parish, dist
    return best_parish

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
    "camera_popover_label": "📷 Take a photo of the issue",
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
    "map_click_hint": "Click anywhere on the map to set the pin — the nearest parish fills in automatically.",
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
     "a": "NAWASA's main office is now located on Lucas Street, St. George's (previously on the Carenage). Sub-offices are located at Seaton James Street, Grenville; Lower Depradine Street, Gouyave; and additional sub-offices in Sauteurs, St. David's, and Grand Anse."},
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
    import pandas as pd
    if not os.path.exists(REPORTS_PATH):
        return
    try:
        df = pd.read_csv(REPORTS_PATH)
    except Exception:
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
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writeheader()
        df = pd.read_csv(REPORTS_PATH)
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
# Staff Analytics Helpers (Added/Updated)
# ---------------------------------------------------------------------------
def _extract_parish(location_text, parishes):
    """Best-effort match of a known parish name inside the free-text
    location field."""
    if not isinstance(location_text, str) or not location_text:
        return None
    for parish in parishes:
        short_name = parish.split(" (")[0].strip()
        if short_name and short_name in location_text:
            return parish
    return None

def render_staff_analytics(reports_df, parishes):
    """Renders a small analytics section: reports by issue type and parish."""
    if reports_df is None or reports_df.empty:
        return
    st.markdown('<div class="aqua-section-label">📊 Analytics</div>', unsafe_allow_html=True)
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.caption("Reports by issue type")
        if "issue_type" in reports_df.columns:
            issue_counts = reports_df["issue_type"].value_counts()
            if not issue_counts.empty:
                st.bar_chart(issue_counts)
            else:
                st.caption("No issue type data yet.")
    with chart_col2:
        st.caption("Reports by parish")
        if "location" in reports_df.columns:
            parish_series = reports_df["location"].apply(lambda loc: _extract_parish(loc, parishes)).dropna()
            if len(parish_series) >= 3:
                st.bar_chart(parish_series.value_counts())
            else:
                st.caption("Not enough recognizable parish data yet to chart.")
    if "resolved_at" in reports_df.columns:
        try:
            import pandas as pd
            resolved = reports_df[
                (reports_df["status"] == "Resolved")
                & (reports_df["resolved_at"].astype(str).str.strip() != "")
            ]
            if not resolved.empty:
                durations = pd.to_datetime(resolved["resolved_at"]) - pd.to_datetime(resolved["timestamp"])
                avg_hours = durations.mean().total_seconds() / 3600
                st.metric(
                    "Avg. time to resolve", f"{avg_hours:.1f} hrs",
                    help=f"Based on {len(resolved)} resolved report(s) with a recorded resolution time.",
                )
        except Exception:
            pass
    else:
        st.caption(
            "💡 Track a `resolved_at` timestamp when a report is marked Resolved "
            "to unlock an average resolution time metric here."
        )

# ---------------------------------------------------------------------------
# Outage helpers
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
# Usage tracking
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
    df = df.tail(30)
    df.to_csv(USAGE_PATH, index=False)

def check_and_record_usage():
    session_count = st.session_state.get("_session_message_count", 0)
    st.session_state["_session_message_count"] = session_count + 1
    increment_daily_usage()
    return True, None

def usage_limit_message(reason):
    if reason == "session":
        return t("limit_session_reached")
    return t("limit_daily_reached")

def send_notification_email(sender_email, sender_password, to_email, subject, body,
                              smtp_host="smtp.gmail.com", smtp_port=587):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_email
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

def log_water_report(location: str, issue_type: str, description: str,
                      name: str = "Not provided", phone: str = "Not provided",
                      severity: str = "Unknown") -> str:
    reference = save_report(name, phone, location, issue_type, description, severity=severity)
    try:
        st.session_state["_last_logged_report"] = {
            "reference": reference, "status": "Received",
            "issue_type": issue_type, "severity": severity,
        }
    except Exception:
        pass
    return f"Report logged successfully. Reference number: {reference}. A technician will follow up."

# ---------------------------------------------------------------------------
# Voice helpers
# ---------------------------------------------------------------------------
VOICE_ACCENT_CHAIN = [
    {"tld": "com.jm", "label": "Caribbean"},
    {"tld": "co.uk", "label": "Warm Standard English"},
    {"tld": "us", "label": "Standard English"},
]

def speak_text(text, lang_code="en"):
    if not HAS_TTS:
        return None
    for accent in VOICE_ACCENT_CHAIN:
        try:
            buf = io.BytesIO()
            gTTS(text=text, lang=lang_code, tld=accent["tld"], slow=False).write_to_fp(buf)
            buf.seek(0)
            return buf.read()
        except Exception:
            continue
    return None

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
    st.session_state.pop("chat", None)

def switch_to_chat(session_id):
    if session_id != st.session_state.current_session_id:
        st.session_state.current_session_id = session_id
        st.session_state.pop("chat", None)

def ordered_session_ids():
    ids = list(st.session_state.chat_sessions.keys())
    ids.remove(st.session_state.current_session_id)
    ids.reverse()
    return [st.session_state.current_session_id] + ids

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------
def build_system_instruction(territory):
    territory_whatsapp = TERRITORY_WHATSAPP.get(territory, TERRITORY_WHATSAPP["Grenada"])
    return f"""
You are AquaAssist, a friendly virtual customer assistant for the National Water and Sewerage Authority (NAWASA) of Grenada, serving the {territory} territory.

LANGUAGE RULE:
Always reply in clear, professional Standard English. You must still fully UNDERSTAND Grenadian Creole if a customer writes in it, but your reply itself must always be in Standard English.

CONVERSATION STYLE:
Sound like an experienced, caring NAWASA customer service representative. Be warm, natural, and conversational. Empathize first, then guide. Keep track of already-provided info.
- When a customer describes a specific problem and gives at least a location, log it immediately using the log_water_report tool.
- If physical, ask for a photo using the camera button or "+" icon.
- NAWASA contact details: Phone (473) 440-2155, WhatsApp via {territory_whatsapp}, Website https://nawasa.gd/.
"""

# ---------------------------------------------------------------------------
# UI Style setup
# ---------------------------------------------------------------------------
if st.session_state.high_contrast:
    BRAND_PRIMARY, BRAND_HOVER, BRAND_ACCENT = "#00385E", "#00243D", "#0077CC"
    BRAND_BG, BRAND_BG_SOFT, BRAND_CARD, BRAND_TEXT = "#FFFFFF", "#F0F0F0", "#FFFFFF", "#000000"
elif st.session_state.dark_mode:
    BRAND_PRIMARY, BRAND_HOVER, BRAND_ACCENT = "#2E86C6", "#3D97D9", "#00AEEF"
    BRAND_BG, BRAND_BG_SOFT, BRAND_CARD, BRAND_TEXT = "#0B121C", "#141E2C", "#141E2C", "#E8F0FA"
else:
    BRAND_PRIMARY, BRAND_HOVER, BRAND_ACCENT = "#005A9C", "#0077CC", "#00AEEF"
    BRAND_BG, BRAND_BG_SOFT, BRAND_CARD, BRAND_TEXT = "#F6FBFF", "#EAF6FF", "#FFFFFF", "#33414F"

USER_BUBBLE_BG, USER_BUBBLE_TEXT = "#D9F3FF", "#003B5C"
ASSISTANT_BUBBLE_BORDER, ASSISTANT_BUBBLE_TEXT = f"{BRAND_PRIMARY}33", BRAND_TEXT

if st.session_state.dark_mode and not st.session_state.high_contrast:
    HOURS_BANNER_BG, HOURS_BANNER_BORDER, HOURS_BANNER_TEXT = "#0F2A3D", "#1D4A66", "#CFEBFF"
    HOURS_BANNER_SOON_BG, HOURS_BANNER_SOON_BORDER, HOURS_BANNER_SOON_TEXT = "#3A2C0E", "#6B4F13", "#FFE1A8"
else:
    HOURS_BANNER_BG, HOURS_BANNER_BORDER, HOURS_BANNER_TEXT = "#EAF6FF", "#B8DDF7", "#003B5C"
    HOURS_BANNER_SOON_BG, HOURS_BANNER_SOON_BORDER, HOURS_BANNER_SOON_TEXT = "#FFF6E5", "#F3CB80", "#7A4A00"

WHATSAPP_GREEN = "#25D366"
BASE_FONT_SIZE = "1.15rem" if st.session_state.large_text else "0.95rem"

logo_b64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()
avatar_b64 = ""
if os.path.exists(AVATAR_PATH):
    with open(AVATAR_PATH, "rb") as f:
        avatar_b64 = base64.b64encode(f.read()).decode()
nawasa_logo_b64 = ""
if logo_path.exists():
    with open(logo_path, "rb") as f:
        nawasa_logo_b64 = base64.b64encode(f.read()).decode()

def nawasa_logo_tag(size_px=56, css_class=""):
    if nawasa_logo_b64:
        return f'<img class="{css_class}" src="data:image/png;base64,{nawasa_logo_b64}" style="width:{size_px}px;height:{size_px}px;" />'
    return f'<span class="{css_class}" style="width:{size_px}px;height:{size_px}px;">NAWASA</span>'

_WAVE_BG_SVG = f"data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%201200%20200'%20preserveAspectRatio='none'%3E%3Cpath%20d='M0,60%20C220,130%20420,10%20600,70%20C780,130%20980,10%201200,70%20L1200,200%20L0,200%20Z'%20fill='{BRAND_HOVER.replace('#', '%23')}'%20fill-opacity='0.045'/%3E%3Cpath%20d='M0,80%20C200,140%20400,20%20600,80%20C800,140%201000,20%201200,80%20L1200,200%20L0,200%20Z'%20fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.06'/%3E%3Cpath%20d='M0,120%20C220,60%20420,180%20620,120%20C820,60%201020,180%201200,120%20L1200,200%20L0,200%20Z'%20fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.10'/%3E%3C/svg%3E"
_BLOBS_BG_SVG = f"data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%201600%20900'%3E%3Cdefs%3E%3Cfilter%20id='blur'%3E%3CfeGaussianBlur%20stdDeviation='95'/%3E%3C/filter%3E%3C/defs%3E%3Cellipse%20cx='180'%20cy='140'%20rx='360'%20ry='210'%20fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.24'%20filter='url(%23blur)'/%3E%3Cellipse%20cx='1420'%20cy='100'%20rx='300'%20ry='190'%20fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.20'%20filter='url(%23blur)'/%3E%3Cellipse%20cx='240'%20cy='780'%20rx='380'%20ry='230'%20fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.18'%20filter='url(%23blur)'/%3E%3Cellipse%20cx='800'%20cy='440'%20rx='460'%20ry='250'%20fill='{BRAND_HOVER.replace('#', '%23')}'%20fill-opacity='0.13'%20filter='url(%23blur)'/%3E%3C/svg%3E"
_BUBBLES_BG_SVG = "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%20500%20500'%3E%3Ccircle%20cx='60'%20cy='430'%20r='16'%20fill='white'%20fill-opacity='0.05'/%3E%3Ccircle%20cx='420'%20cy='300'%20r='14'%20fill='white'%20fill-opacity='0.05'/%3E%3C/svg%3E"

_ATMOSPHERE_CSS = f"""
.stApp {{ background-color: {BRAND_BG}; background-image: url("{_BLOBS_BG_SVG}"), url("{_WAVE_BG_SVG}"); background-repeat: no-repeat, repeat-x; background-position: center, bottom; background-size: 120% 120%, 1200px 200px; background-attachment: fixed; }}
.stApp::before {{ content: ""; position: fixed; inset: 0; background-image: url("{_BUBBLES_BG_SVG}"); z-index: -1; opacity: 0.5; }}
"""

CSS_BLOCK = f"""<style>
html, body, [class*="css"] {{ font-family: 'Poppins', sans-serif; font-size: {BASE_FONT_SIZE}; }}
{_ATMOSPHERE_CSS}
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: transparent !important; }}
.aqua-hero {{ background: linear-gradient(135deg, {BRAND_PRIMARY} 0%, {BRAND_HOVER} 100%); border-radius: 24px 24px 0 0; padding: 1.6rem; color: white; position: relative; overflow: hidden; }}
.aqua-card {{ background: {BRAND_CARD}cc; backdrop-filter: blur(14px); border-radius: 18px; padding: 1.1rem; margin-bottom: 1rem; border: 1px solid {BRAND_PRIMARY}22; }}
.aqua-section-label {{ font-size: 0.8rem; font-weight: 700; color: {BRAND_PRIMARY}; text-transform: uppercase; margin: 1.4rem 0 0.6rem 0; }}
.whatsapp-btn {{ background-color: {WHATSAPP_GREEN}; color: white !important; padding: 0.55rem 1rem; border-radius: 999px; text-decoration: none; font-weight: 700; display: block; text-align: center; }}
.aqua-primary-btn button {{ background-color: {BRAND_PRIMARY} !important; color: white !important; border: none !important; }}
[data-testid="stChatMessage"] {{ border-radius: 18px; backdrop-filter: blur(8px); }}
</style>"""

st.markdown('<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">', unsafe_allow_html=True)
st.markdown(CSS_BLOCK, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# AUTHENTICATION GATE
# ---------------------------------------------------------------------------
if not st.session_state.auth_done:
    st.markdown('<div style="max-width:460px; margin:auto; padding-top:4rem;">', unsafe_allow_html=True)
    st.markdown(f'<div style="text-align:center;">{nawasa_logo_tag(72)}<h2>AquaAssist</h2></div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.session_state.territory = st.selectbox("Select Territory", TERRITORIES)
    st.session_state.api_key = st.text_input("API Key", type="password")
    if st.button("Start Chatting", use_container_width=True):
        if st.session_state.api_key:
            st.session_state.auth_done = True
            st.rerun()
    st.markdown('</div></div>', unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH)
    mode = st.radio("Mode", ["💬 Customer Portal", "🔐 Staff Portal"])
    if mode == "💬 Customer Portal":
        if st.button("＋ New Chat", use_container_width=True):
            start_new_chat()
            st.rerun()
    st.divider()
    st.markdown(f'<a href="{WHATSAPP_LINK}" class="whatsapp-btn">Chat on WhatsApp</a>', unsafe_allow_html=True)
    if st.button("Sign Out"):
        st.session_state.auth_done = False
        st.rerun()

# ---------------------------------------------------------------------------
# STAFF PORTAL (Integrated Analytics)
# ---------------------------------------------------------------------------
if mode == "🔐 Staff Portal":
    st.title("Staff Portal")
    if "staff_authed" not in st.session_state: st.session_state.staff_authed = False
    if not st.session_state.staff_authed:
        pwd = st.text_input("Passcode", type="password")
        if st.button("Login"):
            if pwd == STAFF_PASSCODE:
                st.session_state.staff_authed = True
                st.rerun()
        st.stop()

    reports_df = load_reports()
    if reports_df.empty:
        st.info("No reports yet.")
    else:
        st.metric("Total Reports", len(reports_df))
        
        # Display Status Summary
        status_counts = reports_df["status"].value_counts().to_dict()
        status_cols = st.columns(len(STATUS_STAGES))
        for col, stage in zip(status_cols, STATUS_STAGES):
            col.metric(stage, status_counts.get(stage, 0))

        # --- INTEGRATED ANALYTICS SECTION ---
        render_staff_analytics(reports_df, GRENADA_PARISHES)

        # Map Section
        st.markdown(f'<div class="aqua-section-label">{t("staff_map_label")}</div>', unsafe_allow_html=True)
        if HAS_MAP:
            m = folium.Map(location=GRENADA_CENTER, zoom_start=11)
            for _, r in reports_df.iterrows():
                c = parse_report_coords(r.get("location", ""))
                if c: folium.Marker(c, popup=f"{r['reference']}: {r['status']}").add_to(m)
            st_folium(m, height=400, use_container_width=True)
        
        # Data Editor
        st.data_editor(reports_df, use_container_width=True)
    st.stop()

# ---------------------------------------------------------------------------
# CUSTOMER PORTAL
# ---------------------------------------------------------------------------
if "active_portal_tab" not in st.session_state: st.session_state.active_portal_tab = "chat"
tabs = st.columns(5)
for col, key in zip(tabs, ["chat", "report", "faq", "history", "settings"]):
    if col.button(key.title(), use_container_width=True):
        st.session_state.active_portal_tab = key
        st.rerun()

active_tab = st.session_state.active_portal_tab

# Chat UI Logic
if active_tab == "chat":
    st.markdown('<div class="aqua-hero"><h1>AquaAssist</h1><p>NAWASA Virtual Assistant</p></div>', unsafe_allow_html=True)
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("audio"): st.audio(msg["audio"])

    if prompt := st.chat_input("Ask about your water service..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Typing..."):
                # Simplified chat logic for this code block
                client = genai.Client(api_key=st.session_state.api_key)
                response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
                full_reply = response.text
                st.markdown(full_reply)
                
                audio = None
                if st.session_state.voice_replies:
                    audio = speak_text(full_reply)
                    if audio: st.audio(audio)
                    
                st.session_state.messages.append({"role": "assistant", "content": full_reply, "audio": audio})

elif active_tab == "report":
    st.header("Report an Issue")
    with st.form("report_form"):
        r_name = st.text_input("Name")
        r_phone = st.text_input("Phone")
        r_loc = st.text_input("Location")
        r_type = st.selectbox("Issue Type", ["Leak", "No Water", "Other"])
        r_desc = st.text_area("Details")
        if st.form_submit_button("Submit"):
            ref = save_report(r_name, r_phone, r_loc, r_type, r_desc)
            st.success(f"Submitted! Reference: {ref}")

elif active_tab == "faq":
    st.header("FAQs")
    for item in FAQS:
        with st.expander(item["q"]): st.write(item["a"])

elif active_tab == "history":
    st.header("Chat History")
    for m in st.session_state.messages:
        st.write(f"**{m['role'].title()}**: {m['content']}")

elif active_tab == "settings":
    st.header("Settings")
    st.session_state.dark_mode = st.toggle("Dark Mode", value=st.session_state.dark_mode)
    st.session_state.voice_replies = st.toggle("Voice Replies", value=st.session_state.voice_replies)
    if st.button("Apply Changes"): st.rerun()

st.markdown('<div style="text-align:center; padding:2rem; opacity:0.6;">Powered by NAWASA</div>', unsafe_allow_html=True)
