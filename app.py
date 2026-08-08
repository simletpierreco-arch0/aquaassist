import streamlit as st
import google.generativeai as genai

# 1. PAGE SETUP
st.set_page_config(page_title="AquaAssist", page_icon="💧")

# 2. DESIGN (Blue Wave Theme)
st.markdown("""
    <style>
    .stApp { background-color: #F6FBFF; }
    .header {
        background: linear-gradient(135deg, #005A9C 0%, #0077CC 100%);
        padding: 30px; border-radius: 0 0 20px 20px;
        color: white; text-align: center; margin: -60px -20px 20px -20px;
    }
    </style>
    <div class="header">
        <h1>💧 AquaAssist</h1>
        <p>Official NAWASA AI Support</p>
    </div>
""", unsafe_allow_html=True)

# 3. SESSION STATE
if "messages" not in st.session_state:
    st.session_state.messages = []
if "auth" not in st.session_state:
    st.session_state.auth = False

# 4. LOGIN SCREEN
if not st.session_state.auth:
    st.subheader("NAWASA Customer Portal")
    loc = st.selectbox("Territory", ["Grenada", "Carriacou", "Petit Martinique"])
    key = st.text_input("Gemini API Key", type="password")
    if st.button("Start Chatting", use_container_width=True):
        if key:
            st.session_state.key = key
            st.session_state.loc = loc
            st.session_state.auth = True
            st.rerun()
    st.stop()

# 5. MAIN CHAT
st.caption(f"📍 {st.session_state.loc} Territory")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about your water service..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            genai.configure(api_key=st.session_state.key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=f"You are AquaAssist, a NAWASA rep for {st.session_state.loc}."
            )
            response = model.generate_content(prompt)
            answer = response.text
            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception as e:
            st.error(f"Connection Error: {str(e)}")
