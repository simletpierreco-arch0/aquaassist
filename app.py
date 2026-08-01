import streamlit as st

st.set_page_config(
    page_title="AquaAssist",
    page_icon="💧",
    layout="centered"
)

st.markdown("""
<style>
.main {
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
    font-size: 24px;
}

.message {
    text-align: center;
    font-size: 18px;
    color: #1F2937;
}

.footer {
    text-align: center;
    color: gray;
    margin-top: 30px;
}
</style>
""", unsafe_allow_html=True)

# Replace with your logo filename
st.image("nawasa_logo.png", width=180)

st.markdown('<div class="title">AquaAssist</div>', unsafe_allow_html=True)

st.markdown('<div class="subtitle">🚧 Currently Under Development</div>', unsafe_allow_html=True)

st.markdown("""
<div class="message">
Thank you for visiting the <strong>NAWASA AquaAssist AI Chatbot</strong>.<br><br>

Our team is currently making improvements and fixing a few technical issues to provide you with the best possible experience.<br><br>

<b>Please check back within the next 24 hours.</b>
</div>
""", unsafe_allow_html=True)

st.info("Thank you for your patience and understanding.")

st.markdown(
    '<div class="footer"><b>Developed by Sub Pod 1 Team</b></div>',
    unsafe_allow_html=True
)
