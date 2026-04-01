/**
 * EmuRunner – animated running emu SVG used as thinking indicator.
 * Returns a DOM element with a small emu that runs in place (facing left)
 * plus subtle trailing dots.
 */

function createEmuRunner() {
    const wrapper = document.createElement('span');
    wrapper.className = 'typing';

    wrapper.innerHTML = `
        <span class="emu-runner"><svg viewBox="0 0 40 36" fill="none" xmlns="http://www.w3.org/2000/svg">
            <g class="emu-body-group">
                <!-- Neck -->
                <path d="M14 18 Q12 10 10 5 Q9 3 10 2" stroke="#1f2937" stroke-width="2.2" stroke-linecap="round" fill="none"/>
                <!-- Head -->
                <circle cx="9" cy="2.5" r="2.5" fill="#1f2937"/>
                <!-- Beak -->
                <path d="M6.5 2.5 L3 3.5 L6.5 4" fill="#374151"/>
                <!-- Eye -->
                <circle cx="8.2" cy="1.8" r="0.7" fill="#fff"/>
                <!-- Body -->
                <ellipse cx="20" cy="20" rx="9" ry="6" fill="#1f2937"/>
                <!-- Tail feathers -->
                <path d="M29 18 Q33 14 32 11" stroke="#1f2937" stroke-width="2" stroke-linecap="round" fill="none"/>
                <path d="M28 19 Q34 16 34 13" stroke="#1f2937" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Back leg -->
            <g class="emu-leg-back">
                <path d="M18 25 L15 33 L12 33" stroke="#374151" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Front leg -->
            <g class="emu-leg-front">
                <path d="M22 25 L19 33 L16 33" stroke="#374151" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
        </svg></span>
        <span class="thinking-dots"><span></span><span></span><span></span></span>
    `;

    return wrapper;
}

module.exports = { createEmuRunner };
