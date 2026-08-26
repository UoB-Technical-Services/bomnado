/**
 * The part editor's behaviour. Nothing here is interpolated by a template: everything the page
 * needs comes from data attributes on the main region (`data-page="part-editor"` and friends, see
 * pages/part_editor.html) and from the form. The shell calls `init(main)` on load and after every
 * htmx swap of the region; listeners are delegated on the region, so swapped content just works.
 */
(function (global) {
    // Loaded before the shell's own script: create the namespace if it is not there yet.
    const root = global.Bomnado = global.Bomnado || {};
    const pages = root.pages = root.pages || {};

    const csrf = () => (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';

    /** Re-fetch the main region in place (the library and the drawer stay). */
    function reloadMain() {
        PageChanges.supressNote();
        return htmx.ajax('GET', window.location.pathname, { target: '#app_main', select: '#app_main', swap: 'outerHTML show:none' });
    }

    async function remove(url, afterwards) {
        const response = await fetch(url, { method: 'DELETE', headers: { 'X-CSRFToken': csrf() } });
        await processErrors(response);
        await afterwards();
    }

    /** The More menu, the supplier and deal cards: one delegated handler for every data-action. */
    function actions(main, data) {
        main.addEventListener('click', (event) => {
            const button = event.target.closest('[data-action]');
            if (!button || !main.contains(button)) { return; }
            const action = button.dataset.action;
            if (action === 'duplicate-part') {
                bootbox.confirm(`Duplicate ${data.partReference}?`, (ok) => {
                    if (!ok) { return; }
                    const form = document.createElement('form');
                    form.method = 'post';
                    form.action = data.urlDuplicate;
                    [['csrfmiddlewaretoken', csrf()], ['source_id', data.partId]].forEach(([name, value]) => {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = name;
                        input.value = value;
                        form.appendChild(input);
                    });
                    document.body.appendChild(form);
                    PageChanges.supressNote();
                    form.submit();
                });
            } else if (action === 'delete-part') {
                bootbox.confirm(`Delete ${data.partReference}? This cannot be undone.`, (ok) => {
                    if (ok) { remove(`/api/parts/${data.partId}/`, () => { PageChanges.supressNote(); window.location = data.urlPartList; }); }
                });
            } else if (action === 'delete-source') {
                bootbox.confirm('Delete this supplier?', (ok) => {
                    if (ok) { remove(`/api/partsources/${button.dataset.id}/`, reloadMain); }
                });
            } else if (action === 'delete-deal') {
                bootbox.confirm('Remove this part from the deal?', (ok) => {
                    if (ok) { remove(`/api/deallineitems/${button.dataset.id}/`, reloadMain); }
                });
            }
        });
    }

    /** Named pieces: add rows from the empty-form template, remove unsaved rows, flag saved rows for deletion. */
    function pieces(main) {
        const rows = main.querySelector('#pieceRows');
        const template = main.querySelector('#pieceRowTemplate');
        const totalForms = main.querySelector('#id_named_pieces-TOTAL_FORMS');
        const add = main.querySelector('#addPieceRow');
        if (!rows || !template || !totalForms || !add) { return; }

        function flagDuplicateSuffixes() {
            const inputs = Array.from(rows.querySelectorAll('input[name$="-suffix"]'))
                .filter(input => !input.closest('tr').classList.contains('bomnado-piece-deleted'));
            const counts = {};
            inputs.forEach(input => { if (input.value) { counts[input.value] = (counts[input.value] || 0) + 1; } });
            inputs.forEach(input => {
                const duplicate = input.value && counts[input.value] > 1;
                const reference = `${input.closest('.input-group').querySelector('.input-group-text').textContent}${input.value}`;
                input.setCustomValidity(duplicate ? `${reference} is already used on this part.` : '');
                input.classList.toggle('is-invalid', duplicate);
                let message = input.closest('td').querySelector('.bomnado-piece-duplicate');
                if (duplicate) {
                    if (!message) {
                        message = document.createElement('small');
                        message.className = 'text-danger d-block bomnado-piece-duplicate';
                        input.closest('td').appendChild(message);
                    }
                    message.textContent = `${reference} is already used on this part.`;
                } else if (message) {
                    message.remove();
                }
            });
        }

        add.addEventListener('click', () => {
            const index = parseInt(totalForms.value, 10);
            // insertAdjacentHTML does not run the picture widget's inline script, so it is initialised by hand.
            rows.insertAdjacentHTML('beforeend', template.innerHTML.replace(/__prefix__/g, index));
            totalForms.value = index + 1;
            const row = rows.lastElementChild;
            new TinyPictureField(row.querySelector('.bomnado-tinypicture-widget'));
            row.querySelector('input[name$="-suffix"]').focus();
        });
        rows.addEventListener('input', (event) => {
            const input = event.target;
            if (!input.matches('input[name$="-suffix"]')) { return; }
            // What they see is what will be saved (the server validates again): `top half` -> `TOP-HALF`.
            const before = input.value;
            const after = before.toUpperCase().replace(/[\s_]+/g, '-').replace(/[^0-9A-Z.-]/g, '');
            if (after !== before) {
                const caret = input.selectionStart + (after.length - before.length);
                input.value = after;
                input.setSelectionRange(caret, caret);
            }
            flagDuplicateSuffixes();
        });
        rows.addEventListener('click', (event) => {
            const unsaved = event.target.closest('.bomnado-piece-remove');
            const saved = event.target.closest('.bomnado-piece-delete');
            if (unsaved) {
                unsaved.closest('tr').remove();
                flagDuplicateSuffixes();
            } else if (saved) {
                const row = saved.closest('tr');
                const checkbox = row.querySelector('input[name$="-DELETE"]');
                checkbox.checked = !checkbox.checked;
                row.classList.toggle('bomnado-piece-deleted', checkbox.checked);
                flagDuplicateSuffixes();
            }
        });
    }

    /** Pasting a Fusion 360 property string into Weight or Dimensions reads the value out of it. */
    function fusionPaste(main) {
        const pairs = [['#id_kgs', fusion360_readMass], ['#id_dimensions', fusion360_readAABB]];
        pairs.forEach(([selector, reader]) => {
            const input = main.querySelector(selector);
            if (!input) { return; }
            input.addEventListener('paste', function (event) {
                try {
                    this.value = reader(event.clipboardData.getData('text'));
                    event.preventDefault();
                } catch (e) { /* not a Fusion string: paste as normal */ }
            });
        });
    }

    pages['part-editor'] = {
        init(main) {
            const data = main.dataset;
            actions(main, data);
            pieces(main);
            fusionPaste(main);
            main.querySelectorAll('img[src="undefined"], img[src="null"]').forEach(img => { img.src = data.placeholderPart; });
            BomnadoEditor.install('bomando-part-form');
        },
    };
})(window);
