/**
 * Hovering any element with a `data-picture-preview="<url>"` attribute shows that
 * picture, larger, in a floating box beside it. One listener serves the whole page,
 * so elements added later (e.g. cloned form rows) work without registration.
 *
 * The box stays while the pointer is over it (there is a short grace period for
 * crossing the gap), and the picture is a link to the full-size file, so the normal
 * browser context menu - open in new tab, save image, copy - is available on it.
 *
 * Self-contained (styles are inline) so the standalone documentation page can use it
 * without pulling in the app stylesheet.
 */
(function () {
    const GAP = 6;          // px between the hovered element and the box
    const SIZE = 240;       // px, the picture box
    const GRACE = 250;      // ms allowed to move from the element into the box
    let box = null;
    let link = null;
    let hideTimer = null;

    function ensureBox() {
        if (box) { return; }
        box = document.createElement('div');
        box.className = 'bomnado-picture-preview';
        box.style.cssText = 'display:none; position:absolute; z-index:1080; padding:4px; background:#fff; '
            + 'border:1px solid #ced4da; border-radius:4px; box-shadow:0 4px 12px rgba(0,0,0,0.15);';
        link = document.createElement('a');
        link.target = '_blank';
        link.rel = 'noopener';
        link.title = 'Open the full-size picture';
        const img = document.createElement('img');
        img.style.cssText = `display:block; width:${SIZE}px; height:${SIZE}px; object-fit:contain;`;
        link.appendChild(img);
        box.appendChild(link);
        box.addEventListener('mouseenter', cancelHide);
        box.addEventListener('mouseleave', hide);
        document.body.appendChild(box);
    }

    function show(target) {
        ensureBox();
        cancelHide();
        const url = target.dataset.picturePreview;
        link.href = url;
        link.querySelector('img').src = url;
        box.style.display = 'block';

        // Below the element, left-aligned; flip above / pull left if that would leave the viewport.
        const rect = target.getBoundingClientRect();
        const width = box.offsetWidth;
        const height = box.offsetHeight;
        let left = rect.left;
        let top = rect.bottom + GAP;
        if (left + width > window.innerWidth) { left = Math.max(0, window.innerWidth - width - GAP); }
        if (top + height > window.innerHeight) { top = rect.top - height - GAP; }
        box.style.left = `${left + window.scrollX}px`;
        box.style.top = `${top + window.scrollY}px`;
    }

    function hide() {
        cancelHide();
        if (box) { box.style.display = 'none'; }
    }

    function scheduleHide() {
        cancelHide();
        hideTimer = setTimeout(hide, GRACE);
    }

    function cancelHide() {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    }

    document.addEventListener('mouseover', (event) => {
        const target = event.target.closest('[data-picture-preview]');
        if (target && target.dataset.picturePreview) { show(target); }
    });
    document.addEventListener('mouseout', (event) => {
        const target = event.target.closest('[data-picture-preview]');
        if (target && !target.contains(event.relatedTarget)) { scheduleHide(); }
    });
    window.addEventListener('scroll', hide, true);
})();
