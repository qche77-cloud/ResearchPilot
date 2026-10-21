/* Presentation only: no research events, network requests or account state. */
'use strict';
(() => {
  const root = document.documentElement;
  const key = 'rp-studio-material';
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const transparency = matchMedia('(prefers-reduced-transparency: reduce)');
  const contrast = matchMedia('(prefers-contrast: more)');
  const forced = matchMedia('(forced-colors: active)');
  const pointer = matchMedia('(hover: hover) and (pointer: fine)');
  const filters = CSS.supports('backdrop-filter', 'blur(1px)') || CSS.supports('-webkit-backdrop-filter', 'blur(1px)');
  let preference = null, active = null, frame = 0, point = null;
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'glass' || saved === 'solid') preference = saved;
  } catch { /* Keep a working in-memory choice when storage is unavailable. */ }

  function clearLight() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (active) {
      active.removeAttribute('data-glass-active');
      active.style.removeProperty('--glass-x');
      active.style.removeProperty('--glass-y');
    }
    active = null;
    point = null;
  }

  function systemSolid() {
    return transparency.matches || contrast.matches || forced.matches || !filters;
  }

  function apply() {
    const constrained = systemSolid();
    root.dataset.material = constrained ? 'solid' : preference || 'glass';
    if (root.dataset.material === 'solid' || motion.matches || !pointer.matches) clearLight();
    const button = document.getElementById('material-toggle');
    if (!button) return;
    const solid = root.dataset.material === 'solid';
    button.setAttribute('aria-pressed', String(solid));
    button.setAttribute('aria-label', constrained ? '实色外观：遵循系统设置或浏览器能力' : solid ? '使用玻璃外观' : '减少透明效果');
    button.title = constrained ? '已根据系统设置或浏览器能力使用实色外观' : solid ? '使用玻璃外观' : '减少透明效果';
    button.querySelector('span').textContent = solid ? '实色' : '玻璃';
    button.disabled = constrained;
  }

  const targets = '.rail-item,.new-button,.button,.topbar-search,.material-toggle,.inspector-tab,.company-tabs button';
  function target(node) { return node instanceof Element ? node.closest(targets) : null; }
  document.addEventListener('pointermove', event => {
    if (event.pointerType === 'touch' || !pointer.matches || motion.matches || root.dataset.material !== 'glass') return;
    const node = target(event.target);
    if (!node || node.disabled) { clearLight(); return; }
    if (active !== node) { clearLight(); active = node; active.dataset.glassActive = 'true'; }
    point = { x: event.clientX, y: event.clientY };
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!active?.isConnected || !point) { clearLight(); return; }
      const rect = active.getBoundingClientRect();
      active.style.setProperty('--glass-x', `${Math.round(point.x - rect.left)}px`);
      active.style.setProperty('--glass-y', `${Math.round(point.y - rect.top)}px`);
    });
  }, { passive: true });
  document.addEventListener('pointerout', event => {
    if (active && !active.contains(event.relatedTarget)) clearLight();
  }, { passive: true });
  document.addEventListener('scroll', clearLight, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearLight(); });
  window.addEventListener('blur', clearLight);
  for (const media of [motion, transparency, contrast, forced, pointer]) media.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      preference = event.newValue === 'solid' || event.newValue === 'glass' ? event.newValue : null;
      apply();
    }
  });
  document.getElementById('material-toggle').addEventListener('click', () => {
    if (systemSolid()) return;
    preference = root.dataset.material === 'glass' ? 'solid' : 'glass';
    try { localStorage.setItem(key, preference); } catch { /* In-memory fallback. */ }
    apply();
  });
  apply();
})();
