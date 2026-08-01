import streamlit as st
from pathlib import Path

# Page settings
st.set_page_config(
    page_title="AquaAssist",
    page_icon="💧",
    layout="centered"
)

# Styling
st.markdown("""
<style>

body {
    background-color: #F4FAFD;
}

.main {
    background-color: #F4FAFD;
}

.title {
    text-align: center;
    color: #0072BC;
    font-size: 42px;
    font-weight: 700;
    margin-top: 10px;
}

.subtitle {
    text-align: center;
    color: #005A9C;
    font-size: 25px;
    font-weight: 600;
}

.message {
    text-align: center;
    color: #1F2937;
    font-size: 18px;
    line-height: 1.7;
}

.footer {
    text-align: center;
    color: #666666;
    font-size: 15px;
    margin-top: 35px;
}

</style>
""", unsafe_allow_html=True)


# Load NAWASA Logo
logo_path = Path(__file__).parent / "nawasa_logo.png"

if logo_path.exists():
    st.image(str(logo_path), width=180)
else:
    st.error(
        "NAWASA logo not found. Please ensure nawasa_logo.png "
        "is uploaded to the same folder as app.py."
    )


# Title
st.markdown(
    '<div class="title">💧 AquaAssist</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">🚧 Currently Under Development</div>',
    unsafe_allow_html=True
)


# Message
st.markdown("""
<div class="message">

Thank you for visiting the 
<strong>NAWASA AquaAssist AI Chatbot</strong>.

<br><br>

Our team is currently working on improvements and resolving 
technical issues to provide customers with a better experience.

<br><br>

AquaAssist will soon help NAWASA customers receive faster support,
information, and assistance through artificial intelligence.

<br><br>

<strong>Please check back within the next 24 hours.</strong>

</div>
""", unsafe_allow_html=True)


# Notice box
st.info(
    "💧 Thank you for your patience and understanding. "
    "The AquaAssist team is working hard to improve your experience."
)


# Developer credit
st.markdown("""
<div class="footer">

<strong>Developed by Sub Pod 1 Team</strong><br>
NAWASA AquaAssist AI Project<br>
STEM Innovation Initiative

</div>
""", unsafe_allow_html=True)
