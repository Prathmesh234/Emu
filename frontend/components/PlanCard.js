// PlanCard component — displays a plan with Accept/Refine buttons

const { renderMarkdown } = require('./markdown');

function PlanCard(content) {
    const card = document.createElement('div');
    card.className = 'step-card plan-card';

    // Header
    const header = document.createElement('div');
    header.className = 'plan-card-header';

    const label = document.createElement('span');
    label.className = 'step-label';
    label.textContent = 'PLAN';
    header.appendChild(label);

    card.appendChild(header);

    // Plan content
    const contentEl = document.createElement('div');
    contentEl.className = 'plan-card-content';
    renderMarkdown(contentEl, content);
    card.appendChild(contentEl);

    // Accept/Refine buttons
    const btnRow = document.createElement('div');
    btnRow.className = 'step-confirm-btns';

    const acceptBtn = document.createElement('button');
    acceptBtn.className = 'step-confirm-btn allow';
    acceptBtn.textContent = 'Accept';

    const refineBtn = document.createElement('button');
    refineBtn.className = 'step-confirm-btn deny';
    refineBtn.textContent = 'Refine';

    btnRow.appendChild(acceptBtn);
    btnRow.appendChild(refineBtn);
    card.appendChild(btnRow);

    return { element: card, acceptBtn, refineBtn };
}

module.exports = { PlanCard };
