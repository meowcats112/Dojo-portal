# 🥋 Dojo Member Portal (Streamlit + Google Sheets)

A free, lightweight portal where members can view their **own** leave balance and submit simple account update requests.

## What you'll get
- A hosted web app (Streamlit Community Cloud) — share a single URL with ~50 members.
- Members authenticate with **email + PIN** (stored in your Google Sheet).
- Data lives in two Google Sheets: `Members` and `Requests`.
- You update leave balances manually in Sheets; the app reflects changes instantly.

---

## 1) Prepare Google Sheets
Create **two** Google Sheets (or two tabs in one spreadsheet — each with its own *sheet key* works best as separate files):

- **Members** — columns (exact names):
  - `MemberID`, `MemberName`, `Email`, `LeaveYear`, `AnnualAllowance`, `LeaveTaken`, `LeaveBalance`, `LastUpdated`, `Notes`, and either `PIN` **or** `PIN_Hash`

- **Requests** — columns:
  - `Timestamp`, `MemberEmail`, `MemberID`, `RequestType`, `Message`, `Status`, `HandledBy`, `AdminNotes`

> Tip: Add a **PIN** value for each member (e.g., 6 digits). To avoid storing plain PINs, generate `PIN_Hash` using `utils/hash_pins.py` and delete the `PIN` column.

---

## 2) Get a Google Service Account
1. Go to Google Cloud Console → Create a project → Enable **Google Sheets API**.
2. Create **Service Account** → create a JSON key and copy its fields.
3. In your **Members** and **Requests** Google Sheets, click **Share** and add the service account email (ends with `iam.gserviceaccount.com`) with **Editor** access.

---

## 3) Deploy on Streamlit Community Cloud
1. Push this folder to a **public GitHub repo**.
2. Go to **streamlit.io** → **Deploy an app** → select your repo/branch.
3. Add **Secrets** in the app dashboard:
   - Paste the contents from `.streamlit/secrets.example.toml`, filling in your service account fields.
   - Set `members_sheet_key` / `requests_sheet_key` to your Google Sheet keys (the long ID in the sheet URL).
   - Choose a random `pin_salt` string.

4. After the first run, confirm no errors. Your app URL will look like:
   `https://YOUR-APP-NAME.streamlit.app`

---

## 4) Local testing (optional)
```bash
pip install -r requirements.txt
streamlit run app.py
```
Use a local file `.streamlit/secrets.toml` with the same content as the example, but **never commit** real secrets to Git.

---

## 5) Security notes
- Email + PIN prevents casual snooping; use `PIN_Hash` + salt for better hygiene.
- Do **not** put any sensitive data in the Members sheet. Keep it to names, emails, leave figures.
- If stricter auth is required later, you can add OAuth or a proper auth library.

---

## 6) Customise the UI
- Replace the page icon/title in `app.py`.
- Add your dojo logo with `st.image("https://...")` at the top.
- Add a **Dojo Info** section by reading a third sheet or a Markdown file.

---

## Columns reference
**Members**:
- MemberID, MemberName, Email, LeaveYear, AnnualAllowance, LeaveTaken, LeaveBalance, LastUpdated, Notes, PIN or PIN_Hash

**Requests**:
- Timestamp (auto), MemberEmail, MemberID, RequestType, Message, Status (default "New"), HandledBy, AdminNotes

---

## Hashing PINs (recommended)
```bash
python utils/hash_pins.py --infile members.csv --outfile members_hashed.csv --salt "YOUR_SALT"
```
Then upload `members_hashed.csv` to your Google Sheet and remove the plain `PIN` column.

---

### Need help?
- If you hit an error like “The caller does not have permission”, you likely forgot to **Share** the Google Sheets with your service account email.
- If the app can’t find columns, check your header names exactly match.
