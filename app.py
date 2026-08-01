import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="AquaAssist",
    page_icon="💧",
    layout="centered"
)

st.markdown("""
<style>

.stApp {
    background-color: #F4FAFD;
}

.title {
    text-align: center;
    color: #0072BC;
    font-size: 42px;
    font-weight: bold;
}

.subtitle {
    text-align: center;
    color: #C0392B;
    font-size: 25px;
    font-weight: bold;
}

.message {
    text-align: center;
    color: #1F2937;
    font-size: 18px;
    line-height: 1.7;
}

.footer {
    text-align: center;
    color: gray;
    margin-top: 35px;
    font-size: 15px;
}

</style>
""", unsafe_allow_html=True)


# Center Logo
logo_path = Path(__file__).parent / "nawasa_logo.png"

if logo_path.exists():
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.image(str(logo_path), width=180)


# Heading
st.markdown(
    '<div class="title">💧 AquaAssist</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">⚠️ Chatbot Temporarily Offline</div>',
    unsafe_allow_html=True
)


# Message
st.markdown("""
<div class="message">

We would like to inform our users that the 
<strong>NAWASA AquaAssist AI Chatbot</strong> has been affected by a security issue 
and is currently offline.

<br><br>

Our team is working to get the chatbot back up and running as soon as possible.

<br><br>

<strong>We expect AquaAssist to be restored today by 5:00 PM.</strong>

<br><br>

Thank you for your patience and understanding while we work on this issue.

<br><br>

<strong>— Pod Leader S-Pierre<br>
Sub-Pod 1 Team</strong>

</div>
""", unsafe_allow_html=True)


st.warning(
    "💧 AquaAssist is temporarily unavailable. Please check back after 5:00 PM for updates."
)


# Footer
st.markdown("""
<div class="footer">

<strong>Developed by Sub-Pod 1 Team</strong><br>
NAWASA AquaAssist AI Project

</div>
""", unsafe_allow_html=True)
