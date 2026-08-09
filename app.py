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
    assets/aquaassist_avatar.png (chat-bubble avatar — a blue/aqua water-drop
                                   AI assistant with a thin dashed "orbit"
                                   ring, generated to match the app's theme;
                                   see AVATAR_PATH)
    assets/user_avatar.png.jpg (the customer's chat-bubble avatar — used
                                 verbatim, never regenerated or modified;
                                 see USER_AVATAR_PATH)
    assets/nawasa_logo.png    (the official NAWASA authority logo, shown on
                                the login screen, header, and dashboard.)
    .streamlit/config.toml
    data/reports.csv          (auto-created, and auto-migrated if its schema
                                is missing a column added in a later update)
    data/notifications.csv    (auto-created)
    attachments/              (auto-created, uploaded report files + chat attachments)

BEFORE DEPLOYING:
    STAFF_PASSCODE -> replace "changeme123" below, or set as env var / Streamlit secret

CONFIG VIA ENV VARS OR STREAMLIT SECRETS:
    All of GEMINI_API_KEY, STAFF_PASSCODE, PINECONE_API_KEY, PINECONE_INDEX_NAME,
    and PINECONE_NAMESPACE can be set either as real OS environment variables
    (os.environ) OR via Streamlit Cloud's Settings -> Secrets panel / a local
    .streamlit/secrets.toml file (st.secrets). Both are checked, with
    os.environ taking priority if both happen to be set. On Streamlit
    Community Cloud, use the Secrets panel — plain TOML key = "value" pairs,
    e.g.:
        GEMINI_API_KEY = "your-real-key"
        PINECONE_API_KEY = "your-real-key"
        PINECONE_INDEX_NAME = "your-index-name"

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

OFFICE HOURS UX: office-open status is always labeled "Office Open" (never
just "Open now") throughout the UI. Starting 30 minutes before closing
time, the status pill, sidebar caption, and Chat tab both switch to an
amber "closing soon" state with a live countdown so customers know to call
or WhatsApp before staff go home for the day — see get_business_hours_status()
and the "closing_soon" / "minutes_until_close" fields it returns.

VISUAL DESIGN NOTE (redesign pass): the background is now a deliberately
layered "inside clear, sunlit water" environment rather than a flat color
or a photographic ocean image — see _WAVE_BG_SVG / _BLOBS_BG_SVG /
_BUBBLES_BG_SVG / _LIGHT_RAYS_SVG / _NOISE_SVG and the .stApp CSS rules.
Each layer is independent (base gradient wash, slow-drifting abstract
current blobs, soft light-ray shafts from the top, a faint bubble field,
and a barely-visible grain texture) so the composition reads as intentional
depth rather than a single gradient, while everything still degrades
gracefully in high-contrast mode (which drops all decorative layers for
maximum legibility). Content surfaces (cards, chat bubbles, the hero) use
selective glassmorphism — translucent, blurred, softly bordered — so they
read as floating above the water rather than sitting on top of a photo.

The chat avatar (assets/aquaassist_avatar.png) carries the same accent
color and a thin dashed "AI orbit" ring, which the CSS echoes as a soft
glow behind the hero logo and message avatars — this recurring ring motif
is the app's one signature visual detail; everything else stays quiet and
card-based on purpose. The customer's own chat avatar is
assets/user_avatar.png.jpg, used exactly as provided (never regenerated),
with only CSS framing (circular clip, subtle ring/shadow) applied around
it — see USER_AVATAR_PATH.
"""

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
    # Optional — enables the "closing soon" countdown to tick down on its
    # own every 60 seconds without the customer needing to click anything.
    # Without this package the countdown is still accurate on every page
    # interaction (any click, message, or tab switch), it just won't
    # self-refresh on a timer.
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

try:
    # Optional — powers NAWASA knowledge-base retrieval (see below).
    # pip install pinecone
    from pinecone import Pinecone
    HAS_PINECONE = True
except Exception:
    # Broad except (not just ImportError): if `pinecone-client` and `pinecone`
    # both end up installed in the same environment, the `pinecone` package
    # raises a plain Exception (not ImportError) on import to warn about the
    # rename. We don't want a stale/conflicting environment to take down the
    # whole app — just disable knowledge-base retrieval and carry on, exactly
    # like any other missing optional dependency here.
    HAS_PINECONE = False

# ---------------------------------------------------------------------------
# Config helper — checks a real OS env var first, then falls back to
# Streamlit secrets (works both locally with .streamlit/secrets.toml and on
# Streamlit Community Cloud's Settings -> Secrets panel). Never raises even
# if no secrets.toml exists at all.
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

# ---------------------------------------------------------------------------
# Pinecone knowledge retrieval — OPTIONAL. If PINECONE_API_KEY /
# PINECONE_INDEX_NAME aren't set, or `pinecone` isn't installed, the app
# just skips retrieval and answers using build_system_instruction()/FAQS
# only, exactly like before.
#
# PINECONE_INDEX_NAME -> set this to the EXACT index name you created
# (e.g. "aquaassist-nawasa").
# PINECONE_NAMESPACE  -> leave "" unless you upserted into a namespace.
#
# Handles BOTH common Pinecone setups automatically:
#   Path A: integrated/hosted embedding index (you upserted plain text and
#           let Pinecone embed it — this is the default quickstart flow).
#   Path B: an index you embedded yourself (e.g. with Gemini's
#           text-embedding-004) before upserting.
# ---------------------------------------------------------------------------
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
    """Searches Pinecone for NAWASA knowledge relevant to what the customer
    just asked, and returns a short reference block to ground the AI's
    reply. Returns "" on any failure — retrieval is never fatal, the bot
    just falls back to its built-in facts."""
    index = get_pinecone_index()
    if index is None or not query_text:
        return ""

    # Path A: integrated/hosted embedding index (e.g. Pinecone's own
    # "quickstart" wizard, where you upserted plain text records).
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

    # Path B: self-embedded vectors (Gemini text-embedding-004)
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
# Chat-bubble-only avatar. Kept separate from LOGO_PATH so the header, page
# icon, and sidebar can keep the main AquaAssist logo while only the chat
# message avatars use this image. Falls back to the aquaassist_avatar.png
# filename if the file isn't present at this path yet.
AVATAR_PATH = os.path.join("assets", "aquaassist_avatar.png")
# The customer's own chat-bubble avatar. This exact image is used verbatim —
# never regenerated, replaced, or edited — only lightweight CSS framing
# (circular clip, subtle ring/shadow) is applied around it in the chat UI.
# Falls back to a plain emoji if the file isn't present on disk.
USER_AVATAR_PATH = os.path.join("assets", "user_avatar.png.jpg")
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
# Monday–Friday, 8:00 AM–4:00 PM, Grenada local time. Saturday and Sunday
# are always closed (weekends). NAWASA_HOLIDAYS lists official closure
# dates (YYYY-MM-DD) that are also treated as closed even if they fall on
# a business day — add/edit this list each year as NAWASA publishes its
# holiday schedule.
#
# CLOSING_SOON_WINDOW_MINUTES controls how far ahead of closing time the
# "closing soon" countdown UI (amber status pill, sidebar caption, and
# Chat tab banner) starts showing.
# ---------------------------------------------------------------------------
BUSINESS_HOURS_START = 8   # 8:00 AM
BUSINESS_HOURS_END = 16    # 4:00 PM
CLOSING_SOON_WINDOW_MINUTES = 60
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
    display when closed, and — when open — `closing_soon` (True once we're
    within CLOSING_SOON_WINDOW_MINUTES of BUSINESS_HOURS_END) and
    `minutes_until_close` (an int countdown) for display when open."""
    now = datetime.now(GRENADA_TZ)
    today_str = now.strftime("%Y-%m-%d")
    weekday_idx = now.weekday()  # Monday=0 ... Sunday=6
    is_weekend = weekday_idx >= 5  # Saturday(5) and Sunday(6) — NAWASA is closed weekends
    is_holiday = today_str in NAWASA_HOLIDAYS
    is_open_hour = BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END

    is_open = (not is_weekend) and (not is_holiday) and is_open_hour

    # Figure out the next business day (skipping Sat/Sun/holidays) for the
    # "reopens" message shown when closed.
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

    # Countdown to closing time — only meaningful while the office is open.
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

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
defaults = {
    "auth_done": False,            # True once the customer submits territory + API key
    "territory": "Grenada",
    "customer_name": "",
    "api_key": get_config("GEMINI_API_KEY", ""),
    "dark_mode": False,
    "high_contrast": False,
    "large_text": False,
    "voice_replies": HAS_TTS,
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

st.session_state.messages = st.session_state.chat_sessions[st.session_state.current_session_id]["messages"]

# ---------------------------------------------------------------------------
# Territories
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Grenada geography
# ---------------------------------------------------------------------------
GRENADA_PARISHES = [
    "St. George's (Capital area)", "St. Andrew's", "St. David's",
    "St. John's", "St. Mark's", "St. Patrick's", "Carriacou and Petite Martinique",
]
GRENADA_CENTER = (12.1165, -61.6790)

# Approximate parish center coordinates, used only to auto-suggest the
# nearest parish when a customer pins a location on the map or uses GPS —
# this is a closest-center heuristic, not an official boundary lookup, but
# it's accurate enough to save the customer from picking the parish by hand.
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
    """Returns the GRENADA_PARISHES entry whose approximate center is
    closest (straight-line distance) to the given coordinates. Grenada is
    small enough that this simple heuristic is good enough to auto-fill
    the Parish dropdown when a customer pins a spot on the map."""
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
# Outage announcements
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

# ---------------------------------------------------------------------------
# Email sending helper (Staff Portal — testing flow)
# ---------------------------------------------------------------------------
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
            attached a photo of the issue, assess how serious it looks; otherwise
            leave it "Unknown" rather than guessing from text alone.

    Returns:
        A confirmation message including the reference number for tracking.
    """
    reference = save_report(name, phone, location, issue_type, description, severity=severity)
    # Stashed so the calling Streamlit turn can render a polished report
    # card under the AI's reply instead of relying on the model to spell
    # the details out in plain text — see render_report_card().
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
            gTTS(text=text, lang=lang_code, tld=accent["tld"], slow=False).write_to_fp(buf)
            buf.seek(0)
            return buf.read()
        except Exception:
            continue
    return None

# ---------------------------------------------------------------------------
# Chat session helpers
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
Always reply in clear, professional Standard English, regardless of what language or dialect the customer writes in. You must still fully UNDERSTAND Grenadian Creole (patois) if a customer writes in it — correctly interpret their meaning and intent — but your reply itself must always be in Standard English. Never reply in Creole, patois, or any other language, even if asked to.

CONVERSATION STYLE:
Sound like an experienced, caring NAWASA customer service representative — not a generic AI chatbot. Be warm, natural, and conversational, never robotic or overly formal.
- Prefer natural phrasing over stiff, templated wording.
- Vary your wording across a conversation; avoid repeating the same stock phrases turn after turn.
- Greet customers naturally and maintain a friendly, professional tone throughout.
- Keep track of what's already been said in the conversation and don't ask the customer to repeat information they've already given you.
- When a customer reports a problem, show empathy first, then guide them calmly through the next steps.
- Keep responses concise, clear, and easy to understand.
- Your replies are frequently read aloud by text-to-speech, so favor calm, warm, empathetic phrasing that sounds natural when spoken.

Use the following facts to answer user questions:
- Help customers report water leaks by collecting the location and relevant details.
- Provide information about water supply issues and service interruptions.
- Help customers check for planned maintenance and scheduled outages.
- Explain the available methods for paying NAWASA bills.
- Provide NAWASA customer service contact information and transfer users to a representative when requested.
- If the issue is an emergency, advise the user to contact NAWASA immediately at (473) 440-2155.
- NAWASA's official contact details: Phone (473) 440-2155, WhatsApp via {territory_whatsapp} (this is the number for {territory}), Website https://nawasa.gd/.
- NAWASA's main office is now located on Lucas Street, St. George's (it moved from its former, over 150-year-old building on the Carenage). Sub-offices are located at Seaton James Street, Grenville; Lower Depradine Street, Gouyave; and additional sub-offices in Sauteurs, St. David's, and Grand Anse.
- When a customer describes a specific problem and gives at least a location, log it immediately using the log_water_report tool — do not tell the customer to fill out a separate form themselves.
- When a customer reports a visible physical issue (a leak, burst main, damaged hydrant, water quality concern, etc.), ask them to send a photo of it — they can upload an existing one via the "+" icon in the chat box, or tap the 📷 camera button next to the message box to take one on the spot. This helps our technicians assess severity and prepare before visiting. Ask for this naturally as part of your reply — don't make it a precondition for logging the report, and don't ask for a photo for issues that wouldn't have one (e.g. billing questions or no water supply with nothing to see).
- If the customer attaches a photo or video of the issue, look at it before calling log_water_report and set severity based on what you actually see.
- Use natural understanding, not keyword matching.

If a question is unrelated to NAWASA services, politely explain that you can only assist with NAWASA-related topics and invite the user to ask another water service question.
"""

# ---------------------------------------------------------------------------
# Brand palette
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

USER_BUBBLE_BG = "#D9F3FF"
USER_BUBBLE_TEXT = "#003B5C"
ASSISTANT_BUBBLE_BORDER = f"{BRAND_PRIMARY}33"
ASSISTANT_BUBBLE_TEXT = BRAND_TEXT
if st.session_state.dark_mode and not st.session_state.high_contrast:
    HOURS_BANNER_BG = "#0F2A3D"
    HOURS_BANNER_BORDER = "#1D4A66"
    HOURS_BANNER_TEXT = "#CFEBFF"
    HOURS_BANNER_SOON_BG = "#3A2C0E"
    HOURS_BANNER_SOON_BORDER = "#6B4F13"
    HOURS_BANNER_SOON_TEXT = "#FFE1A8"
else:
    HOURS_BANNER_BG = "#EAF6FF"
    HOURS_BANNER_BORDER = "#B8DDF7"
    HOURS_BANNER_TEXT = "#003B5C"
    HOURS_BANNER_SOON_BG = "#FFF6E5"
    HOURS_BANNER_SOON_BORDER = "#F3CB80"
    HOURS_BANNER_SOON_TEXT = "#7A4A00"

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

# Fallback image for the hero header brand mark when aquaassist_logo.png
# isn't present — uses the chat avatar image instead of the plain water
# droplet emoji.
avatar_b64 = ""
if os.path.exists(AVATAR_PATH):
    with open(AVATAR_PATH, "rb") as f:
        avatar_b64 = base64.b64encode(f.read()).decode()

nawasa_logo_b64 = ""
if logo_path.exists():
    with open(logo_path, "rb") as f:
        nawasa_logo_b64 = base64.b64encode(f.read()).decode()

def nawasa_logo_tag(size_px=56, css_class=""):
    classes = f"aqua-nawasa-logo {css_class}".strip()
    if nawasa_logo_b64:
        return f'<img class="{classes}" src="data:image/png;base64,{nawasa_logo_b64}" style="width:{size_px}px;height:{size_px}px;" />'
    return f'<span class="aqua-login-nawasa-fallback {classes}" style="width:{size_px}px;height:{size_px}px;">NAWASA</span>'

# ---------------------------------------------------------------------------
# Layered water-environment background assets.
#
# The composition is built from independent SVG layers (rather than one
# gradient) so each piece of "inside clear, sunlit water" reads separately:
#   1. _WAVE_BG_SVG      — the bottom wave band (unchanged from before)
#   2. _BLOBS_BG_SVG      — large soft-blurred "abstract current" shapes,
#                            the main atmosphere layer, slowly drifting
#   3. _LIGHT_RAYS_SVG    — faint diagonal light shafts from the top,
#                            like sunlight filtering through clear water
#   4. _BUBBLES_BG_SVG    — a small, faint, slowly-drifting bubble field
#   5. _NOISE_SVG         — a barely-visible grain texture so the whole
#                            thing doesn't read as a flat digital gradient
# All layers are skipped in high-contrast mode for maximum legibility.
# ---------------------------------------------------------------------------
_WAVE_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%201200%20200'%20preserveAspectRatio='none'%3E"
    "%3Cpath%20d='M0,60%20C220,130%20420,10%20600,70%20C780,130%20980,10%201200,70%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_HOVER.replace('#', '%23')}'%20fill-opacity='0.045'/%3E"
    "%3Cpath%20d='M0,80%20C200,140%20400,20%20600,80%20C800,140%201000,20%201200,80%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.06'/%3E"
    "%3Cpath%20d='M0,120%20C220,60%20420,180%20620,120%20C820,60%201020,180%201200,120%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.10'/%3E"
    "%3C/svg%3E"
)

# Soft, blurred "ink/current in water" blobs — the main atmosphere layer
# behind the whole app. Real Gaussian-blurred, elongated organic shapes
# (not simple circles) in the brand's accent/primary/hover tones, scattered
# across a wide canvas and stretched to cover the viewport, so the page
# reads like it's sitting in gently diffused, moving water rather than on
# a flat color or a literal wave-repeat pattern.
_BLOBS_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%201600%20900'%3E"
    "%3Cdefs%3E%3Cfilter%20id='aquaBlobBlur'%20x='-50%25'%20y='-50%25'%20width='200%25'%20height='200%25'%3E"
    "%3CfeGaussianBlur%20stdDeviation='95'/%3E%3C/filter%3E%3C/defs%3E"
    f"%3Cellipse%20cx='180'%20cy='140'%20rx='360'%20ry='210'%20fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.24'%20filter='url(%23aquaBlobBlur)'%20transform='rotate(-18%20180%20140)'/%3E"
    f"%3Cellipse%20cx='1420'%20cy='100'%20rx='300'%20ry='190'%20fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.20'%20filter='url(%23aquaBlobBlur)'%20transform='rotate(14%201420%20100)'/%3E"
    f"%3Cellipse%20cx='240'%20cy='780'%20rx='380'%20ry='230'%20fill='{BRAND_PRIMARY.replace('#', '%23')}'%20fill-opacity='0.18'%20filter='url(%23aquaBlobBlur)'%20transform='rotate(10%20240%20780)'/%3E"
    f"%3Cellipse%20cx='1400'%20cy='800'%20rx='330'%20ry='210'%20fill='{BRAND_ACCENT.replace('#', '%23')}'%20fill-opacity='0.20'%20filter='url(%23aquaBlobBlur)'%20transform='rotate(-12%201400%20800)'/%3E"
    f"%3Cellipse%20cx='800'%20cy='440'%20rx='460'%20ry='250'%20fill='{BRAND_HOVER.replace('#', '%23')}'%20fill-opacity='0.13'%20filter='url(%23aquaBlobBlur)'/%3E"
    "%3C/svg%3E"
)

# Faint diagonal light shafts, like sunlight slanting down through clear
# water. Kept extremely soft (low opacity, wide feathered edges) so it
# reads as ambient light rather than a spotlight or a UI element.
_LIGHT_RAYS_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%201000%201000'%3E"
    "%3Cdefs%3E%3ClinearGradient%20id='aquaRayFade'%20x1='0'%20y1='0'%20x2='0'%20y2='1'%3E"
    "%3Cstop%20offset='0%25'%20stop-color='%23FFFFFF'%20stop-opacity='0.5'/%3E"
    "%3Cstop%20offset='100%25'%20stop-color='%23FFFFFF'%20stop-opacity='0'/%3E"
    "%3C/linearGradient%3E%3C/defs%3E"
    "%3Cg%20fill='url(%23aquaRayFade)'%3E"
    "%3Cpolygon%20points='120,0%20260,0%20-40,900%20-220,900'/%3E"
    "%3Cpolygon%20points='430,0%20530,0%20260,900%20130,900'/%3E"
    "%3Cpolygon%20points='760,0%20890,0%20620,900%20470,900'/%3E"
    "%3C/g%3E%3C/svg%3E"
)

# Very light, slow-drifting bubble/particle field for the main app background.
# Kept deliberately faint (low opacity, large tile, slow animation) so it
# reads as ambient texture behind the existing content rather than a busy
# pattern — per the "subtle, premium, not a huge ocean photo" brief.
def _bubble(cx_, cy_, r_, opacity, color):
    c = color.replace('#', '%23')
    return (f"%3Ccircle%20cx='{cx_}'%20cy='{cy_}'%20r='{r_}'%20fill='{c}'%20fill-opacity='{opacity}'/%3E"
             f"%3Ccircle%20cx='{cx_ - r_*0.35}'%20cy='{cy_ - r_*0.35}'%20r='{r_*0.28}'%20fill='%23FFFFFF'%20fill-opacity='{opacity*1.6}'/%3E")

_BUBBLES_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%20500%20500'%3E"
    + _bubble(60, 430, 16, 0.05, BRAND_ACCENT)
    + _bubble(150, 140, 10, 0.045, BRAND_PRIMARY)
    + _bubble(260, 360, 22, 0.04, BRAND_ACCENT)
    + _bubble(340, 90, 8, 0.05, BRAND_ACCENT)
    + _bubble(420, 300, 14, 0.045, BRAND_PRIMARY)
    + _bubble(460, 460, 11, 0.05, BRAND_ACCENT)
    + _bubble(40, 220, 7, 0.045, BRAND_PRIMARY)
    + _bubble(200, 470, 9, 0.04, BRAND_ACCENT)
    + "%3C/svg%3E"
)

# Barely-visible grain, purely so the large blurred gradients above don't
# read as a flat digital wash. Kept to a tiny, near-invisible opacity.
_NOISE_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%20160%20160'%3E%3Cfilter%20id='aquaGrain'%3E"
    "%3CfeTurbulence%20type='fractalNoise'%20baseFrequency='0.9'%20numOctaves='2'%20stitchTiles='stitch'/%3E"
    "%3CfeColorMatrix%20type='matrix'%20values='0%200%200%200%200%20"
    "0%200%200%200%200%200%200%200%200%200%200%200%200%200.02%200'/%3E"
    "%3C/filter%3E%3Crect%20width='100%25'%20height='100%25'%20filter='url(%23aquaGrain)'/%3E%3C/svg%3E"
)

if st.session_state.high_contrast:
    # High contrast mode intentionally skips all decorative texture — flat
    # background only, to keep contrast and legibility maximized.
    _ATMOSPHERE_CSS = f"""
.stApp {{ background-color: {BRAND_BG}; }}
"""
else:
    _ATMOSPHERE_CSS = f"""
.stApp {{
background-color: {BRAND_BG};
background-image:
radial-gradient(ellipse 900px 500px at 50% -10%, {BRAND_ACCENT}22 0%, transparent 60%),
url("{_LIGHT_RAYS_SVG}"),
url("{_BLOBS_BG_SVG}"),
linear-gradient(180deg, {BRAND_BG_SOFT} 0%, {BRAND_BG} 45%),
url("{_WAVE_BG_SVG}");
background-repeat: no-repeat, no-repeat, no-repeat, no-repeat, repeat-x;
background-position: top, top, 50% 50%, top, bottom;
background-size: 100% 100%, 100% 70%, 120% 120%, 100% 420px, 1200px 200px;
background-attachment: fixed, fixed, fixed, fixed, fixed;
animation: aquaBlobDrift 46s ease-in-out infinite;
position: relative;
}}
@keyframes aquaBlobDrift {{
0% {{ background-position: top, top, 48% 47%, top, bottom; }}
50% {{ background-position: top, top, 53% 53%, top, bottom; }}
100% {{ background-position: top, top, 48% 47%, top, bottom; }}
}}
@keyframes aquaBubbleDrift {{
from {{ background-position: 0px 0px; }}
to {{ background-position: -500px -900px; }}
}}
@keyframes aquaRayDrift {{
0%, 100% {{ opacity: 0.55; transform: translateX(0); }}
50% {{ opacity: 0.85; transform: translateX(14px); }}
}}
.stApp::before {{
content: "";
position: fixed;
inset: 0;
background-image: url("{_BUBBLES_BG_SVG}");
background-repeat: repeat;
background-size: 500px 500px;
animation: aquaBubbleDrift 70s linear infinite;
pointer-events: none;
z-index: -1;
}}
.stApp::after {{
content: "";
position: fixed;
inset: 0;
background:
url("{_NOISE_SVG}"),
radial-gradient(ellipse 1200px 700px at 50% 0%, transparent 55%, {BRAND_BG}55 100%);
background-repeat: repeat, no-repeat;
background-size: 160px 160px, 100% 100%;
pointer-events: none;
z-index: -1;
}}
"""

CSS_BLOCK = f"""<style>
html, body, [class*="css"] {{
/* Emoji fallback fonts appended after Poppins/Inter — those two fonts
   have no emoji glyphs, so without an explicit emoji font in the stack
   some browsers fall back to a flat/monochrome glyph instead of full
   color emoji (this is what was making reaction icons, quick-action
   icons, etc. look colorless). */
font-family: 'Poppins', 'Inter', 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', 'Segoe UI Symbol', sans-serif;
font-size: {BASE_FONT_SIZE};
}}
{_ATMOSPHERE_CSS}
/* ---------------------------------------------------------------------
   Make every Streamlit wrapper between the true page root and our own
   content transparent. Streamlit's own theme paints an opaque background
   on these inner containers (stAppViewContainer / stMain / the main
   block wrapper), which otherwise sits ON TOP of the layered water
   background declared on .stApp above and hides it completely — this is
   the actual reason the background could disappear even though the
   .stApp rules were correct. Every testid Streamlit has used for this
   wrapper across recent versions is covered here defensively.
   ------------------------------------------------------------------- */
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stBottomBlockContainer"],
section.main,
.main {{
background: transparent !important;
background-color: transparent !important;
background-image: none !important;
}}
::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: {BRAND_BG}; }}
::-webkit-scrollbar-thumb {{ background: {BRAND_PRIMARY}55; border-radius: 10px; }}
::-webkit-scrollbar-thumb:hover {{ background: {BRAND_PRIMARY}88; }}
@keyframes aquaFadeUp {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes aquaPulseRing {{ 0% {{ box-shadow: 0 0 0 0 rgba(37, 211, 102, 0.55); }} 70% {{ box-shadow: 0 0 0 14px rgba(37, 211, 102, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(37, 211, 102, 0); }} }}
@keyframes aquaPop {{ 0% {{ opacity: 0; transform: scale(0.92) translateY(8px); }} 60% {{ opacity: 1; transform: scale(1.01) translateY(0); }} 100% {{ opacity: 1; transform: scale(1) translateY(0); }} }}
@keyframes aquaDotBounce {{ 0%, 80%, 100% {{ transform: translateY(0); opacity: 0.5; }} 40% {{ transform: translateY(-5px); opacity: 1; }} }}
@keyframes aquaOrbitGlow {{ 0%, 100% {{ opacity: 0.55; }} 50% {{ opacity: 0.95; }} }}
@keyframes aquaOnlineDotPulse {{ 0%, 100% {{ box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.5); }} 70% {{ box-shadow: 0 0 0 6px rgba(52, 211, 153, 0); }} }}
* {{ scroll-behavior: smooth; }}
.aqua-page {{ animation: aquaFadeUp 0.35s ease-out; }}
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
position: absolute; inset: 0;
background-image: radial-gradient(rgba(255,255,255,0.10) 1.4px, transparent 1.4px);
background-size: 18px 18px; opacity: 0.5; z-index: 1; pointer-events: none;
}}
.aqua-hero-content {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; position: relative; z-index: 2; animation: aquaFadeUp 0.5s ease-out; }}
.aqua-hero-brand {{ display: flex; align-items: center; gap: 0.85rem; min-width: 0; }}
.aqua-hero-brand {{ position: relative; }}
.aqua-hero-brand::before {{
content: ""; position: absolute; left: -6px; top: 50%; transform: translateY(-50%);
width: 72px; height: 72px; border-radius: 50%;
background: radial-gradient({BRAND_ACCENT}55 0%, transparent 70%);
animation: aquaOrbitGlow 3.4s ease-in-out infinite; pointer-events: none; z-index: 0;
}}
.aqua-hero img {{ width: 60px; height: 60px; border-radius: 50%; background: #FFFFFF; padding: 5px; box-shadow: 0 4px 14px rgba(0,0,0,0.22); flex-shrink: 0; position: relative; z-index: 1; }}
.aqua-hero-nawasa-badge {{ width: 52px; height: 52px; border-radius: 50%; background: #FFFFFF; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 14px rgba(0,0,0,0.22); flex-shrink: 0; overflow: hidden; padding: 4px; box-sizing: border-box; }}
.aqua-hero-nawasa-badge img {{ width: 100%; height: 100%; object-fit: contain; }}
.aqua-hero-title {{ font-size: 1.7rem; font-weight: 800; color: #FFFFFF; line-height: 1.15; letter-spacing: -0.02em; }}
.aqua-hero-subtitle {{ font-size: 0.92rem; color: rgba(255,255,255,0.9); font-weight: 500; }}
.aqua-hero-online {{ display: inline-flex; align-items: center; gap: 0.35rem; margin-top: 0.35rem; font-size: 0.72rem; font-weight: 600; color: rgba(255,255,255,0.92); }}
.aqua-hero-online-dot {{ width: 8px; height: 8px; border-radius: 50%; background: #34D399; box-shadow: 0 0 0 2px rgba(255,255,255,0.5); animation: aquaOnlineDotPulse 2.2s infinite; flex-shrink: 0; }}
.aqua-hero-status {{ display: inline-flex; align-items: center; gap: 0.35rem; margin-top: 0.45rem; padding: 0.2rem 0.65rem; border-radius: 999px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.02em; background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.28); color: #FFFFFF; }}
.aqua-hero-status-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
.aqua-hero-status-open .aqua-hero-status-dot {{ background: #34D399; box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.35); }}
.aqua-hero-status-soon .aqua-hero-status-dot {{ background: #F59E0B; box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.35); animation: aquaPulseRing 2.5s infinite; }}
.aqua-hero-status-closed .aqua-hero-status-dot {{ background: #FBBF6B; box-shadow: 0 0 0 3px rgba(251, 191, 107, 0.3); }}
.aqua-wave {{ position: absolute; bottom: -2px; left: 0; width: 100%; line-height: 0; z-index: 1; }}
.aqua-wave-fill {{ fill: {BRAND_BG}; }}
.aqua-card {{
background: {BRAND_CARD}cc;
backdrop-filter: blur(14px) saturate(1.4);
-webkit-backdrop-filter: blur(14px) saturate(1.4);
border-radius: 18px; padding: 1.1rem 1.3rem; margin-bottom: 1rem;
box-shadow: 0 8px 28px rgba(0, 90, 156, 0.10), inset 0 1px 0 rgba(255,255,255,0.35);
border: 1px solid {BRAND_PRIMARY}22; animation: aquaFadeUp 0.4s ease-out; color: {BRAND_TEXT};
}}
.aqua-section-label {{ display: flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; font-weight: 700; color: {BRAND_PRIMARY}; text-transform: uppercase; letter-spacing: 0.06em; margin: 1.4rem 0 0.6rem 0; }}
.aqua-contact-row {{ display: flex; gap: 0.7rem; margin-bottom: 0.5rem; }}
.aqua-contact-card {{
flex: 1; background: {BRAND_CARD}b3; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
border: 1px solid {BRAND_PRIMARY}22; border-radius: 16px; padding: 0.7rem 0.6rem; min-height: 44px;
text-align: center; text-decoration: none !important; box-shadow: 0 2px 8px rgba(0, 90, 156, 0.06);
transition: all 0.18s ease-in-out;
}}
.aqua-contact-card:hover {{ transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0, 90, 156, 0.18); border-color: {BRAND_ACCENT}88; }}
.aqua-contact-icon {{ font-size: 1.3rem; display: block; margin-bottom: 0.2rem; }}
.aqua-contact-label {{ font-size: 0.72rem; font-weight: 700; color: {BRAND_TEXT}; text-transform: uppercase; letter-spacing: 0.04em; display: block; }}
.aqua-contact-value {{ font-size: 0.7rem; color: {BRAND_PRIMARY}; font-weight: 600; }}
.aqua-status-badge {{ display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; background: {BRAND_PRIMARY}18; color: {BRAND_PRIMARY}; }}
.aqua-faq-item {{
background: {BRAND_CARD}cc; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
border: 1px solid {BRAND_PRIMARY}22; border-radius: 14px; padding: 0.8rem 1rem; margin-bottom: 0.6rem;
color: {BRAND_TEXT}; transition: box-shadow 0.15s ease-in-out;
}}
.aqua-faq-item:hover {{ box-shadow: 0 4px 14px rgba(0, 114, 188, 0.1); }}
.aqua-faq-cat {{ font-size: 0.68rem; font-weight: 700; color: {BRAND_ACCENT}; text-transform: uppercase; letter-spacing: 0.05em; }}
[data-testid="stChatMessage"] {{
border-radius: 18px; padding: 0.75rem 1rem; margin-bottom: 0.75rem;
box-shadow: 0 4px 16px rgba(0, 90, 156, 0.10); animation: aquaFadeUp 0.3s ease-out;
border: 1px solid transparent; gap: 0.65rem; transition: box-shadow 0.15s ease-in-out;
backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
}}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"], [data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] {{ box-shadow: 0 0 0 2px {BRAND_CARD}, 0 0 0 3px {BRAND_PRIMARY}30; border-radius: 50%; overflow: hidden; }}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] {{ box-shadow: 0 0 0 2px {BRAND_CARD}, 0 0 0 3px {BRAND_ACCENT}55, 0 0 12px {BRAND_ACCENT}40; }}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] img {{ object-fit: cover; }}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] img {{ object-fit: cover; }}
[data-testid="stChatMessage"]:has(img[alt="assistant avatar"]), [data-testid="stChatMessageAvatarAssistant"] ~ div, div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {{ background: {BRAND_CARD}d9; border: 1px solid {ASSISTANT_BUBBLE_BORDER}; border-radius: 6px 18px 18px 18px; color: {ASSISTANT_BUBBLE_TEXT}; }}
[data-testid="stChatMessage"]:has(img[alt="assistant avatar"]) p, div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) p {{ color: {ASSISTANT_BUBBLE_TEXT}; }}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ background: {USER_BUBBLE_BG}e6; border: 1px solid {USER_BUBBLE_BG}; border-radius: 18px 6px 18px 18px; flex-direction: row-reverse; text-align: right; }}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p {{ color: {USER_BUBBLE_TEXT}; }}
[data-testid="stSpinner"] > div {{ display: flex; align-items: center; gap: 0.5rem; color: {BRAND_PRIMARY}; font-weight: 600; }}
[data-testid="stSpinner"] svg {{ display: none; }}
[data-testid="stSpinner"] > div::before {{
content: ""; display: inline-flex; width: 34px; height: 8px;
background-image: radial-gradient({BRAND_PRIMARY} 40%, transparent 41%), radial-gradient({BRAND_PRIMARY} 40%, transparent 41%), radial-gradient({BRAND_PRIMARY} 40%, transparent 41%);
background-size: 8px 8px; background-repeat: no-repeat; background-position: 0 center, 13px center, 26px center;
animation: aquaDotBounce 1.2s infinite ease-in-out;
}}
div.stButton > button {{ border-radius: 12px; border: 1px solid {BRAND_PRIMARY}30; background-color: {BRAND_CARD}e6; backdrop-filter: blur(6px); color: {BRAND_PRIMARY}; font-weight: 600; padding: 0.7rem 0.6rem; min-height: 44px; box-shadow: 0 2px 6px rgba(0, 90, 156, 0.06); transition: all 0.18s ease-in-out; }}
div.stButton > button:hover {{ border-color: {BRAND_HOVER}; color: {BRAND_HOVER}; background-color: {BRAND_BG_SOFT}; box-shadow: 0 6px 16px rgba(0, 90, 156, 0.16); transform: translateY(-2px); }}
div.stButton > button:focus-visible {{ outline: 2px solid {BRAND_ACCENT}; outline-offset: 2px; }}
div.stButton > button:active {{ transform: translateY(0px) scale(0.98); }}
.aqua-primary-btn button {{ background-color: {BRAND_PRIMARY} !important; color: #FFFFFF !important; border: none !important; }}
.aqua-primary-btn button:hover {{ background-color: {BRAND_HOVER} !important; color: #FFFFFF !important; }}
div[class*="st-key-aqua_nav_"] {{ box-sizing: border-box; }}
div[class*="st-key-aqua_nav_"] button {{
position: relative; box-sizing: border-box !important; font-size: 0.78rem !important;
min-height: 3.6rem !important; max-height: 3.6rem !important; height: 3.6rem !important;
width: 100% !important; min-width: 100% !important; max-width: 100% !important;
display: flex !important; align-items: center; justify-content: center; text-align: center;
white-space: normal; line-height: 1.15; padding: 0.35rem 0.2rem !important; overflow-wrap: break-word;
}}
div[class*="st-key-aqua_nav_"][class*="_active"] button {{ background-color: {BRAND_PRIMARY} !important; color: #FFFFFF !important; border-color: {BRAND_PRIMARY} !important; font-weight: 700 !important; box-shadow: 0 4px 14px rgba(0, 90, 156, 0.28) !important; transform: translateY(-1px); }}
div[class*="st-key-aqua_nav_"][class*="_active"] button:hover {{ background-color: {BRAND_HOVER} !important; color: #FFFFFF !important; }}
div[class*="st-key-aqua_nav_"][class*="_active"] button::after {{ content: ""; position: absolute; left: 50%; bottom: -6px; transform: translateX(-50%); width: 55%; height: 3px; border-radius: 3px; background-color: {BRAND_ACCENT}; }}
section[data-testid="stSidebar"] {{ background-color: {BRAND_CARD}e6; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); background-image: url("{_WAVE_BG_SVG}"); background-repeat: repeat-x; background-position: bottom; background-size: 900px 150px; border-right: 1px solid {BRAND_PRIMARY}22; }}
.aqua-sidebar-newchat button {{ background-color: {BRAND_PRIMARY} !important; color: #FFFFFF !important; border: none !important; width: 100%; font-weight: 700; }}
.aqua-sidebar-newchat button:hover {{ background-color: {BRAND_HOVER} !important; transform: none; }}
.aqua-history-btn button {{ text-align: left !important; justify-content: flex-start !important; background: transparent !important; box-shadow: none !important; border: none !important; padding: 0.4rem 0.3rem !important; font-weight: 500 !important; color: {BRAND_TEXT} !important; }}
.aqua-history-btn button:hover {{ background: {BRAND_BG_SOFT} !important; transform: none !important; box-shadow: none !important; color: {BRAND_PRIMARY} !important; }}
.aqua-history-active button {{ background: {BRAND_PRIMARY}14 !important; color: {BRAND_PRIMARY} !important; font-weight: 700 !important; }}
.whatsapp-float {{ position: fixed; bottom: 24px; right: 24px; z-index: 9999; background-color: {WHATSAPP_GREEN}; color: white !important; text-decoration: none !important; width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.6rem; box-shadow: 0 4px 16px rgba(37, 211, 102, 0.45); transition: transform 0.15s ease-in-out; animation: aquaPulseRing 2.5s infinite; }}
.whatsapp-float:hover {{ transform: scale(1.1); animation: none; }}
.whatsapp-btn {{ display: inline-flex; align-items: center; gap: 0.5rem; background-color: {WHATSAPP_GREEN}; color: white !important; text-decoration: none !important; padding: 0.55rem 1rem; border-radius: 999px; font-weight: 700; font-size: 0.9rem; width: 100%; justify-content: center; box-sizing: border-box; }}
.whatsapp-btn:hover {{ opacity: 0.9; }}
.aqua-login-wrap {{ max-width: min(460px, 94vw); width: 100%; margin: 0 auto; animation: aquaFadeUp 0.4s ease-out; }}
.aqua-login-header {{ display: flex; align-items: center; justify-content: center; gap: 0.6rem; padding: 1.6rem 0.5rem 1rem 0.5rem; text-align: center; }}
.aqua-login-header-left, .aqua-login-header-right {{ display: none; }}
.aqua-login-header-center {{ flex: 1 1 auto; text-align: center; display: flex; flex-direction: column; align-items: center; }}
.aqua-nawasa-logo {{ display: block; margin: 0 auto 0.6rem auto; }}
.aqua-login-title {{ font-size: 1.6rem; font-weight: 800; color: {BRAND_TEXT}; letter-spacing: -0.02em; line-height: 1.1; }}
.aqua-login-subtitle {{ font-size: 0.85rem; color: {BRAND_PRIMARY}; font-weight: 500; }}
.aqua-login-card {{ margin-top: 0.3rem; }}
.aqua-demo-tag {{ display: inline-block; margin-top: 0.5rem; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; }}
.aqua-login-demo-tag {{ color: {BRAND_PRIMARY}; background: {BRAND_PRIMARY}14; border: 1px solid {BRAND_PRIMARY}30; }}
.aqua-hero-demo-tag {{ color: #FFFFFF; background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.28); }}
.aqua-mic-btn button {{ border-radius: 50% !important; width: 2.75rem !important; height: 2.75rem !important; min-height: 2.75rem !important; padding: 0 !important; font-size: 1.1rem !important; }}
[data-testid="stChatInput"] {{ border-radius: 20px; }}
[data-testid="stChatInput"] textarea {{ font-size: 0.95rem; padding-top: 0.65rem; padding-bottom: 0.65rem; }}
[data-testid="stChatInputContainer"] {{ background: {BRAND_CARD}d9 !important; backdrop-filter: blur(10px); border-radius: 20px !important; border: 1px solid {BRAND_PRIMARY}30 !important; box-shadow: 0 2px 10px rgba(0, 90, 156, 0.06); transition: box-shadow 0.15s ease-in-out, border-color 0.15s ease-in-out; }}
[data-testid="stChatInputContainer"]:focus-within {{ border-color: {BRAND_ACCENT} !important; box-shadow: 0 0 0 3px {BRAND_ACCENT}22; }}
button[data-testid="stChatInputSubmitButton"] {{ background-color: {BRAND_PRIMARY} !important; border-radius: 50% !important; color: #FFFFFF !important; position: relative; transition: background-color 0.15s ease-in-out, transform 0.15s ease-in-out; }}
button[data-testid="stChatInputSubmitButton"]:hover {{ background-color: {BRAND_HOVER} !important; transform: scale(1.06); }}
button[data-testid="stChatInputSubmitButton"] svg {{ fill: #FFFFFF !important; }}
button[data-testid="stChatInputSubmitButton"]::after {{ content: "💧"; position: absolute; top: -6px; right: -4px; font-size: 0.6rem; line-height: 1; filter: drop-shadow(0 1px 1px rgba(0,0,0,0.25)); }}
html, body {{ background-color: {BRAND_BG} !important; }}
:root, .stApp {{ --background-color: {BRAND_BG} !important; --secondary-background-color: {BRAND_BG_SOFT} !important; --text-color: {BRAND_TEXT} !important; }}
[data-testid*="Bottom"], [class*="bottom"] {{
background: {BRAND_BG} !important;
background-image: linear-gradient(180deg, {BRAND_BG_SOFT} 0%, {BRAND_BG} 100%), url("{_WAVE_BG_SVG}") !important;
background-repeat: no-repeat, repeat-x !important;
background-position: top, bottom !important;
background-size: 100% 100%, 1200px 200px !important;
}}
.aqua-login-dm-toggle {{ display: flex; justify-content: flex-end; margin-bottom: -0.4rem; }}
.aqua-login-dm-toggle [data-testid="stWidgetLabel"] p {{ font-size: 0.72rem !important; }}
/* In-chat typing indicator — three dots bouncing inside the assistant's
   own bubble background, so it reads as "AquaAssist is typing" rather
   than a generic page loader. */
.aqua-typing-bubble {{ display: flex; align-items: center; gap: 5px; padding: 0.15rem 0.1rem; }}
.aqua-typing-bubble span {{
display: inline-block; width: 8px; height: 8px; border-radius: 50%;
background: {BRAND_PRIMARY}; opacity: 0.6; animation: aquaDotBounce 1.1s infinite ease-in-out;
}}
.aqua-typing-bubble span:nth-child(2) {{ animation-delay: 0.15s; }}
.aqua-typing-bubble span:nth-child(3) {{ animation-delay: 0.3s; }}
/* Report confirmation card — shown under an AI reply that logged a report,
   or after a manual form submission, instead of a plain success banner. */
.aqua-report-card {{
background: linear-gradient(135deg, {BRAND_CARD}f2, {BRAND_BG_SOFT}f2);
backdrop-filter: blur(10px); border: 1px solid {BRAND_PRIMARY}2a; border-radius: 14px;
padding: 0.75rem 0.9rem; margin: 0.35rem 0 0.5rem 0; box-shadow: 0 4px 14px rgba(0,90,156,0.10);
animation: aquaPop 0.35s ease-out;
}}
.aqua-report-card-head {{ display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }}
.aqua-report-card-icon {{ font-size: 1.3rem; }}
.aqua-report-card-title {{ font-size: 0.78rem; font-weight: 700; color: {BRAND_TEXT}99; text-transform: uppercase; letter-spacing: 0.04em; }}
.aqua-report-card-ref {{ font-size: 1.05rem; font-weight: 800; color: {BRAND_PRIMARY}; letter-spacing: 0.02em; }}
.aqua-report-card-rows {{ display: flex; flex-direction: column; gap: 0.3rem; }}
.aqua-report-card-row {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; color: {BRAND_TEXT}; }}
.aqua-report-card-row span {{ color: {BRAND_TEXT}99; }}
/* Suggested follow-up chips — styled via the keyed wrapper container
   (div[class*="st-key-aqua_chip_wrap"]) so the rule reaches the actual
   button DOM node; raw st.markdown divs around a widget don't nest. */
div[class*="st-key-aqua_chip_wrap"] {{ margin: 0.2rem 0 0.6rem 0; }}
div[class*="st-key-aqua_chip_wrap"] button {{
border-radius: 999px !important; font-size: 0.78rem !important; min-height: 2.2rem !important;
padding: 0.3rem 0.8rem !important; background-color: {BRAND_PRIMARY}10 !important;
border: 1px solid {BRAND_PRIMARY}35 !important; color: {BRAND_PRIMARY} !important; font-weight: 600 !important;
}}
div[class*="st-key-aqua_chip_wrap"] button:hover {{ background-color: {BRAND_PRIMARY}22 !important; transform: translateY(-1px); }}
/* Reaction thumbs — full native emoji color always (overriding the
   generic button rule's forced text color, which is what was making
   these render flat/colorless), dimmed via opacity when unselected so
   the chosen reaction still stands out once picked. */
div[class*="st-key-aqua_react_up_"] button,
div[class*="st-key-aqua_react_down_"] button {{
background: transparent !important; border: 1px solid transparent !important; box-shadow: none !important;
padding: 0.1rem 0.5rem !important; min-height: 2rem !important; height: 2rem !important;
font-size: 1.15rem !important; color: initial !important; opacity: 0.45;
transition: opacity 0.15s ease-in-out, transform 0.15s ease-in-out;
}}
div[class*="st-key-aqua_react_up_"] button:hover,
div[class*="st-key-aqua_react_down_"] button:hover {{ opacity: 0.85; transform: scale(1.12); background: transparent !important; }}
div[class*="st-key-aqua_react_up_active"] button,
div[class*="st-key-aqua_react_down_active"] button {{
opacity: 1 !important; background: {BRAND_PRIMARY}14 !important; border-radius: 999px !important;
border: 1px solid {BRAND_PRIMARY}30 !important;
}}
/* Empty/first-load state polish — staggered fade/slide-in. Quick-action
   buttons are wrapped in a keyed container (div[class*="st-key-aqua_qa_wrap"])
   so nth-of-type targets each button's own Streamlit wrapper directly —
   two raw st.markdown calls around a widget do NOT nest in the real DOM,
   so this container approach is used instead of wrapping divs. */
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"] {{ opacity: 0; animation: aquaFadeUp 0.45s ease-out forwards; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(1) {{ animation-delay: 0ms; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(2) {{ animation-delay: 70ms; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(3) {{ animation-delay: 140ms; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(4) {{ animation-delay: 210ms; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(5) {{ animation-delay: 280ms; }}
div[class*="st-key-aqua_qa_wrap"] div[data-testid="stButton"]:nth-of-type(6) {{ animation-delay: 350ms; }}
.aqua-footer {{ text-align: center; font-size: 0.72rem; color: {BRAND_TEXT}99; padding: 0.9rem 0 0.3rem 0; letter-spacing: 0.02em; }}
.aqua-footer strong {{ color: {BRAND_PRIMARY}; font-weight: 700; }}
.aqua-hours-banner {{ display: flex; align-items: flex-start; gap: 0.55rem; background: {HOURS_BANNER_BG}; border: 1px solid {HOURS_BANNER_BORDER}; border-radius: 14px; padding: 0.65rem 0.9rem; margin-bottom: 0.85rem; color: {HOURS_BANNER_TEXT}; font-size: 0.8rem; line-height: 1.45; animation: aquaFadeUp 0.3s ease-out; }}
.aqua-hours-banner-icon {{ flex-shrink: 0; font-size: 0.95rem; line-height: 1.4; }}
.aqua-hours-banner-soon {{ background: {HOURS_BANNER_SOON_BG}; border-color: {HOURS_BANNER_SOON_BORDER}; color: {HOURS_BANNER_SOON_TEXT}; }}
[data-testid="stAlertContainer"] {{ border-radius: 16px !important; border: 1px solid transparent !important; box-shadow: 0 2px 12px rgba(0, 90, 156, 0.08); animation: aquaFadeUp 0.25s ease-out; }}
[data-testid="stAlertContainer"][data-baseweb="notification"] {{ padding: 0.85rem 1rem !important; }}
div[data-testid="stAlertContainer"]:has(svg[data-testid="stIconMaterial"]) {{ align-items: flex-start; }}
/* Alert boxes: card background + colored left accent (theme-aware) instead
   of Streamlit's baked-in light pastel backgrounds, which never adapted to
   dark mode and made alert text unreadable against a dark page. */
[data-testid="stAlertContainer"] {{ background-color: {BRAND_CARD} !important; border-left: 4px solid transparent !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stNotificationContentError"]) {{ border-left-color: #E5484D !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stNotificationContentSuccess"]) {{ border-left-color: #30A46C !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stNotificationContentWarning"]) {{ border-left-color: #F5A623 !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stNotificationContentInfo"]) {{ border-left-color: {BRAND_ACCENT} !important; }}
[data-testid="stNotificationContentError"],
[data-testid="stNotificationContentSuccess"],
[data-testid="stNotificationContentWarning"],
[data-testid="stNotificationContentInfo"] {{ color: {BRAND_TEXT} !important; }}

/* ---------------------------------------------------------------------
   Native Streamlit widget theming — none of these ever adapted to the
   dark_mode/high_contrast toggles before, so they stayed on Streamlit's
   baked-in light theme (white boxes, dark-gray labels) even with a dark
   page behind them, making everything hard to read in dark mode.
   ------------------------------------------------------------------- */
/* Widget labels (covers text_input, selectbox, text_area, number_input,
   date_input, file_uploader, radio, multiselect, toggle, checkbox — they
   all render their label through this one testid). */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p {{ color: {BRAND_TEXT} !important; }}
/* General body text Streamlit renders itself (captions, markdown, help
   text, metric labels) that isn't inside one of our own .aqua-* cards. */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {{ color: {BRAND_TEXT} !important; }}
/* Text/number/date input boxes and text areas. */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-baseweb="base-input"],
[data-baseweb="input"] {{ background-color: {BRAND_CARD} !important; color: {BRAND_TEXT} !important; border-color: {BRAND_PRIMARY}44 !important; }}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stNumberInput"] input::placeholder {{ color: {BRAND_TEXT}77 !important; }}
/* Selectbox / multiselect trigger box. */
[data-baseweb="select"] > div {{ background-color: {BRAND_CARD} !important; color: {BRAND_TEXT} !important; border-color: {BRAND_PRIMARY}44 !important; }}
[data-baseweb="select"] svg {{ fill: {BRAND_TEXT} !important; }}
/* Dropdown/popover menu (selectbox options, multiselect list) — this
   renders in a portal, so it needs its own unscoped rule. */
[data-baseweb="popover"] [data-baseweb="menu"] {{ background-color: {BRAND_CARD} !important; }}
[data-baseweb="menu"] li {{ color: {BRAND_TEXT} !important; }}
[data-baseweb="menu"] li:hover {{ background-color: {BRAND_BG_SOFT} !important; }}
/* Multiselect selected-item tags/chips. */
[data-baseweb="tag"] {{ background-color: {BRAND_PRIMARY}22 !important; color: {BRAND_TEXT} !important; }}
[data-baseweb="tag"] span {{ color: {BRAND_TEXT} !important; }}
/* Radio group (Customer Portal / Staff Portal switch, issue-type picker). */
[data-testid="stRadio"] label, [data-testid="stRadio"] label p {{ color: {BRAND_TEXT} !important; }}
/* File uploader dropzone. */
[data-testid="stFileUploaderDropzone"] {{ background-color: {BRAND_BG_SOFT} !important; border-color: {BRAND_PRIMARY}44 !important; }}
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small {{ color: {BRAND_TEXT} !important; }}
[data-testid="stFileUploaderFile"] {{ color: {BRAND_TEXT} !important; }}
/* Expander (report form, system instruction viewer). */
[data-testid="stExpander"] {{ background-color: {BRAND_CARD} !important; border: 1px solid {BRAND_PRIMARY}22 !important; border-radius: 14px !important; }}
[data-testid="stExpander"] summary {{ color: {BRAND_TEXT} !important; }}
[data-testid="stExpander"] svg {{ fill: {BRAND_TEXT} !important; }}
/* Toggle switch track (dark mode / high contrast / voice reply toggles). */
[data-testid="stToggle"] label div:first-child {{ background-color: {BRAND_BG_SOFT} !important; }}
/* Plain code/text blocks (used for the "view system instruction" panel). */
[data-testid="stText"], [data-testid="stCodeBlock"] {{ background-color: {BRAND_CARD} !important; color: {BRAND_TEXT} !important; }}
[data-testid="stText"] {{ border: 1px solid {BRAND_PRIMARY}22 !important; border-radius: 10px !important; padding: 0.6rem 0.8rem !important; }}
/* Progress bar track (report tracking status). */
[data-testid="stProgress"] > div > div {{ background-color: {BRAND_BG_SOFT} !important; }}
/* Data editor / dataframe (Staff Portal) — nudges the canvas grid toward a
   dark rendering when dark mode is on; full native dark theming of the
   grid isn't controllable purely via CSS. */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {{ color-scheme: {"dark" if st.session_state.dark_mode else "light"}; }}
html, body {{ width: 100%; height: 100%; margin: 0; }}
.stApp {{ min-height: 100vh; width: 100%; }}
#MainMenu, footer {{ visibility: hidden; height: 0; }}
header[data-testid="stHeader"] {{ background: transparent; height: 2.5rem; }}
header[data-testid="stHeader"] * {{ visibility: visible; }}
.block-container {{
padding-top: clamp(0.8rem, 2vw, 1.2rem); padding-bottom: clamp(0.6rem, 1.5vw, 1rem);
padding-left: clamp(0.6rem, 3vw, 1.5rem); padding-right: clamp(0.6rem, 3vw, 1.5rem);
width: 100% !important; max-width: min(720px, 96vw) !important; margin-left: auto !important; margin-right: auto !important; box-sizing: border-box;
}}
.aqua-hero-title, .aqua-dash-greeting {{ font-size: clamp(1.25rem, 4vw, 1.7rem); }}
.aqua-hero-subtitle, .aqua-dash-subtitle {{ font-size: clamp(0.8rem, 2.2vw, 0.92rem); }}
.aqua-login-title {{ font-size: clamp(1.3rem, 4.5vw, 1.6rem); }}
.aqua-contact-row {{ flex-wrap: wrap; }}
.aqua-contact-card {{ min-width: 90px; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 4px; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ border-radius: 12px 12px 0 0; font-weight: 600; }}
@media (max-width: 360px) {{
.block-container {{ padding-left: 0.45rem; padding-right: 0.45rem; }}
.aqua-hero {{ padding: 1.2rem 1.1rem 3rem 1.1rem; }}
div[class*="st-key-aqua_nav_"] button {{ font-size: 0.68rem !important; padding: 0.25rem 0.1rem !important; }}
}}
@media (min-width: 900px) {{
.block-container {{ padding-top: 2rem; padding-bottom: 1.8rem; }}
.aqua-hero {{ padding: 2.1rem 2.2rem 3.8rem 2.2rem; }}
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
# LOGIN / WELCOME GATE
# ---------------------------------------------------------------------------
if not st.session_state.auth_done:
    st.markdown('<div class="aqua-login-wrap">', unsafe_allow_html=True)

    _login_spacer, _login_dm_col = st.columns([0.78, 0.22])
    with _login_dm_col:
        st.markdown('<div class="aqua-login-dm-toggle">', unsafe_allow_html=True)
        _dm_before = st.session_state.dark_mode
        st.session_state.dark_mode = st.toggle(
            "🌙 Dark", value=st.session_state.dark_mode, key="login_dark_mode_toggle",
            help="Preview AquaAssist in dark mode",
        )
        st.markdown('</div>', unsafe_allow_html=True)
        # CSS_BLOCK (built from BRAND_* colors, which read st.session_state.dark_mode)
        # is generated earlier in this same script run, before this toggle
        # exists — so on the run where the click happens, the page has
        # already rendered with the OLD colors. An explicit rerun forces one
        # more pass so the very next paint picks up the new value; without
        # this the toggle looked unresponsive and needed a second, unrelated
        # interaction elsewhere on the page before it visibly took effect.
        if st.session_state.dark_mode != _dm_before:
            st.rerun()

    st.markdown(f"""<div class="aqua-login-header">
<div class="aqua-login-header-center">
{nawasa_logo_tag(72)}
<div class="aqua-login-title">AquaAssist</div>
<div class="aqua-login-subtitle">Your smart water support assistant</div>
<div class="aqua-demo-tag aqua-login-demo-tag">Demo - Developed by Sub Pod-1</div>
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

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
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
    if _sidebar_hours["is_open"] and _sidebar_hours["closing_soon"]:
        st.caption(f"🟡 Office Open — closing in {_sidebar_hours['minutes_until_close']} min · Mon–Fri, 8:00 AM – 4:00 PM")
    elif _sidebar_hours["is_open"]:
        st.caption("🟢 Office Open · Mon–Fri, 8:00 AM – 4:00 PM")
    else:
        st.caption(f"🟠 Offices Closed — reopens {_sidebar_hours['reopens_label']} · Mon–Fri, 8:00 AM – 4:00 PM")

    with st.expander("⚙️ Territory & API key"):
        st.selectbox(
            "NAWASA territory", TERRITORIES,
            index=TERRITORIES.index(st.session_state.territory) if st.session_state.territory in TERRITORIES else 0,
            key="sidebar_territory_select",
            on_change=_sync_territory,
            args=("sidebar_territory_select", "settings_territory_select"),
        )

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
        st.caption("🔊 Voice replies: enabled by default (Caribbean-leaning voice, Standard English fallback)")
    else:
        st.caption("🔊 Voice replies: not installed (add `gtts` to requirements.txt to enable)")
    if HAS_AUTOREFRESH:
        st.caption("⏳ Live closing-soon countdown: enabled")
    else:
        st.caption("⏳ Live closing-soon countdown: not installed (add `streamlit-autorefresh` to requirements.txt for auto-ticking; the count is still correct on every interaction without it)")
    if get_pinecone_index() is not None:
        st.caption("📚 Knowledge base retrieval (Pinecone): enabled")
    elif HAS_PINECONE:
        st.caption("📚 Knowledge base retrieval: installed, but PINECONE_API_KEY / PINECONE_INDEX_NAME not set")
    else:
        st.caption("📚 Knowledge base retrieval: not installed (add `pinecone` to requirements.txt to enable)")

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
    st.caption(f"🤖 AI messages today: {daily_used} (no cap — informational only)")

    reports_df = load_reports()

    if reports_df.empty:
        st.info("No reports submitted yet.")
    else:
        st.metric("Total reports", len(reports_df))

        STATUS_EMOJI = {"Received": "🔴", "Assigned": "🟠", "Crew Dispatched": "🟠",
                         "In Progress": "🔵", "Resolved": "🟢"}
        status_counts = reports_df["status"].value_counts().to_dict()
        status_count_cols = st.columns(len(STATUS_STAGES))
        for scol, stage in zip(status_count_cols, STATUS_STAGES):
            with scol:
                st.metric(f"{STATUS_EMOJI.get(stage, '⚪')} {stage}", status_counts.get(stage, 0))

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

        st.markdown('<div class="aqua-section-label">🔄 Update a report status</div>', unsafe_allow_html=True)
        STATUS_DISPLAY = {s: f"{STATUS_EMOJI.get(s, '⚪')} {s}" for s in STATUS_STAGES}
        with st.form("quick_status_form"):
            qs_ref = st.selectbox("Reference number", reports_df["reference"].tolist(), key="quick_status_ref")
            qs_current = reports_df.loc[reports_df["reference"] == qs_ref, "status"].values
            qs_current_status = qs_current[0] if len(qs_current) else STATUS_STAGES[0]
            qs_display_options = [STATUS_DISPLAY[s] for s in STATUS_STAGES]
            qs_new_display = st.selectbox(
                "New status", qs_display_options,
                index=STATUS_STAGES.index(qs_current_status) if qs_current_status in STATUS_STAGES else 0,
            )
            if st.form_submit_button("Update status"):
                qs_new_status = STATUS_STAGES[qs_display_options.index(qs_new_display)]
                update_report_status(qs_ref, qs_new_status)
                st.success(f"{qs_ref} updated to {qs_new_display}.")
                st.rerun()

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

                st.markdown(f'<div class="aqua-section-label">📣 Contact subscribers</div>', unsafe_allow_html=True)

                with st.expander("🧪 Auto-send email (testing)"):
                    st.caption(
                        "For testing only. Use a Gmail **App Password** (not your normal "
                        "login password) — generate one at "
                        "https://myaccount.google.com/apppasswords (requires 2-Step "
                        "Verification to be turned on first). Nothing typed here is saved "
                        "to disk — it only lives in this browser session."
                    )
                    sender_email_input = st.text_input("Sender email address", key="smtp_sender_email")
                    sender_password_input = st.text_input(
                        "App password", type="password", key="smtp_sender_password"
                    )
                    smtp_host_input = st.text_input("SMTP host", value="smtp.gmail.com", key="smtp_host")
                    smtp_port_input = st.number_input("SMTP port", value=587, key="smtp_port")

                st.caption("Or use the per-contact links below to send manually via your own email or WhatsApp.")

                category_filter_options = sorted(set(
                    cat.strip() for cats in notif_df["categories"].dropna() for cat in str(cats).split(",") if cat.strip()
                ))
                selected_categories = st.multiselect("Filter by category", category_filter_options, key="notify_contact_category_filter")
                if selected_categories:
                    filtered_notif = notif_df[notif_df["categories"].apply(
                        lambda c: any(cat.strip() in selected_categories for cat in str(c).split(","))
                    )]
                else:
                    filtered_notif = notif_df

                contact_message = st.text_area(
                    "Message to include", key="notify_contact_message",
                    placeholder="e.g. Planned maintenance in your area this Friday...",
                )

                if st.button("🚀 Send to all filtered email subscribers (test)", key="auto_send_email_btn"):
                    if not sender_email_input or not sender_password_input:
                        st.error("Enter a sender email and app password above first.")
                    elif not contact_message.strip():
                        st.error("Write a message above first.")
                    else:
                        email_recipients = [
                            str(r).strip() for r in filtered_notif["contact"].astype(str).tolist()
                            if "@" in str(r)
                        ]
                        if not email_recipients:
                            st.warning("No email addresses in the current filter.")
                        else:
                            sent_count, failed = 0, []
                            with st.spinner(f"Sending to {len(email_recipients)} recipient(s)..."):
                                for recipient in email_recipients:
                                    ok, err = send_notification_email(
                                        sender_email_input, sender_password_input, recipient,
                                        "NAWASA Notification", contact_message,
                                        smtp_host_input, int(smtp_port_input),
                                    )
                                    if ok:
                                        sent_count += 1
                                    else:
                                        failed.append((recipient, err))
                            if sent_count:
                                st.success(f"Sent to {sent_count} recipient(s).")
                            for recipient, err in failed:
                                st.error(f"Failed to send to {recipient}: {err}")

                import urllib.parse
                for _, sub_row in filtered_notif.iterrows():
                    contact_value = str(sub_row["contact"]).strip()
                    is_email = "@" in contact_value
                    digits_only = "".join(ch for ch in contact_value if ch.isdigit())
                    contact_col1, contact_col2 = st.columns([3, 1])
                    with contact_col1:
                        st.write(f"**{contact_value}** — _{sub_row['categories']}_")
                    with contact_col2:
                        if is_email:
                            mailto_link = f"mailto:{contact_value}?subject=NAWASA%20Notification&body={urllib.parse.quote(contact_message)}"
                            st.markdown(f"[✉️ Email]({mailto_link})")
                        elif digits_only:
                            wa_link = f"https://wa.me/{digits_only}?text={urllib.parse.quote(contact_message)}"
                            st.markdown(f"[💬 WhatsApp]({wa_link})")
                        else:
                            st.caption("—")

                all_contacts_text = "\n".join(filtered_notif["contact"].astype(str).tolist())
                st.text_area("All matching contacts (copy into your email or SMS tool)",
                              value=all_contacts_text, height=100, key="notify_contacts_copy")
            else:
                st.caption("No subscribers yet.")

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

def _build_composed_location():
    """Builds the Location field text from the currently selected parish,
    landmark, and pinned GPS coordinates. Shared by the GPS button, the
    interactive map click/drag, and the manual lat/lng inputs so all three
    ways of setting a location sync into the report form's Location field
    the same way, without the customer needing to type anything."""
    parts = [
        st.session_state.get("report_landmark", "").strip() if st.session_state.get("report_landmark") else "",
        st.session_state.get("report_parish", ""),
    ]
    pin = st.session_state.get("report_pin", {"lat": GRENADA_CENTER[0], "lng": GRENADA_CENTER[1]})
    loc = ", ".join([p for p in parts if p])
    loc += f" (GPS: {pin['lat']:.5f}, {pin['lng']:.5f})"
    return loc

# ---------------------------------------------------------------------------
# In-chat typing indicator — an animated three-dot bubble rendered in the
# assistant's own avatar/style, shown while a reply is being generated.
# Purely ephemeral: it's drawn once during the blocking API call and never
# stored in st.session_state.messages, so it disappears naturally on the
# st.rerun() that follows every reply (same lifecycle as st.spinner, just
# styled to look like part of the conversation instead of a page loader).
# ---------------------------------------------------------------------------
def render_typing_indicator(avatar):
    with st.chat_message("assistant", avatar=avatar):
        st.markdown(
            '<div class="aqua-typing-bubble">'
            '<span></span><span></span><span></span>'
            '</div>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# Report confirmation card — renders a small polished status card (instead
# of a plain st.success line) whenever a report reference number exists,
# used both for reports the AI logs mid-conversation via log_water_report
# and for the manual "Report & Track" form submission.
# ---------------------------------------------------------------------------
def render_report_card(card):
    severity = card.get("severity", "Unknown")
    severity_colors = {
        "Unknown": (BRAND_PRIMARY, f"{BRAND_PRIMARY}18"),
        "Low": ("#2E9E5B", "#2E9E5B18"),
        "Medium": ("#C98A11", "#C98A1118"),
        "High": ("#D64545", "#D6454518"),
    }
    sev_color, sev_bg = severity_colors.get(severity, severity_colors["Unknown"])
    st.markdown(f"""<div class="aqua-report-card">
<div class="aqua-report-card-head">
<span class="aqua-report-card-icon">✅</span>
<div>
<div class="aqua-report-card-title">Report logged</div>
<div class="aqua-report-card-ref">{card.get('reference', '')}</div>
</div>
</div>
<div class="aqua-report-card-rows">
<div class="aqua-report-card-row"><span>Status</span><b>{card.get('status', 'Received')}</b></div>
<div class="aqua-report-card-row"><span>Issue</span><b>{card.get('issue_type', '—')}</b></div>
<div class="aqua-report-card-row"><span>Severity</span><b style="color:{sev_color};background:{sev_bg};padding:0.05rem 0.5rem;border-radius:999px;">{severity}</b></div>
</div>
</div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Suggested follow-up chips — a small, cheap keyword match against the most
# recent exchange to offer 2-3 relevant next steps as tappable chips, so
# customers can continue without retyping. Falls back to a general set.
# ---------------------------------------------------------------------------
def suggest_followup_chips(messages):
    recent_text = " ".join(m.get("content", "") for m in messages[-3:]).lower()
    topic_chips = [
        (("leak", "burst", "hydrant", "drip"), [
            ("📷 Send a photo", "I'd like to send a photo of the issue."),
            ("📍 Update location", "I need to update the location of my report."),
            ("👤 Talk to an agent", t("qa_rep_prompt")),
        ]),
        (("bill", "payment", "arrears", "invoice"), [
            ("📄 Check my balance", t("qa_checkbill_prompt")),
            ("💳 Payment options", t("qa_bill_prompt")),
            ("👤 Talk to an agent", t("qa_rep_prompt")),
        ]),
        (("outage", "no water", "supply", "maintenance"), [
            ("🚰 Any updates?", "Are there any updates on the outage in my area?"),
            ("📍 Office locations", t("qa_locations_prompt")),
            ("👤 Talk to an agent", t("qa_rep_prompt")),
        ]),
    ]
    for keywords, chips in topic_chips:
        if any(k in recent_text for k in keywords):
            return chips
    return [
        ("👷 Report a leak", t("qa_report_prompt")),
        ("💳 Billing help", t("qa_bill_prompt")),
        ("👤 Talk to an agent", t("qa_rep_prompt")),
    ]

# ---------------------------------------------------------------------------
# Customer-facing live outage map — a read-only view of all currently
# active/upcoming NAWASA outage announcements across every parish (staff
# post these from the Staff Portal). Uses the interactive Folium map when
# available, and a plain list otherwise.
# ---------------------------------------------------------------------------
def render_customer_outage_map():
    outages_df = load_outages()
    if outages_df.empty:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    active = outages_df[
        (outages_df["start_date"].astype(str) <= today) & (outages_df["end_date"].astype(str) >= today)
    ]
    if active.empty:
        return
    with st.expander(f"🗺️ Live outage map — {len(active)} active announcement(s)", expanded=False):
        if HAS_MAP:
            outage_map = folium.Map(
                location=[GRENADA_CENTER[0], GRENADA_CENTER[1]], zoom_start=10,
                tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                attr="Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
            )
            for _, row in active.iterrows():
                center = PARISH_CENTERS.get(row["parish"], GRENADA_CENTER)
                folium.Circle(
                    location=list(center), radius=3500, color="#F5A623", fill=True,
                    fill_color="#F5A623", fill_opacity=0.35,
                    popup=folium.Popup(f"<b>{row['parish']}</b><br>{row['message']}<br>"
                                        f"{row['start_date']} – {row['end_date']}", max_width=220),
                    tooltip=row["parish"],
                ).add_to(outage_map)
            st_folium(outage_map, height=320, use_container_width=True, key="customer_outage_map")
        else:
            st.caption(t("map_not_installed"))
        for _, row in active.iterrows():
            st.markdown(f"**{row['parish']}** ({row['start_date']} – {row['end_date']}): {row['message']}")

if logo_b64:
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" />'
elif avatar_b64:
    logo_html = f'<img src="data:image/png;base64,{avatar_b64}" />'
else:
    logo_html = "💧"

if not api_key:
    st.info("👈 Enter your Google AI Studio API key in the sidebar (Territory & API key) to start chatting.")
    st.stop()

# ---------------------------------------------------------------------------
# Initialize client + chat session
# ---------------------------------------------------------------------------
if ("chat" not in st.session_state
        or st.session_state.get("_key_used") != api_key
        or st.session_state.get("_chat_territory") != st.session_state.territory
        or st.session_state.get("_chat_session_ref") != st.session_state.current_session_id):
    try:
        client = genai.Client(api_key=api_key)
        st.session_state.client = client

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
# ===========================================================================
st.markdown('<div class="aqua-page">', unsafe_allow_html=True)

hours_status = get_business_hours_status()

if hours_status["is_open"] and hours_status["closing_soon"] and HAS_AUTOREFRESH:
    st_autorefresh(interval=60000, key="aqua_closing_soon_autorefresh")

if hours_status["is_open"] and hours_status["closing_soon"]:
    _hero_mins = hours_status["minutes_until_close"]
    status_pill_html = (
        f'<div class="aqua-hero-status aqua-hero-status-soon">'
        f'<span class="aqua-hero-status-dot"></span>Office Open — closing in {_hero_mins} min</div>'
    )
elif hours_status["is_open"]:
    status_pill_html = '<div class="aqua-hero-status aqua-hero-status-open"><span class="aqua-hero-status-dot"></span>Office Open</div>'
else:
    status_pill_html = f'<div class="aqua-hero-status aqua-hero-status-closed"><span class="aqua-hero-status-dot"></span>Offices Closed — reopens {hours_status["reopens_label"]}</div>'

# AquaAssist itself is always reachable (24/7 AI availability), independent
# of NAWASA's human office hours above — shown as its own small "online"
# indicator under the hero title, distinct from the office-hours pill.
online_pill_html = '<div class="aqua-hero-online"><span class="aqua-hero-online-dot"></span>AquaAssist Online</div>'

nawasa_badge_inner = (f'<img src="data:image/png;base64,{nawasa_logo_b64}" />' if nawasa_logo_b64
                      else '<span style="font-size:0.55rem;font-weight:800;color:{0};text-align:center;">NAWASA</span>'.format(BRAND_HOVER))

chat_hero = f"""<div class="aqua-hero">
<div class="aqua-hero-content">
<div class="aqua-hero-brand">
{logo_html}
<div>
<div class="aqua-hero-title">AquaAssist</div>
<div class="aqua-hero-subtitle">NAWASA Official Virtual Assistant</div>
{online_pill_html}
{status_pill_html}
<div class="aqua-demo-tag aqua-hero-demo-tag">Demo - Developed by Sub Pod-1</div>
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
    ("chat", t("tab_chat")), ("report", t("tab_report")), ("faq", t("tab_faq")),
    ("history", t("tab_history")), ("settings", t("tab_settings")),
]
nav_cols = st.columns(len(NAV_ITEMS))
for col, (key, label) in zip(nav_cols, NAV_ITEMS):
    with col:
        is_active_nav = st.session_state.active_portal_tab == key
        container_key = f"aqua_nav_{key}_active" if is_active_nav else f"aqua_nav_{key}"
        with st.container(key=container_key):
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.active_portal_tab = key
                st.rerun()

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
    elif hours_status["closing_soon"]:
        _banner_mins = hours_status["minutes_until_close"]
        st.markdown(
            f'<div class="aqua-hours-banner aqua-hours-banner-soon">'
            f'<span class="aqua-hours-banner-icon">⏳</span>'
            f'<span><strong>Heads up — our Customer Service office closes in {_banner_mins} minute{"s" if _banner_mins != 1 else ""} '
            f'(4:00 PM).</strong> AquaAssist stays available 24/7, but if you\'d like a live representative today, '
            f"now's the time — call {NAWASA_PHONE} or WhatsApp us before we close.</span>"
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown(contact_row_html, unsafe_allow_html=True)

    # Falls back to the file name string (not an emoji) if the AquaAssist
    # avatar image isn't present, per the original app's convention.
    ASSISTANT_AVATAR = AVATAR_PATH if os.path.exists(AVATAR_PATH) else "aquaassist_avatar.png"
    # Uses the customer's own uploaded avatar image exactly as provided —
    # never regenerated — falling back to a plain emoji only if that file
    # genuinely isn't on disk.
    USER_AVATAR = USER_AVATAR_PATH if os.path.exists(USER_AVATAR_PATH) else "🧑"

    for msg_idx, msg in enumerate(st.session_state.messages):
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else USER_AVATAR
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("audio"):
                st.audio(msg["audio"])
            if msg.get("attachment_name"):
                st.caption(f"📎 {msg['attachment_name']}")
            if msg.get("report_card"):
                render_report_card(msg["report_card"])
            if msg.get("used_knowledge_base"):
                st.caption("📚 Answered using NAWASA's knowledge base")
            # --- Message reactions (assistant replies only) — lightweight
            # thumbs up/down feedback stored per-message. Purely a UX
            # signal (not wired to any backend), toggled on click. Each
            # button sits in its own keyed container (same "_active" suffix
            # pattern as the nav bar) so the CSS below can give the
            # selected thumb its full native color and a highlighted
            # background, while the unselected one stays dimmed.
            if msg["role"] == "assistant":
                reaction = msg.get("reaction")
                rcol1, rcol2, rcol_spacer = st.columns([0.06, 0.06, 0.88])
                with rcol1:
                    up_key = f"aqua_react_up_{msg_idx}" + ("_active" if reaction == "up" else "")
                    with st.container(key=up_key):
                        if st.button("👍", key=f"react_up_{msg_idx}", help="Helpful"):
                            msg["reaction"] = None if reaction == "up" else "up"
                            st.rerun()
                with rcol2:
                    down_key = f"aqua_react_down_{msg_idx}" + ("_active" if reaction == "down" else "")
                    with st.container(key=down_key):
                        if st.button("👎", key=f"react_down_{msg_idx}", help="Not helpful"):
                            msg["reaction"] = None if reaction == "down" else "down"
                            st.rerun()

    if not st.session_state.messages:
        # Chat bubbles already fade/slide in on render (see the
        # [data-testid="stChatMessage"] animation rule), so the welcome
        # message gets the same soft entrance automatically.
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.markdown(t("welcome"))

    # --- Suggested follow-up chips — shown only after the most recent
    # assistant reply, so the customer can keep the conversation moving
    # with a tap instead of retyping. Topic is guessed from the last
    # exchange; falls back to a general-purpose set if nothing matches.
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
        followups = suggest_followup_chips(st.session_state.messages)
        if followups:
            chip_clicked = None
            with st.container(key="aqua_chip_wrap"):
                chip_cols = st.columns(len(followups))
                for chip_idx, (chip_col, (chip_label, chip_prompt)) in enumerate(zip(chip_cols, followups)):
                    with chip_col:
                        if st.button(chip_label, key=f"chip_{len(st.session_state.messages)}_{chip_idx}", use_container_width=True):
                            chip_clicked = chip_prompt
            if chip_clicked:
                st.session_state["_queued_followup"] = chip_clicked
                st.rerun()

    input_row = st.columns([0.09, 0.09, 0.08, 0.74])
    with input_row[0]:
        st.markdown('<div class="aqua-mic-btn">', unsafe_allow_html=True)
        mic_clicked = st.button("🎤", key="mic_toggle_btn", help=t("voice_popover_label"))
        st.markdown('</div>', unsafe_allow_html=True)
    with input_row[1]:
        st.markdown('<div class="aqua-mic-btn">', unsafe_allow_html=True)
        camera_clicked = st.button("📷", key="camera_toggle_btn", help=t("camera_popover_label"))
        st.markdown('</div>', unsafe_allow_html=True)
    with input_row[2]:
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

    # Camera capture — a customer can take a photo of the issue on the spot
    # (rather than only uploading an existing one via the chat input's "+"
    # attach button). st.camera_input opens the device camera directly on
    # mobile browsers. Shown in its own toggled panel, mirroring the mic
    # recorder above, with an explicit "Send photo" step so the customer can
    # preview/retake before it's sent.
    camera_photo_input = None
    if camera_clicked:
        st.session_state["_camera_open"] = not st.session_state.get("_camera_open", False)
    if st.session_state.get("_camera_open"):
        with st.container(border=True):
            captured_photo = st.camera_input(
                "Take a photo of the issue", key="camera_capture_input", label_visibility="collapsed",
            )
            if captured_photo is not None:
                if st.button("Send photo", key="send_camera_photo_btn"):
                    camera_photo_input = ("__PHOTO__", captured_photo.getvalue(), captured_photo.type or "image/jpeg")
                    st.session_state["_camera_open"] = False

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
    with st.container(key="aqua_qa_wrap"):
        for row_start in range(0, len(qa_items), 2):
            row_items = qa_items[row_start:row_start + 2]
            qa_cols = st.columns(len(row_items))
            for qa_idx, (col, (label, info)) in enumerate(zip(qa_cols, row_items), start=row_start):
                with col:
                    if st.button(label, use_container_width=True, key=f"qa_{qa_idx}", help=info["desc"]):
                        queued_prompt = info["prompt"]

    render_customer_outage_map()

    if st.session_state.get("_queued_followup"):
        queued_prompt = st.session_state.pop("_queued_followup")

    user_turn = None
    is_audio_turn = False
    is_photo_turn = False
    if voice_text_input:
        user_turn = voice_text_input
        is_audio_turn = True
    elif camera_photo_input:
        user_turn = camera_photo_input
        is_photo_turn = True
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
                render_typing_indicator(ASSISTANT_AVATAR)
                st.session_state.pop("_last_logged_report", None)
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

            new_msg = {"role": "assistant", "content": reply_text, "audio": reply_audio}
            _logged = st.session_state.pop("_last_logged_report", None)
            if _logged:
                new_msg["report_card"] = _logged
            st.session_state.messages.append(new_msg)
            st.rerun()
        elif is_photo_turn:
            _, photo_bytes, photo_mime_type = user_turn
            ensure_files()
            attachment_name = f"{uuid.uuid4().hex[:8]}_camera_photo.jpg"
            with open(os.path.join(ATTACHMENTS_DIR, attachment_name), "wb") as out:
                out.write(photo_bytes)

            st.session_state.messages.append({
                "role": "user", "content": "📷 Sent a photo",
                "attachment_name": attachment_name,
            })

            allowed, limit_reason = check_and_record_usage()
            if not allowed:
                reply_text = usage_limit_message(limit_reason)
            else:
                render_typing_indicator(ASSISTANT_AVATAR)
                st.session_state.pop("_last_logged_report", None)
                try:
                    photo_part = types.Part.from_bytes(data=photo_bytes, mime_type=photo_mime_type)
                    bot_response = st.session_state.chat.send_message([
                        photo_part,
                        "The customer just took and sent a photo of a NAWASA water service "
                        "issue (e.g. a leak, burst pipe, or damaged hydrant) using their camera. "
                        "Look at what's visible and respond helpfully — ask for the location and "
                        "any other missing details if you don't already have them.",
                    ])
                    reply_text = bot_response.text
                except Exception as e:
                    reply_text = f"⚠️ Error: {e}"

            reply_audio = None
            if st.session_state.voice_replies:
                reply_audio = speak_text(reply_text, "en")

            new_msg = {"role": "assistant", "content": reply_text, "audio": reply_audio}
            _logged = st.session_state.pop("_last_logged_report", None)
            if _logged:
                new_msg["report_card"] = _logged
            st.session_state.messages.append(new_msg)
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
                    retrieved_context = ""
                else:
                    render_typing_indicator(ASSISTANT_AVATAR)
                    st.session_state.pop("_last_logged_report", None)
                    retrieved_context = ""
                    try:
                        # --- Pinecone retrieval: ground the reply in the
                        # NAWASA knowledge base before sending to Gemini.
                        retrieved_context = retrieve_nawasa_knowledge(cleaned_input) if cleaned_input else ""
                        send_parts = list(message_parts) if message_parts else [cleaned_input]
                        if retrieved_context:
                            send_parts.insert(0, (
                                "[Reference material from the NAWASA knowledge base — use this "
                                "to answer accurately if it's relevant to the customer's question. "
                                "Don't quote it verbatim or mention you're using reference material.]\n"
                                f"{retrieved_context}"
                            ))
                        bot_response = st.session_state.chat.send_message(send_parts)
                        reply_text = bot_response.text
                    except Exception as e:
                        reply_text = f"⚠️ Error: {e}"

                reply_audio = None
                if st.session_state.voice_replies:
                    reply_audio = speak_text(reply_text, "en")

                new_msg = {"role": "assistant", "content": reply_text, "audio": reply_audio}
                _logged = st.session_state.pop("_last_logged_report", None)
                if _logged:
                    new_msg["report_card"] = _logged
                if retrieved_context:
                    new_msg["used_knowledge_base"] = True
                st.session_state.messages.append(new_msg)
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
                if HAS_TTS and st.button(f"🔊 Read aloud", key=f"faq_audio_{cat}_{faq_idx}"):
                    audio = speak_text(f["a"], "en")
                    if audio:
                        st.audio(audio)

# ===================== REPORT & TRACK =====================
elif active_tab == "report":
    st.markdown(f'<div class="aqua-section-label">{t("report_issue")}</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("map_section_label")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)

    # Apply any parish auto-detected from a map click or GPS fix on the
    # previous run. This MUST happen before the Parish selectbox below is
    # instantiated — Streamlit only allows writing to a widget's own
    # session-state key prior to that widget being created in the current
    # script run; writing to it afterwards (e.g. from the map-click handler
    # further down, which runs after this selectbox) raises a
    # StreamlitAPIException.
    if st.session_state.get("_pending_parish"):
        st.session_state["report_parish_select"] = st.session_state.pop("_pending_parish")

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
            st.caption(t("map_gps_button"))
            gps_coords = streamlit_geolocation()
            if gps_coords and gps_coords.get("latitude") is not None:
                new_pin = {"lat": gps_coords["latitude"], "lng": gps_coords["longitude"]}
                if new_pin != st.session_state.get("_last_gps_pin"):
                    st.session_state.report_pin = new_pin
                    st.session_state["_last_gps_pin"] = new_pin
                    # Auto-fill the Parish dropdown from the nearest parish
                    # center. Stage it in _pending_parish rather than writing
                    # report_parish_select directly — that widget was already
                    # instantiated earlier in this run, so Streamlit would
                    # reject a direct write; the staged value is applied at
                    # the top of this tab on the next run instead.
                    _detected_parish = _nearest_parish(new_pin["lat"], new_pin["lng"])
                    st.session_state.report_parish = _detected_parish
                    st.session_state["_pending_parish"] = _detected_parish
                    # Push the new coordinates straight into the report form's
                    # Location field so the customer sees it update immediately,
                    # without needing to touch that field themselves.
                    _new_loc = _build_composed_location()
                    st.session_state["report_location_field"] = _new_loc
                    st.session_state["_last_composed_location"] = _new_loc
                    st.rerun()
            elif gps_coords and gps_coords.get("latitude") is None:
                gps_error_detail = gps_coords.get("message") or gps_coords.get("error") or str(gps_coords)
                st.caption(f"⚠️ Location unavailable: {gps_error_detail}")
                st.caption(
                    "Common causes: location permission was denied in the "
                    "browser, the site isn't loaded over HTTPS (or localhost), "
                    "or device location services are turned off."
                )
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
            draggable=False,
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
                # Auto-fill the Parish dropdown from the nearest parish
                # center. Stage it in _pending_parish rather than writing
                # report_parish_select directly — that widget was already
                # instantiated earlier in this run, so Streamlit would
                # reject a direct write; the staged value is applied at
                # the top of this tab on the next run instead.
                _detected_parish = _nearest_parish(new_lat, new_lng)
                st.session_state.report_parish = _detected_parish
                st.session_state["_pending_parish"] = _detected_parish
                _new_loc = _build_composed_location()
                st.session_state["report_location_field"] = _new_loc
                st.session_state["_last_composed_location"] = _new_loc
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

    composed_location = _build_composed_location()
    # Whenever the underlying parish, landmark, or pin changes (via GPS, map
    # click, or the manual lat/lng fallback inputs), push the refreshed
    # location straight into the report form's Location field so it updates
    # automatically instead of requiring the customer to retype it.
    if st.session_state.get("_last_composed_location") != composed_location:
        st.session_state["report_location_field"] = composed_location
        st.session_state["_last_composed_location"] = composed_location

    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.expander(t("report_form_expander"), expanded=True):
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
            r_location = st.text_input(t("field_location"), value=composed_location, key="report_location_field")

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
                    render_report_card({
                        "reference": reference, "status": "Received",
                        "issue_type": r_issue_type, "severity": r_severity,
                    })
                    st.caption("Save this reference number to track your report below.")
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

    st.selectbox(
        "NAWASA territory", TERRITORIES,
        index=TERRITORIES.index(st.session_state.territory) if st.session_state.territory in TERRITORIES else 0,
        key="settings_territory_select",
        on_change=_sync_territory,
        args=("settings_territory_select", "sidebar_territory_select"),
    )

    new_dark_mode = st.toggle(t("dark_mode"), value=st.session_state.dark_mode, key="settings_dark_mode_toggle")
    new_high_contrast = st.toggle(t("high_contrast"), value=st.session_state.high_contrast, key="settings_high_contrast_toggle")
    new_large_text = st.toggle(t("large_text"), value=st.session_state.large_text, key="settings_large_text_toggle")
    st.caption(t("accessibility_note"))

    parish_options = [""] + GRENADA_PARISHES
    current_parish = st.session_state.get("customer_parish", "")
    new_parish = st.selectbox(
        t("your_parish_label"), parish_options,
        index=parish_options.index(current_parish) if current_parish in parish_options else 0,
        key="settings_customer_parish",
    )

    settings_changed = (
        new_dark_mode != st.session_state.dark_mode
        or new_high_contrast != st.session_state.high_contrast
        or new_large_text != st.session_state.large_text
        or new_parish != current_parish
    )
    st.session_state.dark_mode = new_dark_mode
    st.session_state.high_contrast = new_high_contrast
    st.session_state.large_text = new_large_text
    st.session_state.customer_parish = new_parish
    if settings_changed:
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("settings_conversation")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.caption(f"{len(st.session_state.messages)} {t('conversation_note')}")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)  # aqua-page

st.markdown('<div class="aqua-footer">Powered by <strong>NAWASA</strong></div>', unsafe_allow_html=True)
