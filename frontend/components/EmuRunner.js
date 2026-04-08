/**
 * EmuRunner – animated running emu SVG used as thinking indicator.
 * Returns a DOM element with a small emu that runs in place (facing left)
 * plus subtle trailing dots.
 */

function createEmuRunner() {
    const wrapper = document.createElement('span');
    wrapper.className = 'typing';

    wrapper.innerHTML = `
        <span class="emu-runner"><svg viewBox="0 0 40 36" fill="none" xmlns="http://www.w3.org/2000/svg" class="emu-runner-svg">
            <g class="emu-body-group">
                <!-- Neck -->
                <path class="emu-main-stroke" d="M14 18 Q12 10 10 5 Q9 3 10 2" stroke-width="2.2" stroke-linecap="round" fill="none"/>
                <!-- Head -->
                <circle class="emu-main-fill" cx="9" cy="2.5" r="2.5"/>
                <!-- Beak -->
                <path class="emu-accent-fill" d="M6.5 2.5 L3 3.5 L6.5 4"/>
                <!-- Eye -->
                <circle cx="8.2" cy="1.8" r="0.7" fill="#fff"/>
                <!-- Body -->
                <ellipse class="emu-main-fill" cx="20" cy="20" rx="9" ry="6"/>
                <!-- Tail feathers -->
                <path class="emu-main-stroke" d="M29 18 Q33 14 32 11" stroke-width="2" stroke-linecap="round" fill="none"/>
                <path class="emu-main-stroke" d="M28 19 Q34 16 34 13" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Back leg -->
            <g class="emu-leg-back">
                <path class="emu-accent-stroke" d="M18 25 L15 33 L12 33" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Front leg -->
            <g class="emu-leg-front">
                <path class="emu-accent-stroke" d="M22 25 L19 33 L16 33" stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
        </svg></span>
        <span class="thinking-dots"><span></span><span></span><span></span></span>
    `;

    return wrapper;
}

module.exports = { createEmuRunner };
