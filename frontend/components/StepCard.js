// StepCard component - displays agent step with screenshot, reasoning, and action

const { describeAction, actionIcon } = require('../actions/actionProxy');

function StepCard(data) {
    const card = document.createElement('div');
    card.className = 'step-card';

    // Screenshot thumbnail
    if (data.screenshot) {
        const imgWrap = document.createElement('div');
        imgWrap.className = 'step-screenshot';
        const img = document.createElement('img');
        img.src = `data:image/png;base64,${data.screenshot}`;
        img.alt = 'Screen state';
        img.onclick = () => {
            img.classList.toggle('step-screenshot-expanded');
        };
        img.onerror = () => {
            imgWrap.innerHTML = '<div class="step-screenshot-error">Screenshot failed to load</div>';
        };
        imgWrap.appendChild(img);
        card.appendChild(imgWrap);
    }

    // Reasoning block
    if (data.reasoning) {
        const reasonBlock = document.createElement('div');
        reasonBlock.className = 'step-reasoning';

        const reasonLabel = document.createElement('div');
        reasonLabel.className = 'step-label';
        reasonLabel.textContent = 'Reasoning';
        reasonBlock.appendChild(reasonLabel);

        const reasonText = document.createElement('div');
        reasonText.className = 'step-reasoning-text';
        reasonText.textContent = data.reasoning;
        reasonBlock.appendChild(reasonText);

        card.appendChild(reasonBlock);
    }

    // Action block
    if (data.action && !data.done) {
        const actionBlock = document.createElement('div');
        actionBlock.className = 'step-action';

        const icon = actionIcon(data.action.type);
        const desc = describeAction(data.action);

        const actionLabel = document.createElement('div');
        actionLabel.className = 'step-label';
        actionLabel.textContent = `${icon} Action`;
        actionBlock.appendChild(actionLabel);

        const actionDesc = document.createElement('div');
        actionDesc.className = 'step-action-desc';
        actionDesc.textContent = desc;
        actionBlock.appendChild(actionDesc);

        // Confidence pill
        if (data.confidence != null) {
            const pill = document.createElement('span');
            pill.className = 'step-confidence';
            const pct = Math.round(data.confidence * 100);
            pill.textContent = `${pct}% confident`;
            pill.classList.add(pct >= 80 ? 'high' : pct >= 50 ? 'mid' : 'low');
            actionBlock.appendChild(pill);
        }

        // Status badge (will be updated after execution)
        const badge = document.createElement('div');
        badge.className = 'step-action-status pending';
        badge.textContent = 'Executing...';
        badge.id = 'step-action-status';
        actionBlock.appendChild(badge);

        card.appendChild(actionBlock);
    }

    // Done block
    if (data.done && data.final_message) {
        const doneBlock = document.createElement('div');
        doneBlock.className = 'step-done';
        doneBlock.textContent = data.final_message;
        card.appendChild(doneBlock);
    }

    return { element: card };
}

function DoneCard(message) {
    const card = document.createElement('div');
    card.className = 'step-card';
    const doneBlock = document.createElement('div');
    doneBlock.className = 'step-done';
    doneBlock.textContent = message;
    card.appendChild(doneBlock);
    return { element: card };
}

function ErrorCard(message) {
    const card = document.createElement('div');
    card.className = 'step-card step-error';
    card.textContent = message;
    return { element: card };
}

module.exports = { StepCard, DoneCard, ErrorCard };
