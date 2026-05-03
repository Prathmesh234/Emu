// services/traceLabels.js — demo-friendly labels for actions and tools.

function parseArgs(args) {
    if (!args) return {};
    if (typeof args === 'object') return args;
    try { return JSON.parse(args); } catch (_) { return {}; }
}

function truncate(value, max = 32) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

function titleCase(value) {
    return String(value || '')
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, (m) => m.toUpperCase());
}

function formatKeyCombo(args) {
    const keys = Array.isArray(args.keys)
        ? args.keys
        : [...(args.modifiers || []), args.key].filter(Boolean);
    if (!keys.length) return '';
    return keys.map((key) => {
        const value = String(key).toLowerCase();
        if (value === 'cmd' || value === 'command') return '⌘';
        if (value === 'shift') return '⇧';
        if (value === 'option' || value === 'alt') return '⌥';
        if (value === 'ctrl' || value === 'control') return '⌃';
        if (value === 'enter' || value === 'return') return 'Return';
        if (value === 'escape' || value === 'esc') return 'Esc';
        if (value === 'space') return 'Space';
        return String(key).length === 1 ? String(key).toUpperCase() : titleCase(key);
    }).join('');
}

function appName(args) {
    return truncate(args.app_name || args.name || args.bundle_id || '');
}

function formatActionTrace(action = {}) {
    switch (action.type || '') {
        case 'screenshot':
            return 'Look';
        case 'left_click':
        case 'navigate_and_click':
            return 'Click';
        case 'right_click':
        case 'navigate_and_right_click':
            return 'Right click';
        case 'double_click':
            return 'Double click';
        case 'triple_click':
        case 'navigate_and_triple_click':
            return 'Select text';
        case 'mouse_move':
            return 'Move cursor';
        case 'relative_mouse_move':
            return 'Nudge cursor';
        case 'drag':
        case 'relative_drag':
            return 'Drag';
        case 'scroll':
        case 'horizontal_scroll':
            return action.direction ? `Scroll ${action.direction}` : 'Scroll';
        case 'type_text':
            return action.text ? `Type "${truncate(action.text)}"` : 'Type text';
        case 'key_press': {
            const combo = formatKeyCombo(action);
            return combo ? `Press ${combo}` : 'Press key';
        }
        case 'wait':
            return 'Wait';
        case 'shell_exec':
            return 'Run command';
        case 'memory_read':
            return 'Read memory';
        case 'done':
            return 'Done';
        default:
            return action.type ? titleCase(action.type) : 'Action';
    }
}

function formatToolTrace(toolName, rawArgs, { ok = true } = {}) {
    const args = parseArgs(rawArgs);
    const tool = String(toolName || '').trim();
    let label;

    switch (tool) {
        case 'read_plan': label = 'Read plan'; break;
        case 'update_plan': label = 'Update plan'; break;
        case 'read_memory': label = 'Read memory'; break;
        case 'write_session_file': label = args.filename ? `Write ${truncate(args.filename)}` : 'Write file'; break;
        case 'read_session_file': label = args.filename ? `Read ${truncate(args.filename)}` : 'Read file'; break;
        case 'list_session_files': label = 'List files'; break;
        case 'use_skill': label = args.skill_name ? `Use ${truncate(args.skill_name)}` : 'Use skill'; break;
        case 'create_skill': label = args.name ? `Create ${truncate(args.name)}` : 'Create skill'; break;
        case 'compact_context': label = 'Compact context'; break;
        case 'invoke_hermes': label = 'Launch Hermes'; break;
        case 'check_hermes': label = 'Check Hermes'; break;
        case 'cancel_hermes': label = 'Cancel Hermes'; break;
        case 'list_hermes_jobs': label = 'List Hermes jobs'; break;
        case 'shell_exec': label = 'Run command'; break;
        case 'raise_app':
        case 'bring_app_frontmost':
        case 'cua_launch_app': {
            const app = appName(args);
            label = app ? `Open ${app}` : 'Open app';
            break;
        }
        case 'list_running_apps':
        case 'cua_list_apps': label = 'Find apps'; break;
        case 'cua_list_windows': label = 'Find windows'; break;
        case 'cua_get_window_state': label = 'Inspect window'; break;
        case 'cua_screenshot': label = 'Capture window'; break;
        case 'cua_click': label = 'Click'; break;
        case 'cua_right_click': label = 'Right click'; break;
        case 'cua_double_click': label = 'Double click'; break;
        case 'cua_scroll': label = args.direction ? `Scroll ${args.direction}` : 'Scroll'; break;
        case 'cua_type_text':
        case 'cua_type_text_chars': label = args.text ? `Type "${truncate(args.text)}"` : 'Type text'; break;
        case 'cua_set_value': label = 'Set value'; break;
        case 'cua_press_key':
        case 'cua_hotkey': {
            const combo = formatKeyCombo(args);
            label = combo ? `Press ${combo}` : 'Press key';
            break;
        }
        case 'cua_move_cursor': label = 'Move cursor'; break;
        case 'cua_drag': label = 'Drag'; break;
        case 'cua_check_permissions': label = 'Check permissions'; break;
        case 'cua_get_config': label = 'Read driver config'; break;
        case 'cua_get_screen_size': label = 'Read screen size'; break;
        case 'cua_get_cursor_position':
        case 'cua_get_agent_cursor_state': label = 'Check cursor'; break;
        case 'cua_set_agent_cursor_enabled':
        case 'cua_set_agent_cursor_motion':
        case 'cua_set_agent_cursor_style': label = 'Update cursor'; break;
        default: label = tool ? titleCase(tool.replace(/^cua_/, '')) : 'Use tool';
    }

    return ok === false ? `${label} failed` : label;
}

function isDriverTool(toolName) {
    const tool = String(toolName || '');
    return tool === 'list_running_apps' || tool.startsWith('cua_');
}

function hasDedicatedToolEvent(toolName) {
    const tool = String(toolName || '');
    return (
        isDriverTool(tool) ||
        tool === 'raise_app' ||
        tool === 'bring_app_frontmost' ||
        tool === 'shell_exec' ||
        tool === 'use_skill' ||
        tool === 'create_skill' ||
        tool === 'write_session_file' ||
        tool === 'invoke_hermes' ||
        tool === 'cancel_hermes'
    );
}

module.exports = {
    formatActionTrace,
    formatToolTrace,
    hasDedicatedToolEvent,
    isDriverTool,
};
