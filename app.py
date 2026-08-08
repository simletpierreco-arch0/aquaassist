import streamlit as st
import google.generativeai as genai
import os

# 1. PAGE SETUP
st.set_page_config(page_title="AquaAssist", page_icon="💧", layout="wide")

# 2. DESIGN (Blue Wave Theme)
st.markdown("""
    <style>
    .stApp { background-color: #F6FBFF; }
    .header {
        background: linear-gradient(135deg, #005A9C 0%, #0077CC 100%);
        padding: 40px; border-radius: 0 0 30px 30px;
        color: white; text-align: center; margin: -60px -20px 20px -20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .stChatMessage { border-radius: 15px; border: 1px solid #E0E8F0; }
    </style>
    <div class="header">
        <h1 style='margin:0;'>💧 AquaAssist</h1>
        <p style='margin:0; opacity:0.9;'>Official NAWASA AI Customer Support</p>
    </div>
""", unsafe_allow_html=True)

# 3. SESSION STATE
if "messages" not in st.session_state:
    st.session_state.messages = []
if "auth" not in st.session_state:
    st.session_state.auth = False

# 4. LOGIN SCREEN
if not st.session_state.auth:
    st.markdown("### Welcome to AquaAssist")
    loc = st.selectbox("Select Territory", ["Grenada", "Carriacou", "Petit Martinique"])
    key = st.text_input("Enter your Gemini API Key", type="password", help="Get a key at aistudio.google.com")
    
    if st.button("Start Chatting", use_container_width=True):
        if key.startswith("AIza"): # Simple validation
            st.session_state.key = key
            st.session_state.loc = loc
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Please enter a valid Gemini API Key.")
    st.stop()

# 5. MAIN CHAT INTERFACE
st.caption(f"📍 Serving: {st.session_state.loc} | NAWASA Official AI")

# Display historical messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User input
if prompt := st.chat_input("How can I help you with your water service today?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        try:
            # Setup AI
            genai.configure(api_key=st.session_state.key)
            
            # Using the most robust model name
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=f"You are AquaAssist, a NAWASA representative for {st.session_state.loc}. Reply in professional Standard English. Be helpful and empathetic."
            )
            
            response = model.generate_content(prompt)
            full_response
