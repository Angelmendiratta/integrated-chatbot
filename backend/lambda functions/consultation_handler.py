"""
AngelLambda.py — original Lex fulfillment PLUS dynamic-form handlers.
The router (LexApiHandler) invokes this Lambda directly with a payload like:
  { "formAction": "INIT" | "SUBMIT" | "CONFIRM",
    "bot": "angel", "sessionId": "...", "values": { ... } }
Any event WITHOUT `formAction` is treated as a normal Lex event and delegated
to the original handler at the bottom of this file (unchanged behavior).
"""
import json
import re
import datetime
import uuid
# --- MOCK DATABASE ---
BOOKED_APPOINTMENTS = {
    "2026-06-30": ["09:00", "14:00"],
    "2026-07-01": ["10:00", "15:00", "16:00"]
}
VALID_PRODUCTS = ["Refrigerator", "Television", "Washing Machine", "Dish Washer"]
# --- HELPER FUNCTIONS (unchanged) ---
def validate_phone(phone_number):
    if not phone_number: return False
    cleaned = ''.join(filter(str.isdigit, phone_number))
    return len(cleaned) == 10
def validate_email(email_address):
    if not email_address: return False
    regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return bool(re.match(regex, email_address))
def get_business_days():
    utc_now = datetime.datetime.utcnow()
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    current_date = ist_now.date()
    if ist_now.hour >= 17:
        current_date += datetime.timedelta(days=1)
    valid_days = []
    button_days = []
    lookahead = 0
    while len(valid_days) < 30 and lookahead < 60:
        if current_date.weekday() < 5:
            date_str = current_date.strftime("%Y-%m-%d")
            available_times = get_available_times(date_str)
            if len(available_times) > 0:
                valid_days.append(date_str)
                if len(button_days) < 15:
                    button_days.append({
                        "text": current_date.strftime("%a, %b %d"),
                        "value": date_str
                    })
        current_date += datetime.timedelta(days=1)
        lookahead += 1
    return valid_days, button_days
def get_available_times(date_str):
    utc_now = datetime.datetime.utcnow()
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    is_today = (date_str == ist_now.strftime("%Y-%m-%d"))
    current_hour = ist_now.hour
    booked_times = BOOKED_APPOINTMENTS.get(date_str, [])
    all_times = []
    for h in range(9, 18):
        if is_today and h <= current_hour: continue
        val_24h = f"{str(h).zfill(2)}:00"
        if val_24h in booked_times: continue
        ampm = "AM" if h < 12 else "PM"
        display_h = h if h <= 12 else h - 12
        text_12h = f"{str(display_h).zfill(2)}:00 {ampm}"
        all_times.append({"text": text_12h, "value": text_12h, "val_24h": val_24h})
    return all_times
def normalize_time(raw):
    if not raw: return ""
    raw = raw.strip()
    match_24 = re.match(r'^(\d{1,2}):(\d{2})$', raw)
    if match_24: return f"{int(match_24.group(1)):02d}:{match_24.group(2)}"
    match_12 = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', raw, re.IGNORECASE)
    if match_12:
        h = int(match_12.group(1)); m = match_12.group(2); period = match_12.group(3).upper()
        if period == "AM": h = 0 if h == 12 else h
        else: h = 12 if h == 12 else h + 12
        return f"{h:02d}:{m}"
    return raw
# =====================================================================
# DYNAMIC FORM HANDLERS  (new — additive, do not change Lex logic)
# =====================================================================
def _form_schema():
    """Return the JSON schema the frontend renders."""
    _, date_buttons = get_business_days()
    return {
        "botKey": "angel",
        "title": "Book a consultation",
        "subtitle": "Angel's Assistant — Maintenance help",
        "fields": [
            {"name": "FirstName",   "label": "First name", "type": "text",
             "required": True, "maxLength": 40, "placeholder": "Jane"},
            {"name": "LastName",    "label": "Last name",  "type": "text",
             "required": True, "maxLength": 40, "placeholder": "Doe"},
            {"name": "PhoneNumber", "label": "Phone",      "type": "phone",
             "required": True, "hint": "10 digits, numbers only"},
            {"name": "EmailAddress","label": "Email",      "type": "email",
             "required": True, "placeholder": "you@example.com"},
            {"name": "ProductName", "label": "Product",    "type": "chips",
             "required": True,
             "options": [{"text": p, "value": p} for p in VALID_PRODUCTS]},
            {"name": "Date",        "label": "Preferred date", "type": "date-grid",
             "required": True, "options": date_buttons},
            # Time list is loaded up-front for the earliest date; the frontend
            # keeps it simple by showing all standard slots and letting the
            # backend re-validate against real availability on submit.
            {"name": "Time",        "label": "Preferred time", "type": "time-grid",
             "required": True,
             "options": [{"text": t["text"], "value": t["text"]}
                         for t in [
                             {"text": f"{h:02d}:00 {'AM' if h < 12 else 'PM'}"} if False else
                             {"text": f"{(h if h<=12 else h-12):02d}:00 {'AM' if h<12 else 'PM'}"}
                             for h in range(9, 18)
                         ]]}
        ]
    }
def _validate_form(values):
    errors = {}
    def req(name, label):
        if not values.get(name) or not str(values[name]).strip():
            errors[name] = f"{label} is required."
    req("FirstName",    "First name")
    req("LastName",     "Last name")
    req("PhoneNumber",  "Phone")
    req("EmailAddress", "Email")
    req("ProductName",  "Product")
    req("Date",         "Date")
    req("Time",         "Time")
    phone = values.get("PhoneNumber", "")
    if phone and not validate_phone(phone):
        errors["PhoneNumber"] = "Enter exactly 10 digits."
    email = values.get("EmailAddress", "")
    if email and not validate_email(email):
        errors["EmailAddress"] = "Enter a valid email address."
    product = values.get("ProductName", "")
    if product and product.lower() not in [p.lower() for p in VALID_PRODUCTS]:
        errors["ProductName"] = "Unsupported product."
    date_str = values.get("Date", "")
    valid_dates, _ = get_business_days()
    if date_str and date_str not in valid_dates:
        errors["Date"] = "That date is unavailable."
    time_str = values.get("Time", "")
    if date_str and time_str:
        avail = get_available_times(date_str)
        if not any(t["text"].lower() == time_str.lower() for t in avail):
            errors["Time"] = "That time slot is no longer available."
    return errors
def _save_booking(values, session_id):
    """
    Persist the booking. Replace this stub with DynamoDB / RDS / SES calls.
    Returns a reference id.
    """
    ref = "AC-" + uuid.uuid4().hex[:8].upper()
    # e.g.  boto3.resource('dynamodb').Table(os.environ['TABLE']).put_item(Item={
    #     'referenceId': ref, 'sessionId': session_id, 'bot': 'angel', **values
    # })
    print(f"[angel] booking saved ref={ref} session={session_id} values={values}")
    return ref
def _form_response(messages=None, session_attrs=None):
    return {
        "messages": messages or [],
        "sessionAttributes": session_attrs or {}
    }
def handle_form_event(event):
    action = (event.get("formAction") or "").upper()
    values = event.get("values", {}) or {}
    session_id = event.get("sessionId", "")
    if action == "INIT":
        schema = _form_schema()
        return _form_response(
            messages=[{"contentType": "PlainText",
                       "content": "Please fill in the form below to book your consultation."}],
            session_attrs={"formSchema": json.dumps(schema)}
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
                {"label": "Name",     "value": f"{values.get('FirstName','').title()} {values.get('LastName','').title()}"},
                {"label": "Phone",    "value": values.get("PhoneNumber","")},
                {"label": "Email",    "value": values.get("EmailAddress","")},
                {"label": "Product",  "value": values.get("ProductName","")},
                {"label": "Date",     "value": values.get("Date","")},
                {"label": "Time",     "value": values.get("Time","")}
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
        success = {
            "title":       "Booking confirmed!",
            "message":     "Our executive will call you at the scheduled time.",
            "referenceId": ref
        }
        return _form_response(session_attrs={"formSuccess": json.dumps(success)})
    return _form_response(messages=[{"contentType": "PlainText",
                                     "content": f"Unknown form action: {action}"}])
# =====================================================================
# LEX FULFILLMENT (original — unchanged)
# =====================================================================
def build_button_response(intent, slot_to_elicit, message_text, button_options, session_attributes=None):
    attrs = dict(session_attributes) if session_attributes is not None else {}
    if button_options:
        lex_buttons = []
        for opt in button_options[:15]:
            if isinstance(opt, dict): lex_buttons.append({"text": opt["text"], "value": opt["value"]})
            else: lex_buttons.append({"text": str(opt), "value": str(opt)})
        attrs['uiButtons'] = json.dumps(lex_buttons)
    else:
        attrs['uiButtons'] = json.dumps([])
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": slot_to_elicit},
            "intent": intent,
            "sessionAttributes": attrs
        },
        "messages": [{"contentType": "PlainText", "content": message_text}]
    }
def lambda_handler(event, context):
    # ---- Dynamic-form bypass ----
    if isinstance(event, dict) and event.get("formAction"):
        return handle_form_event(event)
    # ---- Original Lex flow (unchanged from your file) ----
    try:
        session_state = event.get('sessionState', {})
        intent = session_state.get('intent', {})
        slots = intent.get('slots', {})
        invocation_source = event.get('invocationSource')
        session_attributes = session_state.get('sessionAttributes', {})
        session_attributes['uiButtons'] = json.dumps([])
        if intent.get('name') == 'CancelBooking':
            return {
                "sessionState": {
                    "dialogAction": {"type": "Close"},
                    "intent": {"name": intent.get('name'), "state": "Fulfilled"},
                    "sessionAttributes": {
                        "uiButtons": json.dumps([
                            {"text": "Need More Assistance?",
                             "value": "https://www.icloudy.co/icloudy-contact-us/"}
                        ])
                    }
                },
                "messages": [{"contentType": "PlainText",
                              "content": "No problem, I've canceled the process. Let me know if you need anything else!"}]
            }
        if invocation_source == 'DialogCodeHook':
            # (Same interceptors as your uploaded file — trimmed here for brevity;
            # keep the full body from your existing AngelLambda_updated.py.)
            session_attributes['uiButtons'] = json.dumps([])
            return {
                "sessionState": {
                    "dialogAction": {"type": "Delegate"},
                    "intent": intent,
                    "sessionAttributes": session_attributes
                }
            }
        if invocation_source == 'FulfillmentCodeHook':
            return {
                "sessionState": {
                    "dialogAction": {"type": "Close"},
                    "intent": {"name": intent.get('name'), "state": "Fulfilled"},
                    "sessionAttributes": {
                        "uiButtons": json.dumps([
                            {"text": "Need More Assistance?",
                             "value": "https://www.icloudy.co/icloudy-contact-us/"}
                        ])
                    }
                },
                "messages": [{"contentType": "PlainText",
                              "content": "Your request has been noted! Our executive will call you."}]
            }
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return {
            "sessionState": {
                "dialogAction": {"type": "Delegate"},
                "intent": event.get('sessionState', {}).get('intent', {})
            }
        }