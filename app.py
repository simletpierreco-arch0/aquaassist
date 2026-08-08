import streamlit as st
import google.generativeai as genai

# 1. Page Setup & Blue Wave Theme
st.set_page_config(page_title="AquaAssist", page_icon="💧")

st.markdown("""
    <style>
    .stApp { background-color: #F6FBFF; }
    .header {
        background: linear-gradient(135deg, #005A9C 0%, #0077CC 100%);
        padding: 40px; border-radius: 0 0 30px 30px;
        color: white; text-align: center; margin: -60px -20px 20px -20px;
    }
    </style>
    <div class="header">
        <h1>💧 AquaAssist</h1>
        <p>Official NAWASA AI Support</p>
    </div>
""", unsafe_allow_html=True)

# 2. Session Management
if "messages" not in st.session_state:
    st.session_state.messages = []
if "auth" not in st.session_state:
    st.session_state.auth = False

# 3. Simple Login Screen
if not st.session_state.auth:
    with st.container():
        st.subheader("Customer Login")
        loc = st.selectbox("Select Territory", ["Grenada", "Carriacou", "Petit Martinique"])
        key = st.text_input("Enter Gemini API Key", type="password")
        if st.button("Start Chatting"):
            if key:
                st.session_state.key = key
                st.session_state.loc = loc
                st.session_state.auth = True
                st.rerun()
    st.stop()

# 4. AI Chat Interface
st.caption(f"Connected to NAWASA {st.session_state.loc}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about your water service..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        # CONFIGURE GENAI
        genai.configure(api_key=st.session_state.key)
        
        # USE THE STABLE FLASH MODEL
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=f"You are AquaAssist, a NAWASA representative for {st.session_state.loc}. Reply in professional Standard English."
        )
        
        response = model.generate_content(prompt)
        answer = response.text
        
    except Exception as e:
        # Fallback if 1.5-flash still fails
        answer = f"I'm having trouble connecting. Please ensure your API key is valid. (Error: {str(e)})"

    with st.chat_message("assistant"):
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
