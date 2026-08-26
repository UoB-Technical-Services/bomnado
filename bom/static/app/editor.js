/**
 * The editors' shared behaviour (part and assembly pages): the sticky header's "Unsaved changes"
 * and Discard follow the form, Ctrl+S saves, the jump links follow the scroll, and card headers
 * in a section toggle their cards. Installed by each editor's inline script, which runs on every
 * htmx swap of the main region as well as on a full load.
 *
 *   BomnadoEditor.install('bomando-part-form')
 */
(function (global) {
    function install(formId) {
        const form = document.getElementById(formId);
        const unsaved = document.getElementById('editorUnsaved');
        const discard = document.getElementById('editorDiscard');
        if (!form || !unsaved || !discard) { return; }

        const dirty = () => { unsaved.hidden = false; discard.disabled = false; };
        form.addEventListener('input', dirty);
        form.addEventListener('change', dirty);
        if (!PageChanges._editorHooked) {
            // Widgets (markdown editors, pictures) report through PageChanges.flag: the header listens there too.
            const flag = PageChanges.flag;
            PageChanges.flag = (control) => { flag(control); const u = document.getElementById('editorUnsaved'); const d = document.getElementById('editorDiscard'); if (u) { u.hidden = false; } if (d) { d.disabled = false; } };
            PageChanges._editorHooked = true;
        }
        discard.addEventListener('click', () => {
            bootbox.confirm('Discard your changes?', (ok) => {
                if (!ok) { return; }
                PageChanges.supressNote();
                htmx.ajax('GET', window.location.pathname, { target: '#app_main', select: '#app_main', swap: 'outerHTML show:none' });
            });
        });
        form.addEventListener('submit', () => PageChanges.supressNote());
        form.addEventListener('htmx:configRequest', () => PageChanges.supressNote());
        PageChanges.allow(form);

        // An HS code field links out to the team's tariff site while it holds digits.
        form.querySelectorAll('[data-hs-lookup]').forEach((group) => {
            const input = group.querySelector('input');
            const link = group.querySelector('.bn-hs-link');
            if (!input || !link) { return; }
            const update = () => {
                const code = (input.value || '').replace(/[^0-9]/g, '');
                link.hidden = !code;
                link.href = group.dataset.hsLookup.replace('{code}', code);
            };
            input.addEventListener('input', update);
            update();
        });
        if (!PageChanges._ctrlS) {
            // One document-level handler; it finds the form that is on the page at the time.
            document.addEventListener('keydown', (event) => {
                if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') { return; }
                const current = document.querySelector('.bn-editor form[hx-post]');
                if (!current) { return; }
                event.preventDefault();
                PageChanges.supressNote();
                htmx.trigger(current, 'submit');
            });
            PageChanges._ctrlS = true;
        }

        // Jump links: active section follows the scroll; clicking scrolls the main region smoothly.
        const links = Array.from(document.querySelectorAll('.bn-jump a'));
        const sections = links.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
        const main = document.getElementById('app_main');
        const spy = () => {
            const top = main.scrollTop + 140;
            let current = sections[0];
            sections.forEach(section => { if (section.offsetTop <= top) { current = section; } });
            if (main.scrollTop + main.clientHeight >= main.scrollHeight - 2) { current = sections[sections.length - 1]; }
            links.forEach(a => a.classList.toggle('active', current && a.getAttribute('href') === '#' + current.id));
        };
        if (main._spy) { main.removeEventListener('scroll', main._spy); }
        main._spy = spy;
        main.addEventListener('scroll', spy, { passive: true });
        links.forEach(a => a.addEventListener('click', (event) => {
            event.preventDefault();
            const section = document.querySelector(a.getAttribute('href'));
            if (!section) { return; }
            main.scrollTo({ top: section.offsetTop - 120, behavior: 'smooth' });
            history.replaceState(null, '', a.getAttribute('href'));
        }));

        // Cards with a collapse toggle: the whole header toggles, not just the button.
        document.querySelectorAll('.bn-editor .card-header').forEach(header => {
            const toggle = header.querySelector('[data-toggle="collapse"]');
            if (!toggle) { return; }
            header.addEventListener('click', (event) => {
                if (event.target.closest('button, a, input, select')) { return; }
                $(toggle.dataset.target).collapse('toggle');
            });
        });
    }

    global.BomnadoEditor = { install: install };
})(window);
