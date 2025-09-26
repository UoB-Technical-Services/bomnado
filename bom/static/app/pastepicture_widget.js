/** 
 * Logic for the "pastepicture.html" Django widget.
 */

/**
 * Wraps logic for the `pastepicture.html` Django widget template.
 */
class PastePictureField {

    /** List of instances. */
    static instances = {}

    /** Counter incremented when a new instance is created. */
    static _instanceCounter = 0;

    /**
    * @param element The element to use.
    */
    constructor(element, options) {

        // Make the instances available by name so we can reference in other parts of the application.
        PastePictureField._instanceCounter += 1;
        const instanceName = `${element.id || PastePictureField._instanceCounter}`;
        if (PastePictureField.instances[instanceName] !== undefined) {
            throw new Error(`PastePictureField "${instanceName}" already registered.`);
        }
        PastePictureField.instances[instanceName] = this;
        
        // Save elements.
        this.element = element;
        this.input = element.querySelector('input');
        this.thumbnail = element.querySelector('.bomnado-pastepicture-widget-thumb');
        this.btnBrowse = element.querySelector('.bomnado-pastepicture-widget-browse');
        this.btnPaste = element.querySelector('.bomnado-pastepicture-widget-paste');

        // Listen to change events to update the background image
        // and update the image with the content of the file.
        this.input.addEventListener('change', () => {
            if (this.input.files && this.input.files[0]) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.thumbnail.style.backgroundImage = `url(${e.target.result})`;
                }
                reader.readAsDataURL(this.input.files[0]);
            }
        });

        // BROWSE BUTTON = trigger the input browse button internally.
        this.btnBrowse.addEventListener('click', () => this.input.click());

        // PASTE BUTTON = update the file field with the content in the clipboard.
        this.btnPaste.addEventListener('click', async () => {
            // Get the image on the clipboard (if it exists) and then convert into a
            // format that the <input> accepts.
            const clipdata = await PastePictureField.getClipboardImage();
            if (!clipdata) return;
            const data = new ClipboardEvent('').clipboardData || new DataTransfer();
            data.items.add(clipdata);

            // Update the `files` attribute and trigger the `change` event.
            this.input.files = data.files;
            this.input.dispatchEvent(new Event('change'));
        });
    }

    /** Find the first image on the clipboard or return as a `File` or `null` if one is not there. */
    static async getClipboardImage() {
        const items = await navigator.clipboard.read();
        console.log("items", items);
        for (const item of items) {
            for (const type of item.types) {
                if (type.indexOf('image') === -1) {
                    continue;
                }
                const blob = await item.getType(type);
                let filenameEstimate = type.replace('/', '.');
                let file = new File([blob], filenameEstimate, { type: type, lastModified: Date.now() });
                return file;
            }
        }
        return null;
    }
}