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


def _normalize_time(raw):
    if not raw: return ""
    raw = str(raw).strip()
    match_24 = re.match(r'^(\d{1,2}):(\d{2})(?::\d{2})?$', raw)
    if match_24: return f"{int(match_24.group(1)):02d}:{match_24.group(2)}"
    match_12 = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', raw, re.IGNORECASE)
    if match_12:
        h = int(match_12.group(1)); m = match_12.group(2); period = match_12.group(3).upper()
        if period == "AM": h = 0 if h == 12 else h
        else: h = 12 if h == 12 else h + 12
        return f"{h:02d}:{m}"
    return raw


# ── DYNAMIC FORM HANDLERS ────────────────────────────────────────────

def _form_schema():
    # Use the same date logic you already have
    valid_dates, button_days = get_business_days()
    date_options = [day["value"] for day in button_days]

    return {
        "title": "Schedule Your Consultation",
        "submitLabel": "Confirm Booking",
        "groups": [
            {
                "title": "👤 Personal Details",
                "fields": [
                    { "name": "firstName", "type": "text", "label": "First Name", "required": True, "width": "half" },
                    { "name": "lastName", "type": "text", "label": "Last Name", "required": True, "width": "half" },
                    { "name": "gender", "type": "radio", "label": "Gender", "options": ["Male", "Female"], "required": True },
                    { "name": "phone", "type": "tel", "label": "Phone Number", "placeholder": "10 digits", "required": True, "pattern": "^[0-9]{10}$", "title": "Enter exactly 10 digits", "width": "half" },
                    { "name": "email", "type": "email", "label": "Email Address", "placeholder": "name@domain.com", "required": True, "width": "half" }
                ]
            },
            {
                "title": "🔧 Your Appliance",
                "fields": [
                    { "name": "demoVideo", "type": "video-button", "label": "Watch Form Tutorial (YouTube)", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ" },
                    { "name": "appliance", "type": "select", "label": "Select Product", "options": VALID_PRODUCTS, "required": True },
                    { "name": "billImage", "type": "file", "label": "Upload Bill/Proof Image", "accept": "image/*" },
                    { "name": "problem", "type": "textarea", "label": "Briefly describe the issue (optional)", "placeholder": "e.g., The fridge stopped cooling..." }
                ]
            },
            {
                "title": "📅 Schedule Your Call",
                "fields": [
                    { "name": "prefDate", "type": "select", "label": "Preferred Date", "options": date_options, "required": True, "width": "half" },
                    { "name": "prefTime", "type": "select", "label": "Preferred Time", "options": ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"], "required": True, "width": "half" }
                ]
            },
            {
                "title": "🔔 Confirmation Preference",
                "fields": [
                    { "name": "notifyPref", "type": "radio", "label": "How would you like your confirmation?", "options": ["📱 WhatsApp", "📧 Email", "Both"], "required": True },
                    { "name": "tnc", "type": "checkbox", "label": "I agree to the Terms & Conditions", "required": True }
                ]
            }
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
        requested_time = _normalize_time(values["PreferredTime"])
        if not any(_normalize_time(a["value"]) == requested_time for a in avail):
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
                messages=[{"contentType": "PlainText", "content": "Please fix the highlighted fields."}],
                session_attrs={"formErrors": json.dumps(errors)}
            )
            
        summary = {
            "title": "Confirm your consultation",
            "subtitle": "Review the details before we book.",
            "rows": [
                {"label": "Name",     "value": f"{values.get('firstName','').title()} {values.get('lastName','').title()}"},
                {"label": "Gender",   "value": values.get("gender","")},
                {"label": "Phone",    "value": values.get("phone","")},
                {"label": "Email",    "value": values.get("email","")},
                {"label": "Product",  "value": values.get("appliance","")},
                {"label": "Date",     "value": values.get("prefDate","")},
                {"label": "Time",     "value": values.get("prefTime","")},
                {"label": "Notif",    "value": values.get("notifyPref","")}
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


# ── LEX FULFILLMENT — free-text chat path (buttons + validation) ─────

DHRUV_SLOT_ORDER = ["FirstName", "LastName", "PhoneNumber",
                    "Email", "ProductName", "PreferredDate", "PreferredTime"]

def _slot_val(slots, name):
    s = slots.get(name) if slots else None
    if not s: return None
    v = s.get("value", {}) or {}
    return v.get("interpretedValue") or v.get("originalValue")

def _buttons_for(slot_name, slots):
    if slot_name == "ProductName":
        return [{"text": p, "value": p} for p in VALID_PRODUCTS]
    if slot_name == "PreferredDate":
        return get_available_dates()
    if slot_name == "PreferredTime":
        date_str = _slot_val(slots, "PreferredDate")
        if not date_str: return []
        return [{"text": a["text"], "value": a["value"]} for a in get_available_slots(date_str)]
    return []

def _prompt_for(slot_name):
    return {
        "FirstName":     "What's your first name?",
        "LastName":      "And your last name?",
        "PhoneNumber":   "Please share a 10-digit phone number.",
        "Email":         "What's your email address?",
        "ProductName":   "Which product are you interested in?",
        "PreferredDate": "Which date works for you?",
        "PreferredTime": "Great — pick a time slot."
    }.get(slot_name, f"Please provide {slot_name}.")

def _validate_slot(name, value, slots):
    if value is None or str(value).strip() == "":
        return None
    if name == "PhoneNumber" and not _valid_phone(value):
        return "That doesn't look like a valid 10-digit phone number."
    if name == "Email" and not _valid_email(value):
        return "That doesn't look like a valid email address."
    if name == "ProductName" and value.lower() not in [p.lower() for p in VALID_PRODUCTS]:
        return f"'{value}' isn't a product we service. Please pick one below."
    if name == "PreferredDate":
        try:
            d = datetime.strptime(value, "%Y-%m-%d").date()
            if d <= datetime.today().date():
                return "Please pick a future date from the options below."
        except Exception:
            return "That date isn't valid. Please pick one below."
    if name == "PreferredTime":
        date_str = _slot_val(slots, "PreferredDate")
        if date_str:
            avail = get_available_slots(date_str)
            requested_time = _normalize_time(value)
            if not any(_normalize_time(a["value"]) == requested_time for a in avail):
                return "That time slot isn't available. Please pick one below."
    return None

def _elicit(intent, slots, slot_name, message, session_attrs):
    buttons = _buttons_for(slot_name, slots)
    attrs = dict(session_attrs or {})
    attrs["uiButtons"] = json.dumps(buttons)
    intent["slots"] = slots
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitSlot", "slotToElicit": slot_name},
            "intent": intent,
            "sessionAttributes": attrs
        },
        "messages": [{"contentType": "PlainText", "content": message}]
    }

def _confirm_prompt(intent, slots, session_attrs):
    attrs = dict(session_attrs or {})
    attrs["uiButtons"] = json.dumps([
        {"text": "Yes, book it",   "value": "yes"},
        {"text": "No, cancel",     "value": "no"},
        {"text": "Change Product", "value": "change product"},
        {"text": "Change Date",    "value": "change date"},
        {"text": "Change Time",    "value": "change time"},
        {"text": "Change Phone",   "value": "change phone"},
        {"text": "Change Email",   "value": "change email"}
    ])
    intent["confirmationState"] = "None"
    intent["slots"] = slots
    summary = (f"Please confirm: {_slot_val(slots,'FirstName')} {_slot_val(slots,'LastName')}, "
               f"{_slot_val(slots,'ProductName')} on {_slot_val(slots,'PreferredDate')} at {_slot_val(slots,'PreferredTime')} "
               f"(phone {_slot_val(slots,'PhoneNumber')}, email {_slot_val(slots,'Email')}).")
    return {
        "sessionState": {
            "dialogAction": {"type": "ConfirmIntent"},
            "intent": intent,
            "sessionAttributes": attrs
        },
        "messages": [{"contentType": "PlainText", "content": summary}]
    }

_EDIT_KEYWORDS = {
    "change product": "ProductName", "edit product": "ProductName",
    "change date":    "PreferredDate", "edit date":  "PreferredDate",
    "change time":    "PreferredTime", "edit time":  "PreferredTime",
    "change phone":   "PhoneNumber", "edit phone":   "PhoneNumber",
    "change email":   "Email",       "edit email":   "Email",
    "change name":    "FirstName",   "edit name":    "FirstName"
}

_CONFIRM_YES = {"yes", "yes, book it", "book it", "confirm", "confirmed", "ok", "okay"}
_CONFIRM_NO = {"no", "no, cancel", "cancel", "cancel booking", "stop"}

def _all_slots_filled(slots):
    return all(_slot_val(slots, name) is not None for name in DHRUV_SLOT_ORDER)

def _close_confirmed(intent, slots, session_attrs, session_id):
    values = {n: _slot_val(slots, n) for n in DHRUV_SLOT_ORDER}
    errors = _validate_form(values)
    if errors:
        first_bad = next(iter(errors))
        slots[first_bad] = None
        return _elicit(intent, slots, first_bad, errors[first_bad], session_attrs)

    ref = _save_booking(values, session_id)
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
                      "content": f"Your booking is confirmed! Reference {ref}. Our executive will call you."}]
    }

def _close_cancelled(intent):
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


def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("formAction"):
        return handle_form_event(event)

    try:
        session_state = event.get('sessionState', {})
        intent = session_state.get('intent', {})
        slots = intent.get('slots', {}) or {}
        invocation_source = event.get('invocationSource')
        session_attributes = session_state.get('sessionAttributes', {}) or {}
        input_transcript = (event.get('inputTranscript') or '').strip().lower()

        if invocation_source == 'DialogCodeHook':
            if _all_slots_filled(slots):
                if input_transcript in _CONFIRM_YES or intent.get('confirmationState') == 'Confirmed':
                    return _close_confirmed(intent, slots, session_attributes, event.get('sessionId', ''))
                if input_transcript in _CONFIRM_NO or intent.get('confirmationState') == 'Denied':
                    return _close_cancelled(intent)

            if input_transcript in _EDIT_KEYWORDS:
                target = _EDIT_KEYWORDS[input_transcript]
                slots[target] = None
                return _elicit(intent, slots, target, _prompt_for(target), session_attributes)

            for name in DHRUV_SLOT_ORDER:
                val = _slot_val(slots, name)
                err = _validate_slot(name, val, slots)
                if err:
                    slots[name] = None
                    return _elicit(intent, slots, name, err, session_attributes)

            for name in DHRUV_SLOT_ORDER:
                if _slot_val(slots, name) is None:
                    return _elicit(intent, slots, name, _prompt_for(name), session_attributes)

            return _confirm_prompt(intent, slots, session_attributes)

        if invocation_source == 'FulfillmentCodeHook':
            return _close_confirmed(intent, slots, session_attributes, event.get('sessionId', ''))

    except Exception as e:
        print(f"ERROR: {str(e)}")
        return {
            "sessionState": {
                "dialogAction": {"type": "Delegate"},
                "intent": event.get('sessionState', {}).get('intent', {})
            }
        }

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
