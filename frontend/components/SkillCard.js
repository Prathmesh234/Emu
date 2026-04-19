// SkillCard — skill-activated notification in Trace style
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/chrome.jsx > Trace
//
// Design change: replaces the old skill chip (icon + label + name) with
// a single trace line. Same function signature: SkillCard(skillName).

function SkillCard(skillName) {
    const wrap = document.createElement('div');
    wrap.className = 'trace';
    wrap.textContent = `using skill: ${skillName || 'unknown'}`;
    return { element: wrap };
}

module.exports = { SkillCard };
