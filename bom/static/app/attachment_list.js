/** 
 * Logic for the "attachment_list.html" template.
 */

// Flag a warning if `Dropzone` not included.
if (window.Dropzone === undefined) {
    console.error('Dropzone.js is not included on the page yet. Required by `AttachmentList`.')
}

// Configure `Dropzone` to not automatically attach to elements.
Dropzone.autoDiscover = false;

// Override the `createElement` function to allow creating non-<div> elements.
Dropzone.createElement = function (template) {
    var el = $(template);
    return el[0];
};


/**
 * Wraps logic for the `attachment_list.html` template.
 */
class AttachmentList {

    /** List of instances. */
    static instances = {}

    /** Counter incremented when a new instance is created. */
    static _instanceCounter = 0;

    /** 
     * @param element The element to use.
     * @param options.uploadView The view to POST attachments too.
     * @param options.uploadParams Parameters for the POST (e.g. Django CSRF token)
     * @param options.uploadFieldName The name of the attachment in the POST request.
     */
    constructor(element, options) {

        // Ensure options are given.
        if (!options.uploadView || !options.uploadParams || !options.uploadFieldName) {
            throw new Error('Bad options');
        }

        // Make the instances available by name so we can reference
        // attachments in other parts of the software.
        AttachmentList._instanceCounter += 1;
        const instanceName = `${element.id || AttachmentList._instanceCounter}`;
        const previous = AttachmentList.instances[instanceName];
        if (previous !== undefined && previous.element && document.body.contains(previous.element)) {
            throw new Error(`AttachmentList "${instanceName}" already registered.`);
        }
        AttachmentList.instances[instanceName] = this;

        // Keep the options - the upload params carry the CSRF token needed to delete too.
        this.options = options;

        // Important elements.
        this.element = element;
        this.previewContainer = this.element.querySelector('tbody');

        // The `previewTemplate` for each dropzone.
        // NOTE: Emitting a <tr> requires overriding the library `createElement` function above.
        const template = `<tr>
            <th>
                <img data-dz-thumbnail />
                <span class="nothumb badge badge-secondary"></span>
            </th>
            <td>
                <div class="dz-filename"><span data-dz-name></span></div>
            </td>
            <td>
                <div class="dz-size" data-dz-size></div>
            </td>
            <td class="">
                <div class="btn-group btn-group-sm float-right mr-1" role="group">
                    <a class="action-download btn btn btn-outline-secondary" href="javascript:undefined;">Download</a>
                    <a class="action-remove btn btn btn-outline-danger" href="javascript:undefined;">&times;</a>
                </div>
            </td>
        </tr>`;

        // NOTE: Copy button removed since it was not useful.
        // <a class="action-copy btn btn btn-outline-primary" href="javascript:undefined;">📋</a>

        // Create a dropzone.
        this.dropzone = new Dropzone(this.element, {
            url: options.uploadView,
            params: options.uploadParams,
            paramName: options.uploadFieldName,
            previewTemplate: template,
            previewsContainer: this.previewContainer,
            thumbnailMethod: 'contain',   // Ensures that the datauri thumbnail matches the uploaded image aspect ratio
        });

        // Bind events.
        this.dropzone.on('uploadprogress', this._uploadProgress.bind(this));
        this.dropzone.on('success', this._success.bind(this));
        this.dropzone.on('error', this._error.bind(this));
        this.dropzone.on('addedfile', this._addedFile.bind(this));
    }

    /** 
     * Given a `file` get the name that was actually uploaded to the server. 
     * This only works *after* the file has been uploaded.
     */
    static getServerFilename(file) {
        // NOTE: Irritatingly, setting the new/actual file name from the server in the `success` handler doesn't let
        // us update the dropzone file object. Thus we grab the new name from the DOM instead.
        const filename = file.previewTemplate.querySelector('[data-dz-name]').innerText;
        return filename;
    }

    /** The stored name of the attachment served at `url`, or null if this list does not have it. */
    nameForUrl(url) {
        const file = this.dropzone.files.find(f => f.existing_url && f.existing_url === url);
        return file ? AttachmentList.getServerFilename(file) : null;
    }

    /** The URL of the attachment stored under `name`, or null if this list does not have it. */
    urlForName(name) {
        const file = this.dropzone.files.find(f => f.existing_url && AttachmentList.getServerFilename(f) === name);
        return file ? file.existing_url : null;
    }

    /**
     * Add an existing file ("non-uploaded") to the preview table.
     * @param file Fields include: name, size, delete_link, existing_url
     */
    showFileFromServer(file) {
        // NOTE: Dropzone.js has `displayExistingFile` but this is focused on supporting
        // images. This function fires all the events we require.
        this.dropzone.emit("addedfile", file);
        this.dropzone.emit("complete", file);
        this.dropzone.emit("thumbnail", file, file.existing_url); // TODO - do I need this?
    }

    /** Display upload progress by moving the row's background gradient position. */
    _uploadProgress(file, progress) {
        // Update CSS to indicate load progress.
        file.previewTemplate.style.backgroundPosition = `${100 - progress}%`;

        // If we reach 100%, 1s after the animation completes, set the background to transparent.
        if (progress >= 100) {
            setTimeout(() => { file.previewTemplate.style.background = 'unset'; }, 500 + 1000);
        }
    }

    /** Handle successful uploads. */
    _success(file, response) {
        // Store the delete link (needed for files uploaded, not inserted with displayExistingFile)
        file.delete_link = response.delete_link;
        file.existing_url = response.url;
        // file.name = response.filename;

        // Update the "name" and "url" with the new file.
        // NOTE: Apparently this is the accepted way to do this. Ugh.
        file.previewTemplate.querySelector('[data-dz-name]').innerText = response.filename;
        // file.previewTemplate.querySelector('[data-dz-thumbnail]').src = response.url;
        // TODO: add url to make images clickable to download etc.
    }

    /** Handle upload failures. */
    _error(file, message) {
        console.warn("Unable to upload file.", message, file);
        alert(`Unable to upload file. ${message}`)
        this.dropzone.removeFile(file);
    }

    /** Handle file's being added to the table. Bind button events, etc. */
    _addedFile(file) {
        // print("ADDED FILE", file)
        // Get the file extension.
        const ext = `${file.name.split('.').pop()}`.toLowerCase();

        // Get elements that show / hide based on if it's an image or not.
        const noThumbSpan = file.previewTemplate.querySelector('.nothumb');
        const thumbImage = file.previewTemplate.querySelector('[data-dz-thumbnail]');

        // If it's an image, show the thumnail and remove the help text.
        if (['png', 'jpg', 'jpeg', 'svg'].includes(ext)) {
            noThumbSpan.remove()
        }
        // Otherwise, say the extension and remove the image.
        else {
            thumbImage.remove()
            noThumbSpan.innerText = ext;
        }

        // TODO: Add clicking handlers for video and images.

        // // COPY button
        // file.previewTemplate.querySelector('.action-copy').onclick = async () => {
        //     const filename = AttachmentList.getServerFilename(file);
        //     await navigator.clipboard.writeText(filename);
        //     // TODO: Animation that spins the icon to say done!
        // }

        // DOWNLOAD button
        file.previewTemplate.querySelector('.action-download').onclick = () => {
            // Create a download link for our file.
            // Use the existing_url (from django) or the dataURL (from dropzone).
            const filename = AttachmentList.getServerFilename(file);
            const link = document.createElement('a');
            link.href = file.existing_url || file.dataURL;
            link.download = filename;
            link.click();
        }

        // REMOVE button
        file.previewTemplate.querySelector('.action-remove').onclick = async () => {
            // Try to delete the attachment from the server.
            // If we had a problem, then let the user know.
            // NOTE: This is useful for future validation (attachment used in text) etc.
            const body = new FormData();
            for (const [name, value] of Object.entries(this.options.uploadParams)) {
                body.append(name, value);
            }
            let response = await fetch(file.delete_link, { method: 'POST', body: body });
            if (!response.ok) {
                alert(`Unable to delete attachment. ${response.statusText}`);
                console.warn(response);
                return;
            }

            // If successful, remove from the attachments list.
            this.dropzone.removeFile(file);
        }
    }

    /**
     * Return a Promise that resolves when the uploaded file is pasted in or rejects on upload error.
     * @param file The `File` to upload (e.g. item.getAsFile())
     */
    async uploadFile(file) {
        return new Promise((resolve, reject) => {
            // TODO FIXME NOTE: This is long-term ugly because we just keep attaching event handlers for every
            // pasted file because dropzonejs has no way of `awaiting` a callback for when a specific
            // file has been successfully uploaded.
            let hasRun = false;

            // Handle upload success.
            this.dropzone.on('success', (uploadedFile, response) => {
                if (hasRun) return;
                const filename = AttachmentList.getServerFilename(uploadedFile);
                resolve({ file: file, name: filename, list: this });
            });

            // Handle upload failure.
            this.dropzone.on('error', (file, message) => {
                if (hasRun) return;
                reject({ file: file, message: message, list: this });
            });

            // Add the file.
            this.dropzone.addFile(file);
        });
    }
}