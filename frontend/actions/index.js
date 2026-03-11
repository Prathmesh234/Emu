// Frontend actions — barrel export
// Each action exports: { actionFn, register }
// register(ipcMain, ...) is called from main.js to set up the IPC handler.

const screenshot    = require('./screenshot');
const fullCapture   = require('./fullCapture');
const navigate      = require('./navigate');
const leftClick     = require('./leftClick');
const rightClick    = require('./rightClick');
const leftClickOpen = require('./leftClickOpen');
const tripleClick   = require('./tripleClick');
const drag          = require('./drag');
const scroll        = require('./scroll');
const keyboard      = require('./keyboard');
const exec          = require('./exec');
const window_       = require('./window');

module.exports = {
    // Renderer-side action functions
    captureScreenshot:  screenshot.captureScreenshot,
    fullCapture:        fullCapture.fullCapture,
    navigateMouse:      navigate.navigateMouse,
    leftClick:          leftClick.leftClick,
    rightClick:         rightClick.rightClick,
    leftClickOpen:      leftClickOpen.leftClickOpen,
    tripleClick:        tripleClick.tripleClick,
    drag:               drag.drag,
    scroll:             scroll.scroll,
    keyPress:           keyboard.keyPress,
    typeText:           keyboard.typeText,
    shellExec:          exec.shellExec,

    // IPC registration functions (called from main.js)
    registerAll(ipcMain, deps) {
        screenshot.register(ipcMain, deps);
        fullCapture.register(ipcMain, deps);
        navigate.register(ipcMain, deps.BACKEND_URL);
        leftClick.register(ipcMain, deps.BACKEND_URL);
        leftClickOpen.register(ipcMain, deps.BACKEND_URL);
        tripleClick.register(ipcMain);
        drag.register(ipcMain);
        rightClick.register(ipcMain, deps.BACKEND_URL);
        scroll.register(ipcMain, deps.BACKEND_URL);
        keyboard.register(ipcMain);
        exec.register(ipcMain);
        window_.register(ipcMain, deps.getMainWindow);
    }
};

