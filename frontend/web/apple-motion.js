/* Presentation only: never intercept clicks, change data, or delay form actions. */
(function () {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const springs = new Map();
  let frame = 0;
  let previous = 0;
  // Response 0.32s, damping ratio 1: critically damped, no decorative bounce.
  const omega = 2 * Math.PI / 0.32;
  function render(now) {
    const dt = Math.min((now - (previous || now)) / 1000, 0.032);
    previous = now;
    for (const [element, state] of springs) {
      if (!element.isConnected || reduced.matches) { element.style.removeProperty('transform'); springs.delete(element); continue; }
      // Analytic critically damped solution stays stable during missed frames.
      const displacement = state.value - state.target;
      const coefficient = state.velocity + omega * displacement;
      const decay = Math.exp(-omega * dt);
      state.value = state.target + (displacement + coefficient * dt) * decay;
      state.velocity = (state.velocity - omega * coefficient * dt) * decay;
      element.style.transform = `scale(${state.value})`;
      if (Math.abs(state.value - state.target) < 0.0001 && Math.abs(state.velocity) < 0.001) {
        if (state.target === 1) element.style.removeProperty('transform');
        else element.style.transform = `scale(${state.target})`;
        springs.delete(element);
      }
    }
    if (springs.size) frame = requestAnimationFrame(render);
    else { frame = 0; previous = 0; }
  }
  function target(element, value) {
    if (!element || element.disabled || reduced.matches) return;
    let state = springs.get(element);
    if (!state) {
      const live = element.style.transform.match(/scale\(([\d.]+)\)/);
      state = {value: live ? Number(live[1]) : 1, velocity: 0, target: value};
      springs.set(element, state);
    }
    state.target = value; // Retarget the current position AND velocity.
    if (!frame) frame = requestAnimationFrame(render);
  }
  const actionable = element => element instanceof Element ? element.closest('.btn,.scale-btn,.dialog-close,.qr-card') : null;
  const pointers = new Map();
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    const element = actionable(event.target);
    if (!element || element.disabled) return;
    pointers.set(event.pointerId, element);
    target(element, .97);
  }, {passive: true});
  function release(event) {
    const element = pointers.get(event.pointerId);
    if (element) { target(element, 1); pointers.delete(event.pointerId); }
  }
  document.addEventListener('pointerup', release, {passive: true});
  document.addEventListener('pointercancel', release, {passive: true});
  document.addEventListener('pointermove', event => {
    const element = pointers.get(event.pointerId);
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const inside = event.clientX >= rect.left - 10 && event.clientX <= rect.right + 10 && event.clientY >= rect.top - 10 && event.clientY <= rect.bottom + 10;
    target(element, inside ? .97 : 1);
  }, {passive: true});
  document.addEventListener('keydown', event => {
    if (!event.repeat && [' ', 'Enter'].includes(event.key)) target(actionable(event.target), .97);
  });
  document.addEventListener('keyup', event => {
    if ([' ', 'Enter'].includes(event.key)) target(actionable(event.target), 1);
  });
  function reset() {
    cancelAnimationFrame(frame); frame = 0; previous = 0; pointers.clear();
    for (const element of springs.keys()) element.style.removeProperty('transform');
    springs.clear();
  }
  window.addEventListener('blur', reset);
  document.addEventListener('visibilitychange', () => { if (document.hidden) reset(); });
  reduced.addEventListener('change', reset);
  // Native buttons still own activation and focus. Expose existing busy feedback to AT.
  new MutationObserver(records => {
    for (const record of records) {
      const button = record.target;
      if (button instanceof HTMLButtonElement) {
        button.setAttribute('aria-busy', String(button.disabled && /正在/.test(button.textContent)));
        if (button.disabled) { button.style.removeProperty('transform'); springs.delete(button); }
      }
    }
  }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['disabled']});
})();
