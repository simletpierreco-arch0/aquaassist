import streamlit as st
from pathlib import Path
from datetime import datetime, timedelta, timezone

# -----------------------------
# Page Settings
# -----------------------------
st.set_page_config(
    page_title="AquaAssist",
    page_icon="💧",
    layout="centered"
)

# -----------------------------
# Custom Styling
# -----------------------------
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
    margin-top: 10px;
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
    color: gray;
    font-size: 15px;
    margin-top: 35px;
}

</style>
""", unsafe_allow_html=True)

# -----------------------------
# Logo
# -----------------------------
logo_path = Path(__file__).parent / "nawasa_logo.png"

if logo_path.exists():
    st.markdown(
        '<div style="display:flex;justify-content:center;">',
        unsafe_allow_html=True,
    )

    st.image(str(logo_path), width=180)

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )
else:
    st.warning(
        "NAWASA logo not found. Please ensure nawasa_logo.png is in the same folder as app.py."
    )

# -----------------------------
# Title
# -----------------------------
st.markdown(
    '<div class="title">💧 AquaAssist</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">🚧 Currently Under Development</div>',
    unsafe_allow_html=True
)

# -----------------------------
# Main Message
# -----------------------------
st.markdown("""
<div class="message">

Thank you for visiting the
<strong>NAWASA AquaAssist AI Chatbot</strong>.

<br><br>

Our team is currently making improvements and resolving
technical issues to provide customers with the best possible experience.

<br><br>

AquaAssist will soon assist NAWASA customers by providing
quick information, support, and guidance through artificial intelligence.

<br><br>

<strong>Please check back within the next 24 hours.</strong>

</div>
""", unsafe_allow_html=True)

# -----------------------------
# Information Box
# -----------------------------
st.info(
    "💧 Thank you for your patience and understanding. "
    "The AquaAssist team is working hard to improve your experience."
)

# -----------------------------
# Footer
# -----------------------------
st.markdown("""
<div class="footer">

<strong>Developed by Sub Pod 1 Team</strong><br>
NAWASA AquaAssist AI Project<br>
STEM Innovation Initiative

</div>
""", unsafe_allow_html=True)

# -----------------------------
# Business Hours Configuration
# -----------------------------
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END = 16
CLOSING_SOON_WINDOW_MINUTES = 160

NAWASA_HOLIDAYS = [
    # "2026-01-01",
    # "2026-12-25",
]

GRENADA_TZ = timezone(timedelta(hours=-4))

_WEEKDAY_LABELS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

def get_business_hours_status():
    now = datetime.now(GRENADA_TZ)
    today_str = now.strftime("%Y-%m-%d")

    weekday_idx = now.weekday()

    is_weekend = weekday_idx == 6
    is_holiday = today_str in NAWASA_HOLIDAYS
    is_open_hour = BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END

    is_open = (
        not is_weekend
        and not is_holiday
        and is_open_hour
    )

    next_day = now

    if is_weekend or is_holiday or now.hour >= BUSINESS_HOURS_END:
        next_day += timedelta(days=1)

    while (
        next_day.weekday() == 6
        or next_day.strftime("%Y-%m-%d") in NAWASA_HOLIDAYS
    ):
        next_day += timedelta(days=1)

    if is_weekend:
        closed_reason = "It's Sunday"
    elif is_holiday:
        closed_reason = "Today is a NAWASA holiday"
    elif now.hour < BUSINESS_HOURS_START:
        closed_reason = "We open later this morning"
    else:
        closed_reason = "We've closed for the day"

    same_day = next_day.strftime("%Y-%m-%d") == today_str

    reopens_label = (
        ("today" if same_day else _WEEKDAY_LABELS[next_day.weekday()])
        + f" at {BUSINESS_HOURS_START}:00 AM"
    )

    minutes_until_close = None
    closing_soon = False

    if is_open:
        close_time = now.replace(
            hour=BUSINESS_HOURS_END,
            minute=0,
            second=0,
            microsecond=0,
        )

        minutes_until_close = max(
            0,
            int((close_time - now).total_seconds() // 60),
        )

        closing_soon = (
            minutes_until_close <= CLOSING_SOON_WINDOW_MINUTES
        )

    return {
        "is_open": is_open,
        "closed_reason": closed_reason,
        "reopens_label": reopens_label,
        "closing_soon": closing_soon,
        "minutes_until_close": minutes_until_close,
    }

status = get_business_hours_status()

if status["is_open"]:
    st.success("🟢 NAWASA Customer Service is currently OPEN.")
else:
    st.warning(
        f"🔴 {status['closed_reason']}. Reopens {status['reopens_label']}."
    )
