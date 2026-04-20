/**
 * EmuRunner — subtle thinking indicator
 *
 * Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
 *
 * A small running emu silhouette that loops while the agent is thinking.
 * Design changes (vs prior version):
 *   - Trailing "..." dots removed (the window-header status pill already
 *     communicates "working" — dots were redundant noise).
 *   - Colors pulled from tokens (--ink / --ink-55) so the bird re-tints
 *     with Linen / Ink modes instead of being hardcoded #111111.
 *   - Smaller and slower: 26×26 @ 0.48s (was 32×32 @ 0.35s) — less frantic.
 *   - Simplified SVG: removed the small white eye, the tail now uses a
 *     single stroke, and the beak is slightly thinner for a lighter feel.
 */

function createEmuRunner() {
    const wrapper = document.createElement('span');
    wrapper.className = 'typing';

    wrapper.innerHTML = `
        <span class="emu-runner">
          <svg viewBox="0 0 40 36" fill="none" xmlns="http://www.w3.org/2000/svg" class="emu-runner-svg">
            <g class="emu-body-group">
              <!-- Neck -->
              <path class="emu-main-stroke" d="M14 18 Q12 10 10 5 Q9 3 10 2"
                    stroke-width="2" stroke-linecap="round" fill="none"/>
              <!-- Head -->
              <circle class="emu-main-fill" cx="9" cy="2.5" r="2.3"/>
              <!-- Beak -->
              <path class="emu-accent-fill" d="M6.5 2.5 L3.2 3.5 L6.5 4"/>
              <!-- Body -->
              <ellipse class="emu-main-fill" cx="20" cy="20" rx="8.5" ry="5.6"/>
              <!-- Tail (single subtle sweep) -->
              <path class="emu-main-stroke" d="M28 19 Q33 15 32 11"
                    stroke-width="1.8" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Back leg -->
            <g class="emu-leg-back">
              <path class="emu-accent-stroke" d="M18 25 L15 33 L12 33"
                    stroke-width="1.6" stroke-linecap="round" fill="none"/>
            </g>
            <!-- Front leg -->
            <g class="emu-leg-front">
              <path class="emu-accent-stroke" d="M22 25 L19 33 L16 33"
                    stroke-width="1.6" stroke-linecap="round" fill="none"/>
            </g>
          </svg>
        </span>
    `;

    return wrapper;
}

module.exports = { createEmuRunner };
