import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import hashlib
from datetime import datetime
import pytz

st.set_page_config(page_title="Dojo Member Portal", page_icon="🥋")

if "member" not in st.session_state:
    st.session_state.member = None

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

# --- Login form ---
with st.form("login"):
    email = st.text_input("Your email", placeholder="you@example.com")
    pin = st.text_input("PIN", type="password", placeholder="4–8 digits (ask the dojo if unsure)")
    submitted = st.form_submit_button("View my balance")

if submitted:
    try:
        df = load_members_df()
        required_cols = {"MemberID","MemberName","Email","LeaveYear","AnnualAllowance","LeaveTaken","LeaveBalance","LastUpdated"}
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(f"Your Members sheet is missing columns: {', '.join(missing)}")
        else:
            m = find_member(df, email, pin)
            if m is not None:
                # save to session state (dict)
                st.session_state.member = m.to_dict() if hasattr(m, "to_dict") else dict(m)
                st.success("Found your record.")
            else:
                st.error("No match found. Check your email/PIN or contact the dojo.")
    except Exception as e:
        st.error(f"Error reading data. Check your Secrets and Google Sheet sharing: {e}")

# ---- logged-in view ----
if st.session_state.member is not None:
    member = st.session_state.member

    # Logout
    if st.button("Logout"):
        st.session_state.member = None
        st.rerun()

    # Pull fields
    def as_float(x, default=0):
        try:
            return float(x)
        except Exception:
            return default

    def pct(a, b):
        try:
            a = float(a); b = float(b)
            return 0 if b <= 0 else max(0, min(100, (a / b) * 100))
        except Exception:
            return 0

    name    = member.get("MemberName","")
    year    = member.get("LeaveYear","")
    allow   = as_float(member.get("AnnualAllowance", 0))
    taken   = as_float(member.get("LeaveTaken", 0))
    bal     = as_float(member.get("LeaveBalance", 0))
    updated = member.get("LastUpdated","")
    email   = member.get("Email","")
    
    # --- Navigation (radio buttons that look like tabs) ---
        nav = st.radio(
            "Navigation",
            ["My balance", "Request update", "My requests", "Dojo info"],
            horizontal=True,
            key="main_tabs"  # remembers selection across reruns
        )

        if nav == "My balance":
            st.markdown(f"**{name}**  ·  {email}")
            st.markdown(f"<div class='muted'>Year: {year} · Last updated: {updated}</div>", unsafe_allow_html=True)
            st.write("")
    
            # Card layout with metrics
            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                st.markdown("<div class='card'><div class='title'>Allowance</div>", unsafe_allow_html=True)
                st.metric(label="", value=f"{int(allow) if isinstance(allow, float) and allow.is_integer() else allow}")
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("<div class='card'><div class='title'>Taken</div>", unsafe_allow_html=True)
                st.metric(label="", value=f"{int(taken) if isinstance(taken, float) and taken.is_integer() else taken}")
                st.markdown("</div>", unsafe_allow_html=True)
            with c3:
                st.markdown("<div class='card'><div class='title'>Balance</div>", unsafe_allow_html=True)
                st.metric(label="", value=f"{int(bal) if isinstance(bal, float) and bal.is_integer() else bal}")
                st.markdown("</div>", unsafe_allow_html=True)
        
            st.write("")
            used_pct = pct(taken, allow)
            st.markdown("**Usage**")
            st.progress(int(used_pct), text=f"{used_pct:.0f}% of allowance used")
            st.markdown(f"<div class='muted'>You have {bal:.0f} remaining out of {allow:.0f}.</div>", unsafe_allow_html=True)
        
        elif nav == "Request update":
            st.subheader("Request an update")
        
            req_type = st.selectbox(
                "Request type",
                ["Leave balance query", "Contact change", "Billing question", "Other"],
                key="req_type"
            )
            msg = st.text_area(
                "Message",
                placeholder="What would you like us to update or check?",
                key="req_msg"
            )
        
            send = st.button("Send request", type="primary", key="req_send_btn")
            if send:
                try:
                    append_request(member, req_type, (msg or "").strip())
                    st.success("Thanks — we received your request.")
                    # Optionally clear inputs
                    st.session_state._

# ---- logged-out view ----
else:
    st.info("Enter your email and PIN to view your balance.")
