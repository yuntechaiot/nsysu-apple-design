/* Navigation disclosure only. Existing links and form actions remain native. */
(function () {
  'use strict';
  const button = document.getElementById('nav-toggle');
  const nav = document.getElementById('main-navigation');
  if (!button || !nav) return;
  const desktop = window.matchMedia('(min-width: 48rem)');
  const close = () => button.setAttribute('aria-expanded', 'false');
  button.hidden = false;
  document.documentElement.classList.add('mobile-ui-ready');
  button.addEventListener('click', () => button.setAttribute('aria-expanded', String(button.getAttribute('aria-expanded') !== 'true')));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') {
      close();
      button.focus();
    }
  });
  nav.addEventListener('click', event => {
    if (!desktop.matches && event.target.closest('a,button')) close();
  });
  document.addEventListener('pointerdown', event => {
    if (!desktop.matches && !event.target.closest('.header-inner')) close();
  }, {passive: true});
  desktop.addEventListener('change', close);
})();
