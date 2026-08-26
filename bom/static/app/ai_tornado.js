/**
 * The AI signature: a short neon tornado where a sparkle was, for a couple of seconds when the AI
 * is set going (the top-bar button, a ✦ accelerator, a message sent). Adapted from John's
 * "Tornado Breakout" drop-in: the SVGs and animation are his; this version bursts on demand and
 * stops by itself instead of toggling and surging forever, so it stays a signature, not a show.
 *
 *   BomnadoTornado.burst(element, ms)  - play the tornado inside `element` for `ms` (default 2200),
 *                                        hiding its sparkle SVG meanwhile.
 */
(function (global) {
    const SVGS = `
        <svg class="sparkle" viewBox="0 0 100 100">
            <path d="M50 5 C50 45 55 50 95 50 C55 50 50 55 50 95 C50 55 45 50 5 50 C45 50 50 45 50 5 Z" />
            <circle cx="50" cy="50" r="15" fill="#fff" opacity="0.8"/>
        </svg>
        <svg class="tornado" viewBox="-20 -20 140 140">
            <defs>
                <filter id="bomnado-neon-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="4" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
            </defs>
            <ellipse class="t-ring r1" cx="50" cy="10" rx="60" ry="14" fill="none" stroke="#06b6d4" stroke-width="6" filter="url(#bomnado-neon-glow)" />
            <ellipse class="t-ring r2" cx="50" cy="35" rx="45" ry="11" fill="none" stroke="#3b82f6" stroke-width="6" filter="url(#bomnado-neon-glow)" />
            <ellipse class="t-ring r3" cx="50" cy="60" rx="32" ry="8"  fill="none" stroke="#a855f7" stroke-width="5" filter="url(#bomnado-neon-glow)" />
            <ellipse class="t-ring r4" cx="50" cy="80" rx="20" ry="6"  fill="none" stroke="#ec4899" stroke-width="5" filter="url(#bomnado-neon-glow)" />
            <ellipse class="t-ring r5" cx="50" cy="95" rx="10" ry="4"  fill="#fdf4ff" opacity="0.9" filter="url(#bomnado-neon-glow)" />
        </svg>`;

    const CSS = `
        .magic-icon { display: inline-flex; align-items: center; justify-content: center; position: relative;
            width: 1.2em; height: 1.2em; vertical-align: middle; flex-shrink: 0; perspective: 400px; z-index: 10; }
        .magic-icon svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: visible;
            transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1); }
        .magic-icon .sparkle { fill: #06b6d4; filter: drop-shadow(0 0 6px rgba(6, 182, 212, 0.8)); transform-origin: center; }
        .magic-icon .tornado { opacity: 0; transform: scale(0) translateY(50%); transform-origin: bottom center; }
        .magic-icon .t-ring { transform-origin: 50% 50%; }
        .magic-icon.is-active .sparkle { opacity: 0; transform: scale(0) rotate(720deg); }
        .magic-icon.is-active .tornado { opacity: 1; transform: scale(1.0) translateY(-5%); }
        .magic-icon.is-active.is-surging .tornado { animation: ai-breakout-surge 2s cubic-bezier(0.25, 1, 0.5, 1) forwards; }
        @keyframes ai-breakout-surge {
            0% { transform: scale(1.0) translateY(-5%) rotateZ(0deg); }
            20% { transform: scale(1.1) translateY(-5px) translateX(3px) rotateZ(5deg); }
            40% { transform: scale(1.2) translateY(-10px) translateX(-3px) rotateZ(-4deg); }
            60% { transform: scale(1.15) translateY(-8px) translateX(2px) rotateZ(2deg); }
            80% { transform: scale(1.2) translateY(-12px) translateX(0px) rotateZ(-2deg); }
            100% { transform: scale(1.0) translateY(-5%) rotateZ(0deg); }
        }
        .magic-icon.is-active .t-ring { animation: icon-tornado-spin infinite linear; }
        .magic-icon.is-active .r1 { animation-duration: 0.15s; animation-delay: 0.0s; }
        .magic-icon.is-active .r2 { animation-duration: 0.20s; animation-delay: 0.1s; }
        .magic-icon.is-active .r3 { animation-duration: 0.25s; animation-delay: 0.2s; }
        .magic-icon.is-active .r4 { animation-duration: 0.30s; animation-delay: 0.3s; }
        .magic-icon.is-active .r5 { animation-duration: 0.35s; animation-delay: 0.4s; }
        @keyframes icon-tornado-spin {
            0%   { transform: translateX(-15%) rotateY(0deg) rotateZ(-4deg); }
            25%  { transform: translateX(0%)   rotateY(90deg) rotateZ(0deg); }
            50%  { transform: translateX(15%)  rotateY(180deg) rotateZ(4deg); }
            75%  { transform: translateX(0%)   rotateY(270deg) rotateZ(0deg); }
            100% { transform: translateX(-15%) rotateY(360deg) rotateZ(-4deg); }
        }
        @media (prefers-reduced-motion: reduce) { .magic-icon { display: none !important; } }`;

    function injectStyles() {
        if (document.getElementById('bomnado-tornado-styles')) { return; }
        const style = document.createElement('style');
        style.id = 'bomnado-tornado-styles';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    const running = new WeakMap();

    /** Play the tornado inside `element` for `ms`, in place of its sparkle. Calling again while it plays restarts the clock. */
    function burst(element, ms) {
        if (!element || (global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches)) { return; }
        injectStyles();
        let icon = element.querySelector(':scope > .magic-icon');
        const sparkle = element.querySelector(':scope > .bomnado-ai-icon');
        if (!icon) {
            icon = document.createElement('span');
            icon.className = 'magic-icon';
            icon.innerHTML = SVGS;
            if (sparkle) { sparkle.insertAdjacentElement('afterend', icon); } else { element.prepend(icon); }
        }
        if (sparkle) { sparkle.style.display = 'none'; }
        icon.hidden = false;
        icon.classList.add('is-active');
        requestAnimationFrame(() => icon.classList.add('is-surging'));
        clearTimeout(running.get(element));
        running.set(element, setTimeout(() => {
            icon.classList.remove('is-surging', 'is-active');
            setTimeout(() => { icon.remove(); if (sparkle) { sparkle.style.display = ''; } }, 600);
        }, ms || 2200));
    }

    global.BomnadoTornado = { burst: burst };
})(window);
