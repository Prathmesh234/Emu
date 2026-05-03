// components/conversation/PastSessionRenderer.js
//
// Renders a read-only view of a past session's messages into a chat
// wrapper element. Extracted verbatim from pages/Chat.js (loadPastSession's
// render block) so the main page module stays focused on live state.
//
// Inputs:
//   chatWrapper     — the .chat-wrapper element to append into (already cleared)
//   messages        — array from /sessions/{id}/messages
//   addMessage(role, content)
//                   — page-level helper that creates user/assistant turn DOM
//                     and returns the mount point (used for the user-message path)
//
// Behavior matches the original implementation exactly: groups consecutive
// non-user messages into assistant "turns", renders skill / file / step /
// done cards as appropriate, and marks all step cards as resolved (no
// blinking caret, no pending badge).

const { TurnEmu } = require('./TurnEmu');
const { StepCard, FileCard, SkillCard } = require('../index');
const { formatToolTrace } = require('../../services/traceLabels');

function renderPastSession(chatWrapper, messages, addMessage) {
    if (!messages || messages.length === 0) return;

    let stepNum = 0;
    let currentAssistantBubble = null;
    let currentStepContainer = null;

    function ensureAssistantBubble() {
        if (!currentAssistantBubble) {
            const turn = TurnEmu('');
            currentAssistantBubble = turn.element;
            currentStepContainer  = turn.body;
            chatWrapper.appendChild(currentAssistantBubble);
        }
        return currentStepContainer;
    }

    function flushAssistantBubble() {
        currentAssistantBubble = null;
        currentStepContainer = null;
    }

    messages.forEach(msg => {
        const role = msg.role;
        const content = msg.content || '';
        const meta = msg.metadata || {};

        // Skip screenshot entries
        if (content === '<screenshot>') return;

        if (role === 'user') {
            flushAssistantBubble();
            addMessage('user', content);
            return;
        }

        if (role === 'assistant') {
            // Done message — render as DoneCard or plain text
            const finalMsg = meta.final_message || content.replace(/^DONE\s*—?\s*/, '');
            if (finalMsg) {
                const container = ensureAssistantBubble();
                stepNum++;
                const doneCard = StepCard({
                    action: { type: 'done' },
                    done: true,
                    final_message: finalMsg,
                    confidence: 1.0,
                }, stepNum);
                container.appendChild(doneCard.element);
            }
            flushAssistantBubble();
            return;
        }

        if (role === 'tool') {
            const container = ensureAssistantBubble();
            stepNum++;

            const toolName = meta.tool_name || '';

            // Render skill cards for use_skill
            if (toolName === 'use_skill') {
                let skillName = 'Unknown';
                try {
                    const parsed = JSON.parse(meta.args || '{}');
                    skillName = parsed.skill_name || 'Unknown';
                } catch (_) {}
                const skillCard = SkillCard(skillName);
                container.appendChild(skillCard.element);
                return;
            }

            // Render file cards for write_session_file
            if (toolName === 'write_session_file') {
                let filename = 'file';
                try {
                    const parsed = JSON.parse(meta.args || '{}');
                    filename = parsed.filename || 'file';
                } catch (_) {}
                const fileCard = FileCard(filename, 'created', null);
                container.appendChild(fileCard.element);
                return;
            }

            // Generic tool trace (replaces the old white step-card DOM).
            // Renders as a single resolved trace line — no bordered card,
            // no completion badge. Matches the Finished-frame aesthetic.
            const toolWrap = document.createElement('div');
            toolWrap.className = 'trace resolved';
            toolWrap.textContent = formatToolTrace(toolName || 'tool', meta.args || '{}');
            container.appendChild(toolWrap);
            return;
        }

        if (role === 'action') {
            const container = ensureAssistantBubble();
            stepNum++;

            const actionType = meta.action_type || content.split(/\s+/)[0] || 'unknown';
            const confidence = meta.confidence != null ? meta.confidence : null;
            const reasoning = meta.reasoning || '';
            const actionPayload = meta.action || { type: actionType };

            const stepCard = StepCard({
                action: actionPayload,
                done: false,
                confidence: confidence,
                reasoning_content: reasoning,
            }, stepNum);

            // Past sessions are fully resolved: hide the blinking caret
            // and drop the pending "…" badge. The trace text alone
            // communicates what the agent did.
            stepCard.element.classList.add('resolved');
            const badge = stepCard.element.querySelector('.step-action-status');
            if (badge) badge.remove();

            container.appendChild(stepCard.element);
            return;
        }
    });
}

module.exports = { renderPastSession };
