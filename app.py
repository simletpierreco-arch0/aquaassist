"""
AquaAssist — Streamlit UI (Major upgrade)
NAWASA (National Water and Sewerage Authority, Grenada) AI customer support platform.

Run with:
    pip install -r requirements.txt
    streamlit run app.py

Folder layout expected:
    app.py
    assets/aquaassist_logo.png
    .streamlit/config.toml
    data/reports.csv          (auto-created)
    data/notifications.csv    (auto-created)
    attachments/              (auto-created, uploaded report files)

BEFORE DEPLOYING:
    STAFF_PASSCODE -> replace "changeme123" below, or set as env var / Streamlit secret

WHAT'S FULLY WORKING vs SIMPLIFIED (read this before demoing to a client):
  - Language selector, FAQ search, report tracking with reference numbers,
    file uploads on reports, settings (dark mode/high contrast/large text),
    notifications signup, AI-driven report logging: all fully working.
  - Voice OUTPUT: uses gTTS (Google Text-to-Speech) to generate real spoken
    audio of the bot's replies — fully working, needs internet at runtime.
  - Voice INPUT: Streamlit has no native microphone/live-recording support.
    This build lets customers UPLOAD a voice note (recorded in their phone's
    voice memo app) which Gemini transcribes and understands directly. For
    true in-browser one-tap mic recording, install the optional package
    `audio-recorder-streamlit` — the code below auto-detects it and upgrades
    to live recording if present, with the upload fallback if not.
  - GPS location: same story — no native browser GPS permission prompt in
    Streamlit. Customers type/select their location manually by default.
    If you install the optional package `streamlit-geolocation`, this code
    auto-detects it and offers a one-tap "use my location" button.
  - Conversation memory / history: kept for the current browser session only
    (name, language, past messages). True persistent memory across visits/
    devices needs user accounts + a database — out of scope for this build,
    flagged here so expectations are accurate.
  - UI translation: the AI's chat REPLIES adapt to whatever language the
    customer types in (this uses Gemini's own multilingual ability, works
    for effectively any language/dialect). The UI CHROME (buttons, labels)
    is fully translated for the 4 pinned languages (English, Grenadian
    Creole, Spanish, French). Additional languages in the picker change
    which language the AI replies in, but interface labels stay in English
    until translated — hand-translating 25+ languages of UI strings without
    a native speaker to verify them risks shipping wrong/awkward text.
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
ATTACHMENTS_DIR = "attachments"
REPORTS_FIELDS = ["reference", "timestamp", "name", "phone", "location", "issue_type",
                   "description", "attachment", "status"]
NOTIFY_FIELDS = ["timestamp", "contact", "categories"]
STATUS_STAGES = ["Received", "Assigned", "Crew Dispatched", "In Progress", "Resolved"]

st.set_page_config(
    page_title="AquaAssist",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "💧",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
defaults = {
    "selected_language": None,
    "customer_name": "",
    "dark_mode": False,
    "high_contrast": False,
    "large_text": False,
    "voice_replies": False,
    "messages": [],
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

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

# UI text translations — fully covers the 4 pinned languages. Other languages
# fall back to English UI chrome (see note at top of file).
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
        "voice_toggle_label": "🔊 Speak replies aloud", "voice_popover_label": "🎤 Send a voice message",
        "voice_help_on": "Uses gTTS to read the bot's replies aloud.", "voice_help_off": "Install gTTS to enable this.",
        "issue_leak": "Leak", "issue_no_water": "No water supply", "issue_low_pressure": "Low pressure",
        "issue_billing": "Billing issue", "issue_burst": "Burst main", "issue_hydrant": "Damaged hydrant",
        "issue_quality": "Water quality concern", "issue_other": "Other",
    },
    "Grenadian Creole": {
        "welcome": "Welcome to AquaAssist! 💧 Ah deh fu help yuh wit yuh NAWASA watah service dem.",
        "tab_chat": "💬 Chat", "tab_faq": "❓ FAQ", "tab_report": "📋 Report & Track",
        "tab_history": "🕘 History", "tab_settings": "⚙️ Settings",
        "report_issue": "🚿 Report an issue",
        "quick_actions": "💧 Quick actions", "ask_placeholder": "Aks AquaAssist sumting...",
        "your_name": "Yuh name", "continue": "Continue",
        "call_us": "Call We", "whatsapp_label": "WhatsApp", "chat_now": "Chat now",
        "website_label": "Website",
        "qa_report_label": "🚿 Report a Leak", "qa_report_prompt": "Ah want fu report a watah leak.",
        "qa_maint_label": "🛠️ Maintenance", "qa_maint_prompt": "It got any outage or maintenance planned fu meh area?",
        "qa_bill_label": "💳 Pay My Bill", "qa_bill_prompt": "How ah could pay meh NAWASA bill?",
        "qa_rep_label": "📞 Talk to a Rep", "qa_rep_prompt": "Ah want fu talk to a customer service representative.",
        "settings_preferences": "⚙️ Preferences", "preferred_language": "Language yuh prefer",
        "dark_mode": "🌙 Dark mode", "high_contrast": "🔲 High contrast mode", "large_text": "🔠 Bigger letters",
        "accessibility_note": "Accessibility: dis app support keyboard navigation and screen readers.",
        "settings_conversation": "💬 Chat",
        "conversation_note": "message dem in dis session. Go to the History tab fu search or clear yuh chat.",
        "field_name": "Yuh name", "field_phone": "Phone numbah",
        "field_location": "Location / address wey de issue deh", "field_description": "Describe de issue",
        "field_issue_type": "Kine ah issue", "field_attachment": "Attach a photo, video, or document (optional)",
        "submit_report": "Send de report", "report_form_expander": "Fill out a report — it does go straight to NAWASA staff",
        "track_report_label": "📍 Track a report", "track_report_placeholder": "Put in yuh reference numbah (e.g. NW-A1B2C3D)",
        "get_notified": "🔔 Get notify", "notify_contact_label": "Email or phone numbah",
        "notify_categories_label": "Notify me bout", "subscribe_button": "Subscribe",
        "voice_toggle_label": "🔊 Speak reply dem out loud", "voice_popover_label": "🎤 Send a voice message",
        "voice_help_on": "Uses gTTS fu read de bot reply dem out loud.", "voice_help_off": "Install gTTS fu enable dis.",
        "issue_leak": "Leak", "issue_no_water": "No watah supply", "issue_low_pressure": "Low pressure",
        "issue_billing": "Billing issue", "issue_burst": "Burst main", "issue_hydrant": "Damaged hydrant",
        "issue_quality": "Watah quality concern", "issue_other": "Other",
    },
    "Spanish": {
        "welcome": "¡Bienvenido a AquaAssist! 💧 Estoy aquí para ayudarte con los servicios de agua de NAWASA.",
        "tab_chat": "💬 Chat", "tab_faq": "❓ Preguntas", "tab_report": "📋 Reportar y Rastrear",
        "tab_history": "🕘 Historial", "tab_settings": "⚙️ Ajustes",
        "report_issue": "🚿 Reportar un problema",
        "quick_actions": "💧 Acciones rápidas", "ask_placeholder": "Pregúntale algo a AquaAssist...",
        "your_name": "Tu nombre", "continue": "Continuar",
        "call_us": "Llámanos", "whatsapp_label": "WhatsApp", "chat_now": "Chatea ahora",
        "website_label": "Sitio web",
        "qa_report_label": "🚿 Reportar una Fuga", "qa_report_prompt": "Quisiera reportar una fuga de agua.",
        "qa_maint_label": "🛠️ Mantenimiento", "qa_maint_prompt": "¿Hay cortes o mantenimiento programado en mi área?",
        "qa_bill_label": "💳 Pagar mi Factura", "qa_bill_prompt": "¿Cuáles son mis opciones para pagar mi factura de NAWASA?",
        "qa_rep_label": "📞 Hablar con un Agente", "qa_rep_prompt": "Quisiera hablar con un representante de servicio al cliente.",
        "settings_preferences": "⚙️ Preferencias", "preferred_language": "Idioma preferido",
        "dark_mode": "🌙 Modo oscuro", "high_contrast": "🔲 Modo de alto contraste", "large_text": "🔠 Texto más grande",
        "accessibility_note": "Accesibilidad: esta app admite navegación por teclado y lectores de pantalla de forma nativa.",
        "settings_conversation": "💬 Conversación",
        "conversation_note": "mensajes en esta sesión. Ve a la pestaña Historial para buscar o borrar tu conversación.",
        "field_name": "Tu nombre", "field_phone": "Número de teléfono",
        "field_location": "Ubicación / dirección del problema", "field_description": "Describe el problema",
        "field_issue_type": "Tipo de problema", "field_attachment": "Adjunta una foto, video o documento (opcional)",
        "submit_report": "Enviar reporte", "report_form_expander": "Completa un reporte — va directo al personal de NAWASA",
        "track_report_label": "📍 Rastrear un reporte", "track_report_placeholder": "Ingresa tu número de referencia (ej. NW-A1B2C3D)",
        "get_notified": "🔔 Recibir notificaciones", "notify_contact_label": "Correo o número de teléfono",
        "notify_categories_label": "Notificarme sobre", "subscribe_button": "Suscribirse",
        "voice_toggle_label": "🔊 Escuchar las respuestas en voz alta", "voice_popover_label": "🎤 Enviar un mensaje de voz",
        "voice_help_on": "Usa gTTS para leer las respuestas del bot en voz alta.", "voice_help_off": "Instala gTTS para habilitar esto.",
        "issue_leak": "Fuga", "issue_no_water": "Sin suministro de agua", "issue_low_pressure": "Baja presión",
        "issue_billing": "Problema de facturación", "issue_burst": "Rotura de tubería principal", "issue_hydrant": "Hidrante dañado",
        "issue_quality": "Problema de calidad del agua", "issue_other": "Otro",
    },
    "French": {
        "welcome": "Bienvenue chez AquaAssist! 💧 Je suis là pour vous aider avec les services d'eau de la NAWASA.",
        "tab_chat": "💬 Discussion", "tab_faq": "❓ FAQ", "tab_report": "📋 Signaler et Suivre",
        "tab_history": "🕘 Historique", "tab_settings": "⚙️ Paramètres",
        "report_issue": "🚿 Signaler un problème",
        "quick_actions": "💧 Actions rapides", "ask_placeholder": "Demandez quelque chose à AquaAssist...",
        "your_name": "Votre nom", "continue": "Continuer",
        "call_us": "Appelez-nous", "whatsapp_label": "WhatsApp", "chat_now": "Discuter maintenant",
        "website_label": "Site web",
        "qa_report_label": "🚿 Signaler une Fuite", "qa_report_prompt": "Je voudrais signaler une fuite d'eau.",
        "qa_maint_label": "🛠️ Entretien", "qa_maint_prompt": "Y a-t-il des coupures ou un entretien prévu dans ma région?",
        "qa_bill_label": "💳 Payer ma Facture", "qa_bill_prompt": "Quelles sont mes options pour payer ma facture NAWASA?",
        "qa_rep_label": "📞 Parler à un Agent", "qa_rep_prompt": "Je voudrais parler à un représentant du service client.",
        "settings_preferences": "⚙️ Préférences", "preferred_language": "Langue préférée",
        "dark_mode": "🌙 Mode sombre", "high_contrast": "🔲 Mode contraste élevé", "large_text": "🔠 Texte plus grand",
        "accessibility_note": "Accessibilité: cette application prend en charge la navigation au clavier et les lecteurs d'écran nativement.",
        "settings_conversation": "💬 Conversation",
        "conversation_note": "messages dans cette session. Allez à l'onglet Historique pour rechercher ou effacer votre conversation.",
        "field_name": "Votre nom", "field_phone": "Numéro de téléphone",
        "field_location": "Emplacement / adresse du problème", "field_description": "Décrivez le problème",
        "field_issue_type": "Type de problème", "field_attachment": "Joindre une photo, vidéo ou document (facultatif)",
        "submit_report": "Envoyer le signalement", "report_form_expander": "Remplissez un signalement — il va directement au personnel de la NAWASA",
        "track_report_label": "📍 Suivre un signalement", "track_report_placeholder": "Entrez votre numéro de référence (ex. NW-A1B2C3D)",
        "get_notified": "🔔 Recevoir des notifications", "notify_contact_label": "E-mail ou numéro de téléphone",
        "notify_categories_label": "Me notifier à propos de", "subscribe_button": "S'abonner",
        "voice_toggle_label": "🔊 Lire les réponses à voix haute", "voice_popover_label": "🎤 Envoyer un message vocal",
        "voice_help_on": "Utilise gTTS pour lire les réponses du bot à voix haute.", "voice_help_off": "Installez gTTS pour activer ceci.",
        "issue_leak": "Fuite", "issue_no_water": "Pas d'eau", "issue_low_pressure": "Faible pression",
        "issue_billing": "Problème de facturation", "issue_burst": "Canalisation principale rompue", "issue_hydrant": "Borne d'incendie endommagée",
        "issue_quality": "Problème de qualité de l'eau", "issue_other": "Autre",
    },
}

def t(key):
    lang = st.session_state.get("selected_language") or "English"
    return UI_TEXT.get(lang, UI_TEXT["English"]).get(key, UI_TEXT["English"].get(key, key))

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
# Brand palette — swaps for dark mode / high contrast
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
    BRAND_CREAM = "#12181F"
    BRAND_CREAM_SOFT = "#1C2530"
    BRAND_WHITE = "#1C2530"
else:
    BRAND_BLUE = "#0B76C7"
    BRAND_BLUE_LIGHT = "#4FA8E0"
    BRAND_BLUE_DARK = "#0B2545"
    BRAND_CREAM = "#FDF9F0"
    BRAND_CREAM_SOFT = "#F5EEDC"
    BRAND_WHITE = "#FFFFFF"

WHATSAPP_GREEN = "#25D366"
BASE_FONT_SIZE = "1.15rem" if st.session_state.large_text else "0.95rem"

logo_b64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()

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
}}
.block-container {{
padding-top: 1rem;
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
section[data-testid="stSidebar"] {{
background-color: {BRAND_WHITE};
border-right: 1px solid {BRAND_BLUE}22;
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
def ensure_files():
    os.makedirs(os.path.dirname(REPORTS_PATH), exist_ok=True)
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    if not os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writeheader()
    if not os.path.exists(NOTIFY_PATH):
        with open(NOTIFY_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=NOTIFY_FIELDS).writeheader()

def new_reference():
    return "NW-" + uuid.uuid4().hex[:7].upper()

def save_report(name, phone, location, issue_type, description, attachment_name=""):
    ensure_files()
    reference = new_reference()
    with open(REPORTS_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writerow({
            "reference": reference,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name, "phone": phone, "location": location,
            "issue_type": issue_type, "description": description,
            "attachment": attachment_name, "status": "Received",
        })
    return reference

def load_reports():
    ensure_files()
    import pandas as pd
    return pd.read_csv(REPORTS_PATH)

def update_report_status(reference, new_status):
    import pandas as pd
    df = load_reports()
    df.loc[df["reference"] == reference, "status"] = new_status
    df.to_csv(REPORTS_PATH, index=False)

def track_report(reference):
    df = load_reports()
    match = df[df["reference"].str.upper() == reference.strip().upper()]
    return match.iloc[0] if not match.empty else None

def save_notification_signup(contact, categories):
    ensure_files()
    with open(NOTIFY_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=NOTIFY_FIELDS).writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contact": contact, "categories": ", ".join(categories),
        })

# ---------------------------------------------------------------------------
# Tool the AI can call directly during conversation to log a report
# ---------------------------------------------------------------------------
def log_water_report(location: str, issue_type: str, description: str,
                      name: str = "Not provided", phone: str = "Not provided") -> str:
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

    Returns:
        A confirmation message including the reference number for tracking.
    """
    reference = save_report(name, phone, location, issue_type, description)
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

TTS_LANG_CODES = {"English": "en", "Spanish": "es", "French": "fr", "Grenadian Creole": "en"}

# ---------------------------------------------------------------------------
# LANGUAGE SELECTION GATE — first screen on a fresh session
# ---------------------------------------------------------------------------
if st.session_state.selected_language is None:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=110)
    st.markdown("### 🌐 Choose your language / Escoja su idioma / Choisissez votre langue")
    st.caption("Pin your language below. The AI will also automatically follow whatever language you type in during chat.")

    cols = st.columns(4)
    for col, lang in zip(cols, PRIMARY_LANGUAGES):
        with col:
            if st.button(lang, use_container_width=True, key=f"lang_{lang}"):
                st.session_state.selected_language = lang
                st.rerun()

    with st.expander("More languages"):
        extra = st.selectbox("Search / select a language", [""] + EXTENDED_LANGUAGES)
        if extra and st.button(f"Continue in {extra}"):
            st.session_state.selected_language = extra
            st.rerun()

    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)

    mode = st.radio("View", ["💬 Customer Portal", "🔐 Staff Portal"], label_visibility="collapsed")

    st.markdown(
        f'<a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-btn">📱 Chat on WhatsApp</a>',
        unsafe_allow_html=True,
    )
    st.caption(f"📞 {NAWASA_PHONE}")
    st.caption(f"🌐 [nawasa.gd]({NAWASA_WEBSITE})")
    st.caption(f"🗣️ Language: {st.session_state.selected_language}")
    if st.button("Change language"):
        st.session_state.selected_language = None
        st.rerun()

    st.divider()
    st.header("⚙️ Settings")
    default_key = os.environ.get("GEMINI_API_KEY", "")
    api_key = st.text_input("Gemini API Key", value=default_key, type="password",
                             help="Get a key at https://aistudio.google.com/")
    st.caption(f"Model: `{MODEL_NAME}`")

    if st.button("🔄 Reset conversation"):
        st.session_state.pop("chat", None)
        st.session_state.pop("client", None)
        st.session_state.pop("_key_used", None)
        st.session_state.messages = []
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
        edited_df = st.data_editor(
            reports_df,
            use_container_width=True,
            column_config={
                "status": st.column_config.SelectboxColumn("status", options=STATUS_STAGES),
            },
            disabled=[c for c in REPORTS_FIELDS if c != "status"],
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

if not st.session_state.customer_name:
    with st.expander(f"👋 {t('your_name')} (optional, helps us personalize your visit)"):
        name_input = st.text_input(t("your_name"), key="name_capture")
        if name_input:
            st.session_state.customer_name = name_input
            st.rerun()

if not api_key:
    st.info("👈 Enter your Gemini API key in the sidebar to start chatting.")
    st.stop()

# ---------------------------------------------------------------------------
# Initialize client + chat session
# ---------------------------------------------------------------------------
if ("chat" not in st.session_state
        or st.session_state.get("_key_used") != api_key
        or st.session_state.get("_chat_language") != st.session_state.selected_language):
    try:
        client = genai.Client(api_key=api_key)
        st.session_state.client = client
        st.session_state.chat = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=build_system_instruction(st.session_state.selected_language),
                temperature=0.7,
                tools=[log_water_report],
            ),
        )
        st.session_state._key_used = api_key
        st.session_state._chat_language = st.session_state.selected_language
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
    st.markdown(f'<div class="aqua-section-label">{t("quick_actions")}</div>', unsafe_allow_html=True)
    quick_actions = {
        t("qa_report_label"): t("qa_report_prompt"),
        t("qa_maint_label"): t("qa_maint_prompt"),
        t("qa_bill_label"): t("qa_bill_prompt"),
        t("qa_rep_label"): t("qa_rep_prompt"),
    }
    qa_cols = st.columns(len(quick_actions))
    queued_prompt = None
    for col, (label, prompt) in zip(qa_cols, quick_actions.items()):
        with col:
            if st.button(label, use_container_width=True):
                queued_prompt = prompt

    voice_col1, voice_col2 = st.columns([1, 1])
    with voice_col1:
        st.session_state.voice_replies = st.toggle(
            t("voice_toggle_label"), value=st.session_state.voice_replies,
            disabled=not HAS_TTS,
            help=t("voice_help_on") if HAS_TTS else t("voice_help_off"),
        )

    voice_text_input = None
    with voice_col2:
        with st.popover(t("voice_popover_label")):
            if HAS_MIC_RECORDER:
                audio_bytes = audio_recorder(text="Tap to record", icon_size="2x")
                if audio_bytes:
                    st.audio(audio_bytes)
                    if st.button("Send recording"):
                        voice_text_input = ("__AUDIO__", audio_bytes, "audio/wav")
            else:
                st.caption("Live mic recording isn't installed. Upload a voice note instead:")
                uploaded_audio = st.file_uploader("Voice note", type=["mp3", "wav", "m4a", "ogg"], key="voice_upload")
                if uploaded_audio and st.button("Send this voice note"):
                    voice_text_input = ("__AUDIO__", uploaded_audio.read(), uploaded_audio.type or "audio/mpeg")

    st.markdown('<div class="aqua-section-label">💬 Chat</div>', unsafe_allow_html=True)

    ASSISTANT_AVATAR = LOGO_PATH if os.path.exists(LOGO_PATH) else "💧"
    USER_AVATAR = "🧑"

    for msg in st.session_state.messages:
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else USER_AVATAR
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("audio"):
                st.audio(msg["audio"])

    if not st.session_state.messages:
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.markdown(t("welcome"))

    typed_input = st.chat_input(t("ask_placeholder"))

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
            with st.chat_message("user", avatar=USER_AVATAR):
                st.markdown("🎤 (voice message)")
                st.audio(audio_bytes)

            with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
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
                st.markdown(reply_text)
                reply_audio = None
                if st.session_state.voice_replies:
                    reply_audio = speak_text(reply_text, TTS_LANG_CODES.get(st.session_state.selected_language, "en"))
                    if reply_audio:
                        st.audio(reply_audio)
            st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": reply_audio})
        else:
            cleaned_input = user_turn.strip()
            if cleaned_input:
                st.session_state.messages.append({"role": "user", "content": cleaned_input})
                with st.chat_message("user", avatar=USER_AVATAR):
                    st.markdown(cleaned_input)

                with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
                    with st.spinner("Thinking..."):
                        try:
                            bot_response = st.session_state.chat.send_message(cleaned_input)
                            reply_text = bot_response.text
                        except Exception as e:
                            reply_text = f"⚠️ Error: {e}"
                    st.markdown(reply_text)
                    reply_audio = None
                    if st.session_state.voice_replies:
                        reply_audio = speak_text(reply_text, TTS_LANG_CODES.get(st.session_state.selected_language, "en"))
                        if reply_audio:
                            st.audio(reply_audio)
                st.session_state.messages.append({"role": "assistant", "content": reply_text, "audio": reply_audio})


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
        st.session_state.messages = []
        st.rerun()
    st.caption("Note: history is kept for this browser session only. Closing the tab clears it — persistent history across visits would need user accounts, which isn't part of this build yet.")
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
            for f in [x for x in results if x["category"] == cat]:
                faq_html = f"""<div class="aqua-faq-item">
<div class="aqua-faq-cat">{f['category']}</div>
<b>{f['q']}</b><br>{f['a']}
</div>"""
                st.markdown(faq_html, unsafe_allow_html=True)
                if HAS_TTS and st.button(f"🔊 Read aloud", key=f"faq_audio_{f['q'][:20]}"):
                    audio = speak_text(f["a"], TTS_LANG_CODES.get(st.session_state.selected_language, "en"))
                    if audio:
                        st.audio(audio)

# ===================== REPORT & TRACK TAB =====================
with tab_report:
    st.markdown(f'<div class="aqua-section-label">{t("report_issue")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.expander(t("report_form_expander"), expanded=True):
        with st.form("leak_report_form", clear_on_submit=True):
            r_name = st.text_input(t("field_name"), value=st.session_state.customer_name)
            r_phone = st.text_input(t("field_phone"))

            loc_col1, loc_col2 = st.columns([3, 1])
            with loc_col1:
                r_location = st.text_input(t("field_location"))
            with loc_col2:
                if HAS_GEOLOCATION:
                    coords = streamlit_geolocation()
                    if coords and coords.get("latitude"):
                        r_location = f"{r_location} (GPS: {coords['latitude']:.5f}, {coords['longitude']:.5f})"
                        st.caption("📍 location captured")
                else:
                    st.caption("📍 GPS not installed — enter address manually")

            # Internal values stay in English for consistency in the Staff
            # Portal regardless of the customer's language; only the label
            # shown to the customer is translated.
            issue_type_keys = ["issue_leak", "issue_no_water", "issue_low_pressure", "issue_billing",
                                "issue_burst", "issue_hydrant", "issue_quality", "issue_other"]
            issue_type_values = ["Leak", "No water supply", "Low pressure", "Billing issue",
                                  "Burst main", "Damaged hydrant", "Water quality concern", "Other"]
            r_issue_type = st.selectbox(t("field_issue_type"), issue_type_values,
                                          format_func=lambda v: t(issue_type_keys[issue_type_values.index(v)]))
            r_description = st.text_area(t("field_description"))
            r_attachment = st.file_uploader(t("field_attachment"),
                                              type=["jpg", "jpeg", "png", "mp4", "mov", "pdf", "doc", "docx"])
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
                            out.write(r_attachment.read())
                    reference = save_report(r_name, r_phone, r_location, r_issue_type,
                                             r_description, attachment_name)
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

    new_lang = st.selectbox(t("preferred_language"), PRIMARY_LANGUAGES + EXTENDED_LANGUAGES,
                              index=(PRIMARY_LANGUAGES + EXTENDED_LANGUAGES).index(st.session_state.selected_language)
                              if st.session_state.selected_language in PRIMARY_LANGUAGES + EXTENDED_LANGUAGES else 0)
    if new_lang != st.session_state.selected_language:
        st.session_state.selected_language = new_lang
        st.rerun()

    st.session_state.dark_mode = st.toggle(t("dark_mode"), value=st.session_state.dark_mode)
    st.session_state.high_contrast = st.toggle(t("high_contrast"), value=st.session_state.high_contrast)
    st.session_state.large_text = st.toggle(t("large_text"), value=st.session_state.large_text)
    st.caption(t("accessibility_note"))

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="aqua-section-label">{t("settings_conversation")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.caption(f"{len(st.session_state.messages)} {t('conversation_note')}")
    st.markdown('</div>', unsafe_allow_html=True)
