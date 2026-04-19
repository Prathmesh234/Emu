// PlanCard — plan review block in Trace style
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/frames-b.jsx > F_Confirm
//
// Design change: replaces the old bordered plan card with a trace-styled
// block + new accept/refine buttons. Keeps identical return signature
// { element, acceptBtn, refineBtn } so Chat.js plan_review handler is unchanged.

const { renderMarkdown } = require('./markdown');

function PlanCard(content) {
    const wrap = document.createElement('div');
    wrap.className = 'trace';

    // Plan label
    const label = document.createElement('div');
    label.className = 'trace-reasoning';
    label.textContent = 'Plan';
    label.style.marginBottom = '6px';
    wrap.appendChild(label);

    // Plan content
    const body = document.createElement('div');
    body.className = 'trace-done-text';
    body.style.borderLeft = 'none';
    body.style.paddingLeft = '0';
    renderMarkdown(body, content);
    wrap.appendChild(body);

    // Accept / Refine buttons
    const row = document.createElement('div');
    row.className = 'action-row';
    row.style.marginTop = '12px';

    const acceptBtn = document.createElement('button');
    acceptBtn.className = 'action-btn-primary step-confirm-btn allow';
    acceptBtn.textContent = 'Accept';

    const refineBtn = document.createElement('button');
    refineBtn.className = 'action-btn-ghost';
    refineBtn.textContent = 'refine';

    row.appendChild(acceptBtn);
    row.appendChild(refineBtn);
    wrap.appendChild(row);

    return { element: wrap, acceptBtn, refineBtn };
}

module.exports = { PlanCard };
