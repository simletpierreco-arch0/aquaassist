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

BEFORE DEPLOYING — replace these two placeholders below:
    NAWASA_WHATSAPP_NUMBER  -> real WhatsApp number in international format, no + or spaces
    STAFF_PASSCODE          -> a real passcode for staff to view reports (or set via env var)
"""

import os
import csv
from datetime import datetime

import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# ⚠️ REPLACE THESE BEFORE GOING LIVE
# ---------------------------------------------------------------------------
NAWASA_WHATSAPP_NUMBER = "18095551234"  # <-- put the real NAWASA WhatsApp number here (no + or spaces)
STAFF_PASSCODE = os.environ.get("STAFF_PASSCODE", "changeme123")  # <-- set a real passcode / env var

WHATSAPP_LINK = f"https://wa.me/{NAWASA_WHATSAPP_NUMBER}?text=Hello%20NAWASA%2C%20I%20need%20help%20with%20my%20water%20service."

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
# Brand palette (cream / white / blue) — mirrors .streamlit/config.toml
# ---------------------------------------------------------------------------
BRAND_BLUE = "#0B76C7"
BRAND_BLUE_DARK = "#0B2545"
BRAND_CREAM = "#FDF9F0"
BRAND_CREAM_SOFT = "#F5EEDC"
BRAND_WHITE = "#FFFFFF"
WHATSAPP_GREEN = "#25D366"

# ---------------------------------------------------------------------------
# Custom CSS — droplet accents + chat bubble styling
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {BRAND_CREAM};
    }}
    .aqua-header {{
        display: flex;
        align-items: center;
        gap: 0.9rem;
        padding: 1rem 1.25rem;
        background: linear-gradient(135deg, {BRAND_WHITE} 0%, {BRAND_CREAM_SOFT} 100%);
        border: 1px solid #E0E6EE;
        border-radius: 18px;
        margin-bottom: 1.25rem;
        box-shadow: 0 2px 10px rgba(11, 118, 199, 0.08);
    }}
    .aqua-header img {{
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: {BRAND_WHITE};
        padding: 4px;
        box-shadow: 0 0 0 3px {BRAND_BLUE}20;
    }}
    .aqua-title {{
        font-size: 1.6rem;
        font-weight: 800;
        color: {BRAND_BLUE_DARK};
        line-height: 1.1;
    }}
    .aqua-subtitle {{
        font-size: 0.9rem;
        color: {BRAND_BLUE};
        font-weight: 500;
    }}
    .droplet-divider {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        margin: 0.75rem 0 1.25rem 0;
        color: {BRAND_BLUE};
        opacity: 0.7;
        font-size: 0.85rem;
    }}
    .droplet-divider::before,
    .droplet-divider::after {{
        content: "";
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, transparent, {BRAND_BLUE}55, transparent);
    }}
    [data-testid="stChatMessage"] {{
        border-radius: 16px;
        padding: 0.4rem 0.6rem;
        margin-bottom: 0.4rem;
    }}
    div.stButton > button {{
        border-radius: 999px;
        border: 1px solid {BRAND_BLUE}55;
        background-color: {BRAND_WHITE};
        color: {BRAND_BLUE_DARK};
        font-weight: 600;
        padding: 0.4rem 0.9rem;
    }}
    div.stButton > button:hover {{
        border-color: {BRAND_BLUE};
        color: {BRAND_BLUE};
        background-color: {BRAND_CREAM_SOFT};
    }}
    section[data-testid="stSidebar"] {{
        background-color: {BRAND_WHITE};
        border-right: 1px solid #E5E9F0;
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
- If the issue is an emergency, advise the user to contact NAWASA immediately and provide the appropriate emergency contact information.
- If a customer wants to report a leak or speak to a human, let them know they can use the "Report a Leak" form or the WhatsApp button on this page.

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
# Sidebar: mode switch (Customer chat vs Staff portal) + settings
# ---------------------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)

    mode = st.radio("View", ["💬 Customer Chat", "🔐 Staff Portal"], label_visibility="collapsed")

    st.markdown(
        f'<a href="{WHATSAPP_LINK}" target="_blank" class="whatsapp-btn">📱 Chat on WhatsApp</a>',
        unsafe_allow_html=True,
    )

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
# STAFF PORTAL — password gated view of submitted reports
# ===========================================================================
if mode == "🔐 Staff Portal":
    st.markdown(
        f"""
        <div class="aqua-header">
            <div>
                <div class="aqua-title">🔐 Staff Portal</div>
                <div class="aqua-subtitle">Reports submitted by customers</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "staff_authed" not in st.session_state:
        st.session_state.staff_authed = False

    if not st.session_state.staff_authed:
        entered = st.text_input("Enter staff passcode", type="password")
        if st.button("Log in"):
            if entered == STAFF_PASSCODE:
                st.session_state.staff_authed = True
                st.rerun()
            else:
                st.error("Incorrect passcode.")
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

if os.path.exists(LOGO_PATH):
    import base64
    with open(LOGO_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f"""
        <div class="aqua-header">
            <img src="data:image/png;base64,{logo_b64}" />
            <div>
                <div class="aqua-title">💧 AquaAssist</div>
                <div class="aqua-subtitle">Your Smart Water Support Assistant</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.title("💧 AquaAssist")
    st.caption("Your Smart Water Support Assistant")

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
            ),
        )
        st.session_state._key_used = api_key
    except Exception as e:
        st.error(f"Failed to initialize Gemini client: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Report a Leak — structured form, saved for staff to see
# ---------------------------------------------------------------------------
with st.expander("🚿 Report a Leak / Issue (goes straight to NAWASA staff)"):
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

# ---------------------------------------------------------------------------
# Quick actions
# ---------------------------------------------------------------------------
st.markdown('<div class="droplet-divider">💧 Quick actions 💧</div>', unsafe_allow_html=True)

quick_actions = {
    "🚿 Report a Leak": "I'd like to report a water leak.",
    "🛠️ Planned Maintenance": "Are there any scheduled outages or planned maintenance in my area?",
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
