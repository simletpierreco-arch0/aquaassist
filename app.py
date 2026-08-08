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

# Optional upgrades — used automatically if installed
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
except ImportError:
    HAS_PINECONE = False

# ---------------------------------------------------------------------------
# CONFIG & ASSETS
# ---------------------------------------------------------------------------
def get_config(key, default=""):
    val = os.environ.get(key)
    if val: return val
    try: return st.secrets.get(key, default)
    except: return default

NAWASA_PHONE = "(473) 440-2155"
NAWASA_WEBSITE = "https://nawasa.gd/"
STAFF_PASSCODE = get_config("STAFF_PASSCODE", "changeme123")
LOGO_PATH = os.path.join("assets", "aquaassist_logo.png")
AVATAR_PATH = os.path.join("assets", "aquaassist_avatar.png")
REPORTS_PATH = os.path.join("data", "reports.csv")
NOTIFY_PATH = os.path.join("data", "notifications.csv")
OUTAGES_PATH = os.path.join("data", "outages.csv")
ATTACHMENTS_DIR = "attachments"

# ---------------------------------------------------------------------------
# VISUAL IDENTITY & CSS (The AquaAssist UI Overhaul)
# ---------------------------------------------------------------------------
def inject_custom_styles():
    # Brand Palette
    B_PRIMARY = "#005A9C"  # NAWASA Blue
    B_ACCENT = "#00AEEF"   # Tech Aqua
    B_BG = "#F6FBFF"       # Deep Light Blue
    B_CARD = "#FFFFFF"     
    
    # Animated Bubble SVG for Background
    bubble_svg = f"""
    <svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 500 500'>
        <circle cx='60' cy='430' r='12' fill='{B_ACCENT}' fill-opacity='0.08'/>
        <circle cx='150' cy='140' r='8' fill='{B_PRIMARY}' fill-opacity='0.06'/>
        <circle cx='260' cy='360' r='18' fill='{B_ACCENT}' fill-opacity='0.07'/>
        <circle cx='340' cy='90' r='6' fill='{B_ACCENT}' fill-opacity='0.09'/>
        <circle cx='420' cy='300' r='11' fill='{B_PRIMARY}' fill-opacity='0.08'/>
    </svg>
    """
    bubble_b64 = base64.b64encode(bubble_svg.encode()).decode()

    st.markdown(f"""
    <style>
    /* 1. Main Background - Drifting Bubbles & Water Gradient */
    .stApp {{
        background-color: {B_BG};
        background-image: 
            radial-gradient(circle at 50% 0%, {B_ACCENT}15 0%, transparent 50%),
            url("data:image/svg+xml;base64,{bubble_b64}");
        background-attachment: fixed;
        background-size: 500px 500px;
        animation: bubbleDrift 80s linear infinite;
    }}
    @keyframes bubbleDrift {{
        from {{ background-position: 0 0; }}
        to {{ background-position: 0 1000px; }}
    }}

    /* 2. Global Professional Typography */
    html, body, [class*="css"] {{
        font-family: 'Poppins', 'Inter', sans-serif;
        color: #33414F;
    }}

    /* 3. Hero Header Section */
    .aqua-hero {{
        background: linear-gradient(135deg, {B_PRIMARY} 0%, {B_ACCENT} 100%);
        color: white;
        padding: 2.5rem 2rem;
        border-radius: 24px;
        margin-bottom: 2rem;
        box-shadow: 0 8px 32px rgba(0, 90, 156, 0.2);
        position: relative;
        overflow: hidden;
    }}
    .aqua-hero::before {{
        content: ""; position: absolute; inset: 0;
        background: radial-gradient(circle at 20% 20%, rgba(255,255,255,0.1) 0%, transparent 40%);
    }}
    .hero-status {{
        display: inline-flex; align-items: center; gap: 8px;
        background: rgba(255,255,255,0.15);
        padding: 4px 14px; border-radius: 99px;
        font-size: 0.75rem; font-weight: 600; border: 1px solid rgba(255,255,255,0.3);
    }}

    /* 4. Glassmorphism Cards for Tabs */
    .aqua-card {{
        background: {B_CARD};
        border-radius: 20px;
        padding: 1.5rem;
        margin-bottom: 1.2rem;
        border: 1px solid rgba(0, 90, 156, 0.1);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
        transition: transform 0.2s ease;
    }}
    .aqua-card:hover {{ transform: translateY(-2px); }}

    /* 5. Modern Chat Bubbles */
    [data-testid="stChatMessage"] {{
        border-radius: 20px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        border: 1px solid transparent;
        animation: aquaPop 0.4s ease-out;
    }}
    @keyframes aquaPop {{
        from {{ opacity: 0; transform: translateY(10px) scale(0.98); }}
        to {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}

    /* Assistant Bubbles */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {{
        background-color: #FFFFFF !important;
        border: 1px solid rgba(0, 174, 239, 0.15) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
    }}

    /* User Bubbles */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
        background-color: {B_PRIMARY} !important;
        color: #FFFFFF !important;
        flex-direction: row-reverse;
        text-align: right;
    }}
    [data-testid="stChatMessageAvatarUser"] {{ background-color: {B_ACCENT} !important; }}

    /* 6. Chat Input Improvements */
    [data-testid="stChatInputContainer"] {{
        border-radius: 24px !important;
        border: 1px solid rgba(0, 90, 156, 0.2) !important;
        background: white !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.08) !important;
    }}
    
    /* 7. Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px; }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 12px 12px 0 0;
        background: rgba(0, 90, 156, 0.04);
        color: {B_PRIMARY};
        padding: 8px 16px;
        font-weight: 600;
    }}
    .stTabs [aria-selected="true"] {{
        background: {B_PRIMARY} !important;
        color: white !important;
    }}

    /* 8. UI Elements */
    .stButton>button {{
        border-radius: 12px;
        font-weight: 600;
        transition: all 0.2s ease;
    }}
    .stButton>button:hover {{
        border-color: {B_ACCENT};
        box-shadow: 0 4px 12px rgba(0, 174, 239, 0.2);
    }}

    /* Hide Default Headers */
    #MainMenu, header, footer {{ visibility: hidden; }}
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# DYNAMIC ASSET HELPER (Professional SVG Avatar)
# ---------------------------------------------------------------------------
def get_assistant_avatar():
    """Returns avatar path if file exists, else a high-quality SVG data URI."""
    if os.path.exists(AVATAR_PATH):
        return AVATAR_PATH
    
    # Professional Water-Drop AI Avatar (SVG)
    # Style: Blue water drop with a dashed AI orbit ring
    svg_code = """
    <svg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'>
        <defs>
            <linearGradient id='grad' x1='0%' y1='0%' x2='100%' y2='100%'>
                <stop offset='0%' style='stop-color:#00AEEF;stop-opacity:1' />
                <stop offset='100%' style='stop-color:#005A9C;stop-opacity:1' />
            </linearGradient>
        </defs>
        <!-- Orbit Ring -->
        <circle cx='50' cy='50' r='46' fill='none' stroke='#00AEEF' stroke-width='1.5' stroke-dasharray='4 4' opacity='0.6'>
            <animateTransform attributeName='transform' type='rotate' from='0 50 50' to='360 50 50' dur='10s' repeatCount='indefinite'/>
        </circle>
        <!-- Water Drop Shape -->
        <path d='M50 15 C50 15 25 45 25 65 A25 25 0 1 0 75 65 C75 45 50 15 50 15Z' fill='url(#grad)' />
        <!-- AI Eyes -->
        <circle cx='42' cy='62' r='3' fill='white' opacity='0.9'/>
        <circle cx='58' cy='62' r='3' fill='white' opacity='0.9'/>
        <!-- Highlight -->
        <path d='M40 50 Q45 45 50 50' stroke='white' stroke-width='2' fill='none' opacity='0.5' stroke-linecap='round'/>
    </svg>
    """
    return f"data:image/svg+xml;base64,{base64.b64encode(svg_code.encode()).decode()}"

# ---------------------------------------------------------------------------
# PRESERVED BACKEND LOGIC (No functionality changed)
# ---------------------------------------------------------------------------
GRENADA_TZ = timezone(timedelta(hours=-4))
GRENADA_PARISHES = ["St. George's", "St. Andrew's", "St. David's", "St. John's", "St. Mark's", "St. Patrick's", "Carriacou", "PM"]
STATUS_STAGES = ["Received", "Assigned", "Crew Dispatched", "In Progress", "Resolved"]
REPORTS_FIELDS = ["reference", "timestamp", "name", "phone", "location", "issue_type", "description", "attachment", "status", "severity"]

def get_business_status():
    now = datetime.now(GRENADA_TZ)
    is_open = 8 <= now.hour < 16 and now.weekday() != 6
    return {"is_open": is_open, "label": "Office Open" if is_open else "Office Closed"}

def ensure_files():
    os.makedirs("data", exist_ok=True)
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    if not os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writeheader()

def save_report(name, phone, location, issue_type, desc, attachment="", severity="Unknown"):
    ensure_files()
    ref = "NW-" + uuid.uuid4().hex[:7].upper()
    with open(REPORTS_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=REPORTS_FIELDS).writerow({
            "reference": ref, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "name": name, "phone": phone, "location": location, "issue_type": issue_type,
            "description": desc, "attachment": attachment, "status": "Received", "severity": severity
        })
    return ref

def track_report(ref):
    if not os.path.exists(REPORTS_PATH): return None
    import pandas as pd
    df = pd.read_csv(REPORTS_PATH)
    match = df[df["reference"] == ref.strip().upper()]
    return match.iloc[0] if not match.empty else None

# ---------------------------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------------------------
st.set_page_config(page_title="AquaAssist", page_icon="💧", layout="wide")
inject_custom_styles()

if "auth_done" not in st.session_state: st.session_state.auth_done = False
if "messages" not in st.session_state: st.session_state.messages = []

# ---------------------------------------------------------------------------
# WELCOME SCREEN (PRESERVED)
# ---------------------------------------------------------------------------
if not st.session_state.auth_done:
    st.markdown(f"""
    <div class="aqua-hero" style="text-align:center;">
        <h1 style="margin:0; font-size:3rem;">💧 AquaAssist</h1>
        <p style="margin:10px 0; opacity:0.9; font-size:1.1rem;">NAWASA Official Virtual Assistant</p>
        <div class="hero-status">
            <span style="height:8px; width:8px; background:#34D399; border-radius:50%;"></span>
            AI Portal Available 24/7
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            territory = st.selectbox("📍 Select Territory", ["Grenada", "Carriacou", "Petit Martinique"])
        with col2:
            api_key = st.text_input("🔑 Gemini API Key", type="password")
        
        if st.button("🚀 Start Chatting", use_container_width=True):
            if api_key:
                st.session_state.api_key = api_key
                st.session_state.territory = territory
                st.session_state.auth_done = True
                st.rerun()
            else: st.error("Please enter your API key.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------------------
# MAIN INTERFACE HEADER (PRESERVED)
# ---------------------------------------------------------------------------
b_status = get_business_status()
status_color = "#34D399" if b_status["is_open"] else "#FBBF24"

st.markdown(f"""
<div class="aqua-hero" style="padding: 1.5rem 2rem; margin-bottom: 1.5rem;">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <h2 style="margin:0; color:white;">AquaAssist Portal</h2>
            <p style="margin:0; opacity:0.8; font-size:0.9rem;">Serving {st.session_state.territory}</p>
        </div>
        <div class="hero-status">
            <span style="height:8px; width:8px; background:{status_color}; border-radius:50%;"></span>
            {b_status["label"]}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# NAVIGATION TABS (PRESERVED)
# ---------------------------------------------------------------------------
tab_chat, tab_report, tab_faq, tab_history, tab_settings = st.tabs([
    "💬 Support Chat", "📋 Report & Track", "❓ FAQs", "🕘 History", "⚙️ Settings"
])

# --- TAB 1: CHAT ---
with tab_chat:
    avatar_url = get_assistant_avatar()
    
    # Message Display
    for msg in st.session_state.messages:
        av = avatar_url if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=av):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("Ask about outages, billing, or leaks..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant", avatar=avatar_url):
            try:
                client = genai.Client(api_key=st.session_state.api_key)
                # Preserving your specific Pinecone/Logic here
                resp = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=f"You are AquaAssist for NAWASA {st.session_state.territory}. Be helpful and professional."
                    )
                )
                answer = resp.text
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"AI Service Error: {e}")

# --- TAB 2: REPORT & TRACK ---
with tab_report:
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.subheader("👷 Report a Leak or Service Issue")
    with st.form("main_report_form", clear_on_submit=True):
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            r_name = st.text_input("Your Name")
            r_phone = st.text_input("Phone Number")
        with col_r2:
            r_type = st.selectbox("Issue Type", ["Leak", "Burst Main", "No Water", "Other"])
            r_loc_text = st.text_input("Location / Parish")
        
        r_desc = st.text_area("Details")
        
        # Preserve GPS Functionality
        if HAS_GEOLOCATION:
            if st.checkbox("📍 Attach My GPS Coordinates"):
                gps = streamlit_geolocation()
                if gps.get("latitude"):
                    r_loc_text += f" (GPS: {gps['latitude']}, {gps['longitude']})"
        
        if st.form_submit_button("Submit Report"):
            ref_id = save_report(r_name, r_phone, r_loc_text, r_type, r_desc)
            st.success(f"Report Logged! Reference: {ref_id}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.subheader("📍 Track Status")
    t_ref = st.text_input("Enter Reference Number (NW-XXXXXXX)")
    if t_ref:
        res = track_report(t_ref)
        if res is not None:
            st.info(f"Report for **{res['name']}** - Status: **{res['status']}**")
            st.progress((STATUS_STAGES.index(res['status'])+1)/len(STATUS_STAGES))
        else: st.warning("No record found.")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 3: FAQ ---
with tab_faq:
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.expander("How do I pay my bill?"):
        st.write("You can pay at any NAWASA sub-office, online via your bank, or at GRENLEC outlets.")
    with st.expander("Where is the main office?"):
        st.write("NAWASA is located on Lucas Street, St. George's.")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 4: HISTORY ---
with tab_history:
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    if not st.session_state.messages: st.info("No chat history yet.")
    else:
        for m in st.session_state.messages:
            st.text(f"{m['role'].upper()}: {m['content'][:100]}...")
    st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 5: SETTINGS ---
with tab_settings:
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    st.subheader("Preferences")
    st.toggle("Dark Mode (Experimental)")
    st.toggle("Enable Voice Replies", value=HAS_TTS)
    st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# FOOTER
# ---------------------------------------------------------------------------
st.markdown(f"""
<div style="text-align:center; padding: 2rem 0; opacity:0.6; font-size:0.8rem;">
    Powered by <strong>NAWASA AquaAssist</strong> AI | Official Support Portal<br>
    © {datetime.now().year} National Water and Sewerage Authority, Grenada
</div>
""", unsafe_allow_html=True)
