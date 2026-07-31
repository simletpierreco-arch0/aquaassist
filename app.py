"""
AquaAssist — Streamlit UI (Redesign: login gate, blue/white wave theme, multi-chat history)
NAWASA (National Water and Sewerage Authority, Grenada) AI customer support platform.

Run with:
    pip install -r requirements.txt
    streamlit run app.py

Folder layout expected:
    app.py
    assets/aquaassist_logo.png
    .streamlit/config.toml
    data/reports.csv          (auto-created, and auto-migrated if its schema
                                is missing a column added in a later update)
    data/notifications.csv    (auto-created)
    attachments/              (auto-created, uploaded report files + chat attachments)

BEFORE DEPLOYING:
    STAFF_PASSCODE -> replace "changeme123" below, or set as env var / Streamlit secret
"""

import os
import csv
import io
import uuid
import base64
from datetime import datetime

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
NAWASA_WHATSAPP_LINK = "https://wa.link/rt9dj1"
NAWASA_PHONE = "(473) 440-2155"
NAWASA_WEBSITE = "https://nawasa.gd/"
STAFF_PASSCODE = os.environ.get("STAFF_PASSCODE", "changeme123")
WHATSAPP_LINK = NAWASA_WHATSAPP_LINK

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
LOGO_PATH = os.path.join("assets", "aquaassist_logo.png")
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

st.set_page_config(
    page_title="AquaAssist",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "💧",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
defaults = {
    "auth_done": False,            # True once the customer clicks Guest or Log in
    "account_mode": None,          # "guest" or "account"
    "selected_language": None,
    "customer_name": "",
    "customer_email": "",
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
# Languages
# ---------------------------------------------------------------------------
PRIMARY_LANGUAGES = ["English", "Grenadian Creole", "Spanish", "French"]
EXTENDED_LANGUAGES = [
    "Portuguese", "German", "Italian", "Dutch", "Chinese (Simplified)",
    "Chinese (Traditional)", "Japanese", "Korean", "Hindi", "Arabic",
    "Russian", "Turkish", "Swahili", "Bengali", "Urdu", "Vietnamese",
    "Thai", "Polish", "Greek", "Hebrew", "Romanian", "Czech", "Hungarian",
    "Indonesian", "Malay",
]
# TTS voice codes gTTS understands, for languages where we know one. Anything
# not listed here (including Grenadian Creole, and any language typed in
# freely) falls back to an English voice reading the text phonetically.
TTS_LANG_CODES = {
    "English": "en", "Spanish": "es", "French": "fr",
    "Portuguese": "pt", "German": "de", "Italian": "it", "Dutch": "nl",
    "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
    "Japanese": "ja", "Korean": "ko", "Hindi": "hi", "Arabic": "ar",
    "Russian": "ru", "Turkish": "tr", "Swahili": "sw", "Bengali": "bn",
    "Urdu": "ur", "Vietnamese": "vi", "Thai": "th", "Polish": "pl",
    "Greek": "el", "Hebrew": "iw", "Romanian": "ro", "Czech": "cs",
    "Hungarian": "hu", "Indonesian": "id", "Malay": "ms",
}

# ---------------------------------------------------------------------------
# Grenada geography — for the report location picker
# ---------------------------------------------------------------------------
GRENADA_PARISHES = [
    "St. George's (Capital area)", "St. Andrew's", "St. David's",
    "St. John's", "St. Mark's", "St. Patrick's", "Carriacou and Petite Martinique",
]
GRENADA_CENTER = (12.1165, -61.6790)

# UI text: English is the only hand-written copy — the single source of
# truth for every button, label, and tab name. Every OTHER language,
# including Grenadian Creole and anything from the extended list or typed
# in freely (Japanese, Korean, or literally any language name), is
# auto-translated by Gemini on first use and cached in session state, via
# get_ui_dict()/translate_ui_text() below.
UI_TEXT = {
    "English": {
        "welcome": "Welcome to AquaAssist! 💧 I'm here to help with your NAWASA water services.",
        "tab_chat": "💬 Chat", "tab_faq": "❓ FAQ", "tab_report": "📋 Report & Track",
        "tab_history": "🕘 History", "tab_settings": "⚙️ Settings",
        "report_issue": "🚿 Report an issue",
        "quick_actions": "💧 Quick actions", "ask_placeholder": "Ask AquaAssist something...",
        "your_name": "Your name", "continue": "Continue",
        "call_us": "Call Us", "whatsapp_label": "WhatsApp", "chat_now": "Chat now",
        "website_label": "Website",
        "qa_report_label": "🚿 Report a Leak", "qa_report_prompt": "I'd like to report a water leak.",
        "qa_maint_label": "🛠️ Maintenance", "qa_maint_prompt": "Are there any scheduled outages or planned maintenance in my area?",
        "qa_bill_label": "💳 Pay My Bill", "qa_bill_prompt": "What are my options for paying my NAWASA bill?",
        "qa_rep_label": "📞 Talk to a Rep", "qa_rep_prompt": "I'd like to speak with a customer service representative.",
        "settings_preferences": "⚙️ Preferences", "preferred_language": "Preferred language",
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
        "voice_help_on": "Uses gTTS to read the bot's replies aloud.", "voice_help_off": "Install gTTS to enable this.",
        "issue_leak": "Leak", "issue_no_water": "No water supply", "issue_low_pressure": "Low pressure",
        "issue_billing": "Billing issue", "issue_burst": "Burst main", "issue_hydrant": "Damaged hydrant",
        "issue_quality": "Water quality concern", "issue_other": "Other",
        "new_chat": "＋ New chat", "chat_history": "Recent chats", "no_history": "No previous chats yet.",
        "login_title": "Welcome to AquaAssist", "login_subtitle": "Your smart water support assistant",
        "login_choose": "How would you like to continue?", "login_guest": "Continue as Guest",
        "login_account": "Log in with an account", "login_name": "Name", "login_email": "Email",
        "login_key": "Gemini API key", "login_key_help": "Get a key at https://aistudio.google.com/",
        "login_lang": "Choose your language", "login_start": "Start chatting",
        "login_missing": "Please select a language and enter your API key first.",
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
    },
}


def translate_ui_text(language, client):
    """Translates every English UI_TEXT value into `language` in a single
    Gemini call, preserving emoji/URLs/placeholders and JSON structure.
    Returns the translated dict, or None on any failure."""
    import json
    try:
        source = UI_TEXT["English"]
        prompt = (
            f"Translate the values of this JSON object into {language}. This is the interface text "
            f"for a water utility customer-support app. Keep the exact same JSON keys and the exact "
            f"same number of entries — do not add, remove, merge, or rename keys. Preserve emoji, "
            f"punctuation symbols, URLs, and the example reference code 'NW-A1B2C3D' exactly as-is — "
            f"only translate the human-readable words. Keep the proper nouns 'NAWASA' and 'AquaAssist' "
            f"untranslated. Respond with ONLY the translated JSON object, nothing else, no commentary, "
            f"no markdown code fences:\n\n{json.dumps(source, ensure_ascii=False)}"
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        translated = json.loads(raw)
        if isinstance(translated, dict) and set(translated.keys()) == set(source.keys()):
            return translated
    except Exception:
        pass
    return None


def get_ui_dict(language):
    """Returns the UI_TEXT dict for `language`, auto-translating and caching
    it via Gemini the first time that language is used this session.

    A failed translation attempt is NOT permanently remembered — it is only
    rate-limited (so we don't hammer the API on every Streamlit rerun) and a
    warning is surfaced via st.session_state["ui_translation_warning"] so the
    caller can show the user why the UI is still in English.
    """
    import time

    if not language or language == "English":
        return UI_TEXT["English"]

    cache = st.session_state.setdefault("ui_translations", {})
    if language in cache:
        return cache[language]

    api_key = st.session_state.get("api_key")
    if not api_key:
        return UI_TEXT["English"]

    attempts = st.session_state.setdefault("ui_translation_attempts", {})
    attempt_key = f"{language}::{api_key}"
    last_try = attempts.get(attempt_key, 0)
    if time.time() - last_try < 8:
        return UI_TEXT["English"]
    attempts[attempt_key] = time.time()

    try:
        client = genai.Client(api_key=api_key)
        with st.spinner(f"Translating the interface into {language}..."):
            translated = translate_ui_text(language, client)
        if translated:
            cache[language] = translated
            st.session_state.pop("ui_translation_warning", None)
            return translated
        st.session_state["ui_translation_warning"] = language
    except Exception:
        st.session_state["ui_translation_warning"] = language

    return UI_TEXT["English"]


def t(key):
    lang = st.session_state.get("selected_language") or "English"
    d = get_ui_dict(lang)
    return d.get(key, UI_TEXT["English"].get(key, key))

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


def get_translated_faqs(language, client):
    """Returns the FAQ list translated into `language`, using Gemini once per
    language and caching the result in session state so it isn't re-translated
    on every rerun/click. Falls back to English on any failure."""
    if language == "English":
        return FAQS

    cache = st.session_state.setdefault("faq_translations", {})
    if language in cache:
        return cache[language]

    import json
    try:
        prompt = (
            f"Translate the 'category', 'q', and 'a' fields of every item in this JSON array into "
            f"{language}. Keep the exact same JSON array structure and number of items — do not add, "
            f"remove, merge, or summarize any items, and do not add commentary. Preserve numbers, "
            f"dollar amounts, and proper nouns like NAWASA as-is. Respond with ONLY the translated "
            f"JSON array, nothing else:\n\n{json.dumps(FAQS, ensure_ascii=False)}"
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        translated = json.loads(raw)
        if isinstance(translated, list) and len(translated) == len(FAQS):
            cache[language] = translated
            return translated
    except Exception:
        pass
    return FAQS  # fall back silently to English if translation fails

# ---------------------------------------------------------------------------
# Brand palette — blue & white only, with dark mode / high contrast swaps.
# ---------------------------------------------------------------------------
if st.session_state.high_contrast:
    BRAND_BLUE = "#004C99"
    BRAND_BLUE_LIGHT = "#0066CC"
    BRAND_BLUE_DARK = "#000000"
    BRAND_CREAM = "#FFFFFF"
    BRAND_CREAM_SOFT = "#F0F0F0"
    BRAND_WHITE = "#FFFFFF"
elif st.session_state.dark_mode:
    BRAND_BLUE = "#3B9EE8"
    BRAND_BLUE_LIGHT = "#5FB4F0"
    BRAND_BLUE_DARK = "#E8F0FA"
    BRAND_CREAM = "#0E141B"
    BRAND_CREAM_SOFT = "#182230"
    BRAND_WHITE = "#182230"
else:
    BRAND_BLUE = "#0B76C7"
    BRAND_BLUE_LIGHT = "#4FA8E0"
    BRAND_BLUE_DARK = "#0B2545"
    BRAND_CREAM = "#F4F9FE"
    BRAND_CREAM_SOFT = "#E7F2FC"
    BRAND_WHITE = "#FFFFFF"

WHATSAPP_GREEN = "#25D366"
BASE_FONT_SIZE = "1.15rem" if st.session_state.large_text else "0.95rem"

logo_b64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()

# A soft repeating wave pattern used as a fixed backdrop behind the whole app.
_WAVE_BG_SVG = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%201200%20200'%20preserveAspectRatio='none'%3E"
    "%3Cpath%20d='M0,80%20C200,140%20400,20%20600,80%20C800,140%201000,20%201200,80%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_BLUE.replace('#', '%23')}'%20fill-opacity='0.06'/%3E"
    "%3Cpath%20d='M0,120%20C220,60%20420,180%20620,120%20C820,60%201020,180%201200,120%20L1200,200%20L0,200%20Z'%20"
    f"fill='{BRAND_BLUE.replace('#', '%23')}'%20fill-opacity='0.10'/%3E"
    "%3C/svg%3E"
)

# ---------------------------------------------------------------------------
# Custom CSS — every line flush-left (Markdown treats 4+ space indents as a
# literal code block and refuses to render it as HTML, even with
# unsafe_allow_html=True — keep every line here starting at column 0).
# ---------------------------------------------------------------------------
CSS_BLOCK = f"""<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] {{
font-family: 'Poppins', sans-serif;
font-size: {BASE_FONT_SIZE};
}}
.stApp {{
background-color: {BRAND_CREAM};
background-image: linear-gradient(180deg, {BRAND_CREAM_SOFT} 0%, {BRAND_CREAM} 45%), url("{_WAVE_BG_SVG}");
background-repeat: no-repeat, repeat-x;
background-position: top, bottom;
background-size: 100% 420px, 1200px 200px;
background-attachment: fixed, fixed;
}}
.block-container {{
padding-top: 2.8rem;
max-width: 780px;
}}
::-webkit-scrollbar {{
width: 8px;
height: 8px;
}}
::-webkit-scrollbar-track {{
background: {BRAND_CREAM};
}}
::-webkit-scrollbar-thumb {{
background: {BRAND_BLUE}55;
border-radius: 10px;
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
@keyframes aquaDrift {{
0% {{ background-position-x: 0px, 0px; }}
100% {{ background-position-x: -1200px, -1200px; }}
}}
.aqua-hero {{
position: relative;
background: linear-gradient(120deg, {BRAND_BLUE} 0%, {BRAND_BLUE_LIGHT} 50%, {BRAND_BLUE} 100%);
background-size: 200% 200%;
animation: aquaShimmer 10s ease-in-out infinite;
border-radius: 24px 24px 0 0;
padding: 1.8rem 1.6rem 3.2rem 1.6rem;
margin-bottom: -1px;
overflow: hidden;
}}
.aqua-hero-content {{
display: flex;
align-items: center;
gap: 1rem;
position: relative;
z-index: 2;
animation: aquaFadeUp 0.5s ease-out;
}}
.aqua-hero img {{
width: 64px;
height: 64px;
border-radius: 50%;
background: {BRAND_WHITE};
padding: 5px;
box-shadow: 0 4px 14px rgba(0,0,0,0.18);
}}
.aqua-hero-title {{
font-size: 1.8rem;
font-weight: 800;
color: #FFFFFF;
line-height: 1.15;
letter-spacing: -0.02em;
}}
.aqua-hero-subtitle {{
font-size: 0.95rem;
color: rgba(255,255,255,0.92);
font-weight: 500;
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
fill: {BRAND_CREAM};
}}
.aqua-card {{
background: {BRAND_WHITE};
border-radius: 18px;
padding: 1.1rem 1.3rem;
margin-bottom: 1rem;
box-shadow: 0 2px 12px rgba(11, 118, 199, 0.08);
border: 1px solid {BRAND_BLUE}22;
animation: aquaFadeUp 0.4s ease-out;
color: {BRAND_BLUE_DARK};
}}
.aqua-section-label {{
display: flex;
align-items: center;
gap: 0.4rem;
font-size: 0.8rem;
font-weight: 700;
color: {BRAND_BLUE};
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
background: {BRAND_WHITE};
border: 1px solid {BRAND_BLUE}22;
border-radius: 14px;
padding: 0.7rem 0.6rem;
text-align: center;
text-decoration: none !important;
box-shadow: 0 2px 8px rgba(11, 118, 199, 0.06);
transition: all 0.15s ease-in-out;
}}
.aqua-contact-card:hover {{
transform: translateY(-3px);
box-shadow: 0 6px 16px rgba(11, 118, 199, 0.15);
border-color: {BRAND_BLUE}55;
}}
.aqua-contact-icon {{
font-size: 1.3rem;
display: block;
margin-bottom: 0.2rem;
}}
.aqua-contact-label {{
font-size: 0.72rem;
font-weight: 700;
color: {BRAND_BLUE_DARK};
text-transform: uppercase;
letter-spacing: 0.04em;
display: block;
}}
.aqua-contact-value {{
font-size: 0.7rem;
color: {BRAND_BLUE};
font-weight: 500;
}}
.aqua-status-badge {{
display: inline-block;
padding: 0.2rem 0.7rem;
border-radius: 999px;
font-size: 0.75rem;
font-weight: 700;
background: {BRAND_BLUE}18;
color: {BRAND_BLUE};
}}
.aqua-faq-item {{
background: {BRAND_WHITE};
border: 1px solid {BRAND_BLUE}22;
border-radius: 12px;
padding: 0.8rem 1rem;
margin-bottom: 0.6rem;
color: {BRAND_BLUE_DARK};
}}
.aqua-faq-cat {{
font-size: 0.68rem;
font-weight: 700;
color: {BRAND_BLUE};
text-transform: uppercase;
letter-spacing: 0.05em;
}}
[data-testid="stChatMessage"] {{
border-radius: 16px;
padding: 0.5rem 0.7rem;
margin-bottom: 0.5rem;
box-shadow: 0 1px 4px rgba(0,0,0,0.05);
animation: aquaFadeUp 0.3s ease-out;
}}
div.stButton > button {{
border-radius: 14px;
border: 1px solid {BRAND_BLUE}33;
background-color: {BRAND_WHITE};
color: {BRAND_BLUE_DARK};
font-weight: 600;
padding: 0.7rem 0.5rem;
box-shadow: 0 2px 6px rgba(11, 118, 199, 0.06);
transition: all 0.15s ease-in-out;
}}
div.stButton > button:hover {{
border-color: {BRAND_BLUE};
color: {BRAND_BLUE};
background-color: {BRAND_CREAM_SOFT};
box-shadow: 0 4px 12px rgba(11, 118, 199, 0.15);
transform: translateY(-2px);
}}
.aqua-primary-btn button {{
background-color: {BRAND_BLUE} !important;
color: #FFFFFF !important;
border: none !important;
}}
.aqua-primary-btn button:hover {{
background-color: {BRAND_BLUE_LIGHT} !important;
color: #FFFFFF !important;
}}
section[data-testid="stSidebar"] {{
background-color: {BRAND_WHITE};
background-image: url("{_WAVE_BG_SVG}");
background-repeat: repeat-x;
background-position: bottom;
background-size: 900px 150px;
border-right: 1px solid {BRAND_BLUE}22;
}}
.aqua-sidebar-newchat button {{
background-color: {BRAND_BLUE} !important;
color: #FFFFFF !important;
border: none !important;
width: 100%;
font-weight: 700;
}}
.aqua-sidebar-newchat button:hover {{
background-color: {BRAND_BLUE_LIGHT} !important;
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
color: {BRAND_BLUE_DARK} !important;
}}
.aqua-history-btn button:hover {{
background: {BRAND_CREAM_SOFT} !important;
transform: none !important;
box-shadow: none !important;
color: {BRAND_BLUE} !important;
}}
.aqua-history-active button {{
background: {BRAND_BLUE}14 !important;
color: {BRAND_BLUE} !important;
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
max-width: 520px;
margin: 0 auto;
}}
.aqua-login-hero {{
text-align: center;
padding: 2.2rem 1rem 1rem 1rem;
}}
.aqua-login-hero img {{
width: 84px;
height: 84px;
border-radius: 50%;
background: {BRAND_WHITE};
padding: 6px;
box-shadow: 0 6px 18px rgba(11, 118, 199, 0.18);
margin-bottom: 0.8rem;
}}
.aqua-login-title {{
font-size: 2rem;
font-weight: 800;
color: {BRAND_BLUE_DARK};
letter-spacing: -0.02em;
}}
.aqua-login-subtitle {{
font-size: 1rem;
color: {BRAND_BLUE};
font-weight: 500;
margin-bottom: 0.5rem;
}}
.aqua-mic-btn button {{
border-radius: 50% !important;
width: 2.6rem !important;
height: 2.6rem !important;
padding: 0 !important;
font-size: 1.1rem !important;
}}
</style>
<a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-float" title="Chat on WhatsApp">💬</a>"""

st.markdown(CSS_BLOCK, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------
def build_system_instruction(selected_language):
    return f"""
You are AquaAssist, a friendly virtual customer assistant for the National Water and Sewerage Authority (NAWASA) of Grenada.

LANGUAGE RULE:
The customer has selected "{selected_language}" as their preferred language. Reply in {selected_language} by default, from your very first message.
However, if the customer types in a different language or dialect than {selected_language} — including English, French, Spanish, or Grenadian Creole/patois — switch immediately to match whatever they actually typed, for that message and going forward, even if it differs from their originally selected language. Do not default to English if the customer used another language or dialect. If a customer switches language mid-conversation, switch with them. If you are unsure which language or dialect was used, ask the customer to confirm rather than guessing.

Use the following facts to answer user questions:
- Help customers report water leaks by collecting the location and relevant details.
- Provide information about water supply issues and service interruptions.
- Help customers check for planned maintenance and scheduled outages.
- Explain the available methods for paying NAWASA bills.
- Provide NAWASA customer service contact information and transfer users to a representative when requested.
- If the issue is an emergency, advise the user to contact NAWASA immediately at (473) 440-2155.
- NAWASA's official contact details: Phone (473) 440-2155, WhatsApp via https://wa.link/rt9dj1 (405-5245 / 459-6064 / 405-9143), Website https://nawasa.gd/. Share these when a customer asks how to reach NAWASA directly.
- When a customer describes a specific problem (a leak, no water, low pressure, a billing issue) and gives at least a location, log it immediately using the log_water_report tool — do not tell the customer to fill out a separate form themselves. After logging it, tell the customer their reference number so they can track it, and let them know NAWASA staff will follow up. If you don't have their name or phone number yet, ask for it after logging so staff can reach them, but don't block logging the report on that.
- If the customer attaches a photo or video of the issue, look at it before calling log_water_report and set the tool's severity argument based on what you actually see (e.g. a small drip is "Low", a steady leak is "Medium", a burst main or flooding is "High"). If there's no photo, leave severity as "Unknown" — never guess severity from text description alone.
- The "Report a Leak" form, voice messages, and the WhatsApp button are alternative ways to reach NAWASA, but you should always try to log the report yourself first if the customer is describing it in chat.
- Use natural understanding, not keyword matching — "I have no water", "my bill is wrong", "I smell chlorine", "my meter is leaking" should all be recognized as reportable issues even without exact keywords.

Be helpful, clear, patient, and reassuring.
Keep responses concise, polite, and easy to understand.
If a question is unrelated to NAWASA services, politely explain that you can only assist with NAWASA-related topics and invite the user to ask another water service question.
"""

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
# Voice helpers
# ---------------------------------------------------------------------------
def speak_text(text, lang_code="en"):
    if not HAS_TTS:
        return None
    try:
        buf = io.BytesIO()
        gTTS(text=text, lang=lang_code).write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception:
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
# LOGIN / WELCOME GATE — first screen on a fresh session
# ---------------------------------------------------------------------------
if not st.session_state.auth_done:
    st.markdown('<div class="aqua-login-wrap">', unsafe_allow_html=True)
    logo_tag = f'<img src="data:image/png;base64,{logo_b64}" />' if logo_b64 else "💧"
    st.markdown(f"""<div class="aqua-login-hero">
{logo_tag}
<div class="aqua-login-title">AquaAssist</div>
<div class="aqua-login-subtitle">Your smart water support assistant — NAWASA</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)

    # --- Language selection ---
    st.markdown(f"**🌐 {t('login_lang')}**")
    lang_cols = st.columns(4)
    for col, lang in zip(lang_cols, PRIMARY_LANGUAGES):
        with col:
            active = st.session_state.selected_language == lang
            if st.button(lang, use_container_width=True, key=f"lang_{lang}",
                         type="primary" if active else "secondary"):
                st.session_state.selected_language = lang
                st.rerun()
    with st.expander("More languages"):
        extra = st.selectbox("Search / select a language", [""] + EXTENDED_LANGUAGES,
                              index=(EXTENDED_LANGUAGES.index(st.session_state.selected_language) + 1)
                              if st.session_state.selected_language in EXTENDED_LANGUAGES else 0)
        if extra and extra != st.session_state.selected_language:
            st.session_state.selected_language = extra
            st.rerun()
        st.caption("Don't see your language? Type any language or dialect below.")
        custom_lang = st.text_input("Any other language", key="login_custom_lang",
                                     placeholder="e.g. Haitian Creole, Tagalog, Igbo...")
        if custom_lang.strip() and st.button(f"Use “{custom_lang.strip()}”", key="login_custom_lang_btn"):
            st.session_state.selected_language = custom_lang.strip()
            st.rerun()

    if st.session_state.selected_language:
        st.caption(f"Selected: **{st.session_state.selected_language}**")
        if st.session_state.get("ui_translation_warning") == st.session_state.selected_language:
            st.caption(f"⚠️ Couldn't translate the interface into {st.session_state.selected_language} yet — showing English. Check your API key; this will retry automatically.")

    st.divider()

    # --- API key ---
    st.session_state.api_key = st.text_input(
        f"🔑 {t('login_key')}", value=st.session_state.api_key, type="password",
        help=t("login_key_help"),
    )

    st.divider()

    # --- Guest vs account ---
    st.markdown(f"**{t('login_choose')}**")
    login_choice = st.radio(" ", [t("login_guest"), t("login_account")],
                             label_visibility="collapsed", horizontal=True)

    account_name, account_email = "", ""
    if login_choice == t("login_account"):
        account_name = st.text_input(t("login_name"))
        account_email = st.text_input(t("login_email"))

    st.markdown('<div class="aqua-primary-btn">', unsafe_allow_html=True)
    start_clicked = st.button(f"💧 {t('login_start')}", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if start_clicked:
        if not st.session_state.selected_language or not st.session_state.api_key:
            st.error(t("login_missing"))
        elif login_choice == t("login_account") and not account_name:
            st.error(t("login_name") + " " + ("required" if st.session_state.selected_language == "English" else "*"))
        else:
            st.session_state.account_mode = "account" if login_choice == t("login_account") else "guest"
            st.session_state.customer_name = account_name
            st.session_state.customer_email = account_email
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
    st.caption(f"🗣️ Language: {st.session_state.selected_language}")
    st.caption(f"👤 {'Guest' if st.session_state.account_mode == 'guest' else (st.session_state.customer_name or 'Account')}")

    with st.expander("⚙️ Account & language"):
        lang_options = PRIMARY_LANGUAGES + EXTENDED_LANGUAGES
        current_in_list = st.session_state.selected_language in lang_options
        new_lang = st.selectbox(
            t("preferred_language"),
            lang_options + ([st.session_state.selected_language] if not current_in_list else []),
            index=lang_options.index(st.session_state.selected_language) if current_in_list
            else len(lang_options),
            key="sidebar_lang_select",
        )
        custom_lang = st.text_input("Or type any other language", key="sidebar_custom_lang",
                                     placeholder="e.g. Haitian Creole, Tagalog, Igbo...")
        target_lang = custom_lang.strip() if custom_lang.strip() else new_lang
        if target_lang != st.session_state.selected_language:
            st.session_state.selected_language = target_lang
            st.session_state.pop("chat", None)
            st.rerun()

        new_key = st.text_input("Gemini API Key", value=api_key, type="password",
                                 help="Get a key at https://aistudio.google.com/")
        if new_key != api_key:
            st.session_state.api_key = new_key
            st.rerun()
        api_key = st.session_state.api_key

        if st.button("Log out / switch account"):
            st.session_state.auth_done = False
            st.session_state.account_mode = None
            st.rerun()

    if st.button("🔄 Reset conversation"):
        st.session_state.pop("chat", None)
        st.session_state.pop("client", None)
        st.session_state.pop("_key_used", None)
        st.session_state.chat_sessions[st.session_state.current_session_id]["messages"] = []
        st.rerun()

    with st.expander("📜 View system instruction"):
        st.text(build_system_instruction(st.session_state.selected_language))

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

logo_html = f'<img src="data:image/png;base64,{logo_b64}" />' if logo_b64 else "💧"
chat_hero = f"""<div class="aqua-hero">
<div class="aqua-hero-content">
{logo_html}
<div>
<div class="aqua-hero-title">AquaAssist</div>
<div class="aqua-hero-subtitle">Your Smart Water Support Assistant</div>
</div>
</div>
<svg class="aqua-wave" viewBox="0 0 500 40" preserveAspectRatio="none">
<path class="aqua-wave-fill" d="M0,20 C150,45 350,-5 500,20 L500,40 L0,40 Z"></path>
</svg>
</div>"""
st.markdown(chat_hero, unsafe_allow_html=True)

contact_row = f"""<div class="aqua-contact-row">
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
st.markdown(contact_row, unsafe_allow_html=True)

if st.session_state.get("customer_parish"):
    for outage in get_active_outages_for_parish(st.session_state.customer_parish):
        st.warning(f"{t('outage_banner_prefix')} {outage['parish']}: {outage['message']} "
                   f"({outage['start_date']} – {outage['end_date']})")

if not api_key:
    st.info("👈 Enter your Gemini API key in the sidebar (Account & language) to start chatting.")
    st.stop()

# ---------------------------------------------------------------------------
# Initialize client + chat session (recreated when key, language, or the
# active chat session changes)
# ---------------------------------------------------------------------------
if ("chat" not in st.session_state
        or st.session_state.get("_key_used") != api_key
        or st.session_state.get("_chat_language") != st.session_state.selected_language
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
                system_instruction=build_system_instruction(st.session_state.selected_language),
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
        st.session_state._chat_language = st.session_state.selected_language
        st.session_state._chat_session_ref = st.session_state.current_session_id
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Tabs — Chat / FAQ / Report & Track / Settings
# ---------------------------------------------------------------------------
tab_chat, tab_faq, tab_report, tab_history, tab_settings = st.tabs(
    [t("tab_chat"), t("tab_faq"), t("tab_report"), t("tab_history"), t("tab_settings")]
)

# ===================== CHAT TAB =====================
with tab_chat:
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
    quick_actions = {
        t("qa_report_label"): t("qa_report_prompt"),
        t("qa_maint_label"): t("qa_maint_prompt"),
        t("qa_bill_label"): t("qa_bill_prompt"),
        t("qa_rep_label"): t("qa_rep_prompt"),
    }
    qa_cols = st.columns(len(quick_actions))
    queued_prompt = None
    for qa_idx, (col, (label, prompt)) in enumerate(zip(qa_cols, quick_actions.items())):
        with col:
            if st.button(label, use_container_width=True, key=f"qa_{qa_idx}"):
                queued_prompt = prompt

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
                reply_audio = speak_text(reply_text, TTS_LANG_CODES.get(st.session_state.selected_language, "en"))

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

                with st.spinner("Thinking..."):
                    try:
                        bot_response = st.session_state.chat.send_message(message_parts if message_parts else cleaned_input)
                        reply_text = bot_response.text
                    except Exception as e:
                        reply_text = f"⚠️ Error: {e}"

                reply_audio = None
                if st.session_state.voice_replies:
                    reply_audio = speak_text(reply_text, TTS_LANG_CODES.get(st.session_state.selected_language, "en"))

                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": reply_audio})
                st.rerun()


# ===================== HISTORY TAB =====================
with tab_history:
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

# ===================== FAQ TAB =====================
with tab_faq:
    st.markdown('<div class="aqua-section-label">❓ Frequently Asked Questions</div>', unsafe_allow_html=True)
    st.caption("Sourced from the official NAWASA FAQ page (nawasa.gd).")

    active_faqs = FAQS
    if st.session_state.selected_language != "English":
        with st.spinner(f"Loading FAQs in {st.session_state.selected_language}..."):
            active_faqs = get_translated_faqs(st.session_state.selected_language, st.session_state.client)
        if active_faqs is FAQS:
            st.caption(f"⚠️ Couldn't translate FAQs into {st.session_state.selected_language} right now — showing English.")

    faq_query = st.text_input("Search FAQs", placeholder="e.g. billing, leak, disconnection...")
    results = search_faqs(faq_query, active_faqs)
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
                    audio = speak_text(f["a"], TTS_LANG_CODES.get(st.session_state.selected_language, "en"))
                    if audio:
                        st.audio(audio)

# ===================== REPORT & TRACK TAB =====================
with tab_report:
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

# ===================== SETTINGS TAB =====================
with tab_settings:
    st.markdown(f'<div class="aqua-section-label">{t("settings_preferences")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)

    lang_options = PRIMARY_LANGUAGES + EXTENDED_LANGUAGES
    current_in_list = st.session_state.selected_language in lang_options
    new_lang = st.selectbox(
        t("preferred_language"),
        lang_options + ([st.session_state.selected_language] if not current_in_list else []),
        index=lang_options.index(st.session_state.selected_language) if current_in_list
        else len(lang_options),
        key="settings_lang_select",
    )
    custom_lang = st.text_input("Or type any other language", key="settings_custom_lang",
                                 placeholder="e.g. Haitian Creole, Tagalog, Igbo...")
    target_lang = custom_lang.strip() if custom_lang.strip() else new_lang
    if target_lang != st.session_state.selected_language:
        st.session_state.selected_language = target_lang
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
