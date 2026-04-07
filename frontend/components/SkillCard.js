// SkillCard component — compact notification when a skill is used

function SkillCard(skillName) {
    const card = document.createElement('div');
    card.className = 'step-card skill-card';

    const icon = document.createElement('span');
    icon.className = 'skill-card-icon';
    icon.textContent = '\u26A1'; // ⚡

    const info = document.createElement('div');
    info.className = 'skill-card-info';

    const label = document.createElement('span');
    label.className = 'skill-card-label';
    label.textContent = 'Skill activated';
    info.appendChild(label);

    const name = document.createElement('span');
    name.className = 'skill-card-name';
    name.textContent = skillName || 'Unknown skill';
    info.appendChild(name);

    card.appendChild(icon);
    card.appendChild(info);

    return { element: card };
}

module.exports = { SkillCard };
