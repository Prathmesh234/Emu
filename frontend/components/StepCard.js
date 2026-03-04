// StepCard component - displays agent step with step number, reasoning, and action

const { describeAction, actionIcon } = require('../actions/actionProxy');

function StepCard(data, stepNum) {
    const card = document.createElement('div');
    card.className = 'step-card';

    // Step header with number
    const header = document.createElement('div');
    header.className = 'step-header';

    const numBadge = document.createElement('span');
    numBadge.className = 'step-number';
    numBadge.textContent = stepNum || '?';
    header.appendChild(numBadge);

    const headerLabel = document.createElement('span');
    headerLabel.textContent = data.done ? 'Complete' : `Step ${stepNum || '?'}`;
    header.appendChild(headerLabel);

    // Confidence pill (inline in header)
    if (data.confidence != null && !data.done) {
        const pill = document.createElement('span');
        pill.className = 'step-confidence';
        const pct = Math.round(data.confidence * 100);
        pill.textContent = `${pct}%`;
        pill.classList.add(pct >= 80 ? 'high' : pct >= 50 ? 'mid' : 'low');
        header.appendChild(pill);
    }

    card.appendChild(header);

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

    // Reasoning block — prefer reasoning_content (model's thinking), fall back to reasoning (JSON)
    const reasoningText = data.reasoning_content || '';
    if (reasoningText) {
        const reasonBlock = document.createElement('div');
        reasonBlock.className = 'step-reasoning';

        const reasonLabel = document.createElement('div');
        reasonLabel.className = 'step-label';
        reasonLabel.textContent = 'Thinking';
        reasonBlock.appendChild(reasonLabel);

        const reasonEl = document.createElement('div');
        reasonEl.className = 'step-reasoning-text';
        // Truncate long reasoning with expand toggle
        const MAX_CHARS = 300;
        if (reasoningText.length > MAX_CHARS) {
            reasonEl.textContent = reasoningText.slice(0, MAX_CHARS) + '…';
            reasonEl.style.cursor = 'pointer';
            let expanded = false;
            reasonEl.onclick = () => {
                expanded = !expanded;
                reasonEl.textContent = expanded ? reasoningText : reasoningText.slice(0, MAX_CHARS) + '…';
            };
        } else {
            reasonEl.textContent = reasoningText;
        }
        reasonBlock.appendChild(reasonEl);

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

        // Status badge (will be updated after execution)
        const badge = document.createElement('div');
        badge.className = 'step-action-status pending';
        badge.textContent = 'Executing…';
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
