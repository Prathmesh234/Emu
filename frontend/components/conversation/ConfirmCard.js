// components/conversation/ConfirmCard.js — Details card for confirmations
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/frames/frames-b.jsx > F_Confirm
//
// A quiet bordered card that lists key/value details before the user
// confirms an action. Used wherever the agent pauses for approval:
// shell_exec, payments, any structured "here's what I'll do" preview.
//
// Usage:
//   const card = ConfirmCard([
//     ['Action', 'Shell command'],
//     ['Command', 'rm -rf /tmp/cache'],
//   ]);
//   container.appendChild(card.element);

function ConfirmCard(rows) {
    const wrap = document.createElement('div');
    wrap.className = 'confirm-card';

    rows.forEach(([key, value]) => {
        const row = document.createElement('div');
        row.className = 'confirm-card-row';

        const k = document.createElement('span');
        k.className = 'confirm-card-key';
        k.textContent = key;

        const v = document.createElement('span');
        v.className = 'confirm-card-val';
        v.textContent = value;

        row.appendChild(k);
        row.appendChild(v);
        wrap.appendChild(row);
    });

    return { element: wrap };
}

module.exports = { ConfirmCard };
