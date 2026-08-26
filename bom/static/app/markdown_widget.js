/**
 * Logic for the "markdown.html" Django widget: a Toast UI Editor over a hidden textarea.
 *
 * The textarea is what the form submits. Whatever mode the user edits in (markdown
 * or WYSIWYG) the textarea always holds markdown, so the server never sees HTML.
 *
 * Sugar kept from the previous (ace) editor:
 *   - pasting / dropping a file uploads it to the page's AttachmentList and inserts
 *     a markdown image or link using the name the server stored it under;
 *   - typing a backtick offers part / assembly references to complete, and a
 *     toolbar button does the same in either mode.
 */

// Flag a warning if Toast UI is not included.
if (window.toastui === undefined || window.toastui.Editor === undefined) {
    console.error('toastui-editor.js is not included on the page yet. Required by `MarkdownField`.')
}

/**
 * Wraps logic for the `markdown.html` Django widget template.
 */
class MarkdownField {

    /** List of instances, by root element id. */
    static instances = {}

    /** Counter incremented when a new instance is created. */
    static _instanceCounter = 0;

    /** The number of pasted files uploaded. */
    static _uploadCounter = 0;

    /** Assemblies the user can see, fetched once per page for reference completion. */
    static _assemblies = null;

    /** Tell the user something went wrong without a blocking native dialog. */
    static notify(message) {
        console.error(message);
        if (window.bootbox) {
            bootbox.alert(message);
        }
    }

    /** Find the field wrapping the textarea with the given form field name. */
    static forTextarea(name) {
        return Object.values(MarkdownField.instances).find(f => f.textarea.name === name) || null;
    }

    /**
     * @param element The root element of the widget (contains the textarea and the editor container).
     * @param options.pasteAttachmentList String `widget_id` of the AttachmentList to upload into. Default 'mainAttachments'.
     */
    constructor(element, options) {

        // Make the instances available by name so we can reference in other parts of the application.
        MarkdownField._instanceCounter += 1;
        const instanceName = `${element.id || MarkdownField._instanceCounter}`;
        if (MarkdownField.instances[instanceName] !== undefined) {
            throw new Error(`MarkdownField "${instanceName}" already registered.`);
        }
        MarkdownField.instances[instanceName] = this;

        // Save defaults.
        this.options = options || {};
        this.options.pasteAttachmentList = this.options.pasteAttachmentList || 'mainAttachments';

        // Save elements. The root is the positioning context for the reference popup.
        this.element = element;
        this.element.style.position = 'relative';
        this.textarea = element.querySelector('textarea');
        this.editorElement = element.querySelector('.bomnado-markdown-widget-editor');

        // Toolbar button for inserting a reference (works in both modes).
        const referenceButton = document.createElement('button');
        referenceButton.type = 'button';
        referenceButton.className = 'bomnado-reference-button';
        referenceButton.textContent = 'REF';  // text glyph, like Toast's own 'CB' button
        referenceButton.title = 'Insert a part or assembly reference (or type a backtick)';
        referenceButton.addEventListener('click', () => this.openReferencePicker());

        // Create the editor.
        this.editor = new toastui.Editor({
            el: this.editorElement,
            initialValue: this.textarea.value,
            initialEditType: 'markdown',
            previewStyle: 'tab',
            height: 'auto',
            minHeight: '140px',
            usageStatistics: false,
            autofocus: false,
            toolbarItems: [
                ['heading', 'bold', 'italic', 'strike'],
                ['hr', 'quote'],
                ['ul', 'ol', 'task'],
                ['table', 'image', 'link', 'code', 'codeblock'],
                [{ name: 'reference', tooltip: 'Insert a part or assembly reference', el: referenceButton }],
            ],
            hooks: {
                // Pasted / dropped / toolbar-chosen images go to the attachment list.
                addImageBlobHook: (blob, callback) => this.uploadBlob(blob, callback),
            },
            customHTMLRenderer: {
                // Attachments are referenced by bare file name in the markdown (the server
                // resolves them when rendering pages); resolve them here too so the
                // preview and WYSIWYG views can show the picture.
                image: (node, context) => {
                    const { getChildrenText, skipChildren } = context;
                    skipChildren();
                    return {
                        type: 'openTag', tagName: 'img', selfClose: true,
                        attributes: { src: this.resolveAttachment(node.destination), alt: getChildrenText(node) },
                    };
                },
            },
            events: {
                change: () => this.sync(),
                changeMode: () => this.onModeChanged(),
                keyup: (editorType, event) => this.onKeyUp(editorType, event),
            },
        });

        // Keep the textarea current, and once more just before submit to be safe.
        this.sync(false);
        if (this.textarea.form) {
            this.textarea.form.addEventListener('submit', () => this.sync(false));
        }

        // Non-image files pasted into the editor are uploaded and linked.
        this.element.addEventListener('paste', (event) => this.onPaste(event), true);

        // Reference completion popup.
        this.picker = new ReferencePicker(this);
    }

    /**
     * Markdown with attachment URLs turned back into bare file names.
     *
     * Stored text refers to attachments by name (the server resolves them when it
     * renders pages), but the WYSIWYG view has to hold the real URL to show the
     * picture, and Toast serialises that URL back out. Undo that here.
     */
    normaliseAttachments(markdown) {
        const uploader = this.uploader;
        if (!uploader) {
            return markdown;
        }
        return markdown.replace(/\]\(([^)\s]+)\)/g, (whole, destination) => {
            const name = uploader.nameForUrl(destination);
            return name ? `](${name})` : whole;
        });
    }

    /** Copy the editor's markdown into the textarea. */
    sync(flagChange = true) {
        if (this.suppressSync) {
            return;
        }
        const markdown = this.normaliseAttachments(this.editor.getMarkdown());
        if (markdown !== this.textarea.value) {
            this.valueBeforeChange = this.textarea.value;
            this.changedAt = performance.now();
            this.textarea.value = markdown;
            // (A class declaration is not a window property, hence typeof.)
            if (flagChange && typeof PageChanges !== 'undefined') {
                PageChanges.flag(this.textarea);
            }
        }
    }

    /**
     * Switching between markdown and WYSIWYG re-serialises the text (for example
     * "-" list bullets come back as "*"). That is not an edit, so the stored text is
     * put back to what it was; the normalised form is only kept once the user
     * actually changes something in the new mode.
     */
    onModeChanged() {
        if (this.changedAt !== undefined && performance.now() - this.changedAt < 200) {
            this.textarea.value = this.valueBeforeChange;
            this.changedAt = undefined;
        }
        // Coming back to markdown, show attachments by name rather than the URLs the
        // WYSIWYG view needed (without that counting as an edit).
        if (this.editor.isMarkdownMode()) {
            const source = this.editor.getMarkdown();
            const cleaned = this.normaliseAttachments(source);
            if (cleaned !== source) {
                this.suppressSync = true;
                try {
                    this.editor.setMarkdown(cleaned, false);
                } finally {
                    this.suppressSync = false;
                }
            }
        }
    }

    /** The AttachmentList uploads go to, if the page has one. */
    get uploader() {
        if (typeof AttachmentList === 'undefined') {
            return null;
        }
        return AttachmentList.instances[this.options.pasteAttachmentList] || null;
    }

    /** Turn a bare attachment file name into a URL for display, if the attachment list knows it. */
    resolveAttachment(destination) {
        if (!destination || /^(https?:)?\//i.test(destination) || destination.startsWith('data:')) {
            return destination;
        }
        const uploader = this.uploader;
        const url = uploader && uploader.urlForName(destination);
        return url || destination;
    }

    /** Upload an image blob (paste, drop, or the image dialog) and insert it by its stored name. */
    async uploadBlob(blob, callback) {
        const uploader = this.uploader;
        if (!uploader) {
            console.log(`Skipping upload as no AttachmentList for ${this.options.pasteAttachmentList}`);
            return;
        }
        MarkdownField._uploadCounter += 1;
        const file = blob instanceof File ? blob : new File([blob], `pasted-${MarkdownField._uploadCounter}.png`, { type: blob.type });
        try {
            const { name } = await uploader.uploadFile(file);
            // In WYSIWYG the node's src is shown directly, so it needs the real URL;
            // sync() turns it back into the bare name for storage.
            const shown = this.editor.isMarkdownMode() ? name : (uploader.urlForName(name) || name);
            callback(shown, '');
        } catch (error) {
            MarkdownField.notify(`Unable to upload file: ${error.message || error}`);
        }
    }

    /** Upload pasted non-image files and insert a link to each. Images are handled by Toast UI's hook. */
    async onPaste(event) {
        const uploader = this.uploader;
        if (!uploader || !event.clipboardData) {
            return;
        }
        const files = [...event.clipboardData.items]
            .filter(item => item.kind === 'file' && !item.type.startsWith('image/'))
            .map(item => item.getAsFile())
            .filter(Boolean);
        if (!files.length) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        for (const file of files) {
            try {
                const { name } = await uploader.uploadFile(file);
                this.editor.insertText(`[${name}](${name})`);
            } catch (error) {
                MarkdownField.notify(`Unable to upload file: ${error.message || error}`);
            }
        }
    }

    /** Typing inside an open backtick offers references to complete, in either mode. */
    onKeyUp(editorType, event) {
        if (this.picker.handlesKey(event.key)) {
            return;
        }
        const context = editorType === 'markdown' ? this.openBacktickContext() : this.openBacktickContextWysiwyg();
        if (context) {
            this.picker.open(context.term, (reference) => context.complete(reference));
        } else {
            this.picker.close();
        }
    }

    /** The partial reference after an unmatched backtick in `text`, or null. */
    static partialReference(text) {
        const match = text.match(/`([\w.\-]*)$/);
        if (!match) {
            return null;
        }
        const before = text.slice(0, match.index);
        if ((before.match(/`/g) || []).length % 2 === 1) {
            return null; // the backtick closes an earlier one
        }
        return match[1];
    }

    /**
     * Markdown mode: if the caret sits after an unmatched backtick on the current line,
     * describe the partial reference being typed and how to complete it.
     */
    openBacktickContext() {
        const [[line, ch]] = this.editor.getSelection();
        const text = (this.editor.getMarkdown().split('\n')[line - 1] || '').slice(0, ch - 1);
        const term = MarkdownField.partialReference(text);
        if (term === null) {
            return null;
        }
        return {
            term,
            complete: (reference) => {
                // Replace the partial reference and close the backtick.
                this.editor.setSelection([line, ch - term.length], [line, ch]);
                this.editor.replaceSelection(`${reference}\``);
                this.editor.focus();
            },
        };
    }

    /**
     * WYSIWYG mode: same, reading the text before the caret from the ProseMirror
     * state (Toast UI exposes no public API for that). The backtick is plain text
     * here, so completing replaces backtick + partial with the reference as inline code.
     */
    openBacktickContextWysiwyg() {
        const view = this.editor.wwEditor && this.editor.wwEditor.view;
        if (!view) {
            return null;
        }
        const { $from, empty } = view.state.selection;
        if (!empty || !$from.parent.isTextblock) {
            return null;
        }
        const text = $from.parent.textBetween(0, $from.parentOffset, '\n');
        const term = MarkdownField.partialReference(text);
        if (term === null) {
            return null;
        }
        const [, caret] = this.editor.getSelection();
        return {
            term,
            complete: (reference) => {
                this.editor.setSelection(caret - term.length - 1, caret);
                this.editor.replaceSelection(reference);
                this.editor.setSelection(caret - term.length - 1, caret - term.length - 1 + reference.length);
                this.editor.exec('code');
                const after = caret - term.length - 1 + reference.length;
                this.editor.setSelection(after, after);
                this.editor.focus();
            },
        };
    }

    /** Toolbar button: pick a reference and insert it as inline code in either mode. */
    openReferencePicker() {
        this.picker.open('', (reference) => this.insertReference(reference), true);
    }

    /** Insert `reference` as inline code at the caret, in whichever mode is active. */
    insertReference(reference) {
        if (this.editor.isMarkdownMode()) {
            this.editor.replaceSelection(`\`${reference}\``);
        } else {
            const [from] = this.editor.getSelection();
            this.editor.replaceSelection(reference);
            this.editor.setSelection(from, from + reference.length);
            this.editor.exec('code');
            this.editor.setSelection(from + reference.length, from + reference.length);
        }
        this.editor.focus();
    }

    /** Matching parts and their pieces (server search) and assemblies (cached list) for a term. */
    static async searchReferences(term) {
        const needle = term.toUpperCase();
        const partsRequest = fetch(`/api/parts/search/?${new URLSearchParams({ search: term })}`).then(r => r.json());
        if (MarkdownField._assemblies === null) {
            MarkdownField._assemblies = fetch('/api/subassemblies/').then(r => r.json()).catch(() => []);
        }
        const [parts, assemblies] = await Promise.all([partsRequest, MarkdownField._assemblies]);
        const matching = assemblies
            .filter(a => !needle || `${a.reference} ${a.name}`.toUpperCase().includes(needle))
            .slice(0, 10)
            .map(a => ({ icon: '📦', reference: a.reference, name: a.name }));
        // Each part is followed by its `PARENT>SUFFIX` pieces that start with the term
        // (so `CHASSIS` lists `CHASSIS>TOP` beneath it, and `CHASSIS>T` narrows to it).
        const rows = parts.flatMap(p => [
            { icon: '🔩', reference: p.reference, name: p.name },
            ...(p.named_pieces || [])
                .filter(sp => needle && sp.reference.toUpperCase().startsWith(needle))
                .map(sp => ({ icon: '🔹', reference: sp.reference, name: sp.note })),
        ]);
        return [...matching, ...rows];
    }
}


/**
 * A small popup listing part / assembly references. Opened by MarkdownField either
 * at the caret (backtick completion) or under the toolbar (reference button).
 */
class ReferencePicker {

    static KEYS = ['ArrowUp', 'ArrowDown', 'Enter', 'Tab', 'Escape'];

    constructor(field) {
        this.field = field;
        this.onPick = null;
        this.items = [];
        this.index = 0;
        this.requestId = 0;

        this.root = document.createElement('div');
        this.root.className = 'bomnado-reference-picker d-none';
        this.input = document.createElement('input');
        this.input.type = 'search';
        this.input.className = 'form-control form-control-sm d-none';
        this.input.placeholder = 'Type a reference…';
        this.list = document.createElement('div');
        this.list.className = 'list-group list-group-flush';
        this.root.append(this.input, this.list);
        field.element.appendChild(this.root);

        // Keys while the popup is open steer the popup, not the editor.
        field.element.addEventListener('keydown', (event) => this.onKeyDown(event), true);
        this.input.addEventListener('input', () => this.search(this.input.value));
        document.addEventListener('click', (event) => {
            if (this.isOpen && !this.root.contains(event.target) && !event.target.closest('.bomnado-reference-button')) {
                this.close();
            }
        });
    }

    get isOpen() {
        return !this.root.classList.contains('d-none');
    }

    handlesKey(key) {
        return this.isOpen && ReferencePicker.KEYS.includes(key);
    }

    /** Show the popup for `term`; `withInput` adds a search box (toolbar mode). */
    open(term, onPick, withInput = false) {
        this.onPick = onPick;
        this.root.classList.remove('d-none');
        this.input.classList.toggle('d-none', !withInput);
        this.position(withInput);
        if (withInput) {
            this.input.value = term;
            this.input.focus();
        }
        this.search(term);
    }

    close() {
        this.root.classList.add('d-none');
        this.items = [];
        this.list.innerHTML = '';
    }

    /** Put the popup under the caret (markdown completion) or under the toolbar (button). */
    position(underToolbar) {
        const host = this.field.element.getBoundingClientRect();
        let top = 40, left = 8;
        const selection = window.getSelection();
        if (!underToolbar && selection && selection.rangeCount) {
            const caret = selection.getRangeAt(0).getBoundingClientRect();
            if (caret.width || caret.height) {
                top = caret.bottom - host.top + 4;
                left = Math.min(caret.left - host.left, host.width - 320);
            }
        }
        this.root.style.top = `${Math.max(0, top)}px`;
        this.root.style.left = `${Math.max(0, left)}px`;
    }

    async search(term) {
        const requestId = ++this.requestId;
        let items = [];
        try {
            items = await MarkdownField.searchReferences(term);
        } catch (error) {
            console.warn('Reference search failed', error);
        }
        if (requestId !== this.requestId || !this.isOpen) {
            return; // superseded or closed meanwhile
        }
        this.items = items;
        this.index = 0;
        this.render();
    }

    render() {
        this.list.innerHTML = '';
        if (!this.items.length) {
            const empty = document.createElement('div');
            empty.className = 'list-group-item list-group-item-action disabled small text-muted';
            empty.textContent = 'No matching parts or assemblies';
            this.list.appendChild(empty);
            return;
        }
        this.items.forEach((item, i) => {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = `list-group-item list-group-item-action py-1 small${i === this.index ? ' active' : ''}`;
            const reference = document.createElement('kbd');
            reference.textContent = item.reference;
            const name = document.createElement('span');
            name.className = 'ml-2 text-truncate';
            name.textContent = item.name || '';
            row.append(document.createTextNode(`${item.icon} `), reference, name);
            row.addEventListener('mousedown', (event) => { event.preventDefault(); this.pick(i); });
            this.list.appendChild(row);
        });
    }

    highlight(delta) {
        if (!this.items.length) { return; }
        this.index = (this.index + delta + this.items.length) % this.items.length;
        this.render();
        const active = this.list.querySelector('.active');
        if (active) { active.scrollIntoView({ block: 'nearest' }); }
    }

    pick(index) {
        const item = this.items[index];
        if (!item) { return; }
        const onPick = this.onPick;
        this.close();
        onPick(item.reference);
    }

    onKeyDown(event) {
        if (!this.handlesKey(event.key)) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        switch (event.key) {
            case 'ArrowDown': this.highlight(1); break;
            case 'ArrowUp': this.highlight(-1); break;
            case 'Enter':
            case 'Tab': this.pick(this.index); break;
            case 'Escape': this.close(); this.field.editor.focus(); break;
        }
    }
}
