// Tooltip component - wraps an element with a tooltip

function Tooltip(element, text = '') {
    const wrapper = document.createElement('div');
    wrapper.className = 'tooltip-wrapper';

    const tooltipEl = document.createElement('div');
    tooltipEl.className = 'tooltip';
    tooltipEl.textContent = text;

    wrapper.appendChild(element);
    wrapper.appendChild(tooltipEl);

    // Show/hide based on disabled state or hover
    const updateVisibility = () => {
        if (element.disabled && text) {
            wrapper.classList.add('tooltip-enabled');
        } else {
            wrapper.classList.remove('tooltip-enabled');
        }
    };

    // Observe disabled attribute changes
    const observer = new MutationObserver(updateVisibility);
    observer.observe(element, { attributes: true, attributeFilter: ['disabled'] });

    updateVisibility();

    return {
        element: wrapper,
        setText: (newText) => {
            text = newText;
            tooltipEl.textContent = newText;
            updateVisibility();
        },
        show: () => wrapper.classList.add('tooltip-enabled'),
        hide: () => wrapper.classList.remove('tooltip-enabled'),
        destroy: () => observer.disconnect()
    };
}

module.exports = { Tooltip };
