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

def append_contact_update(member: dict, update_type: str, update_name: str, *,
                          phone: str = "", email: str = "",
                          addr1: str = "", addr2: str = "", suburb: str = "", postcode: str = ""):
    """Append a structured Contact update to the Requests sheet.
    Works with your headers and only fills columns that exist."""
    tz = pytz.timezone("Australia/Sydney")
    ts = datetime.now(tz).strftime("%d-%m-%Y %H:%M:%S")

    gc = get_gsheets_client()
    ws = gc.open_by_key(st.secrets["sheets"]["requests_sheet_key"]).sheet1
    headers = ws.row_values(1)

    # Base required fields per your sheet
    row_map = {
        "Timestamp": ts,
        "MemberEmail": member.get("Email", ""),
        "MemberID": member.get("MemberID", ""),
        "RequestType": "Contact update",
        "Message": "",  # we'll keep this empty if structured cols exist
        "FromDate": "",
        "ToDate": "",
        "LeaveReason": "",
        "LeaveDescription": "",
        "Status": "New",
        "HandledBy": "",
        "AdminNotes": "",
        # Structured contact fields (only set if present)
        "UpdateType": update_type,
        "UpdateName": update_name,
        "UpdatePhone": phone,
        "UpdateEmail": email,
        "Addr1": addr1,
        "Addr2": addr2,
        "Suburb": suburb,
        "PostCode": postcode,
    }

    # If structured columns are missing, put everything into Message for safety
    structured_cols = ["UpdateType","UpdateName","UpdatePhone","UpdateEmail","Addr1","Addr2","Suburb","PostCode"]
    if not any(c in headers for c in structured_cols):
        parts = [f"Type: {update_type}", f"Name: {update_name}"]
        if phone: parts.append(f"Phone: {phone}")
        if email: parts.append(f"Email: {email}")
        if any([addr1, addr2, suburb, postcode]):
            addr = ", ".join([p for p in [addr1, addr2, suburb, postcode] if p])
            parts.append(f"Address: {addr}")
        row_map["Message"] = " | ".join(parts)

    # Emit values in the exact order of your sheet’s headers
    values = [row_map.get(h, "") for h in headers]
    ws.append_row(values)



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
        ["My balance", "Leave request", "Update contact details", "My requests", "Dojo info"],
        horizontal=True,
        key="main_tabs"  # remembers selection across reruns
    )

    if nav == "My balance":

        st.info("Leave per calendar year")

        # Card layout with metrics
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            st.markdown("<div class='card'><div class='title'>Total</div>", unsafe_allow_html=True)
            st.metric(label="", value=f"{int(allow) if isinstance(allow, float) and allow.is_integer() else allow}")
            st.caption("week(s)")
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='card'><div class='title'>Taken</div>", unsafe_allow_html=True)
            st.metric(label="", value=f"{int(taken) if isinstance(taken, float) and taken.is_integer() else taken}")
            st.caption("week(s)")
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown("<div class='card'><div class='title'>Remaining</div>", unsafe_allow_html=True)
            st.metric(label="", value=f"{int(bal) if isinstance(bal, float) and bal.is_integer() else bal}")
            st.caption("week(s)")
            st.markdown("</div>", unsafe_allow_html=True)

        st.write("")

        # --- Calculate free vs paid usage ---
        free_allowance = 4
        paid_allowance = max(0, allow - free_allowance)
        
        free_used = min(taken, free_allowance)
        paid_used = max(0, taken - free_allowance)
        
        free_used_pct = (free_used / allow) * 100 if allow > 0 else 0
        paid_used_pct = (paid_used / allow) * 100 if allow > 0 else 0
        
        # --- Custom progress bar ---
        st.markdown("**Usage**", unsafe_allow_html=True)
        
        bar_html = f"""
        <div style="background-color:#e0e0e0;border-radius:10px;height:24px;width:100%;overflow:hidden;display:flex">
          <div style="background-color:#4CAF50;width:{free_used_pct}%;"></div>
          <div style="background-color:#FF9800;width:{paid_used_pct}%;"></div>
        </div>
        <p style="font-size:0.85em;margin-top:4px">
          <span style="color:#4CAF50">■</span> Free weeks used: {int(free_used)} / {int(free_allowance)} &nbsp; 
          <span style="color:#FF9800">■</span> Paid weeks used: {int(paid_used)} / {int(paid_allowance)}
        </p>
        """
        
        st.markdown(bar_html, unsafe_allow_html=True)
        
        # --- Summary line ---
        st.markdown(
            f"<div class='muted'>You have {bal:.0f} weeks remaining out of {allow:.0f} total.</div>",
            unsafe_allow_html=True
        )

        st.write("")  # spacer
        st.write("")  # spacer
        st.markdown(f"<div class='muted'>Year: {year} · Last updated: {updated}</div>", unsafe_allow_html=True)
        st.write("")  # spacer

    elif nav == "Leave request":
        st.subheader("Request Leave")

        # --- Reminder about dojo policy ---
        st.info(
        "Leave requests must be submitted in writing with at least fourteen (14) days’ notice.  \nLeave is taken in full weekly blocks (minimum of one week), with a maximum of eight (8) weeks permitted per calendar year. \nThe first four (4) weeks of leave each calendar year are free of charge. Any approved leave beyond four (4) weeks, up to the annual maximum of eight (8) weeks, will incur a $10.00 per week processing fee. \nStudents are not permitted to attend classes during an approved leave period. \nAdditional leave may be considered in cases of serious illness or injury where a valid medical certificate is provided."
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
            ["", "Personal", "Injury or Serious Illness"],
            key="lr_reason"
        )

        if not reason:
            st.info("⚠️ Please select a leave reason before submitting.")

        if reason == "Injury or Serious Illness":
            st.warning("A medical certificate stating nature of injury/illness and recovery time is required.  \nPlease send through to admin@example.com")

    
        description = st.text_input(
            "Short description",
            max_chars=120,
            key="lr_desc"
        )
    
        snapped_start = next_monday(start_sel)
        if start_sel.weekday() != 0:
            st.info(f"Start date will be adjusted to Monday: **{snapped_start.strftime('%d-%m-%Y')}**")
    
        end_date = snapped_start + _dt.timedelta(days=7 * int(weeks) - 1)
        st.caption(f"Requested period: **{snapped_start.strftime('%d-%m-%Y')} → {end_date.strftime('%d-%m-%Y')}** ({int(weeks)} week(s))")
    
        if st.button("Submit leave request", type="primary", key="lr_submit"):
                # --- Required field checks ---
            if not snapped_start:
                st.error("Please select a start date.")
            elif not weeks or weeks < 1:
                st.error("Please enter at least 1 week.")
            elif not reason:
                st.error("Please select a leave reason.")
            elif not description or not description.strip():
                st.error("Please enter a short description for your leave request.")
            else:
                try:
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
                    
                        append_leave_request(member, snapped_start, int(weeks), reason, description)
                        st.success("Leave request submitted. We’ll review it soon.")
                        st.session_state.lr_weeks = 1
                        st.session_state.lr_desc = ""
                        st.session_state.lr_reason = "Personal"
                        st.session_state.lr_start_monday = next_monday(_dt.date.today())
                except Exception as e:
                    st.error(f"Could not submit leave request: {e}")


    elif nav == "Update contact details":
        st.subheader("Update contact details")
    
        # Choose detail to update
        detail_type = st.selectbox(
            "Which detail would you like to update?",
            ["Phone number", "Address", "Email"],
            key="upd_detail_type"
        )
    
        # Show the relevant field right away (reactive)
        value = ""
        if detail_type == "Phone number":
            person_name = st.text_input("Name of person", key="upd_name")
            value = st.text_input("New phone number", key="upd_phone")
        elif detail_type == "Address":
            addr1 = st.text_input("Address Line 1", key="upd_addr1")
            addr2 = st.text_input("Address Line 2", key="upd_addr2")
            suburb = st.text_input("Suburb", key="upd_suburb")
            postcode = st.text_input("Post Code", key="upd_postcode")
        elif detail_type == "Email":
            person_name = st.text_input("Name of person", key="upd_name")
            value = st.text_input("New email address", key="upd_email")
    
    
            # Submit button
            if st.button("Submit update", type="primary", key="upd_submit"):
                try:
                    if detail_type == "Phone number":
                        import re
                        raw = phone  # from st.text_input above
                        digits = re.sub(r"\D", "", raw)  # keep only numbers
        
                        if len(digits) == 10 and digits.startswith("0"):
                            formatted = f"{digits[0:4]} {digits[4:7]} {digits[7:10]}"  # 0400 123 456
                            append_contact_update(member, "Phone number", person_name, phone=formatted)
                            st.success(f"Your contact update has been submitted: {formatted}")
                        else:
                            st.error("Please enter a valid 10-digit mobile (e.g. 0400 123 456).")
        
                    elif detail_type == "Email":
                        append_contact_update(member, "Email", person_name, email=new_email)
                        st.success("Your contact update has been submitted.")
        
                    elif detail_type == "Address":
                        append_contact_update(
                            member, "Address", person_name,
                            addr1=addr1, addr2=addr2, suburb=suburb, postcode=postcode
                        )
                        st.success("Your contact update has been submitted.")
        
                except Exception as e:
                    st.error(f"Could not submit update: {e}")

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
                    r_df.get("MemberEmail", "").astype(str).str.strip().str.lower() == str(email).strip().lower()
                ]
                if "MemberID" in mine.columns:
                    mine = mine[mine["MemberID"].astype(str).str.strip().str.lower() == str(member.get("MemberID","")).strip().lower()]
                
                    if mine.empty:
                        st.info("No requests yet.")
                    
                    else:
                        # Normalise RequestType for counting / filtering
                        rt = mine.get("RequestType", "").astype(str).str.strip().str.lower()
                        is_leave   = rt == "leave request"
                        is_contact = rt == "contact update"
                    
                        # ---- Build counts for labels ----
                        total_leave_all    = int(is_leave.sum())
                        total_contact_all  = int(is_contact.sum())
                        total_all_all      = len(mine)
        
                        pending_values = {"new","pending","in review","in-progress","submitted"}
                        status_lower = mine.get("Status","").astype(str).str.strip().str.lower()
                        total_leave_pending   = int((is_leave   & status_lower.isin(pending_values)).sum())
                        total_contact_pending = int((is_contact & status_lower.isin(pending_values)).sum())
                        total_all_pending     = int(status_lower.isin(pending_values).sum())
    
                    
                        # ---- Category picker (with counts) ----
                        cat_choice = st.radio(
                        "Category",
                            [
                                f"Leave requests ({total_leave_pending}/{total_leave_all} pending)",
                                f"Contact updates ({total_contact_pending}/{total_contact_all} pending)",
                                f"All ({total_all_pending}/{total_all_all} pending)"
                            ],
                            horizontal=True,
                            key="myreq_category"
                        )
    
                    
                        # Apply category filter
                        view = mine.copy()
                        if cat_choice.startswith("Leave requests"):
                            view = view[is_leave]
                        elif cat_choice.startswith("Contact updates"):
                            view = view[is_contact]
                        # else: All → no extra filter
    
                        # Recompute counts for selected category
                        status_lower_view = view.get("Status","").astype(str).str.strip().str.lower()
                        selected_total = len(view)
                        selected_pending = int(status_lower_view.isin(pending_values).sum())
    
                        # ---- Pending vs All toggle (with counters) ----
                        show_choice = st.radio(
                            "Show",
                            [f"Pending ({selected_pending})", f"All ({selected_total})"],
                            horizontal=True,
                            key="myreq_filter"
                        )
                        if show_choice.startswith("Pending"):
                            view = view[status_lower_view.isin(pending_values)]
    
                        # Done filtering?
                        if view.empty:
                            st.info("No requests matching this filter.")
                        else:
                            # ---- Format dates DD-MM-YYYY ----
                            if "FromDate" in view.columns:
                                view["FromDate"] = pd.to_datetime(view["FromDate"], errors="coerce", dayfirst=True).dt.strftime("%d-%m-%Y")
                            if "ToDate" in view.columns:
                                view["ToDate"]   = pd.to_datetime(view["ToDate"],   errors="coerce", dayfirst=True).dt.strftime("%d-%m-%Y")
                            if "Timestamp" in view.columns:
                                ts_parsed = pd.to_datetime(view["Timestamp"], errors="coerce", dayfirst=True)
                                view["Timestamp"] = ts_parsed.dt.strftime("%d-%m-%Y %H:%M")
    
                            # ---- Choose columns based on category ----
                            prefer_leave = [c for c in ["Timestamp","FromDate","ToDate","Weeks","LeaveReason","LeaveDescription","Status","AdminNotes"] if c in view.columns]
                            prefer_contact = [c for c in ["Timestamp","UpdateType","UpdateName","UpdatePhone","UpdateEmail","Addr1","Addr2","Suburb","PostCode","Status","AdminNotes"] if c in view.columns]
                            fallback = [c for c in ["Timestamp","RequestType","Message","Status","AdminNotes"] if c in view.columns]
        
                            if cat_choice.startswith("Leave requests") and prefer_leave:
                                cols_order = prefer_leave
                            elif cat_choice.startswith("Contact updates") and prefer_contact:
                                cols_order = prefer_contact
                            else:
                                # "All" or when structured columns aren't present
                                # Use a union that keeps things readable
                                cols_union = prefer_leave + [c for c in prefer_contact if c not in prefer_leave]
                                cols_order = cols_union if cols_union else fallback
        
                            # ---- Sort newest first if we have Timestamp ----
                            if "Timestamp" in view.columns:
                                view["_ts"] = pd.to_datetime(view["Timestamp"], errors="coerce", dayfirst=True)
                                view = view.sort_values("_ts", ascending=False).drop(columns=["_ts"], errors="ignore")
        
                            st.data_editor(
                                view[cols_order],
                                use_container_width=True,
                                hide_index=True,
                                disabled=True,  # makes it read-only
                                column_config={
                                    "Addr1": st.column_config.Column("Address Line 1", width="large"),
                                    "Addr2": st.column_config.Column("Address Line 2", width="large"),
                                    "Suburb": st.column_config.Column("Suburb", width="medium"),
                                    "PostCode": st.column_config.Column("Post Code", width="small"),
                                }
                            )


        except Exception as e:
            st.error(f"Could not load requests: {e}")


    elif nav == "Dojo info":
        st.subheader("Dojo info")
        st.markdown("""
- **Timetable:** See our latest class times on the noticeboard or website.
- **Leave policy:** For full details of the Membership Suspension Policy, please refer to the Membership Terms & Conditions.
- **Contact:** skwaverley@gmail.com · 0483 956 262
        """)

# ---- logged-out view ----
else:
    st.info("Enter your email and PIN to view your balance.")
