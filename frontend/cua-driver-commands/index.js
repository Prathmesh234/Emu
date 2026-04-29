// frontend/cua-driver-commands/index.js
//
// Register IPC handlers for emu-cua-driver MCP tools.
// Each handler thin-wraps emuCuaDriverProcess.callTool() and maps
// the MCP result to a format the frontend understands.

function registerAll(ipcMain, deps) {
    const { callTool } = deps;

    // Helper: wrap a tool name and return IPC handler
    const wrap = (toolName) => async (_event, args) => {
        try {
            const result = await callTool(toolName, args);
            return { success: !result?.isError, output: _summarize(result), base64: _extractBase64(result) };
        } catch (err) {
            console.error(`[emu-cua-driver IPC] ${toolName} error:`, err.message);
            return { success: false, error: err.message };
        }
    };

    // Register all emu-cua-driver IPC channels
    ipcMain.handle('emu-cua:screenshot',       wrap('screenshot'));
    ipcMain.handle('emu-cua:click',            wrap('click'));
    ipcMain.handle('emu-cua:right-click',      wrap('right_click'));
    ipcMain.handle('emu-cua:double-click',     wrap('double_click'));
    ipcMain.handle('emu-cua:scroll',           wrap('scroll'));
    ipcMain.handle('emu-cua:type',             wrap('type_text'));
    ipcMain.handle('emu-cua:hotkey',           wrap('hotkey'));
    ipcMain.handle('emu-cua:list-apps',        wrap('list_apps'));
    ipcMain.handle('emu-cua:launch-app',       wrap('launch_app'));
    ipcMain.handle('emu-cua:get-window-state', wrap('get_window_state'));

    console.log('[emu-cua-driver] IPC handlers registered');
}

/**
 * Extract text content from MCP CallTool.Result.
 * MCP result shape: { content: [{type: 'text'|'image', text?: string, data?: bytes}], isError, ... }
 */
function _summarize(result) {
    if (!result?.content) return null;
    return result.content
        .filter(c => c.type === 'text')
        .map(c => c.text)
        .join('\n');
}

/**
 * Extract base64 image from MCP CallTool.Result (for screenshots).
 * MCP returns PNG as an image content block with base64-encoded data.
 */
function _extractBase64(result) {
    if (!result?.content) return null;
    const imgBlock = result.content.find(c => c.type === 'image');
    return imgBlock?.data ?? null;
}

module.exports = { registerAll };
