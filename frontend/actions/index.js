// Frontend actions — barrel export
// Each action exports: { actionFn, register }
// register(ipcMain, ...) is called from main.js to set up the IPC handler.

const screenshot    = require('./screenshot');
const fullCapture   = require('./fullCapture');
const navigate      = require('./navigate');
const leftClick     = require('./leftClick');
const rightClick    = require('./rightClick');
const leftClickOpen = require('./leftClickOpen');
const doubleClick   = require('./doubleClick');
const tripleClick   = require('./tripleClick');
const drag          = require('./drag');
const relativeMove  = require('./relativeMove');
const relativeDrag  = require('./relativeDrag');
const scroll        = require('./scroll');
const horizontalScroll = require('./horizontalScroll');
const getMousePosition = require('./getMousePosition');
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
    doubleClick:        doubleClick.doubleClick,
    tripleClick:        tripleClick.tripleClick,
    drag:               drag.drag,
    relativeMove:       relativeMove.relativeMove,
    relativeDrag:       relativeDrag.relativeDrag,
    scroll:             scroll.scroll,
    horizontalScroll:   horizontalScroll.horizontalScroll,
    getMousePosition:   getMousePosition.getMousePosition,
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
        doubleClick.register(ipcMain);
        tripleClick.register(ipcMain);
        drag.register(ipcMain);
        relativeMove.register(ipcMain);
        relativeDrag.register(ipcMain);
        rightClick.register(ipcMain, deps.BACKEND_URL);
        scroll.register(ipcMain, deps.BACKEND_URL);
        horizontalScroll.register(ipcMain);
        getMousePosition.register(ipcMain);
        keyboard.register(ipcMain);
        exec.register(ipcMain);
        window_.register(ipcMain, deps.getMainWindow);
    }
};

