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
 */
(function (global) {
    const KEY = 'bomnado.ai.chat';
    const root = document.getElementById('aiChat');
    if (!root) { return; }
    const pill = document.getElementById('aiChatPill');
    const body = document.getElementById('aiChatBody');
    const threads = document.getElementById('aiChatThreads');
    const title = document.getElementById('aiChatTitle');
    const pillTitle = document.getElementById('aiChatPillTitle');
    const context = document.body.dataset.aiContext || '';
    const header = root.querySelector('.bomnado-ai-chat-title');

    /** The AI signature: a couple of seconds of tornado where a sparkle was, when the AI is set going. */
    function signature(element) {
        if (global.BomnadoTornado) { global.BomnadoTornado.burst(element); }
    }

    const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } };
    const state = Object.assign({ open: false, min: false, x: null, y: null, w: 420, h: 560, thread: null, draft: '' }, load());
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
        root.hidden = !state.open || state.min;
        pill.hidden = !state.open || !state.min;
        if (!root.hidden) { clamp(); }
        save();
    }

    const handle = root.querySelector('[data-drag-handle]');
    handle.addEventListener('mousedown', (event) => {
        if (event.target.closest('button')) { return; }
        event.preventDefault();
        const startX = event.clientX - state.x, startY = event.clientY - state.y;
        const move = (e) => { state.x = e.clientX - startX; state.y = e.clientY - startY; clamp(); };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); save(); };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
    });
    if (window.ResizeObserver) {
        new ResizeObserver(() => {
            if (root.hidden) { return; }
            const rect = root.getBoundingClientRect();
            if (Math.abs(rect.width - state.w) > 1 || Math.abs(rect.height - state.h) > 1) {
                state.w = rect.width; state.h = rect.height; save();
            }
        }).observe(root);
    }
    window.addEventListener('resize', () => { if (!root.hidden) { clamp(); } });

    // --- opening conversations ------------------------------------------------------------------
    function open(thread) {
        state.open = true; state.min = false;
        if (thread !== undefined) { state.thread = thread; }
        show();
        threads.hidden = true;
        const url = root.dataset.openUrl + '?thread=' + (state.thread === null ? '' : state.thread)
            + '&context=' + encodeURIComponent(context);
        htmx.ajax('GET', url, { target: '#aiChatBody', swap: 'innerHTML' });
    }

    function mounted() {
        const thread = document.getElementById('aiChatThread');
        if (!thread) { return; }
        state.thread = thread.dataset.threadId ? parseInt(thread.dataset.threadId, 10) : null;
        title.textContent = thread.dataset.title || 'AI';
        pillTitle.textContent = thread.dataset.title || 'AI';
        const form = document.getElementById('aiChatComposer');
        form.querySelector('input[name="context"]').value = context;
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

    function listFiles() {
        const input = document.getElementById('aiChatFiles');
        const list = document.getElementById('aiChatFileList');
        list.innerHTML = '';
        Array.from(input.files).forEach((f) => {
            const item = document.createElement('li');
            item.textContent = f.name;
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
    document.getElementById('aiChatMin').addEventListener('click', () => { state.min = true; show(); });
    document.getElementById('aiChatClose').addEventListener('click', () => { state.open = false; show(); });
    pill.addEventListener('click', () => { state.min = false; show(); open(); });
    document.getElementById('aiChatList').addEventListener('click', () => {
        threads.hidden = !threads.hidden;
        if (!threads.hidden) { htmx.ajax('GET', root.dataset.threadsUrl, { target: '#aiChatThreads', swap: 'innerHTML' }); }
    });

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
        const link = event.target.closest('[data-ai-thread]');
        if (link) { event.preventDefault(); open(parseInt(link.dataset.aiThread, 10)); }
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
