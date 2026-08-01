import streamlit as st
from pathlib import Path

# Page Configuration
st.set_page_config(
    page_title="AquaAssist",
    page_icon="💧",
    layout="centered"
)

# Custom CSS Styling
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
    color: #005A9C;
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
    color: #666666;
    font-size: 15px;
    margin-top: 35px;
}

</style>
""", unsafe_allow_html=True)


# Display NAWASA Logo in Center
logo_path = Path(__file__).parent / "nawasa_logo.png"

if logo_path.exists():

    left, center, right = st.columns([1, 2, 1])

    with center:
        st.image(
            str(logo_path),
            width=180
        )

else:
    st.warning(
        "NAWASA logo not found. "
        "Please upload nawasa_logo.png to the same folder as app.py."
    )


# AquaAssist Heading
st.markdown(
    '<div class="title">💧 AquaAssist</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">🚧 Currently Under Development</div>',
    unsafe_allow_html=True
)


# Main Announcement
st.markdown("""
<div class="message">

Thank you for visiting the 
<strong>NAWASA AquaAssist AI Chatbot</strong>.

<br><br>

Our team is currently making improvements and resolving 
technical issues to provide customers with the best possible experience.

<br><br>

AquaAssist will soon provide intelligent assistance to NAWASA customers,
helping users access information and support faster.

<br><br>

<strong>Please check back within the next 24 hours.</strong>

</div>
""", unsafe_allow_html=True)


# Notification Box
st.info(
    "💧 Thank you for your patience and understanding. "
    "The AquaAssist team is working hard to improve your experience."
)


# Team Credit
st.markdown("""
<div class="footer">

<strong>Developed by Sub Pod 1 Team</strong><br>
NAWASA AquaAssist AI Chatbot Project<br>
STEM Innovation Initiative

</div>
""", unsafe_allow_html=True)
