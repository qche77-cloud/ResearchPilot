/* Small visual behaviours, independent of research and paid tool execution. */
'use strict';
window.StudioInteractions = (() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const hoverDevice = matchMedia('(hover: hover)');
  const tooltip = document.createElement('div');
  tooltip.id = 'studio-tooltip';
  tooltip.className = 'studio-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  tooltip.hidden = true;
  document.body.append(tooltip);
  let owner = null, showTimer, hideTimer, evidenceProvider = () => null;
  let focusPriority = false, pointerX = null, pointerY = null;
  const running = new Set();

  function animate(node, frames, options = {}) {
    if (!node || reduced.matches) return;
    const animation = node.animate(frames, {
      duration: 220, easing: 'cubic-bezier(.22,1,.36,1)', ...options,
    });
    running.add(animation);
    animation.finished.catch(() => {}).finally(() => running.delete(animation));
  }

  function hideTip() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    if (owner) {
      const ids = (owner.getAttribute('aria-describedby') || '').split(' ').filter(id => id && id !== tooltip.id);
      if (ids.length) owner.setAttribute('aria-describedby', ids.join(' '));
      else owner.removeAttribute('aria-describedby');
    }
    owner = null;
    tooltip.hidden = true;
    tooltip.replaceChildren();
  }

  function positionTip() {
    if (!owner?.isConnected) { hideTip(); return; }
    const anchor = owner.getBoundingClientRect(), box = tooltip.getBoundingClientRect();
    const gap = 10, edge = 12;
    let left = anchor.left + (anchor.width - box.width) / 2;
    let top = anchor.top - box.height - gap;
    if (owner.closest('.rail')) { left = anchor.right + gap; top = anchor.top; }
    if (top < edge) top = anchor.bottom + gap;
    left = Math.max(edge, Math.min(innerWidth - box.width - edge, left));
    top = Math.max(edge, Math.min(innerHeight - box.height - edge, top));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function showTip(button) {
    if (!button.isConnected || button.disabled || document.querySelector('dialog[open]')) return;
    hideTip();
    owner = button;
    const card = evidenceProvider(button);
    const title = document.createElement('strong');
    title.textContent = card ? `[${button.dataset.cite}] ${card.title || '引用来源'}` :
      button.dataset.tip || button.getAttribute('aria-label') || button.querySelector('b')?.textContent || '';
    tooltip.classList.toggle('evidence-preview', Boolean(card));
    tooltip.append(title);
    if (card) {
      const meta = document.createElement('span');
      meta.className = 'tooltip-meta';
      meta.textContent = `来源日期 ${card.date || '未知'} · 此回答 / 报告版本的证据`;
      const quote = document.createElement('p');
      const excerpt = card.excerpts?.[0] || card.text;
      quote.textContent = excerpt ? String(excerpt).slice(0, 180) : '未保存可核对的采集文本。';
      const hint = document.createElement('span');
      hint.className = 'tooltip-hint';
      hint.textContent = '点击查看完整原文；结论是否成立仍需结合资料判断';
      tooltip.append(meta, quote, hint);
    }
    if (!title.textContent) { hideTip(); return; }
    const ids = (button.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
    button.setAttribute('aria-describedby', [...ids, tooltip.id].join(' '));
    tooltip.hidden = false;
    positionTip();
    animate(tooltip, [{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 150 });
  }

  function candidate(target) {
    const button = target.closest?.('.rail-item,.icon-button,.citation,.history-item,.chart-point');
    if (!button || button.disabled) return null;
    // Replace browser-native tips only where our accessible tooltip is available.
    if (button.hasAttribute('title')) {
      button.dataset.tip = button.getAttribute('title');
      button.removeAttribute('title');
    }
    return button;
  }

  function schedule(button) {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    if (owner === button && !tooltip.hidden) return;
    hideTip();
    showTimer = setTimeout(() => showTip(button), 380);
  }
  document.addEventListener('pointerover', event => {
    if (!hoverDevice.matches || event.pointerType === 'touch' || focusPriority) return;
    const button = candidate(event.target);
    if (button) schedule(button);
  });
  document.addEventListener('pointerout', event => {
    if (focusPriority) return;
    const button = candidate(event.target);
    if (!button || button.contains(event.relatedTarget)) return;
    clearTimeout(showTimer);
    hideTimer = setTimeout(hideTip, 160);
  });
  tooltip.addEventListener('pointerenter', () => clearTimeout(hideTimer));
  tooltip.addEventListener('pointerleave', hideTip);
  document.addEventListener('pointermove', event => {
    const moved = pointerX === null || Math.abs(event.clientX - pointerX) + Math.abs(event.clientY - pointerY) > 2;
    pointerX = event.clientX; pointerY = event.clientY;
    if (!moved || !focusPriority || !hoverDevice.matches || event.pointerType === 'touch') return;
    focusPriority = false;
    const button = candidate(event.target);
    if (button) schedule(button);
    else hideTip();
  });
  document.addEventListener('focusin', event => {
    const button = candidate(event.target);
    if (button) { focusPriority = true; schedule(button); }
  });
  document.addEventListener('focusout', () => { focusPriority = false; hideTip(); });
  document.addEventListener('pointerdown', () => { focusPriority = false; hideTip(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTip(); });
  document.addEventListener('scroll', hideTip, true);
  window.addEventListener('resize', hideTip);
  reduced.addEventListener('change', () => {
    if (reduced.matches) { for (const animation of running) animation.cancel(); running.clear(); }
  });

  function transition(reason) {
    if (reason === 'page') {
      animate(document.querySelector('#main > :first-child'), [
        { opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' },
      ], { duration: 260 });
      document.querySelectorAll('.home .launch,.home .templates,.stock-card').forEach((node, index) => {
        animate(node, [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }],
          { duration: 240, delay: Math.min(index, 4) * 35 });
      });
    } else if (reason === 'panel') {
      animate(document.querySelector('.inspector-content'), [
        { opacity: .3, transform: 'translateX(7px)' }, { opacity: 1, transform: 'translateX(0)' },
      ], { duration: 180 });
    } else if (reason === 'version') {
      animate(document.querySelector('.paper'), [{ opacity: .35 }, { opacity: 1 }], { duration: 200 });
    }
  }

  function spotlight(node) {
    animate(node, [
      { boxShadow: '0 0 0 0 rgba(99,88,218,0)' },
      { boxShadow: '0 0 0 5px rgba(99,88,218,.13)', offset: .3 },
      { boxShadow: '0 0 0 2px rgba(99,88,218,.03)' },
    ], { duration: 650 });
  }

  return {
    beforeRender: hideTip, transition, spotlight,
    setEvidenceProvider: provider => { evidenceProvider = provider; },
    busy: value => {
      document.querySelector('#studio').classList.toggle('is-pending', value);
      document.querySelector('#main').setAttribute('aria-busy', String(value));
    },
    openPalette: () => animate(document.querySelector('#palette'), [
      { opacity: 0, transform: 'translateY(-8px) scale(.985)' }, { opacity: 1, transform: 'translateY(0) scale(1)' },
    ], { duration: 200 }),
    showLineage: () => animate(document.querySelector('.lineage'), [
      { opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' },
    ]),
    activeCount: () => running.size,
  };
})();
