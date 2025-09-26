/** 
 * Logic for the "markdown.html" Django widget.
 */

// Flag a warning if `ace` not included.
if (window.ace === undefined) {
    console.error('ace.js is not included on the page yet. Required by `MarkdownField`.')
}

/**
 * Wraps logic for the `markdown.html` Django widget template.
 */
class MarkdownField {

    /** List of instances. */
    static instances = {}

    /** Counter incremented when a new instance is created. */
    static _instanceCounter = 0;

    /** The number of pasted files uploaded. */
    static _uploadCounter = 0;

    /** For a given autocomplete call, get a list of completions. */
    getCompletions = async (editor, session, pos, prefix, callback) => {

        // Grab the latest parts and assemblies from the database.
        // NOTE: This requests all the parts and assemblies from the database that we can access.
        // TODO: It would be good to score parts higher if they area already an assembly, in the assembly editor context.
        const parts = await(await fetch('/api/parts/')).json();
        const assemblies = await(await fetch('/api/subassemblies/')).json();
        const txPart = p => { return { value: `${p.reference}`, score: 1, meta: `${p.name}`, caption: `🔩 ${p.reference}` } };
        const txAssembly = p => { return { value: `${p.reference}`, score: 1, meta: `${p.name}`, caption: `📦 ${p.reference}` } };
        const completions = [...assemblies.map(txAssembly), ...parts.map(txPart)];

        // Note: the callback won't fire if the caret is at a word that doesn't have these letters.
        callback(null, completions);
    }

    /**
    * @param element The element to use.
    * @param options.pasteAttachmentList String name of the `widget_id` of the attachment list to use. Default is 'mainAttachments'
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

        // Save elements.
        this.element = element;
        this.textarea = element.querySelector('textarea');
        this.editorElement = element.querySelector('.bomnado-markdown-widget-ace');

        // Create ace editor.
        this.editor = ace.edit(this.editorElement, {
            mode: "ace/mode/markdown",
            autoScrollEditorIntoView: true,
            maxLines: 30,
            minLines: 5,
            wrap: true
        });

        // When the user adds the ` (backtick) string, open the autocomplete window.
        this.editor.commands.on('afterExec', (e) => {
            if (e.command.name == 'insertstring' && /^[\w`]$/.test(e.args)) {
                this.editor.execCommand('startAutocomplete');
            }
        });

        // Enable autocomplete.
        this.editor.setOptions({
            enableBasicAutocompletion: [{ getCompletions: this.getCompletions }],
            enableSnippets: false,
            enableLiveAutocompletion: false // disabled to stop hammering the server each autocomplete
        });

        // Setup session.
        this.session = this.editor.getSession();
        this.session.setValue(this.textarea.value);
        this.session.on('change', () => {
            this.textarea.value = this.editor.session.getValue();
        });

        // Handle paste event to put images into the attachments list if one is specified.
        this.element.addEventListener('paste', async (event) => {
            // console.log("PASTED", event);

            // Find the requested attachment list.
            const uploader = AttachmentList.instances[this.options.pasteAttachmentList];
            if (!uploader) {
                console.log(`Skipping upload as no AttachmentList for ${this.options.pasteAttachmentList}`);
                return;
            }

            // Get any files in the clipboard data.
            const { items } = event.clipboardData;

            // Upload each one.
            for (let item of items) {
                // Skip if not a file.
                if (item.kind !== 'file') {
                    continue;
                }

                // Increment page-unique ID.
                MarkdownField._uploadCounter += 1;
                const uploadCount = MarkdownField._uploadCounter;

                // Add in some content that let's the user know the upload is progressing and
                // store the range it was written into.
                const uploadContent = `![Uploading #${uploadCount}]()`;
                this.editor.session.insert(this.editor.getCursorPosition(), uploadContent);
                const range = this.editor.find(uploadContent, {
                    wrap: true,
                    caseSensitive: true,
                    wholeWord: true,
                    regExp: false,
                    preventScroll: true // Do not change selection!
                });
                
                // Wait for the file to upload and then replace the `uploadContent` text
                // with the proper file name as stored on the server.
                try {
                    const { name } = await uploader.uploadFile(item.getAsFile());
                    this.editor.session.replace(range, `![](${name})`);
                }
                catch (error) {
                    alert(`Unable to upload file: ${message}`);
                    this.editor.session.replace(range, '');
                }
            }
        }, true);
    }
}