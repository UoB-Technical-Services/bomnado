/**
 * The assembly editor's behaviour: the component search (select2 over the parts API, plus the
 * project's assemblies), inserting and removing line items (htmx swaps of the table), colouring the
 * references that the instructions mention, the "find unreferenced" check, and deletion. Driven by
 * data attributes on the main region (`data-page="assembly-editor"`, see pages/assembly_editor.html);
 * the shell calls `init(main)` on load and after every swap.
 */
(function (global) {
    // Loaded before the shell's own script: create the namespace if it is not there yet.
    const root = global.Bomnado = global.Bomnado || {};
    const pages = root.pages = root.pages || {};

    const csrf = () => (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';

    function init(main) {
        const data = main.dataset;
        let refreshColourise = () => {};

        /** The line-items table: the search box hides rows in place. Hidden rows keep their form
         *  fields in the document, so a filtered save still submits every line. */
        function configureTable() {
            const container = main.querySelector('#existingsubComponentsContainer');
            if (!container) { return; }
            const input = container.querySelector('.bn-table-search');
            const count = container.querySelector('[data-role="count"]');
            const rows = [...container.querySelectorAll('#subComponentsTable tbody tr')];
            const update = () => {
                const needle = ((input && input.value) || '').toUpperCase();
                let shown = 0;
                rows.forEach((row) => {
                    const hit = !needle || row.textContent.toUpperCase().includes(needle);
                    row.style.display = hit ? '' : 'none';
                    shown += hit ? 1 : 0;
                });
                if (count) {
                    const what = `component${rows.length === 1 ? '' : 's'}`;
                    count.textContent = needle ? `${shown} of ${rows.length} ${what}` : `${rows.length} ${what}`;
                }
            };
            if (input) { input.addEventListener('input', update); }
            update();
        }

        /** Swap the table for the fragment an htmx endpoint returns, then wire it up again. */
        async function swapLineItems(url, values) {
            await htmx.ajax('POST', url, { target: '#existingsubComponentsContainer', swap: 'outerHTML', values: values });
            configureTable();
            refreshColourise();
        }

        /** The component search: assemblies of this project are few (loaded once); parts are searched server-side. */
        async function createInsertables() {
            const select = main.querySelector('#componentSearch');
            if (!select) { return; }
            const assemblies = await (await fetch(`/api/subassemblies/${data.rootId}/available`)).json();
            const searchText = (p) => `${p.has_open_feedback ? 'needs review ' : ''}${p.reference} ${p.name}`.toUpperCase();
            const txPart = p => ({ type: 'part', id: `part-${p.id}`, text: p.reference, data: p });
            const txAssembly = p => ({ type: 'assembly', id: `assembly-${p.id}`, text: p.reference, data: p });

            function matchingAssemblies(term) {
                const needle = term.toUpperCase();
                let found = assemblies.filter(a => searchText(a).includes(needle));
                if (!found.length && needle.includes('.')) {
                    found = assemblies.filter(a => searchText(a).includes(needle.split('.', 1)[0]));
                }
                return found.map(txAssembly);
            }

            /** The same reference markup the server renders (templatetags/utils.reference_html). */
            function formatInsertable(item) {
                if (!item.id) { return item.text; }
                const d = item.data;
                const marks = root.marks || {};
                const dots = (d.has_open_feedback ? `<span class="bn-mark is-bad" title="${marks.bad || ''}"></span>` : '')
                    + (d.missing && d.missing.length ? `<span class="bn-mark is-warn" title="Missing ${d.missing.join(', ')}"></span>` : '')
                    + (d.sale_code ? '<span class="bn-tag">sale</span>' : '');
                const classes = `bn-ref is-${item.type} bomlink ${item.type}${d.deprecated ? ' is-deprecated' : ''}`;
                const placeholder = item.type === 'part' ? data.placeholderPart
                    : (d.is_toplevel ? data.placeholderRoot : data.placeholderAssembly);
                return $(`<span><div class="table-icon"><img src="${d.picture_url || placeholder}"/></div> `
                    + `<a class="${classes}"><span class="reference">${d.reference}</span>${dots}</a> <small>${d.name}</small></span>`);
            }

            const search = $(select).select2({
                allowClear: true,
                placeholder: 'Choose a part or assembly to insert...',
                ajax: {
                    url: '/api/parts/search/',
                    delay: 150,
                    data: params => ({ search: params.term || '' }),
                    // The slim jQuery build has no $.ajax: fetch instead.
                    transport: (params, success, failure) => {
                        const controller = new AbortController();
                        fetch(`${params.url}?${new URLSearchParams(params.data)}`, { signal: controller.signal, headers: { Accept: 'application/json' } })
                            .then(response => processErrors(response).then(r => r.json()))
                            .then(success)
                            .catch(err => { if (err.name !== 'AbortError') { failure(err); } });
                        return { abort: () => controller.abort() };
                    },
                    processResults: (parts, params) => ({ results: [...matchingAssemblies(params.term || ''), ...parts.map(txPart)] }),
                },
                templateResult: formatInsertable,
            });
            search.removeAttr('disabled');
        }

        async function insertSelected() {
            const selected = $(main.querySelector('#componentSearch')).select2('data')[0];
            if (!selected) { bootbox.alert('Choose a part or assembly to insert.'); return; }
            const request = { quantity: '1' };
            request[selected.type === 'part' ? 'child_part' : 'child_subassembly'] = selected.data.id;
            await swapLineItems(data.urlLineAdd, request);
            $(main.querySelector('#componentSearch')).val(null).trigger('change');
        }

        /** References the instructions mention in backticks are coloured in the table. */
        function colouriseUsed() {
            const textarea = main.querySelector('textarea[name=instructions]');
            if (!textarea) { return; }
            refreshColourise = () => {
                main.querySelectorAll('#subComponentsTable .bomlink .reference').forEach((ref) => {
                    ref.parentNode.classList.toggle('in-instructions', textarea.value.indexOf(`\`${ref.innerText}\``) > -1);
                });
            };
            const field = MarkdownField.forTextarea('instructions');
            if (field) { field.editor.on('change', refreshColourise); }
            refreshColourise();
        }

        /** Things in backticks in the instructions that are not line items. */
        async function findUnreferencedItems() {
            const field = MarkdownField.forTextarea('instructions');
            const markdown = field ? field.editor.getMarkdown() : main.querySelector('textarea[name=instructions]').value;
            const entries = [...new Set((markdown.match(/`.*?`/g) || []).map(e => e.toUpperCase().replace(/^`(.*)`$/, '$1')))];
            const references = [...new Set([...main.querySelectorAll('#subComponentsTable .bomlink .reference')].map(r => r.innerText.toUpperCase()))];
            const delta = entries.filter(x => !references.includes(x));
            const parts = await (await fetch('/api/parts/')).json();
            const assemblies = await (await fetch('/api/subassemblies/')).json();
            const known = [...assemblies, ...parts].map(p => p.reference.toUpperCase());
            const inDb = delta.filter(x => known.includes(x)).sort();
            const outDb = delta.filter(x => !known.includes(x)).sort();
            const list = items => items.length ? `<ul>${items.map(r => '<li><code>' + r + '</code></li>').join('')}</ul>` : '<p class="text-muted">None.</p>';
            bootbox.alert(`<p>${inDb.length} item(s) referenced in the instructions are not line items. That may be fine (a part in a sub-assembly), but worth a look:</p>${list(inDb)}<p>These quoted strings are not parts or assemblies (measurements, labels):</p>${list(outDb)}`);
        }

        function deleteAssembly() {
            bootbox.confirm(`Delete ${data.assemblyReference}? If it is a top-level assembly, every assembly under it goes too.`, async (ok) => {
                if (!ok) { return; }
                const response = await fetch(`/api/subassemblies/${data.assemblyId}/`, { method: 'DELETE', headers: { 'X-CSRFToken': csrf() }, mode: 'same-origin' });
                await processErrors(response);
                PageChanges.supressNote();
                window.location = data.urlAfterDelete;
            });
        }

        /** A reference picked in spec / instructions / QC that is not a line item: offer to add it. */
        let offer = null;
        function closeOffer() {
            if (offer) { offer.remove(); offer = null; }
        }
        function offerLineItem(anchor, item) {
            closeOffer();
            offer = document.createElement('div');
            offer.className = 'bn-addref';
            const chipKind = item.kind === 'assembly' ? 'assembly' : 'part';
            offer.innerHTML = `<span class="bn-ref is-${chipKind}">${item.reference}</span> is not in this BOM.`;
            const actions = document.createElement('div');
            actions.className = 'bn-addref-actions';
            const skip = document.createElement('button');
            skip.type = 'button';
            skip.className = 'btn btn-sm btn-outline-secondary';
            skip.textContent = 'Not now';
            skip.addEventListener('click', closeOffer);
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-sm btn-primary';
            add.textContent = 'Add to the BOM';
            add.addEventListener('click', async () => {
                const request = { quantity: '1' };
                request[item.kind === 'assembly' ? 'child_subassembly' : 'child_part'] = item.id;
                closeOffer();
                await swapLineItems(data.urlLineAdd, request);
            });
            actions.append(skip, add);
            offer.appendChild(actions);
            anchor.appendChild(offer);                                     // the widget is position: relative
            setTimeout(closeOffer, 15000);                                 // it is an offer, not a demand
        }
        main.addEventListener('bomnado:reference-inserted', (event) => {
            const item = event.detail || {};
            if (!item.id || item.kind === 'piece') { return; }             // pieces are not BOM items
            if (item.reference === data.assemblyReference) { return; }     // itself
            const used = [...main.querySelectorAll('#subComponentsTable .bomlink .reference')]
                .map(r => r.innerText.toUpperCase());
            if (used.includes(item.reference.toUpperCase())) { return; }
            offerLineItem(event.target, item);
        });

        main.addEventListener('click', (event) => {
            const button = event.target.closest('[data-action]');
            if (!button || !main.contains(button)) { return; }
            if (offer && !offer.contains(event.target)) { closeOffer(); }
            const action = button.dataset.action;
            if (action === 'delete-assembly') { deleteAssembly(); }
            else if (action === 'find-unreferenced') { findUnreferencedItems(); }
            else if (action === 'insert-line') { insertSelected(); }
            else if (action === 'delete-line') {
                bootbox.confirm(`Remove ${button.dataset.name} from this assembly?`, (ok) => {
                    if (ok) { swapLineItems(data.urlLineDelete.replace('/0/', `/${button.dataset.id}/`), {}); }
                });
            }
        });
        configureTable();
        createInsertables();
        colouriseUsed();
        BomnadoEditor.install('bomando-assembly-form');
    }

    pages['assembly-editor'] = { init: init };
})(window);
