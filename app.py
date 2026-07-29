"""
AquaAssist — Streamlit UI
Converted from DAY_8_real_chat.ipynb

Run with:
    pip install streamlit google-genai pandas
    streamlit run app.py

Folder layout expected:
    app.py
    assets/aquaassist_logo.png
    .streamlit/config.toml   (theme — cream / white / blue)
    data/reports.csv         (created automatically on first report)

BEFORE DEPLOYING — set a real staff passcode:
    STAFF_PASSCODE  -> replace "changeme123" below, or set as an env var / Streamlit secret
"""

import os
import csv
import base64
from datetime import datetime

import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# NAWASA contact details
# ---------------------------------------------------------------------------
NAWASA_WHATSAPP_LINK = "https://wa.link/rt9dj1"  # NAWASA WhatsApp (routes to 405-5245 / 459-6064 / 405-9143)
NAWASA_PHONE = "(473) 440-2155"
NAWASA_WEBSITE = "https://nawasa.gd/"
STAFF_PASSCODE = os.environ.get("STAFF_PASSCODE", "changeme123")  # <-- set a real passcode / env var

WHATSAPP_LINK = NAWASA_WHATSAPP_LINK

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
LOGO_PATH = os.path.join("assets", "aquaassist_logo.png")
REPORTS_PATH = os.path.join("data", "reports.csv")
REPORTS_FIELDS = ["timestamp", "name", "phone", "location", "issue_type", "description", "status"]

st.set_page_config(
    page_title="AquaAssist",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "💧",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Brand palette (cream / white / blue)
# ---------------------------------------------------------------------------
BRAND_BLUE = "#0B76C7"
BRAND_BLUE_LIGHT = "#4FA8E0"
BRAND_BLUE_DARK = "#0B2545"
BRAND_CREAM = "#FDF9F0"
BRAND_CREAM_SOFT = "#F5EEDC"
BRAND_WHITE = "#FFFFFF"
WHATSAPP_GREEN = "#25D366"

logo_b64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
    html, body, [class*="css"] {{
        font-family: 'Poppins', sans-serif;
    }}
    .stApp {{
        background-color: {BRAND_CREAM};
    }}
    .block-container {{
        padding-top: 1rem;
        max-width: 780px;
    }}

    /* Hero banner with wave */
    .aqua-hero {{
        position: relative;
        background: linear-gradient(135deg, {BRAND_BLUE} 0%, {BRAND_BLUE_LIGHT} 100%);
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
        font-size: 1.7rem;
        font-weight: 800;
        color: {BRAND_WHITE};
        line-height: 1.15;
        letter-spacing: -0.02em;
    }}
    .aqua-hero-subtitle {{
        font-size: 0.95rem;
        color: rgba(255,255,255,0.9);
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

    /* Card container */
    .aqua-card {{
        background: {BRAND_WHITE};
        border-radius: 18px;
        padding: 1.1rem 1.3rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 12px rgba(11, 118, 199, 0.08);
        border: 1px solid #ECEFF3;
    }}

    /* Section label */
    .aqua-section-label {{
        display: flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.8rem;
        font-weight: 700;
        color: {BRAND_BLUE};
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 1.2rem 0 0.6rem 0;
    }}

    /* Chat bubbles */
    [data-testid="stChatMessage"] {{
        border-radius: 16px;
        padding: 0.5rem 0.7rem;
        margin-bottom: 0.5rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    }}
    [data-testid="stChatMessageContent"] {{
        font-size: 0.95rem;
    }}

    /* Quick action cards */
    div.stButton > button {{
        border-radius: 14px;
        border: 1px solid #E3E9F0;
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

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {BRAND_WHITE};
        border-right: 1px solid #E5E9F0;
    }}

    /* Floating WhatsApp button */
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
    }}
    .whatsapp-float:hover {{
        transform: scale(1.08);
    }}

    /* Sidebar whatsapp link */
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

    <a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-float" title="Chat on WhatsApp">💬</a>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """
You are AquaAssist, a friendly virtual customer assistant for the National Water and Sewerage Authority (NAWASA) of Grenada.

LANGUAGE RULE:
Always reply in the same language the customer writes in — including English, French, Spanish, or Grenadian Creole/patois. Do not default to English if the customer used another language or dialect. If a customer switches language mid-conversation, switch with them. If you are unsure which language or dialect was used, ask the customer to confirm rather than guessing.

Use the following facts to answer user questions:
- Help customers report water leaks by collecting the location and relevant details.
- Provide information about water supply issues and service interruptions.
- Help customers check for planned maintenance and scheduled outages.
- Explain the available methods for paying NAWASA bills.
- Provide NAWASA customer service contact information and transfer users to a representative when requested.
- If the issue is an emergency, advise the user to contact NAWASA immediately at (473) 440-2155.
- NAWASA's official contact details: Phone (473) 440-2155, WhatsApp via https://wa.link/rt9dj1 (405-5245 / 459-6064 / 405-9143), Website https://nawasa.gd/. Share these when a customer asks how to reach NAWASA directly.
- When a customer describes a specific problem (a leak, no water, low pressure, a billing issue) and gives at least a location, log it immediately using the log_water_report tool — do not tell the customer to fill out a separate form themselves. After logging it, confirm to the customer that it's been logged and let them know NAWASA staff will follow up. If you don't have their name or phone number yet, ask for it after logging so staff can reach them, but don't block logging the report on that.
- The "Report a Leak" form and the WhatsApp button are alternative ways to reach NAWASA, but you should always try to log the report yourself first if the customer is describing it in chat.

Be helpful, clear, patient, and reassuring.
Keep responses concise, polite, and easy to understand.
If a question is unrelated to NAWASA services, politely explain that you can only assist with NAWASA-related topics and invite the user to ask another water service question.
"""

MODEL_NAME = "gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# Report storage helpers
# ---------------------------------------------------------------------------
def ensure_reports_file():
    os.makedirs(os.path.dirname(REPORTS_PATH), exist_ok=True)
    if not os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REPORTS_FIELDS)
            writer.writeheader()

def save_report(name, phone, location, issue_type, description):
    ensure_reports_file()
    with open(REPORTS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORTS_FIELDS)
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "phone": phone,
            "location": location,
            "issue_type": issue_type,
            "description": description,
            "status": "New",
        })

def load_reports():
    ensure_reports_file()
    import pandas as pd
    return pd.read_csv(REPORTS_PATH)

# ---------------------------------------------------------------------------
# Tool the AI can call directly during conversation to log a report
# ---------------------------------------------------------------------------
def log_water_report(location: str, issue_type: str, description: str,
                      name: str = "Not provided", phone: str = "Not provided") -> str:
    """Logs a customer's water service issue into the NAWASA staff system so a
    technician can follow up on it. Call this as soon as the customer has
    described their problem and given at least a location — even in normal
    conversation, without requiring them to fill out a separate form. If the
    customer hasn't given their name or phone number, still log the report
    using "Not provided" for those fields, but politely ask for them
    afterward so staff can follow up directly.

    Args:
        location: The location or address where the issue is happening.
        issue_type: One of "Leak", "No water supply", "Low pressure", "Billing issue", "Other".
        description: A short description of the issue in the customer's own words.
        name: The customer's name, if given.
        phone: The customer's phone number, if given.

    Returns:
        A confirmation message that the report was logged.
    """
    save_report(name, phone, location, issue_type, description)
    return "Report logged successfully in the NAWASA staff system. A technician will follow up."

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)

    mode = st.radio("View", ["💬 Customer Chat", "🔐 Staff Portal"], label_visibility="collapsed")

    st.markdown(
        f'<a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-btn">📱 Chat on WhatsApp</a>',
        unsafe_allow_html=True,
    )
    st.caption(f"📞 {NAWASA_PHONE}")
    st.caption(f"🌐 [nawasa.gd]({NAWASA_WEBSITE})")

    st.divider()
    st.header("⚙️ Settings")
    default_key = os.environ.get("GEMINI_API_KEY", "")
    api_key = st.text_input(
        "Gemini API Key",
        value=default_key,
        type="password",
        help="Get a key at https://aistudio.google.com/",
    )
    st.caption(f"Model: `{MODEL_NAME}`")

    if st.button("🔄 Reset conversation"):
        st.session_state.pop("chat", None)
        st.session_state.pop("client", None)
        st.session_state.pop("_key_used", None)
        st.session_state.pop("messages", None)
        st.rerun()

    with st.expander("📜 View system instruction"):
        st.text(SYSTEM_INSTRUCTION)

# ===========================================================================
# STAFF PORTAL
# ===========================================================================
if mode == "🔐 Staff Portal":
    st.markdown(
        f"""
        <div class="aqua-hero">
            <div class="aqua-hero-content">
                <div>
                    <div class="aqua-hero-title">🔐 Staff Portal</div>
                    <div class="aqua-hero-subtitle">Reports submitted by customers</div>
                </div>
            </div>
            <svg class="aqua-wave" viewBox="0 0 500 40" preserveAspectRatio="none">
                <path class="aqua-wave-fill" d="M0,20 C150,45 350,-5 500,20 L500,40 L0,40 Z"></path>
            </svg>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
        st.dataframe(reports_df, use_container_width=True)

        csv_bytes = reports_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download reports as CSV",
            data=csv_bytes,
            file_name="nawasa_reports.csv",
            mime="text/csv",
        )

    st.stop()

# ===========================================================================
# CUSTOMER CHAT MODE
# ===========================================================================

logo_html = f'<img src="data:image/png;base64,{logo_b64}" />' if logo_b64 else "💧"

st.markdown(
    f"""
    <div class="aqua-hero">
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
    </div>
    """,
    unsafe_allow_html=True,
)

if not api_key:
    st.info("👈 Enter your Gemini API key in the sidebar to start chatting.")
    st.stop()

# ---------------------------------------------------------------------------
# Initialize client + chat session
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat" not in st.session_state or st.session_state.get("_key_used") != api_key:
    try:
        client = genai.Client(api_key=api_key)
        st.session_state.client = client
        st.session_state.chat = client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
                tools=[log_water_report],
            ),
        )
        st.session_state._key_used = api_key
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Report a Leak — structured form
# ---------------------------------------------------------------------------
st.markdown('<div class="aqua-section-label">🚿 Report an issue</div>', unsafe_allow_html=True)
with st.container():
    st.markdown('<div class="aqua-card">', unsafe_allow_html=True)
    with st.expander("Fill out a report — goes straight to NAWASA staff"):
        with st.form("leak_report_form", clear_on_submit=True):
            r_name = st.text_input("Your name")
            r_phone = st.text_input("Phone number")
            r_location = st.text_input("Location / address of the issue")
            r_issue_type = st.selectbox(
                "Issue type",
                ["Leak", "No water supply", "Low pressure", "Billing issue", "Other"],
            )
            r_description = st.text_area("Describe the issue")
            submitted = st.form_submit_button("Submit report")

            if submitted:
                if not r_name or not r_phone or not r_location:
                    st.error("Please fill in your name, phone number, and location.")
                else:
                    save_report(r_name, r_phone, r_location, r_issue_type, r_description)
                    st.success("✅ Your report has been submitted. NAWASA staff will follow up.")
    st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Quick actions
# ---------------------------------------------------------------------------
st.markdown('<div class="aqua-section-label">💧 Quick actions</div>', unsafe_allow_html=True)

quick_actions = {
    "🚿 Report a Leak": "I'd like to report a water leak.",
    "🛠️ Maintenance": "Are there any scheduled outages or planned maintenance in my area?",
    "💳 Pay My Bill": "What are my options for paying my NAWASA bill?",
    "📞 Talk to a Rep": "I'd like to speak with a customer service representative.",
}

qa_cols = st.columns(len(quick_actions))
queued_prompt = None
for col, (label, prompt) in zip(qa_cols, quick_actions.items()):
    with col:
        if st.button(label, use_container_width=True):
            queued_prompt = prompt

# ---------------------------------------------------------------------------
# Render chat history
# ---------------------------------------------------------------------------
st.markdown('<div class="aqua-section-label">💬 Chat</div>', unsafe_allow_html=True)

ASSISTANT_AVATAR = LOGO_PATH if os.path.exists(LOGO_PATH) else "💧"
USER_AVATAR = "🧑"

for msg in st.session_state.messages:
    avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else USER_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

if not st.session_state.messages:
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        st.markdown(
            "Welcome to AquaAssist! 💧 I'm here to help with your NAWASA water services. "
            "Ask me a question, tap a quick action above, or use the Report a Leak form."
        )

# ---------------------------------------------------------------------------
# Chat input loop
# ---------------------------------------------------------------------------
typed_input = st.chat_input("Ask AquaAssist something...")
user_input = queued_prompt or typed_input

if user_input:
    cleaned_input = user_input.strip()
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

        st.session_state.messages.append({"role": "assistant", "content": reply_text})

# ---------------------------------------------------------------------------
# Optional: session history audit
# ---------------------------------------------------------------------------
with st.expander("🕵️ Chat history audit (raw Gemini session)"):
    if "chat" in st.session_state:
        try:
            for message in st.session_state.chat.get_history():
                role = message.role.upper()
                text = message.parts[0].text
                st.markdown(f"**[{role}]:** {text}")
        except Exception as e:
            st.caption(f"No history yet ({e})")
