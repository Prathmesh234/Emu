// Coworker actions module - routes to appropriate backend (skylight or cua)

module.exports = {
  skylight: require('./skylight'),
  cuaShell: require('./cua-shell'),
};
