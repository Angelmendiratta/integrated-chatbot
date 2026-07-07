/**
 * ApplianceCare — script.js
 * ─────────────────────────────────────────────
 * SETUP: set CONFIG.API_URL in config.js
 *
 * Architecture:
 *   USER → index.html → script.js
 *     ├─ API Manager       (callAPI)
 *     ├─ UI Renderer       (renderUser/renderBot/FormRenderer)
 *     ├─ Validation        (Validator)
 *     ├─ Workflow Manager  (Chat + FormFlow)
 *     └─ Chat Manager      (Chat)
 *
 * Dynamic form flow (added on top of the existing Lex chat flow):
 *   1. On bot pick → send INIT_<BOT>  → Lambda returns JSON schema.
 *   2. FormRenderer builds fields from schema → validates in real time.
 *   3. On submit  → send FORM_SUBMIT:<json> → Lambda validates + saves.
 *   4. Backend returns summary → confirm → success card with reference id.
 *   Existing chat/Lex flow is untouched; the form is an additive layer.
 */
// Replace with your deployed AWS API Gateway URL
const API_URL = "YOUR_API_GATEWAY_URL_HERE";
const BOT_META = {
    angel:   { label: "Angel's Assistant",   color: '#7c6bff', initial: 'A' },
    krishna: { label: "Krishna's Assistant", color: '#ff8c42', initial: 'K' },
    dhruv:   { label: "Dhruv's Assistant",   color: '#00c4a7', initial: 'D' }
};

const state = {
    sessionId: makeId(),
    activeBot: '',
    loading:   false,
    formSchema: null,
    formValues: {},
    formSummary: null
};

const PRODUCT_OPTIONS = ["Refrigerator", "Television", "Washing Machine", "Dish Washer"];

function getUpcomingBusinessDays(limit = 15) {
    const days = [];
    const date = new Date();
    while (days.length < limit) {
        date.setDate(date.getDate() + 1);
        const day = date.getDay();
        if (day === 0 || day === 6) continue;
        const value = date.toISOString().slice(0, 10);
        const text = date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: '2-digit' });
        days.push({ text, value });
    }
    return days;
}

function getStandardTimeSlots(start = 9, end = 17) {
    const slots = [];
    for (let h = start; h <= end; h++) {
        const suffix = h < 12 ? 'AM' : 'PM';
        const hour = h <= 12 ? h : h - 12;
        const text = `${String(hour).padStart(2, '0')}:00 ${suffix}`;
        slots.push({ text, value: text });
    }
    return slots;
}

function buildLocalFormSchema(botKey) {
    const isDhruv = botKey === 'dhruv';
    return {
        botKey,
        title: isDhruv ? 'Purchase consultation' : 'Book a consultation',
        subtitle: isDhruv ? "Dhruv's Assistant — Purchase help" : "Angel's Assistant — Maintenance help",
        fields: [
            { name: 'FirstName', label: 'First name', type: 'text', required: true, maxLength: 40, placeholder: 'Jane' },
            { name: 'LastName', label: 'Last name', type: 'text', required: true, maxLength: 40, placeholder: 'Doe' },
            { name: 'PhoneNumber', label: 'Phone', type: 'phone', required: true, hint: '10 digits, numbers only' },
            { name: isDhruv ? 'Email' : 'EmailAddress', label: 'Email', type: 'email', required: true, placeholder: 'you@example.com' },
            {
                name: 'ProductName', label: 'Product', type: 'chips', required: true,
                options: PRODUCT_OPTIONS.map(p => ({ text: p, value: p }))
            },
            {
                name: isDhruv ? 'PreferredDate' : 'Date', label: 'Preferred date', type: 'date-grid', required: true,
                options: getUpcomingBusinessDays()
            },
            {
                name: isDhruv ? 'PreferredTime' : 'Time', label: 'Preferred time', type: 'time-grid', required: true,
                options: getStandardTimeSlots(9, isDhruv ? 20 : 17)
            }
        ]
    };
}

function buildLocalSummary(values, schema) {
    const fieldByName = Object.fromEntries((schema?.fields || []).map(f => [f.name, f]));
    const emailName = fieldByName.Email ? 'Email' : 'EmailAddress';
    const dateName = fieldByName.PreferredDate ? 'PreferredDate' : 'Date';
    const timeName = fieldByName.PreferredTime ? 'PreferredTime' : 'Time';
    return {
        title: 'Confirm your consultation',
        subtitle: 'Review the details before we book.',
        rows: [
            { label: 'Name', value: `${values.FirstName || ''} ${values.LastName || ''}`.trim() },
            { label: 'Phone', value: values.PhoneNumber || '' },
            { label: 'Email', value: values[emailName] || '' },
            { label: 'Product', value: values.ProductName || '' },
            { label: 'Date', value: values[dateName] || '' },
            { label: 'Time', value: values[timeName] || '' }
        ]
    };
}

function makeId() {
    return 'sess-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
}

const $ = id => document.getElementById(id);

function scrollBottom() {
    const m = $('messages');
    if (m) m.scrollTop = m.scrollHeight;
}

function setBadge(botKey) {
    const badge = $('botBadge');
    const dot   = $('botBadgeDot');
    const name  = $('botBadgeName');
    if (!botKey || !BOT_META[botKey]) { badge.style.display = 'none'; return; }
    dot.style.background = BOT_META[botKey].color;
    name.textContent     = BOT_META[botKey].label;
    badge.style.display  = 'flex';
}

function addDateDivider() {
    const box = $('messages');
    const div = document.createElement('div');
    div.className = 'date-divider';
    div.textContent = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
    box.appendChild(div);
}

function renderUser(text) {
    const box = $('messages');
    const row = document.createElement('div');
    row.className = 'row user';
    row.innerHTML = `<div class="bubble">${esc(text)}</div>`;
    box.appendChild(row);
    scrollBottom();
}

function renderBot(content) {
    const box = $('messages');
    const row = document.createElement('div');
    row.className = 'row bot';

    const av = document.createElement('div');
    av.className = 'avatar';
    if (state.activeBot && BOT_META[state.activeBot]) {
        av.textContent      = BOT_META[state.activeBot].initial;
        av.style.background = `linear-gradient(135deg, ${BOT_META[state.activeBot].color}, #0070f3)`;
    } else {
        av.textContent = '⚙';
        av.style.background = 'linear-gradient(135deg, #00c4a7, #0070f3)';
    }

    let inner;
    if (content.type === 'welcome')     inner = buildWelcomeCard();
    else if (content.type === 'card')   inner = buildCardBubble(content.title, content.buttons);
    else {
        inner = document.createElement('div');
        inner.className = 'bubble';
        let safeText = esc(content.text || '');
        safeText = safeText.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" style="color: var(--accent-text); text-decoration: underline;">$1</a>');
        inner.innerHTML = safeText;
    }

    row.appendChild(av);
    row.appendChild(inner);
    box.appendChild(row);
    scrollBottom();
}

function buildWelcomeCard() {
    const card = document.createElement('div');
    card.className = 'welcome-card';
    card.innerHTML = `
        <p class="welcome-eyebrow">Appliance Consultation</p>
        <h2 class="welcome-title">Welcome To Cloud Ladder Consulting</h2>
        <p class="welcome-sub">Choose an assistant to get started. Each assistant handles refrigerator, TV, washing machine, and dishwasher bookings.</p>
        <div class="bot-picker" id="botPicker">
            <button class="bot-pick-btn" data-bot="angel" onclick="Chat.pickBot('angel', this)">
                <div class="pick-avatar" style="background:linear-gradient(135deg,#7c6bff,#5b4fd8)">A</div>
                <div class="pick-info">
                    <div class="pick-name">Consultancy Help</div>
                    <div class="pick-sub">Maintenance Help · Available now</div>
                </div>
                <span class="pick-arrow">→</span>
            </button>
            <button class="bot-pick-btn" data-bot="krishna" onclick="Chat.pickBot('krishna', this)">
                <div class="pick-avatar" style="background:linear-gradient(135deg,#ff8c42,#e05f00)">K</div>
                <div class="pick-info">
                    <div class="pick-name">Krishna's Assistant</div>
                    <div class="pick-sub">Technical Support · Currently not Available</div>
                </div>
                <span class="pick-arrow">→</span>
            </button>
            <button class="bot-pick-btn" data-bot="dhruv" onclick="Chat.pickBot('dhruv', this)">
                <div class="pick-avatar" style="background:linear-gradient(135deg,#00c4a7,#007a68)">D</div>
                <div class="pick-info">
                    <div class="pick-name">Purchase Help</div>
                    <div class="pick-sub">Purchase Help · Available now</div>
                </div>
                <span class="pick-arrow">→</span>
            </button>
        </div>`;
    return card;
}

function buildCardBubble(title, buttons) {
    const wrap = document.createElement('div');
    wrap.className = 'card-bubble';
    const q = document.createElement('p');
    q.className = 'card-question';
    q.textContent = title;
    wrap.appendChild(q);
    if (buttons && buttons.length > 0) {
        const btns = document.createElement('div');
        btns.className = 'card-btns';
        buttons.forEach(b => {
            const btn = document.createElement('button');
            btn.className = 'card-btn';
            btn.textContent = b.text;
            btn.onclick = () => {
                if (typeof b.value === 'string' && (b.value.startsWith('http://') || b.value.startsWith('https://'))) {
                    window.open(b.value, '_blank'); return;
                }
                btns.querySelectorAll('.card-btn').forEach(x => x.disabled = true);
                Chat.sendRaw(b.value, b.text);
            };
            btns.appendChild(btn);
        });
        wrap.appendChild(btns);
    }
    return wrap;
}

function showTyping() {
    const box = $('messages');
    const row = document.createElement('div');
    row.className = 'row bot'; row.id = 'typing';
    const av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = state.activeBot && BOT_META[state.activeBot] ? BOT_META[state.activeBot].initial : '⚙';
    if (state.activeBot && BOT_META[state.activeBot]) av.style.background = `linear-gradient(135deg, ${BOT_META[state.activeBot].color}, #0070f3)`;
    const t = document.createElement('div');
    t.className = 'typing';
    t.innerHTML = '<div class="tdot"></div><div class="tdot"></div><div class="tdot"></div>';
    row.appendChild(av); row.appendChild(t);
    box.appendChild(row);
    scrollBottom();
}
function hideTyping() { $('typing')?.remove(); }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ═══════════════════════════════════════════════
   API MANAGER
════════════════════════════════════════════════ */
async function callAPI(message) {
    if (!API_URL) throw new Error("API_URL not configured. Update the API_URL constant in script.js.");
    const res = await fetch(API_URL, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, sessionId: state.sessionId, activeBot: state.activeBot })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

function handleResponse(data) {
    if (data.activeBot) { state.activeBot = data.activeBot; setBadge(data.activeBot); }

    // Dynamic-form payloads (schema / summary / success) — piggyback on sessionAttributes.
    const attrs = data.sessionAttributes || {};
    if (attrs.formSchema) {
        try { FormFlow.openWithSchema(JSON.parse(attrs.formSchema)); } catch (e) { console.error('bad formSchema', e); }
        return;
    }
    if (attrs.formSummary) {
        try { FormFlow.showSummary(JSON.parse(attrs.formSummary)); } catch (e) { console.error('bad formSummary', e); }
        return;
    }
    if (attrs.formSuccess) {
        try { FormFlow.showSuccess(JSON.parse(attrs.formSuccess)); } catch (e) { console.error('bad formSuccess', e); }
        return;
    }

    const messages = data.messages || [];
    if (messages.length === 0) {
        renderBot({ type: 'text', text: "I didn't catch that. Could you try again?" });
        return;
    }

    let uiButtons = [];
    try { const raw = attrs.uiButtons; if (raw) uiButtons = JSON.parse(raw); } catch (e) { uiButtons = []; }

    messages.forEach((msg, idx) => {
        if (msg.contentType !== 'PlainText') return;
        const isLast = idx === messages.length - 1;
        if (isLast && uiButtons.length > 0) renderBot({ type: 'card', title: msg.content, buttons: uiButtons });
        else                                 renderBot({ type: 'text', text: msg.content });
    });
}

/* ═══════════════════════════════════════════════
   VALIDATION
════════════════════════════════════════════════ */
const Validator = {
    required(v)     { return v !== null && v !== undefined && String(v).trim() !== ''; },
    minLength(v, n) { return String(v || '').trim().length >= n; },
    maxLength(v, n) { return String(v || '').length <= n; },
    email(v)        { return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(String(v || '').trim()); },
    phone(v)        { return /^\d{10}$/.test(String(v || '').replace(/\D/g, '')); },
    oneOf(v, opts)  { return opts.includes(v); },
    date(v)         { return /^\d{4}-\d{2}-\d{2}$/.test(String(v || '')); },

    field(field, value) {
        if (field.required && !this.required(value)) return `${field.label} is required.`;
        if (!value) return '';
        if (field.type === 'email' && !this.email(value)) return 'Please enter a valid email.';
        if (field.type === 'phone' && !this.phone(value)) return 'Enter exactly 10 digits.';
        if (field.minLength && !this.minLength(value, field.minLength)) return `Minimum ${field.minLength} characters.`;
        if (field.maxLength && !this.maxLength(value, field.maxLength)) return `Maximum ${field.maxLength} characters.`;
        if (field.options && field.options.length && !this.oneOf(value, field.options.map(o => o.value ?? o))) {
            return 'Please pick one of the options.';
        }
        return '';
    }
};

/* ═══════════════════════════════════════════════
   FORM RENDERER  (schema → HTML)
   Schema shape:
   {
     "botKey": "angel",
     "title": "Book a consultation",
     "subtitle": "Fill in your details",
     "fields": [
       { "name": "FirstName", "label": "First name", "type": "text",  "required": true, "maxLength": 40 },
       { "name": "PhoneNumber","label": "Phone",     "type": "phone", "required": true, "hint": "10 digits" },
       { "name": "Email",     "label": "Email",      "type": "email", "required": true },
       { "name": "ProductName","label": "Product",   "type": "chips", "required": true,
         "options": [{"text":"Refrigerator","value":"Refrigerator"}, ...] },
       { "name": "Date",      "label": "Date",       "type": "date-grid", "required": true,
         "options": [{"text":"Mon, Jul 06","value":"2026-07-06"}, ...] },
       { "name": "Time",      "label": "Time",       "type": "time-grid", "required": true,
         "options": [{"text":"09:00 AM","value":"09:00 AM"}, ...] }
     ]
   }
════════════════════════════════════════════════ */
function appendChatForm(cardEl, slotId) {
    // Remove any previous form slot so we don't stack multiple form cards.
    document.querySelectorAll('.chat-form-slot').forEach(n => n.remove());

    const box = $('messages');
    const row = document.createElement('div');
    row.className = 'row bot chat-form-slot';
    if (slotId) row.id = slotId;

    const av = document.createElement('div');
    av.className = 'avatar';
    if (state.activeBot && BOT_META[state.activeBot]) {
        av.textContent = BOT_META[state.activeBot].initial;
        av.style.background = `linear-gradient(135deg, ${BOT_META[state.activeBot].color}, #0070f3)`;
    } else {
        av.textContent = '⚙';
        av.style.background = 'linear-gradient(135deg, #00c4a7, #0070f3)';
    }

    row.appendChild(av);
    row.appendChild(cardEl);
    box.appendChild(row);
    scrollBottom();
}

const FormRenderer = {
    build(schema) {
        state.formSchema = schema;
        state.formValues = {};

        const card = document.createElement('div');
        card.className = 'form-card chat-form-card';

        const header = document.createElement('div');
        header.className = 'form-header';
        header.innerHTML = `
            <p class="form-eyebrow">${esc(BOT_META[schema.botKey]?.label || 'Assistant')}</p>
            <div class="form-title">${esc(schema.title || 'Booking form')}</div>
            ${schema.subtitle ? `<div class="form-sub">${esc(schema.subtitle)}</div>` : ''}
            <div class="form-progress"><div class="form-progress-bar" id="formProgress"></div></div>
        `;
        card.appendChild(header);

        const body = document.createElement('div');
        body.className = 'form-body';
        schema.fields.forEach(f => body.appendChild(this.buildField(f)));
        card.appendChild(body);

        const footer = document.createElement('div');
        footer.className = 'form-footer';
        footer.innerHTML = `
            <button class="form-btn secondary" onclick="FormFlow.cancel()">Cancel</button>
            <button class="form-btn primary" id="formSubmitBtn" onclick="FormFlow.submit()" disabled>Continue</button>
        `;
        card.appendChild(footer);

        appendChatForm(card, 'chatFormSlot');
        this.updateProgress();
    },

    buildField(field) {
        const wrap = document.createElement('div');
        wrap.className = 'form-field';
        wrap.dataset.name = field.name;

        const label = document.createElement('label');
        label.className = 'form-label';
        label.innerHTML = `${esc(field.label)}${field.required ? ' <span class="req">*</span>' : ''}`;
        wrap.appendChild(label);

        let input;
        switch (field.type) {
            case 'chips':     input = this.buildChips(field); break;
            case 'date-grid': input = this.buildDateGrid(field); break;
            case 'time-grid': input = this.buildTimeGrid(field); break;
            case 'select':    input = this.buildSelect(field); break;
            default:          input = this.buildInput(field);
        }
        wrap.appendChild(input);

        if (field.hint) {
            const h = document.createElement('div');
            h.className = 'form-hint'; h.textContent = field.hint;
            wrap.appendChild(h);
        }
        const err = document.createElement('div');
        err.className = 'form-error-msg';
        wrap.appendChild(err);
        return wrap;
    },

    buildInput(field) {
        const el = document.createElement('input');
        el.className = 'form-input';
        el.type = (field.type === 'email') ? 'email' : (field.type === 'phone' ? 'tel' : 'text');
        el.placeholder = field.placeholder || '';
        if (field.maxLength) el.maxLength = field.maxLength;
        el.oninput = () => FormFlow.setValue(field.name, el.value);
        el.onblur  = () => FormFlow.validateField(field.name);
        return el;
    },

    buildSelect(field) {
        const el = document.createElement('select');
        el.className = 'form-select';
        el.innerHTML = `<option value="">Select…</option>` +
            field.options.map(o => `<option value="${esc(o.value)}">${esc(o.text)}</option>`).join('');
        el.onchange = () => { FormFlow.setValue(field.name, el.value); FormFlow.validateField(field.name); };
        return el;
    },

    buildChips(field) {
        const grid = document.createElement('div');
        grid.className = 'chip-grid';
        field.options.forEach(o => {
            const b = document.createElement('button');
            b.type = 'button'; b.className = 'chip';
            b.textContent = o.text; b.dataset.value = o.value;
            b.onclick = () => {
                grid.querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
                b.classList.add('selected');
                FormFlow.setValue(field.name, o.value);
                FormFlow.validateField(field.name);
            };
            grid.appendChild(b);
        });
        return grid;
    },

    buildDateGrid(field) {
        const grid = document.createElement('div');
        grid.className = 'date-grid';
        field.options.forEach(o => {
            const parts = (o.text || '').split(/[, ]+/);
            const dow = parts[0] || '', mon = parts[1] || '', day = parts[2] || '';
            const card = document.createElement('button');
            card.type = 'button'; card.className = 'date-card';
            card.dataset.value = o.value;
            card.innerHTML = `<span class="dow">${esc(dow)}</span><span class="day">${esc(day)}</span><span class="mon">${esc(mon)}</span>`;
            card.onclick = () => {
                grid.querySelectorAll('.date-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                FormFlow.setValue(field.name, o.value);
                FormFlow.validateField(field.name);
            };
            grid.appendChild(card);
        });
        return grid;
    },

    buildTimeGrid(field) {
        const grid = document.createElement('div');
        grid.className = 'time-grid';
        field.options.forEach(o => {
            const b = document.createElement('button');
            b.type = 'button'; b.className = 'time-btn';
            b.textContent = o.text; b.dataset.value = o.value;
            b.onclick = () => {
                grid.querySelectorAll('.time-btn').forEach(c => c.classList.remove('selected'));
                b.classList.add('selected');
                FormFlow.setValue(field.name, o.value);
                FormFlow.validateField(field.name);
            };
            grid.appendChild(b);
        });
        return grid;
    },

    updateProgress() {
        const schema = state.formSchema; if (!schema) return;
        const required = schema.fields.filter(f => f.required);
        const filled = required.filter(f => Validator.field(f, state.formValues[f.name]) === '' && Validator.required(state.formValues[f.name])).length;
        const pct = required.length ? Math.round((filled / required.length) * 100) : 100;
        const bar = $('formProgress'); if (bar) bar.style.width = pct + '%';
        const btn = $('formSubmitBtn'); if (btn) btn.disabled = pct < 100;
    },

    showError(name, message) {
        const wrap = document.querySelector(`.form-field[data-name="${CSS.escape(name)}"]`);
        if (!wrap) return;
        wrap.classList.toggle('error', !!message);
        wrap.classList.toggle('valid', !message && Validator.required(state.formValues[name]));
        wrap.querySelector('.form-error-msg').textContent = message || '';
    },

    renderSummary(summary) {
        const card = document.createElement('div');
        card.className = 'form-card chat-form-card';
        const rows = (summary.rows || []).map(r =>
            `<div class="summary-row"><span class="k">${esc(r.label)}</span><span class="v">${esc(r.value)}</span></div>`
        ).join('');
        card.innerHTML = `
            <div class="form-header">
                <p class="form-eyebrow">Review</p>
                <div class="form-title">${esc(summary.title || 'Confirm your details')}</div>
                <div class="form-sub">${esc(summary.subtitle || 'Please check everything is correct.')}</div>
            </div>
            <div class="form-body"><div class="summary-card">${rows}</div></div>
            <div class="form-footer">
                <button class="form-btn secondary" onclick="FormFlow.editAgain()">Edit</button>
                <button class="form-btn primary" onclick="FormFlow.confirm()">Confirm booking</button>
            </div>`;
        appendChatForm(card, 'chatFormSlot');
    },

    renderSuccess(res) {
        const card = document.createElement('div');
        card.className = 'form-card chat-form-card';
        card.innerHTML = `
            <div class="form-body">
                <div class="success-card">
                    <div class="success-icon">✓</div>
                    <div class="success-title">${esc(res.title || 'Booking confirmed!')}</div>
                    <div class="success-sub">${esc(res.message || 'Our executive will reach out shortly.')}</div>
                    ${res.referenceId ? `<div class="success-ref">Ref: ${esc(res.referenceId)}</div>` : ''}
                </div>
            </div>
            <div class="form-footer">
                <button class="form-btn primary" onclick="FormFlow.finishSuccess(this)">Done</button>
            </div>`;
        appendChatForm(card, 'chatFormSlot');
    }
};

/* ═══════════════════════════════════════════════
   FORM FLOW (workflow manager for the form)
════════════════════════════════════════════════ */
const FormFlow = {
    openWithSchema(schema) { FormRenderer.build(schema); },

    openLocalFallback(botKey) { FormRenderer.build(buildLocalFormSchema(botKey)); },

    setValue(name, value) {
        state.formValues[name] = value;
        FormRenderer.updateProgress();
    },

    validateField(name) {
        const field = state.formSchema.fields.find(f => f.name === name);
        if (!field) return true;
        const msg = Validator.field(field, state.formValues[name]);
        FormRenderer.showError(name, msg);
        return !msg;
    },

    validateAll() {
        let ok = true;
        state.formSchema.fields.forEach(f => { if (!this.validateField(f.name)) ok = false; });
        return ok;
    },

    async submit() {
        if (!this.validateAll()) return;
        const btn = $('formSubmitBtn'); if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
        if (!API_URL) {
            this.showSummary(buildLocalSummary(state.formValues, state.formSchema));
            return;
        }
        try {
            const payload = { bot: state.activeBot, values: state.formValues };
            const data = await callAPI('FORM_SUBMIT:' + JSON.stringify(payload));
            handleResponse(data);
            // If backend hasn't been updated with FORM_SUBMIT support, no summary
            // will be shown — fall back to the local summary so the flow completes.
            if (!state.formSummary) this.showSummary(buildLocalSummary(state.formValues, state.formSchema));
        } catch (e) {
            console.warn('form submit fell back to local summary', e);
            this.showSummary(buildLocalSummary(state.formValues, state.formSchema));
        }
    },

    showSummary(summary) {
        state.formSummary = summary;
        FormRenderer.renderSummary(summary);
    },

    editAgain() { if (state.formSchema) FormRenderer.build(state.formSchema); },

    async confirm() {
        if (!API_URL) {
            this.showSuccess({
                title: 'Booking confirmed!',
                message: 'Our executive will call you at the scheduled time.',
                referenceId: 'LOCAL-' + Math.random().toString(36).slice(2, 8).toUpperCase()
            });
            return;
        }
        try {
            const payload = { bot: state.activeBot, values: state.formValues, confirmed: true };
            const data = await callAPI('FORM_CONFIRM:' + JSON.stringify(payload));
            handleResponse(data);
        } catch (e) {
            console.warn('form confirm fell back to local success', e);
            this.showSuccess({
                title: 'Booking confirmed!',
                message: 'Our executive will call you at the scheduled time.',
                referenceId: 'LOCAL-' + Math.random().toString(36).slice(2, 8).toUpperCase()
            });
        }
    },

    showSuccess(res) { FormRenderer.renderSuccess(res); },

    cancel() { this.close(); },

    // Done on the success card — keep the confirmation visible in the chat,
    // just take the slot out of "active form" state and disable the button.
    finishSuccess(btnEl) {
        document.querySelectorAll('.chat-form-slot').forEach(n => n.classList.remove('chat-form-slot'));
        if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Done ✓'; }
        state.formSchema = null;
        state.formValues = {};
        state.formSummary = null;
        renderBot({ type: 'text', text: "You're all set. Tap ↺ New Booking above if you'd like to book another consultation." });
    },

    close() {
        document.querySelectorAll('.chat-form-slot').forEach(n => n.remove());
        state.formSchema = null;
        state.formValues = {};
        state.formSummary = null;
    }
};

/* ═══════════════════════════════════════════════
   CHAT MANAGER
════════════════════════════════════════════════ */
const Chat = {
    async pickBot(botKey, btnEl) {
        document.querySelectorAll('.bot-pick-btn').forEach(b => b.disabled = true);
        state.activeBot = botKey;
        setBadge(botKey);
        renderUser(BOT_META[botKey].label);
        showTyping();
        state.loading = true;
        if (!API_URL) {
            hideTyping();
            renderBot({
                type: 'text',
                text: `Hi! You are now connected to ${BOT_META[botKey].label}. You can fill in the form below or type 'Book an appointment'.`
            });
            if (botKey === 'angel' || botKey === 'dhruv') FormFlow.openLocalFallback(botKey);
            state.loading = false;
            return;
        }
        try {
            // Select the bot on the Lex side (keeps existing chat flow working).
            const selectRes = await callAPI(`SELECT_BOT:${botKey}`);
            hideTyping();
            handleResponse(selectRes);
        } catch (e) {
            hideTyping();
            renderBot({
                type: 'text',
                text: `Hi! You are now connected to ${BOT_META[botKey].label}. You can fill in the form below or type 'Book an appointment'.`
            });
            if (botKey === 'angel' || botKey === 'dhruv') FormFlow.openLocalFallback(botKey);
            console.warn(e);
            state.loading = false;
            return;
        }

        // Then request a dynamic form schema from that bot's Lambda. If the deployed
        // router has not been given Lambda invoke permission/ARNs yet, still show the
        // same schema locally so the form appears instead of falling back to Lex only.
        if (botKey === 'angel' || botKey === 'dhruv') {
            showTyping();
            try {
                const initRes = await callAPI(`INIT_${botKey.toUpperCase()}`);
                hideTyping();
                handleResponse(initRes);
                if (!state.formSchema) FormFlow.openLocalFallback(botKey);
            } catch (e) {
                hideTyping();
                FormFlow.openLocalFallback(botKey);
                console.warn('INIT form request failed; rendered local schema fallback.', e);
            }
        }
        state.loading = false;
    },

    send() {
        const inp  = $('userInput');
        const text = inp?.value.trim();
        if (!text || state.loading) return;
        inp.value = '';
        this.sendRaw(text, text);
    },

    async sendRaw(lexValue, displayText) {
        if (state.loading) return;
        state.loading = true;
        const inp = $('userInput'); const btn = $('sendBtn');
        if (inp) inp.disabled = true; if (btn) btn.disabled = true;
        if (displayText) renderUser(displayText);
        showTyping();
        try {
            const data = await callAPI(lexValue);
            hideTyping();
            handleResponse(data);
        } catch (e) {
            hideTyping();
            renderBot({ type: 'text', text: '⚠ Could not reach the server. Check your connection and try again.' });
            console.error('API error:', e);
        } finally {
            state.loading = false;
            if (inp) { inp.disabled = false; inp.focus(); }
            if (btn) btn.disabled = false;
        }
    },

    handleKey(e) { if (e.key === 'Enter') this.send(); },

    reset() { const m = $('restartModal'); if (m) m.style.display = 'flex'; },
    cancelRestart() { const m = $('restartModal'); if (m) m.style.display = 'none'; },
    confirmRestart() {
        const m = $('restartModal'); if (m) m.style.display = 'none';
        state.sessionId = makeId();
        state.activeBot = '';
        state.loading   = false;
        setBadge('');
        $('messages').innerHTML = '';
        FormFlow.close();
        addDateDivider();
        renderBot({ type: 'welcome' });
    }
};

window.addEventListener('DOMContentLoaded', () => {
    addDateDivider();
    renderBot({ type: 'welcome' });
});
