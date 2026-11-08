/* Standalone mobile layouts; retain the native article and EPUB controllers. */
(() => {
  const oldStyle = document.querySelector('link[href="/real-preview.css"]');
  if (oldStyle) oldStyle.href = '/native-reader.css';
  const script = document.createElement('script');
  script.src = '/next-ui.js';
  document.body.append(script);
})();
