/**
 * The floating AI chat window (partial/ai_chat.html).
 *
 * The conversation lives on the server; this script only owns the window: where it is, how big,
 * whether it is open or minimised, which conversation it shows and an unsent draft - all kept in
 * localStorage so the window comes back exactly as it was after every page load. The body is
 * htmx fragments from /ai/chat/; while a turn runs the messages poll themselves.
 *
 * Jumping-off points anywhere on a page: `data-ai-prompt="..."` (opens the window with that text
 * typed, `data-ai-send="1"` sends it straight away) and `data-ai-thread="<id>"` (opens a
 * conversation). The page says what it is about with `<body data-ai-context="part:12">`.
 *
 * The window is docked in the page's right-hand drawer (`#app_drawer`); the floating window only
 * remains for a page without one.
 */
(function (global) {
    const KEY = 'bomnado.ai.chat';
    const root = document.getElementById('aiChat');
    if (!root) { return; }
    const pill = document.getElementById('aiChatPill');
    const body = document.getElementById('aiChatBody');
    const title = document.getElementById('aiChatTitle');
    const pillTitle = document.getElementById('aiChatPillTitle');
    /** What the page is about right now: the main region carries it, and the main region gets swapped. */
    const currentContext = () => {
        const main = document.getElementById('app_main');
        return (main && main.dataset.aiContext) || document.body.dataset.aiContext || '';
    };
    const currentReference = () => {
        const main = document.getElementById('app_main');
        return (main && main.dataset.aiReference) || '';
    };
    const header = root.querySelector('.bomnado-ai-chat-title');
    const drawer = document.getElementById('app_drawer');
    const floatButton = document.getElementById('aiChatFloat');

    /** The AI signature: a couple of seconds of tornado where a sparkle was, when the AI is set going. */
    function signature(element) {
        if (global.BomnadoTornado) { global.BomnadoTornado.burst(element); }
    }

    /** The context the person dismissed with the chip's x: kept in memory only, so it comes back
     *  with the next record, and with a fresh page load. */
    let dismissedContext = '';

    /** The composer's page chip and hidden context input, from one place: what the page is about,
     *  unless the person dismissed it. */
    function renderPageChip(form) {
        const input = form.querySelector('input[name="context"]');
        const context = currentContext();
        const reference = currentReference();
        const suppressed = context !== '' && dismissedContext === context;
        if (input) { input.value = suppressed ? '' : context; }
        let chip = form.querySelector('.bomnado-ai-chat-page');
        if (!reference || suppressed) {
            if (chip) { chip.remove(); }
            return;
        }
        if (!chip) {
            chip = document.createElement('div');
            chip.className = 'bomnado-ai-chat-page';
            chip.title = 'What "this" means: the record on this page';
            form.querySelector('.bomnado-ai-chat-input').insertAdjacentElement('beforebegin', chip);
        }
        chip.textContent = '\u21B3 ' + reference;
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'bomnado-ai-chat-page-clear';
        clear.setAttribute('data-ai-clear-context', '');
        clear.title = 'Send without this page as context';
        clear.setAttribute('aria-label', clear.title);
        clear.innerHTML = '&times;';
        chip.appendChild(clear);
    }

    const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } };
    const state = Object.assign({ open: false, min: false, x: null, y: null, w: 420, h: 560, thread: null, draft: '', mode: 'docked' }, load());
    const docked = () => drawer !== null;
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* private mode */ } };

    // --- placement --------------------------------------------------------------------------
    function clamp() {
        const w = Math.min(Math.max(state.w, 320), window.innerWidth - 16);
        const h = Math.min(Math.max(state.h, 260), window.innerHeight - 16);
        let x = state.x === null ? window.innerWidth - w - 24 : state.x;
        let y = state.y === null ? window.innerHeight - h - 24 : state.y;
        x = Math.min(Math.max(x, 0), window.innerWidth - w);
        y = Math.min(Math.max(y, 0), window.innerHeight - h);
        Object.assign(root.style, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' });
        state.x = x; state.y = y; state.w = w; state.h = h;
    }

    function show() {
        if (docked()) {
            // Docked: the drawer opens and closes; minimise means close (the top-bar button brings it back).
            if (root.parentElement !== drawer) { drawer.appendChild(root); }
            root.classList.remove('is-floating');
            root.removeAttribute('style');
            const open = state.open && !state.min;
            drawer.classList.toggle('is-open', open);
            root.hidden = !open;
            pill.hidden = true;
        } else {
            if (root.parentElement !== document.body) { document.body.appendChild(root); }
            root.classList.add('is-floating');
            root.hidden = !state.open || state.min;
            pill.hidden = !state.open || !state.min;
            if (!root.hidden) { clamp(); }
        }
        if (floatButton) { floatButton.title = docked() ? 'Pop out into a floating window' : 'Dock into the page'; }
        save();
    }
    if (floatButton) {
        floatButton.addEventListener('click', () => { state.mode = docked() ? 'floating' : 'docked'; state.min = false; show(); });
    }

    const handle = root.querySelector('[data-drag-handle]');
    handle.addEventListener('mousedown', (event) => {
        if (event.target.closest('button') || docked()) { return; }
        event.preventDefault();
        const startX = event.clientX - state.x, startY = event.clientY - state.y;
        const move = (e) => { state.x = e.clientX - startX; state.y = e.clientY - startY; clamp(); };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); save(); };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
    });
    if (window.ResizeObserver) {
        new ResizeObserver(() => {
            if (root.hidden || docked()) { return; }
            const rect = root.getBoundingClientRect();
            if (Math.abs(rect.width - state.w) > 1 || Math.abs(rect.height - state.h) > 1) {
                state.w = rect.width; state.h = rect.height; save();
            }
        }).observe(root);
    }
    window.addEventListener('resize', () => { if (!root.hidden && !docked()) { clamp(); } });

    // --- opening conversations ------------------------------------------------------------------
    function open(thread) {
        state.open = true; state.min = false;
        if (thread !== undefined) { state.thread = thread; }
        show();
        const url = root.dataset.openUrl + '?thread=' + (state.thread === null ? '' : state.thread)
            + '&context=' + encodeURIComponent(currentContext());
        htmx.ajax('GET', url, { target: '#aiChatBody', swap: 'innerHTML' });
    }

    function mounted() {
        const thread = document.getElementById('aiChatThread');
        if (!thread) { return; }
        state.thread = thread.dataset.threadId ? parseInt(thread.dataset.threadId, 10) : null;
        title.textContent = 'AI';
        title.title = thread.dataset.title || '';
        pillTitle.textContent = thread.dataset.title || 'AI';
        const form = document.getElementById('aiChatComposer');
        renderPageChip(form);
        const text = document.getElementById('aiChatText');
        if (state.draft && !text.value) { text.value = state.draft; }
        text.addEventListener('input', () => { state.draft = text.value; save(); });
        text.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
        });
        text.addEventListener('paste', (event) => {
            const files = Array.from(event.clipboardData.files || []);
            if (files.length) { event.preventDefault(); addFiles(files); }
        });
        document.getElementById('aiChatAttach').addEventListener('click', () => document.getElementById('aiChatFiles').click());
        document.getElementById('aiChatFiles').addEventListener('change', listFiles);
        form.addEventListener('htmx:configRequest', () => { state.draft = ''; save(); });
        save();
        messagesSwapped();
        if (state.open && !state.min) { text.focus(); }
    }

    function messagesSwapped() {
        const messages = document.getElementById('aiChatMessages');
        if (!messages) { return; }
        const running = messages.dataset.running === '1';
        const sendButton = document.getElementById('aiChatSend');
        const text = document.getElementById('aiChatText');
        if (sendButton && text && !text.disabled) { sendButton.disabled = running; }
        // A change to the record this page shows: offer a reload.
        const touched = (messages.dataset.touched || '').trim().split(/\s+/);
        const reload = messages.querySelector('.bomnado-ai-chat-reload');
        const context = currentContext();
        if (reload && context && touched.includes(context.replace('assembly:', 'subassembly:'))) { reload.hidden = false; }
        messages.scrollTop = messages.scrollHeight;
    }

    function send() {
        const form = document.getElementById('aiChatComposer');
        const text = document.getElementById('aiChatText');
        const files = document.getElementById('aiChatFiles');
        if (!form || (!text.value.trim() && !files.files.length)) { return; }
        if (document.getElementById('aiChatSend').disabled) { return; }
        signature(header);
        htmx.trigger(form, 'submit');
    }

    // --- files: chosen, dropped or pasted --------------------------------------------------------
    function addFiles(files) {
        const input = document.getElementById('aiChatFiles');
        const transfer = new DataTransfer();
        Array.from(input.files).forEach(f => transfer.items.add(f));
        files.forEach((f, index) => {
            const named = f.name && f.name !== 'image.png' ? f : new File([f], 'pasted-' + (input.files.length + index + 1) + '.png', { type: f.type });
            transfer.items.add(named);
        });
        input.files = transfer.files;
        listFiles();
    }

    function removeFile(index) {
        const input = document.getElementById('aiChatFiles');
        const transfer = new DataTransfer();
        Array.from(input.files).forEach((f, i) => { if (i !== index) { transfer.items.add(f); } });
        input.files = transfer.files;
        listFiles();
    }

    function listFiles() {
        const input = document.getElementById('aiChatFiles');
        const list = document.getElementById('aiChatFileList');
        list.innerHTML = '';
        Array.from(input.files).forEach((f, index) => {
            const item = document.createElement('li');
            const name = document.createElement('span');
            name.textContent = f.name;
            name.title = f.name;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.innerHTML = '&times;';
            remove.title = 'Remove';
            remove.setAttribute('aria-label', 'Remove ' + f.name);
            remove.addEventListener('click', () => removeFile(index));
            item.appendChild(name);
            item.appendChild(remove);
            list.appendChild(item);
        });
        list.hidden = !input.files.length;
    }

    root.addEventListener('dragover', (event) => { event.preventDefault(); root.classList.add('is-over'); });
    root.addEventListener('dragleave', () => root.classList.remove('is-over'));
    root.addEventListener('drop', (event) => {
        event.preventDefault();
        root.classList.remove('is-over');
        if (event.dataTransfer.files.length) { addFiles(Array.from(event.dataTransfer.files)); }
    });

    // --- controls ----------------------------------------------------------------------------------
    document.getElementById('aiChatNew').addEventListener('click', () => open('new'));
    const minButton = document.getElementById('aiChatMin');
    if (minButton) { minButton.addEventListener('click', () => { state.min = true; show(); }); }
    document.getElementById('aiChatClose').addEventListener('click', () => { state.open = false; show(); });
    pill.addEventListener('click', () => { state.min = false; show(); open(); });

    document.addEventListener('click', (event) => {
        const toggle = event.target.closest('#aiChatToggle');
        if (toggle) {
            event.preventDefault();
            if (state.open && !state.min) { state.open = false; show(); } else { signature(toggle); open(); signature(header); }
            return;
        }
        const prompt = event.target.closest('[data-ai-prompt]');
        if (prompt) {
            event.preventDefault();
            signature(prompt);
            open(state.thread);
            signature(header);
            const onMounted = () => {
                const text = document.getElementById('aiChatText');
                if (!text) { return; }
                text.value = prompt.dataset.aiPrompt;
                state.draft = text.value; save();
                text.focus();
                text.setSelectionRange(text.value.length, text.value.length);
                if (prompt.dataset.aiSend === '1') { send(); }
            };
            body.addEventListener('htmx:afterSettle', onMounted, { once: true });
            return;
        }
        const clearContext = event.target.closest('[data-ai-clear-context]');
        if (clearContext) {
            event.preventDefault();
            dismissedContext = currentContext();
            const form = document.getElementById('aiChatComposer');
            if (form) { renderPageChip(form); }
            return;
        }
        const link = event.target.closest('[data-ai-thread]');
        if (link) { event.preventDefault(); open(parseInt(link.dataset.aiThread, 10)); }
    });

    // The page changed under the window (htmx swapped the main region): "this" now means the new record.
    document.addEventListener('bomnado:main-swapped', () => {
        const form = document.getElementById('aiChatComposer');
        if (form) { renderPageChip(form); }
    });

    document.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            if (state.open && !state.min) { state.open = false; show(); } else { open(); }
        }
    });

    body.addEventListener('htmx:afterSwap', (event) => {
        if (event.detail.target.id === 'aiChatBody' || event.detail.target.id === 'aiChatThread') { mounted(); }
        else if (event.detail.target.id === 'aiChatMessages') { messagesSwapped(); }
    });
    // Messages swap themselves (polling) with outerHTML: the event fires on the new element's parent.
    body.addEventListener('htmx:afterSettle', (event) => {
        if (event.detail.target.id === 'aiChatMessages') { messagesSwapped(); }
    });

    show();
    if (state.open && !state.min) { open(); }
})(window);
