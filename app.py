import os
import streamlit as st
import uuid
import base64
from google import genai
from google.genai import types

# 1. PAGE CONFIG
st.set_page_config(page_title="AquaAssist", page_icon="💧", layout="wide")

# 2. BRANDING & COLORS (The "Blue Wave" Design)
BRAND_PRIMARY = "#005A9C"
BRAND_ACCENT = "#00AEEF"
BRAND_BG = "#F6FBFF"

# This is where the "100vh" belongs - inside a Python string!
CSS = f"""
<style>
    .stApp {{
        background-color: {BRAND_BG};
        background-image: linear-gradient(180deg, #EAF6FF 0%, {BRAND_BG} 40%);
    }}
    .aqua-hero {{
        background: linear-gradient(135deg, {BRAND_PRIMARY} 0%, #0077CC 100%);
        color: white;
        padding: 40px 20px;
        border-radius: 20px;
        text-align: center;
        margin-bottom: 20px;
    }}
    .stChatMessage {{ border-radius: 15px; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# 3. INITIALIZE SESSION STATE
if "messages" not in st.session_state:
    st.session_state.messages = []
if "auth_done" not in st.session_state:
    st.session_state.auth_done = False

# 4. LOGIN SCREEN
if not st.session_state.auth_done:
    st.markdown('<div class="aqua-hero"><h1>💧 AquaAssist</h1><p>NAWASA Customer Support AI</p></div>', unsafe_allow_html=True)
    with st.container():
        st.subheader("Welcome to AquaAssist")
        territory = st.selectbox("Select Territory", ["Grenada", "Carriacou", "Petit Martinique"])
        api_key = st.text_input("Enter Gemini API Key", type="password")
        if st.button("Start Chatting"):
            if api_key:
                st.session_state.api_key = api_key
                st.session_state.territory = territory
                st.session_state.auth_done = True
                st.rerun()
            else:
                st.error("Please enter an API key.")
    st.stop()

# 5. CHAT INTERFACE (Once Logged In)
st.markdown(f'<div class="aqua-hero"><h1>AquaAssist: {st.session_state.territory}</h1><p>How can I help you with your water service today?</p></div>', unsafe_allow_html=True)

# Display Messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat Input
if prompt := st.chat_input("Ask about outages, leaks, or billing..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # AI Response Logic
    try:
        client = genai.Client(api_key=st.session_state.api_key)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=f"You are AquaAssist, a NAWASA support bot for {st.session_state.territory}. Be helpful and professional."
            )
        )
        answer = response.text
    except Exception as e:
        answer = f"I'm having trouble connecting to the AI. Error: {e}"

    with st.chat_message("assistant"):
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
