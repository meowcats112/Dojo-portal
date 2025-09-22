import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import hashlib
from datetime import datetime
import pytz

st.set_page_config(page_title="Dojo Member Portal", page_icon="🥋")

# --- Styling ---
st.markdown("""
    <style>
    .metric-label { font-weight:600; }
    </style>
""", unsafe_allow_html=True)

# --- Config / Secrets ---
def get_gsheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=60)
def load_members_df():
    gc = get_gsheets_client()
    ws = gc.open_by_key(st.secrets["sheets"]["members_sheet_key"]).sheet1
    return pd.DataFrame(ws.get_all_records())

def pin_hash(raw_pin: str) -> str:
    salt = st.secrets.get("security", {}).get("pin_salt", "")
    return hashlib.sha256((salt + str(raw_pin)).encode()).hexdigest()

def find_member(df, email, pin):
    email = (email or "").strip().lower()
    if not email: return None
    row = df[df["Email"].str.strip().str.lower() == email]
    if row.empty: return None
    r = row.iloc[0]
    # Prefer hashed PIN if available
    if "PIN_Hash" in row.columns and str(r.get("PIN_Hash","")).strip():
        if pin_hash(pin) != str(r["PIN_Hash"]).strip():
            return None
    elif "PIN" in row.columns:
        if (pin or "").strip() != str(r["PIN"]).strip():
            return None
    else:
        # If no PIN column, treat as open (not recommended)
        pass
    return r

def append_request(member, req_type, message):
    tz = pytz.timezone("Australia/Sydney")
    ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    gc = get_gsheets_client()
    ws = gc.open_by_key(st.secrets["sheets"]["requests_sheet_key"]).sheet1
    ws.append_row([
        ts,
        member.get("Email",""),
        member.get("MemberID",""),
        req_type,
        message,
        "New",
        "",
        ""
    ])

# --- UI ---
st.markdown("## 🥋 Dojo Member Portal")
st.caption("View your leave balance and request simple updates.")

with st.form("login"):
    email = st.text_input("Your email", placeholder="you@example.com")
    pin = st.text_input("PIN", type="password", placeholder="4–8 digits (ask the dojo if unsure)")
    submitted = st.form_submit_button("View my balance")
member = None
if submitted:
    try:
        df = load_members_df()
        # Basic required columns check
        required_cols = {"MemberID","MemberName","Email","LeaveYear","AnnualAllowance","LeaveTaken","LeaveBalance","LastUpdated"}
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"Your Members sheet is missing columns: {', '.join(missing)}")
        else:
            member = find_member(df, email, pin)
            if not member is None:
                st.success("Found your record.")
            else:
                st.error("No match found. Check your email/PIN or contact the dojo.")
    except Exception as e:
        st.error(f"Error reading data. Check your Secrets and Google Sheet sharing: {e}")

if member is not None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Year", member.get("LeaveYear",""))
    col2.metric("Allowance", member.get("AnnualAllowance",""))
    col3.metric("Taken", member.get("LeaveTaken",""))
    col4.metric("Balance", member.get("LeaveBalance",""))
    st.caption(f"Last updated: {member.get('LastUpdated','')}")
    st.divider()

    st.subheader("Request an update")
    req_type = st.selectbox("Request type", ["Leave balance query","Contact change","Billing question","Other"])
    msg = st.text_area("Message")
    if st.button("Send request"):
        try:
            append_request(member, req_type, msg.strip())
            st.success("Thanks — we received your request.")
        except Exception as e:
            st.error(f"Could not submit request: {e}")
else:
    st.info("Enter your email and PIN to view your balance.")
