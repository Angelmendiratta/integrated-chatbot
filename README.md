# ApplianceCare Chatbot

A dual-assistant chatbot for an appliance company:

- **Angel** — Service & maintenance assistant (bookings, repairs)
- **Dhruv** — Sales & purchase assistant (product help, purchase consultations)

The user can either **chat freely** (routed to AWS Lex) or use a **dynamic in-chat form** to book a consultation without typing.

---

## Golden rule of this project

> **The Lambda decides. The browser only renders.**

Every form label, field, option list, date, time slot, product name, and validation rule lives in the AWS Lambda files (`AngelLambda.py` / `DhruvLambda.py`). The frontend (`public/script.js`) does not know any of that — it only:

1. asks the Lambda for a schema,
2. draws it,
3. sends the values back,
4. shows whatever the Lambda replies with (errors, summary, or success).

If you want to add a field, change a label, change validation, change the product list, or change the time slots → **edit the Lambda, not the JS.**

---

## Architecture

```text
┌─────────────┐      HTTPS       ┌──────────────┐      Lambda invoke     ┌───────────────┐
│   Browser   │ ───────────────▶ │  API Gateway │ ────────────────────▶  │ Router Lambda │
│ (public/*)  │                  │  POST /chat  │                        │ LexApiHandler │
└─────────────┘                  └──────────────┘                        └───────┬───────┘
                                                                                 │
                        ┌────────────────────────┬───────────────────────────────┤
                        │ INIT_*  / FORM_SUBMIT  │  free-text message            │
                        ▼                        ▼                               ▼
              ┌──────────────────┐    ┌──────────────────┐              ┌──────────────┐
              │  Angel Lambda    │    │  Dhruv Lambda    │              │   AWS Lex    │
              │  (form schema +  │    │  (form schema +  │              │   bot v2     │
              │   validation +   │    │   validation +   │              └──────┬───────┘
              │   save booking)  │    │   save booking)  │                     │
              └──────────────────┘    └──────────────────┘             (fulfillment)
                                                                              │
                                                                       ┌──────▼──────┐
                                                                       │ Angel/Dhruv │
                                                                       │   Lambda    │
                                                                       └─────────────┘
```

Two message paths, one endpoint:

1. **Form path** — messages prefixed `INIT_*`, `FORM_SUBMIT:*`, `FORM_CONFIRM:*` bypass Lex entirely. The router direct-invokes the right business Lambda and returns its response verbatim.
2. **Chat path** — anything else is sent to the correct Lex bot via `lexv2-runtime.recognize_text()`.

---

## Repo layout

```text
├── public/                    # Static frontend (loaded inside an iframe)
│   ├── index.html             # Skeleton: bot picker + form/chat mounts
│   ├── style.css              # All visual styling
│   ├── script.js              # UI + FormRenderer + FormFlow + Chat (NO business logic)
│   └── config.js              # API_URL for your API Gateway
│
├── src/                       # TanStack Start wrapper that serves public/
│   └── routes/
│       ├── __root.tsx
│       └── index.tsx          # <iframe src="/index.html">
│
├── aws-lambdas/               # Deployed to AWS Lambda (auto-deploy via GH Actions)
│   ├── LexApiHandler.py       # Router — proxies to Lex or a business Lambda
│   ├── AngelLambda.py         # Service assistant: schema + validation + save
│   └── DhruvLambda.py         # Sales assistant: schema + validation + save
│
└── .github/workflows/
    └── deploy-lambdas.yml     # Auto-deploys aws-lambdas/*.py to AWS on push
```

---

## The three files that matter, block by block

### 1. `public/script.js` — the browser (dumb renderer)

Sections in order:

- **`BOT_META`** — display metadata for each bot chip (name, colour, avatar letter). Purely cosmetic.
- **`state`** — plain object holding `sessionId`, `activeBot`, `formSchema`, `formValues`, `formSummary`. That's it — no product lists, no dates.
- **`renderUser` / `renderBot` / `buildWelcomeCard` / `buildCardBubble` / `showTyping` / `hideTyping`** — DOM helpers that draw chat bubbles.
- **`callAPI(message)`** — the one and only network call. `POST { message, sessionId, activeBot }` to `CONFIG.API_URL`.
- **`handleResponse(data)`** — reads `data.sessionAttributes` and dispatches:
  - `formSchema` → `FormFlow.openWithSchema(...)`
  - `formErrors` → `FormFlow.showErrors(...)` (per-field messages under each input)
  - `formSummary` → `FormFlow.showSummary(...)` (review card)
  - `formSuccess` → `FormFlow.showSuccess(...)` (confirmation card)
  - `uiButtons`   → quick-reply buttons attached to the last chat bubble
- **`FormRenderer`** — a switch statement over `field.type`. Supported types: `text`, `email`, `phone`, `select`, `chips`, `date-grid`, `time-grid`. Each `build*` method returns a DOM node. `updateProgress()` only checks that required fields are non-empty (to enable the Continue button) — **no format validation, no regex, nothing Lambda-owned.**
- **`FormFlow`** — orchestrator:
  - `openWithSchema` → hand schema to renderer.
  - `setValue` → store value, refresh progress, clear any old server error on that field.
  - `submit` → send `FORM_SUBMIT:<json>` to Lambda. Response drives the next screen.
  - `showErrors` → paint per-field errors from Lambda.
  - `showSummary` / `confirm` / `showSuccess` → render whatever the Lambda returned.
- **`Chat`** — top-level UI controller:
  - `pickBot(botKey)` → sends `SELECT_BOT:<bot>` then `INIT_<BOT>`.
  - `send` / `sendRaw` → forwards free-text to the router (Lex path).
  - `reset` / `confirmRestart` → clears the conversation.

There is deliberately **no `PRODUCT_OPTIONS`, no `getBusinessDays()`, no `Validator.email/phone/date`, no local fallback schema** in this file. If those ever reappear here, delete them and put them in the Lambda.

### 2. `aws-lambdas/LexApiHandler.py` — the router (pure proxy)

- **`get_registry()`** — reads `ANGEL_BOT_ID`, `DHRUV_BOT_ID`, `ANGEL_LAMBDA_ARN`, `DHRUV_LAMBDA_ARN`, `REGION` from env vars. Returns the config for each bot.
- **`CORS_HEADERS` / `_ok` / `_err_response`** — response helpers. All responses include CORS so the browser can call the API.
- **`_invoke_business_lambda(arn, region, payload)`** — one boto3 call that direct-invokes Angel or Dhruv with a JSON payload like `{ formAction: "INIT", bot, sessionId, values }`. The router **never builds a form schema itself** — that used to duplicate logic; it doesn't anymore.
- **`lambda_handler(event, context)`** — dispatch on the first token of `message`:
  1. Empty session + no prefix → return nothing (waiting for bot pick).
  2. `SELECT_BOT:<bot>` → confirm active bot in the session.
  3. `INIT_ANGEL` / `INIT_DHRUV` → invoke that bot's Lambda with `formAction: "INIT"` and return the schema it produced.
  4. `FORM_SUBMIT:<json>` / `FORM_CONFIRM:<json>` → invoke that bot's Lambda with the values and return its verdict.
  5. Anything else → forward to AWS Lex via `lexv2-runtime.recognize_text()`.
  Final step for Lex responses: if the message contains a "we'll call you back" phrase, attach a "Need More Assistance?" quick-reply button. Everything is wrapped in try/except that returns 500 on failure.

### 3. `aws-lambdas/AngelLambda.py` and `DhruvLambda.py` — the business assistants

Same shape in both files:

- **Domain data** — `VALID_PRODUCTS`, `BOOKED_APPOINTMENTS` (mock DB), business-day and time-slot generators. Change these to change what the form shows.
- **`validate_phone`, `validate_email`** (Angel) / `_valid_email`, `_valid_phone` (Dhruv) — format checks.
- **`get_business_days()` / `get_available_dates()`** — the next N business days as `{text, value}` buttons.
- **`get_available_times(date)` / `get_available_slots(date)`** — slots for a specific date, minus already-booked ones and past times for today.
- **`_form_schema()`** — the JSON the frontend renders. Fields, labels, requiredness, options, hints all come from here.
- **`_validate_form(values)`** — the only real validation in the system. Returns a `{ fieldName: errorMessage }` dict; empty dict means "all good".
- **`_save_booking(values, session_id)`** — stub that logs and returns a reference id. **Replace this** with a DynamoDB `put_item` or an SES `send_email` call.
- **`handle_form_event(event)`** — the router calls this when `event.formAction` is set:
  - `INIT`    → return `sessionAttributes.formSchema`
  - `SUBMIT`  → validate; return `formErrors` on failure or `formSummary` on success
  - `CONFIRM` → re-validate; save; return `formSuccess` with a reference id
- **`lambda_handler(event, context)`** — first checks `event.formAction` and delegates to the form handler if present. Otherwise falls through to the original Lex fulfillment logic (unchanged).

---

## Local development

Requirements: [Bun](https://bun.sh) (or Node 20+).

```bash
bun install
bun run dev
```

Open http://localhost:8080. The chatbot lives inside an iframe at `/index.html`.

Configure the API URL in `public/config.js`:

```js
const CONFIG = {
    API_URL: "https://xxxxx.execute-api.ap-southeast-1.amazonaws.com/prod/chat"
};
```

---

## AWS setup (one-time)

You need three Lambda functions and one API Gateway route.

### 1. Create the Lambdas

| Lambda | Handler | Runtime | Source file |
|---|---|---|---|
| `applcare-router` | `LexApiHandler.lambda_handler` | Python 3.11+ | `aws-lambdas/LexApiHandler.py` |
| `applcare-angel`  | `AngelLambda.lambda_handler`   | Python 3.11+ | `aws-lambdas/AngelLambda.py` |
| `applcare-dhruv`  | `DhruvLambda.lambda_handler`   | Python 3.11+ | `aws-lambdas/DhruvLambda.py` |

### 2. Environment variables (router only)

| Name | Value |
|---|---|
| `REGION` | e.g. `ap-southeast-1` |
| `ANGEL_BOT_ID` | Lex bot id for Angel |
| `DHRUV_BOT_ID` | Lex bot id for Dhruv |
| `ANGEL_LAMBDA_ARN` | Full ARN of `applcare-angel` |
| `DHRUV_LAMBDA_ARN` | Full ARN of `applcare-dhruv` |

### 3. IAM — router role

- `lexv2:RecognizeText` on both Lex bots
- `lambda:InvokeFunction` on the Angel + Dhruv ARNs

### 4. API Gateway

- HTTP API → `POST /chat` → integrates with `applcare-router`
- Enable CORS (`*` origin, `POST, OPTIONS`, `Content-Type` header)
- Copy the invoke URL into `public/config.js` (append `/chat`)

---

## Continuous deployment (Lambdas → AWS via GitHub)

`.github/workflows/deploy-lambdas.yml` runs on every push to `main` that touches `aws-lambdas/**`. It zips each `.py` file and calls `aws lambda update-function-code` in parallel for all three functions.

Add these GitHub repo secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user with `lambda:UpdateFunctionCode` |
| `AWS_SECRET_ACCESS_KEY` | that user's secret |
| `AWS_REGION` | e.g. `ap-southeast-1` |
| `ROUTER_LAMBDA_NAME` | e.g. `applcare-router` |
| `ANGEL_LAMBDA_NAME`  | e.g. `applcare-angel` |
| `DHRUV_LAMBDA_NAME`  | e.g. `applcare-dhruv` |

Minimal IAM policy for the deploy user:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "lambda:UpdateFunctionCode",
    "Resource": [
      "arn:aws:lambda:REGION:ACCOUNT_ID:function:applcare-router",
      "arn:aws:lambda:REGION:ACCOUNT_ID:function:applcare-angel",
      "arn:aws:lambda:REGION:ACCOUNT_ID:function:applcare-dhruv"
    ]
  }]
}
```

---

## Daily workflow

**Frontend change (HTML/CSS/JS/React)** — edit, commit, push. Your static host rebuilds.

**Lambda change (Python)** — edit under `aws-lambdas/`, commit, push. GitHub Actions ships it to AWS in ~30 seconds. Watch it under the **Actions** tab.

---

## The form protocol (wire format)

```text
Frontend → Router → Business Lambda
{message: "INIT_ANGEL"}
                    → {formAction: "INIT",    bot, sessionId}
                    ← {messages, sessionAttributes.formSchema}

{message: "FORM_SUBMIT:{...values...}"}
                    → {formAction: "SUBMIT",  bot, sessionId, values}
                    ← {sessionAttributes.formSummary}
                      OR {sessionAttributes.formErrors: {FieldName: "message"}}

{message: "FORM_CONFIRM:{...values...}"}
                    → {formAction: "CONFIRM", bot, sessionId, values}
                    ← {sessionAttributes.formSuccess: {title, message, referenceId}}
```

To persist bookings for real, replace `_save_booking()` in each business Lambda with a DynamoDB write and/or an SES email.

---

## Troubleshooting

- **Form doesn't appear** — check `public/config.js` has the right `API_URL`, and that `ANGEL_LAMBDA_ARN` / `DHRUV_LAMBDA_ARN` are set on the router.
- **Form validation "doesn't work"** — validation lives in the Lambda's `_validate_form()`; the frontend only echoes the errors it receives. Check the Lambda's CloudWatch logs.
- **GitHub Action fails with `AccessDenied`** — the IAM user needs `lambda:UpdateFunctionCode` on the exact function ARN.
- **Lex path returns nothing** — verify the bot id + alias `TSTALIASID` exist and the router role has `lexv2:RecognizeText`.
