"""
DhruvLambda.py — original Lex fulfillment PLUS dynamic-form handlers.
Same protocol as AngelLambda:
  event = { "formAction": "INIT"|"SUBMIT"|"CONFIRM",
            "bot": "dhruv", "sessionId": "...", "values": {...} }
"""
import re
import json
import uuid
from datetime import datetime, timedelta
# ── DOMAIN DATA (from your existing file) ────────────────────────────
VALID_PRODUCTS = ["Refrigerator", "Television", "Washing Machine", "Dishwasher"]
TIME_SLOTS = [
    ("09:00 AM", "09:00 AM"), ("10:00 AM", "10:00 AM"), ("11:00 AM", "11:00 AM"),
    ("12:00 PM", "12:00 PM"), ("01:00 PM", "01:00 PM"), ("02:00 PM", "02:00 PM"),
    ("03:00 PM", "03:00 PM"), ("04:00 PM", "04:00 PM"), ("05:00 PM", "05:00 PM"),
    ("06:00 PM", "06:00 PM"), ("07:00 PM", "07:00 PM"), ("08:00 PM", "08:00 PM")
]
BOOKED_SLOTS = {
    "2026-07-10": ["09:00", "12:00", "15:00"],
    "2026-07-11": ["10:00", "17:00"]
}
def get_available_dates():
    buttons = []
    curr = datetime.today()
    while len(buttons) < 15:
        curr += timedelta(days=1)
        if curr.weekday() < 5:
            buttons.append({
                "text":  curr.strftime("%a, %b %d"),
                "value": curr.strftime("%Y-%m-%d")
            })
    return buttons
def get_available_slots(date_str):
    booked = BOOKED_SLOTS.get(date_str, [])
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    available = []
    for val, label in TIME_SLOTS:
        slot_time = datetime.strptime(val, "%I:%M %p").time()
        val_24h = slot_time.strftime("%H:%M")
        if val_24h in booked: continue
        if date_str == today_str and slot_time <= now.time(): continue
        available.append({"value": val, "text": label})
    return available
def _valid_email(v): return bool(re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', v or ""))
def _valid_phone(v): return bool(re.fullmatch(r'\d{10}', (v or "").replace(" ", "")))
# ── DYNAMIC FORM HANDLERS ────────────────────────────────────────────
def _form_schema():
    return {
        "botKey": "dhruv",
        "title": "Sales Lead",
        "subtitle": "Dhruv's Assistant — Purchase help",
        "fields": [
            {"name": "FirstName",   "label": "First ", "type": "text",
             "required": True, "maxLength": 40},
            {"name": "LastName",    "label": "Last name",  "type": "text",
             "required": True, "maxLength": 40},
            {"name": "PhoneNumber", "label": "Phone",      "type": "phone",
             "required": True, "hint": "10 digits"},
            {"name": "Email",       "label": "Email",      "type": "email",
             "required": True, "placeholder": "you@example.com"},
            {"name": "ProductName", "label": "Product",    "type": "chips",
             "required": True,
             "options": [{"text": p, "value": p} for p in VALID_PRODUCTS]},
            {"name": "PreferredDate", "label": "Preferred date", "type": "date-grid",
             "required": True, "options": get_available_dates()},
            {"name": "PreferredTime", "label": "Preferred time", "type": "time-grid",
             "required": True,
             "options": [{"text": t, "value": v} for v, t in TIME_SLOTS]}
        ]
    }
def _validate_form(values):
    errors = {}
    def req(name, label):
        if not values.get(name) or not str(values[name]).strip():
            errors[name] = f"{label} is required."
    req("FirstName",     "First name")
    req("LastName",      "Last name")
    req("PhoneNumber",   "Phone")
    req("Email",         "Email")
    req("ProductName",   "Product")
    req("PreferredDate", "Date")
    req("PreferredTime", "Time")
    if values.get("PhoneNumber") and not _valid_phone(values["PhoneNumber"]):
        errors["PhoneNumber"] = "Enter exactly 10 digits."
    if values.get("Email") and not _valid_email(values["Email"]):
        errors["Email"] = "Enter a valid email address."
    if values.get("ProductName") and values["ProductName"].lower() not in [p.lower() for p in VALID_PRODUCTS]:
        errors["ProductName"] = "Unsupported product."
    if values.get("PreferredDate"):
        try:
            d = datetime.strptime(values["PreferredDate"], "%Y-%m-%d").date()
            if d <= datetime.today().date():
                errors["PreferredDate"] = "Please pick a future date."
        except Exception:
            errors["PreferredDate"] = "Invalid date."
    if values.get("PreferredDate") and values.get("PreferredTime"):
        avail = get_available_slots(values["PreferredDate"])
        if not any(a["value"].lower() == values["PreferredTime"].lower() for a in avail):
            errors["PreferredTime"] = "That time slot is no longer available."
    return errors
def _save_booking(values, session_id):
    ref = "DH-" + uuid.uuid4().hex[:8].upper()
    # Replace with DynamoDB / RDS / SES / etc.
    print(f"[dhruv] booking saved ref={ref} session={session_id} values={values}")
    return ref
def _form_response(messages=None, session_attrs=None):
    return {"messages": messages or [], "sessionAttributes": session_attrs or {}}
def handle_form_event(event):
    action = (event.get("formAction") or "").upper()
    values = event.get("values", {}) or {}
    session_id = event.get("sessionId", "")
    if action == "INIT":
        return _form_response(
            messages=[{"contentType": "PlainText",
                       "content": "Please fill in the form below to book your purchase consultation."}],
            session_attrs={"formSchema": json.dumps(_form_schema())}
        )
    if action == "SUBMIT":
        errors = _validate_form(values)
        if errors:
            return _form_response(
                messages=[{"contentType": "PlainText",
                           "content": "Please fix the highlighted fields."}],
                session_attrs={"formErrors": json.dumps(errors)}
            )
        summary = {
            "title": "Confirm your consultation",
            "subtitle": "Review the details before we book.",
            "rows": [
                {"label": "Name",    "value": f"{values.get('FirstName','').title()} {values.get('LastName','').title()}"},
                {"label": "Phone",   "value": values.get("PhoneNumber","")},
                {"label": "Email",   "value": values.get("Email","")},
                {"label": "Product", "value": values.get("ProductName","")},
                {"label": "Date",    "value": values.get("PreferredDate","")},
                {"label": "Time",    "value": values.get("PreferredTime","")}
            ]
        }
        return _form_response(session_attrs={"formSummary": json.dumps(summary)})
    if action == "CONFIRM":
        errors = _validate_form(values)
        if errors:
            return _form_response(
                messages=[{"contentType": "PlainText",
                           "content": "Some details are no longer valid. Please review the form again."}],
                session_attrs={"formErrors": json.dumps(errors)}
            )
        ref = _save_booking(values, session_id)
        return _form_response(session_attrs={"formSuccess": json.dumps({
            "title":       "Booking confirmed!",
            "message":     f"Our executive will call you at {values.get('PreferredTime','')} on {values.get('PreferredDate','')}.",
            "referenceId": ref
        })})
    return _form_response(messages=[{"contentType": "PlainText",
                                     "content": f"Unknown form action: {action}"}])
# ── LEX FULFILLMENT (original behavior preserved) ────────────────────
def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("formAction"):
        return handle_form_event(event)
    # Original Lex flow — keep your existing DhruvLambda_updated.py logic here
    # unchanged. Stubbed delegate for illustration:
    intent = event.get("sessionState", {}).get("intent", {})
    return {
        "sessionState": {
            "sessionAttributes": {"uiButtons": json.dumps([])},
            "dialogAction": {"type": "Delegate"},
            "intent": {"name": intent.get("name", ""), "slots": intent.get("slots", {})}
        }
    }