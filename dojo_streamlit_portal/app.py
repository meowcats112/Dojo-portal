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

def append_leave_request(member: dict, start_monday, weeks: int, reason="Personal", description=""):
    """Append a weekly leave request (start on Monday, minimum 1 week). Falls back to Message if columns missing."""
    tz = pytz.timezone("Australia/Sydney")
    ts = datetime.now(tz).strftime("%d-%m-%Y %H:%M:%S")  # 👈 timestamp in DD-MM-YYYY
    gc = get_gsheets_client()
    ws = gc.open_by_key(st.secrets["sheets"]["requests_sheet_key"]).sheet1

    start_monday = pd.to_datetime(start_monday).date()
    end_date = (start_monday + pd.Timedelta(days=7 * weeks - 1)).date()

    # Format dates as DD-MM-YYYY
    start_s = start_monday.strftime("%d-%m-%Y")
    end_s = end_date.strftime("%d-%m-%Y")

    headers = ws.row_values(1)
    have = {h: (h in headers) for h in ["StudentName","FromDate","ToDate","Weeks","LeaveReason","LeaveDescription"]}

    base = [
        ts,
        member.get("Email",""),
        member.get("MemberID",""),
        "Leave request",
        "",  # Message (blank if using structured cols)
        "New",
        "",
        ""
    ]

    if all(have.values()):
        row = base + [
            member.get("MemberName",""),
            start_s,
            end_s,
            int(weeks),
            reason,
            description.strip()
        ]
        ws.append_row(row)
    else:
        msg = f"Leave request | {member.get('MemberName','')} | {start_s} → {end_s} | {weeks} week(s) | Reason: {reason}"
        if description.strip():
            msg += f" | Desc: {description.strip()}"
        ws.append_row(base[:4] + [msg] + base[5:])

def _eq_str(a, b):
    return str(a).strip().lower() == str(b).strip().lower()


# --- UI ---
# Heading + logout row
col1, col2 = st.columns([6,1])  # wide column for heading, small one for button
with col1:
    st.markdown("### 🥋 Dojo Member Portal")
with col2:
    if st.button("Logout"):
        st.session_state.member = None
        st.rerun()

# --- Login form (only show if not already logged in) ---
if st.session_state.member is None:
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
                # Find all rows that match this email + PIN
                matches = df[
                    (df["Email"].str.strip().str.lower() == email.strip().lower())
                    & (df["PIN"].astype(str) == pin)
                ]
                
                if not matches.empty:
                    if len(matches) > 1:
                        # More than one student under this account → let user pick
                        student_names = matches["MemberName"].tolist()
                        chosen = st.selectbox("Select a student", student_names, key="student_picker")
                        member_row = matches[matches["MemberName"] == chosen].iloc[0].to_dict()
                    else:
                        # Just one student
                        member_row = matches.iloc[0].to_dict()
                
                    st.session_state.member = member_row
                    st.success("Found your record.")
                    st.rerun()
                else:
                    st.error("No match found. Check your email/PIN or contact the dojo.")
                    
        except Exception as e:
            st.error(f"Error reading data. Check your Secrets and Google Sheet sharing: {e}")

# ---- logged-in view ----
if st.session_state.member is not None:
    member = st.session_state.member

     # Check if this email/PIN has multiple students
    try:
        df = load_members_df()
        matches = df[
            (df["Email"].str.strip().str.lower() == member["Email"].strip().lower())
            & (df["PIN"].astype(str) == str(member["PIN"]))
        ]
        if len(matches) > 1:
            student_names = matches["MemberName"].tolist()
            chosen = st.selectbox("Select a student", student_names, index=student_names.index(member["MemberName"]), key="student_picker")
            # Update the active student if changed
            new_row = matches[matches["MemberName"] == chosen].iloc[0].to_dict()
            st.session_state.member = new_row
            member = new_row
    except Exception as e:
        st.error(f"Could not load student list: {e}")

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

    st.markdown(f"**{name}**  ·  {email}")
    st.write("")  # spacer

    # --- Navigation (radio buttons that look like tabs) ---
    nav = st.radio(
        "Navigation",
        ["My balance", "Leave request", "Request update", "My requests", "Dojo info"],
        horizontal=True,
        key="main_tabs"  # remembers selection across reruns
    )

    if nav == "My balance":

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

        st.write("")  # spacer
        st.write("")  # spacer
        st.markdown(f"<div class='muted'>Year: {year} · Last updated: {updated}</div>", unsafe_allow_html=True)
        st.write("")  # spacer

    elif nav == "Leave request":
        st.subheader("Request Leave")

        # --- Reminder about dojo policy ---
        st.info(
        "Members may suspend their membership for 8 weeks per calendar year. " 
        "The first 4 weeks will be free of charge and the following 4 weeks will be at a discounted rate of \$10 per week. " 
        "Suspensions must be submitted via the portal with a minimum of 14 days notice. "
        "Failure to do so may incur a \$10 short-notice fee or result in request being rejected."
    )
    
        import datetime as _dt
        def next_monday(d: _dt.date) -> _dt.date:
            return d if d.weekday() == 0 else d + _dt.timedelta(days=(7 - d.weekday()))
    
        today = _dt.date.today()
        default_start = next_monday(today)
        start_sel = st.date_input(
            "Start date (must be a Monday)",
            value=default_start,
            key="lr_start_monday"
        )
    
        weeks = st.number_input(
            "Number of weeks",
            min_value=1, step=1, value=1,
            help="Leave is taken in whole weeks (Mon–Sun).",
            key="lr_weeks"
        )
    
        reason = st.selectbox(
            "Leave reason",
            ["Personal", "Injury or Serious Illness"],
            key="lr_reason"
        )

        if reason == "Injury or Serious Illness":
            st.warning("A medical certificate stating nature of injury/illness and recovery time is required.  \nPlease send through to admin@example.com")

    
        description = st.text_input(
            "Short description (optional)",
            max_chars=120,
            key="lr_desc"
        )
    
        snapped_start = next_monday(start_sel)
        if start_sel.weekday() != 0:
            st.info(f"Start date will be adjusted to Monday: **{snapped_start.strftime('%d-%m-%Y')}**")
    
        end_date = snapped_start + _dt.timedelta(days=7 * int(weeks) - 1)
        st.caption(f"Requested period: **{snapped_start.strftime('%d-%m-%Y')} → {end_date.strftime('%d-%m-%Y')}** ({int(weeks)} week(s))")
    
        if st.button("Submit leave request", type="primary", key="lr_submit"):
             # --- Overlap validation: check existing leave requests for this member ---
            gc = get_gsheets_client()
            r_ws = gc.open_by_key(st.secrets["sheets"]["requests_sheet_key"]).sheet1
            r_df = pd.DataFrame(r_ws.get_all_records())
    
            overlap_found = False
            conflict_rows = pd.DataFrame()
    
            if not r_df.empty:
                mine = r_df[r_df["MemberEmail"].str.strip().str.lower() == str(email).strip().lower()]
                if "MemberID" in mine.columns:
                    mine = mine[mine["MemberID"].astype(str).str.strip().str.lower() == str(member.get("MemberID","")).strip().lower()]
                    if not mine.empty:
                        # Only leave requests
                        if "RequestType" in mine.columns:
                            mine = mine[mine["RequestType"].str.strip().str.lower() == "leave request"]
    
                    # Try parse FromDate/ToDate (DD-MM-YYYY or other); fall back to message parsing if needed
                    if "FromDate" in mine.columns and "ToDate" in mine.columns:
                        start_new = snapped_start
                        end_new = end_date
    
                        # Parse with dayfirst for DD-MM-YYYY
                        mine["_from"] = pd.to_datetime(mine["FromDate"], errors="coerce", dayfirst=True)
                        mine["_to"]   = pd.to_datetime(mine["ToDate"],   errors="coerce", dayfirst=True)
    
                        # Any overlap if: existing_from <= new_end AND existing_to >= new_start
                        conflict_mask = (mine["_from"].notna() & mine["_to"].notna() &
                                         (mine["_from"].dt.date <= end_new) &
                                         (mine["_to"].dt.date   >= start_new))
                        conflict_rows = mine[conflict_mask]
                        overlap_found = not conflict_rows.empty
    
            if overlap_found:
                # Show conflicts with friendly dates
                show = conflict_rows.copy()
                show["FromDate"] = pd.to_datetime(show["_from"]).dt.strftime("%d-%m-%Y")
                show["ToDate"]   = pd.to_datetime(show["_to"]).dt.strftime("%d-%m-%Y")
                st.error("This period overlaps an existing leave request. Please choose a different Monday or weeks.")
                st.dataframe(show[["FromDate", "ToDate", "Weeks", "Status"]] if "Weeks" in show.columns else show[["FromDate","ToDate","Status"]],
                             use_container_width=True, hide_index=True)
            try:
                append_leave_request(member, snapped_start, int(weeks), reason, description)
                st.success("Leave request submitted. We’ll review it soon.")
                st.session_state.lr_weeks = 1
                st.session_state.lr_desc = ""
                st.session_state.lr_reason = "Personal"
                st.session_state.lr_start_monday = next_monday(_dt.date.today())
            except Exception as e:
                st.error(f"Could not submit leave request: {e}")


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
                st.session_state.req_type = "Leave balance query"
                st.session_state.req_msg = ""
            except Exception as e:
                st.error(f"Could not submit request: {e}")

    elif nav == "My requests":
        st.subheader("My leave requests")
    
        try:
            gc = get_gsheets_client()
            r_ws = gc.open_by_key(st.secrets["sheets"]["requests_sheet_key"]).sheet1
            r_df = pd.DataFrame(r_ws.get_all_records())
    
            if r_df.empty:
                st.info("No requests yet.")
            else:
                # Filter to this member (email + MemberID)
                mine = r_df[
                    r_df.get("MemberEmail", "").astype(str).str.strip().str.lower()
                    == str(email).strip().lower()
                ]
                
                # Filter to this member (email + MemberID)
                mine = r_df[
                    r_df.get("MemberEmail", "").astype(str).str.strip().str.lower() == str(email).strip().lower()
                ]
                if "MemberID" in mine.columns:
                    mine = mine[mine["MemberID"].astype(str).str.strip().str.lower() == str(member.get("MemberID","")).strip().lower()]
                
                # Keep only leave requests if column exists
                if "RequestType" in mine.columns:
                    mine = mine[mine["RequestType"].astype(str).str.strip().str.lower() == "leave request"]
                
                total_count = len(mine)
                pending_values = {"new", "pending", "in review", "in-progress", "submitted"}
                pending_count = 0
                if "Status" in mine.columns and not mine.empty:
                    status_lower = mine["Status"].astype(str).str.strip().str.lower()
                    pending_count = status_lower.isin(pending_values).sum()
                
                # Toggle with counters
                show_choice = st.radio(
                    "Show",
                    [f"Pending only ({pending_count})", f"All ({total_count})"],
                    horizontal=True,
                    key="myreq_filter"
                )
                
                # Apply filter based on selection
                if "Status" in mine.columns and show_choice.startswith("Pending"):
                    status_lower = mine["Status"].astype(str).str.strip().str.lower()
                    mine = mine[status_lower.isin(pending_values)]

    
                if mine.empty:
                    st.info("No requests matching this filter.")
                else:
                    # Format dates in DD-MM-YYYY
                    if "FromDate" in mine.columns:
                        mine["FromDate"] = pd.to_datetime(
                            mine["FromDate"], errors="coerce", dayfirst=True
                        ).dt.strftime("%d-%m-%Y")
                    if "ToDate" in mine.columns:
                        mine["ToDate"] = pd.to_datetime(
                            mine["ToDate"], errors="coerce", dayfirst=True
                        ).dt.strftime("%d-%m-%Y")
                    if "Timestamp" in mine.columns:
                        ts_parsed = pd.to_datetime(
                            mine["Timestamp"], errors="coerce", dayfirst=True
                        )
                        mine["Timestamp"] = ts_parsed.dt.strftime("%d-%m-%Y %H:%M")
    
                    # Choose display columns
                    cols_order = [c for c in
                                  ["Timestamp","FromDate","ToDate","Weeks","LeaveReason","LeaveDescription","Status","AdminNotes"]
                                  if c in mine.columns]
                    if not cols_order:
                        cols_order = [c for c in ["Timestamp","Message","Status","AdminNotes"] if c in mine.columns]
    
                    # Sort newest first
                    if "Timestamp" in mine.columns:
                        mine["_ts"] = pd.to_datetime(mine["Timestamp"], errors="coerce", dayfirst=True)
                        mine = mine.sort_values("_ts", ascending=False).drop(columns=["_ts"], errors="ignore")
    
                    st.dataframe(mine[cols_order], use_container_width=True, hide_index=True)
    
        except Exception as e:
            st.error(f"Could not load requests: {e}")


    elif nav == "Dojo info":
        st.subheader("Dojo info")
        st.markdown("""
- **Timetable:** See our latest class times on the noticeboard or website.
- **Leave policy:** Members have an annual allowance; please submit requests early where possible.
- **Contact:** admin@yourdojo.com · 0400 000 000
        """)

# ---- logged-out view ----
else:
    st.info("Enter your email and PIN to view your balance.")
