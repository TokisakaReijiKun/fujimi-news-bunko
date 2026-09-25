function advanceBrowserSpeechIndex(controller, elapsedSeconds) {
  if (controller.hasBoundaryEvents) return controller.index;
  const textLength = Math.max(1, Number(controller.textLength) || 1);
  const rate = Number(controller.rate) || 1;
  const charactersPerSecond = Number(controller.charactersPerSecond) || 0;
  return Math.min(textLength * 0.98, controller.index + elapsedSeconds * charactersPerSecond * rate);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { advanceBrowserSpeechIndex };
}
