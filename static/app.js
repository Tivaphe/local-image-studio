/* ===== Local Image Studio — JS partagé ===== */

// Raccourcis utilitaires (globaux pour tous les scripts de page)
window.$ = (s, el = document) => el.querySelector(s);
window.$$ = (s, el = document) => [...el.querySelectorAll(s)];

// Badge d'état du moteur (présent sur toutes les pages via la topbar)
async function refreshEngineBadge() {
  const badge = $('#engine-badge');
  if (!badge) return;
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    if (j.engine_ready) {
      badge.textContent = 'moteur ✓';
      badge.className = 'badge badge-ok';
    } else {
      badge.textContent = 'moteur absent';
      badge.className = 'badge badge-warn';
    }
  } catch (e) {}
}
refreshEngineBadge();

// Notification toast légère (utilisée pour Ctrl+V, File d'attente, Brouillon, etc.)
let _toastTimer = null;
window.showToast = function showToast(message, actionLabel = null, actionCb = null, durationMs = 4200) {
  let box = $('#lis-toast');
  if (!box) {
    box = document.createElement('div');
    box.id = 'lis-toast';
    box.className = 'lis-toast';
    document.body.appendChild(box);
  }
  box.innerHTML = `<span class="lis-toast-msg"></span>`;
  box.querySelector('.lis-toast-msg').textContent = message;
  if (actionLabel && typeof actionCb === 'function') {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn small lis-toast-btn';
    btn.textContent = actionLabel;
    btn.addEventListener('click', () => {
      box.classList.remove('show');
      actionCb();
    });
    box.appendChild(btn);
  }
  box.classList.add('show');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    box.classList.remove('show');
  }, durationMs);
};

// ===========================================================================
//  Lightbox plein écran avec :
//  - Préchargement & navigation instantanée (0 reload)
//  - Flèches ← / → (ou ↑ / ↓) et Molette souris : défilement sans rechargement
//  - Espace / bouton « Avant / Après » / clic sur l'image :
//    bascule instantanée entre l'image source (Avant) et l'image modifiée (Après)
//  - Zoom (100 % à 800 %) & Déplacement (Pan) 100 % synchronisés entre toutes
//    les images du lot et la comparaison Avant / Après
// ===========================================================================
const _lbState = {
  items: [],
  activeIndex: 0,
  lastResultIndex: 0,
  prevViewedIndex: 0,
  stageImgs: [],
  thumbBtns: [],
  wheelAccum: 0,
  lastWheelStepAt: 0,
  zoom: 1,
  panX: 0,
  panY: 0,
  pointerSession: null,
};

function _normalizeLightboxArgs(first, second, third) {
  let rawItems = [];
  let startIndex = 0;
  let opts = {};

  if (Array.isArray(first)) {
    rawItems = first;
    if (typeof second === 'number') {
      startIndex = second;
      opts = third || {};
    } else if (second && typeof second === 'object') {
      opts = second;
      startIndex = typeof opts.startIndex === 'number' ? opts.startIndex : 0;
    }
  } else if (typeof first === 'string') {
    if (Array.isArray(second)) {
      rawItems = second;
      opts = third || {};
      const found = rawItems.findIndex(it => (typeof it === 'string' ? it : it.src) === first);
      startIndex = found >= 0 ? found : (opts.startIndex || 0);
    } else if (second && typeof second === 'object' && Array.isArray(second.items)) {
      rawItems = second.items;
      opts = second;
      const found = rawItems.findIndex(it => (typeof it === 'string' ? it : it.src) === first);
      startIndex = typeof second.startIndex === 'number'
        ? second.startIndex
        : (found >= 0 ? found : 0);
    } else {
      rawItems = [{ src: first, downloadUrl: first.split('?')[0], label: '', role: 'result' }];
      startIndex = 0;
    }
  }

  const items = rawItems.filter(Boolean).map((it, idx) => {
    if (typeof it === 'string') {
      return {
        src: it,
        downloadUrl: it.split('?')[0],
        label: rawItems.length > 1 ? `Image ${idx + 1}` : '',
        role: 'result',
        badge: rawItems.length > 1 ? `IMAGE ${idx + 1}/${rawItems.length}` : '',
      };
    }
    const src = it.src || it.url || '';
    const role = it.role || 'result';
    let badge = it.badge;
    if (!badge) {
      if (role === 'source') badge = 'AVANT (SOURCE)';
      else if (role === 'ref') badge = `RÉFÉRENCE #${idx + 1}`;
      else badge = rawItems.length > 1 ? `IMAGE ${idx + 1}/${rawItems.length}` : '';
    }
    return {
      src,
      downloadUrl: it.downloadUrl || src.split('?')[0],
      label: it.label || '',
      role,
      badge,
    };
  }).filter(it => Boolean(it.src));

  return { items, startIndex, opts };
}

function _applyLightboxTransform() {
  const { zoom, panX, panY, stageImgs } = _lbState;
  const transform = zoom <= 1.001
    ? 'translate3d(0px, 0px, 0px) scale(1)'
    : `translate3d(${Math.round(panX)}px, ${Math.round(panY)}px, 0px) scale(${zoom.toFixed(3)})`;
  stageImgs.forEach(img => {
    img.style.transform = transform;
  });
  const stage = $('#lb-stage');
  if (stage) {
    stage.classList.toggle('is-zoomed', zoom > 1.01);
  }
  const resetBtn = $('#lb-zoom-reset');
  if (resetBtn) {
    resetBtn.textContent = `${Math.round(zoom * 100)}%`;
    resetBtn.classList.toggle('active-zoom', zoom > 1.01);
  }
}

function setLightboxZoom(nextZoom, clientX = null, clientY = null) {
  const prevZoom = _lbState.zoom || 1;
  const clamped = Math.max(1, Math.min(8, Number(nextZoom) || 1));
  if (clamped <= 1.01) {
    _lbState.zoom = 1;
    _lbState.panX = 0;
    _lbState.panY = 0;
    _applyLightboxTransform();
    return;
  }

  const stage = $('#lb-stage');
  if (stage && clientX !== null && clientY !== null) {
    const rect = stage.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const ox = clientX - cx;
    const oy = clientY - cy;
    const ratio = clamped / prevZoom;
    _lbState.panX = ox - ratio * (ox - _lbState.panX);
    _lbState.panY = oy - ratio * (oy - _lbState.panY);
  } else {
    const ratio = clamped / prevZoom;
    _lbState.panX *= ratio;
    _lbState.panY *= ratio;
  }

  _lbState.zoom = clamped;
  _applyLightboxTransform();
}

function _ensureLightboxDom() {
  let lb = $('#lightbox');
  if (lb) return lb;

  lb = document.createElement('div');
  lb.id = 'lightbox';
  lb.className = 'lightbox';
  lb.setAttribute('role', 'dialog');
  lb.setAttribute('aria-modal', 'true');
  lb.innerHTML = `
    <div class="lb-topbar">
      <div class="lb-info">
        <span class="lb-badge" id="lb-badge" hidden></span>
        <span class="lb-counter" id="lb-counter" hidden></span>
        <span class="lb-label" id="lb-label"></span>
      </div>
      <div class="lb-actions">
        <div class="lb-zoom-controls" title="Zoom & Déplacement synchronisés sur toutes les images (Ctrl+Molette ou Double-clic)">
          <button type="button" class="btn small ghost lb-zbtn" id="lb-zoom-out" title="Dézoomer (-)">🔍−</button>
          <button type="button" class="btn small ghost lb-zbtn" id="lb-zoom-reset" title="Réinitialiser le zoom à 100% (0)">100%</button>
          <button type="button" class="btn small ghost lb-zbtn" id="lb-zoom-in" title="Zoomer (+)">🔍+</button>
          <button type="button" class="btn small ghost lb-zbtn" id="lb-zoom-2x" title="Zoom ×2 synchronisé">×2</button>
          <button type="button" class="btn small ghost lb-zbtn" id="lb-zoom-4x" title="Zoom ×4 synchronisé">×4</button>
        </div>
        <button type="button" class="btn small lb-compare-btn" id="lb-compare-btn" hidden
                title="Basculer instantanément entre l'image source et l'image modifiée (Touche Espace)">
          ⇄ Avant / Après <kbd>Espace</kbd>
        </button>
        <a class="btn small ghost lb-download" id="lb-download" download>⬇ Télécharger</a>
        <button type="button" class="x" id="lb-close" title="Fermer (Échap)">×</button>
      </div>
    </div>

    <div class="lb-stage-wrap" id="lb-stage-wrap">
      <button type="button" class="lb-nav lb-prev" id="lb-prev" title="Image précédente (Flèche gauche / Molette)">‹</button>
      <div class="lb-stage" id="lb-stage"></div>
      <button type="button" class="lb-nav lb-next" id="lb-next" title="Image suivante (Flèche droite / Molette)">›</button>
    </div>

    <div class="lb-bottombar" id="lb-bottombar" hidden>
      <div class="lb-thumbs" id="lb-thumbs"></div>
      <div class="lb-shortcuts">
        <span><kbd>←</kbd> <kbd>→</kbd> / <strong>Molette</strong> : défiler (zoom synchronisé)</span>
        <span id="lb-space-hint" hidden>· <kbd>Espace</kbd> / <strong>clic</strong> : Source ↔ Modifiée</span>
        <span>· <strong>Ctrl+Molette</strong> / <strong>Double-clic</strong> / <kbd>+</kbd><kbd>-</kbd> : zoomer & glisser</span>
        <span>· <kbd>Échap</kbd> : fermer</span>
      </div>
    </div>
  `;

  // Fermeture en cliquant sur le fond ou le bouton ×
  lb.addEventListener('click', e => {
    if (
      e.target === lb ||
      e.target.id === 'lb-stage-wrap' ||
      e.target.id === 'lb-close' ||
      e.target.classList.contains('x')
    ) {
      closeLightbox();
    }
  });

  lb.querySelector('#lb-prev').addEventListener('click', e => {
    e.stopPropagation();
    stepLightbox(-1);
  });
  lb.querySelector('#lb-next').addEventListener('click', e => {
    e.stopPropagation();
    stepLightbox(+1);
  });
  lb.querySelector('#lb-compare-btn').addEventListener('click', e => {
    e.stopPropagation();
    toggleLightboxSourceCompare();
  });

  // Boutons de zoom synchronisé
  lb.querySelector('#lb-zoom-out').addEventListener('click', e => {
    e.stopPropagation();
    setLightboxZoom(_lbState.zoom / 1.35);
  });
  lb.querySelector('#lb-zoom-in').addEventListener('click', e => {
    e.stopPropagation();
    setLightboxZoom(_lbState.zoom * 1.35);
  });
  lb.querySelector('#lb-zoom-reset').addEventListener('click', e => {
    e.stopPropagation();
    setLightboxZoom(1);
  });
  lb.querySelector('#lb-zoom-2x').addEventListener('click', e => {
    e.stopPropagation();
    setLightboxZoom(Math.abs(_lbState.zoom - 2) < 0.05 ? 1 : 2);
  });
  lb.querySelector('#lb-zoom-4x').addEventListener('click', e => {
    e.stopPropagation();
    setLightboxZoom(Math.abs(_lbState.zoom - 4) < 0.05 ? 1 : 4);
  });

  const stage = lb.querySelector('#lb-stage');

  // Double-clic : bascule zoom 100% <-> 250% centré sur le point cliqué
  stage.addEventListener('dblclick', e => {
    e.stopPropagation();
    e.preventDefault();
    if (_lbState.zoom > 1.05) {
      setLightboxZoom(1);
    } else {
      setLightboxZoom(2.5, e.clientX, e.clientY);
    }
  });

  // Glisser pour se déplacer (Pan) quand zoomé, ou clic / clic maintenu pour Avant / Après
  stage.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.stopPropagation();
    try { stage.setPointerCapture(e.pointerId); } catch (_) {}

    const sourceIdx = _lbState.items.findIndex(it => it.role === 'source');
    const canHoldCompare = _lbState.zoom <= 1.01 && _lbState.items.length > 1 && sourceIdx !== -1 && _lbState.activeIndex !== sourceIdx;

    _lbState.pointerSession = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startPanX: _lbState.panX,
      startPanY: _lbState.panY,
      moved: false,
      downAt: performance.now(),
      holdFromIndex: canHoldCompare ? _lbState.activeIndex : null,
    };

    if (canHoldCompare) {
      setLightboxIndex(sourceIdx);
    }
  });

  stage.addEventListener('pointermove', e => {
    const sess = _lbState.pointerSession;
    if (!sess || sess.pointerId !== e.pointerId) return;
    const dx = e.clientX - sess.startX;
    const dy = e.clientY - sess.startY;
    if (Math.hypot(dx, dy) > 5) {
      sess.moved = true;
    }
    if (_lbState.zoom > 1.01 && sess.moved) {
      stage.classList.add('is-panning');
      _lbState.panX = sess.startPanX + dx;
      _lbState.panY = sess.startPanY + dy;
      _applyLightboxTransform();
    }
  });

  const endPointer = e => {
    const sess = _lbState.pointerSession;
    if (!sess) return;
    _lbState.pointerSession = null;
    stage.classList.remove('is-panning');
    try { stage.releasePointerCapture(sess.pointerId); } catch (_) {}

    const elapsed = performance.now() - sess.downAt;
    if (sess.holdFromIndex !== null) {
      if (elapsed > 180) {
        setLightboxIndex(sess.holdFromIndex);
      }
      return;
    }
    // Clic court sans déplacement -> bascule Source <-> Modifiée
    if (!sess.moved && e.type === 'pointerup' && elapsed <= 260 && _lbState.items.length > 1) {
      toggleLightboxSourceCompare();
    }
  };
  stage.addEventListener('pointerup', endPointer);
  stage.addEventListener('pointercancel', endPointer);

  // Molette de la souris :
  // - Ctrl + Molette (ou Alt + Molette) : Zoom centré sur le curseur
  // - Molette simple : défilement instantané entre les images (en gardant le zoom synchronisé !)
  lb.addEventListener('wheel', e => {
    if (!lb.classList.contains('show')) return;
    e.preventDefault();

    if (e.ctrlKey || e.metaKey || e.altKey) {
      const factor = e.deltaY < 0 ? 1.2 : (1 / 1.2);
      setLightboxZoom(_lbState.zoom * factor, e.clientX, e.clientY);
      return;
    }

    if (_lbState.items.length <= 1) return;
    const rawDelta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
    if (!rawDelta) return;

    const now = performance.now();
    if (e.deltaMode !== 0 || Math.abs(rawDelta) >= 40) {
      if (now - _lbState.lastWheelStepAt < 35) return;
      _lbState.lastWheelStepAt = now;
      _lbState.wheelAccum = 0;
      stepLightbox(rawDelta > 0 ? +1 : -1);
      return;
    }

    _lbState.wheelAccum += rawDelta;
    if (Math.abs(_lbState.wheelAccum) >= 45) {
      const dir = _lbState.wheelAccum > 0 ? +1 : -1;
      _lbState.wheelAccum = 0;
      _lbState.lastWheelStepAt = now;
      stepLightbox(dir);
    }
  }, { passive: false });

  // Navigation au clavier (flèches + Espace + Zoom +/-/0 + Échap)
  window.addEventListener('keydown', e => {
    if (!lb.classList.contains('show')) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeLightbox();
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      if (_lbState.items.length > 1) {
        e.preventDefault();
        stepLightbox(+1);
      }
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      if (_lbState.items.length > 1) {
        e.preventDefault();
        stepLightbox(-1);
      }
    } else if (e.key === ' ' || e.code === 'Space') {
      if (_lbState.items.length > 1) {
        e.preventDefault();
        toggleLightboxSourceCompare();
      }
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      setLightboxZoom(_lbState.zoom * 1.3);
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      setLightboxZoom(_lbState.zoom / 1.3);
    } else if (e.key === '0') {
      e.preventDefault();
      setLightboxZoom(1);
    }
  });

  document.body.appendChild(lb);
  return lb;
}

function setLightboxIndex(index) {
  const { items, stageImgs, thumbBtns } = _lbState;
  if (!items.length) return;
  const count = items.length;
  const nextIdx = ((index % count) + count) % count;
  const prevIdx = _lbState.activeIndex;

  if (nextIdx !== prevIdx) {
    _lbState.prevViewedIndex = prevIdx;
  }
  _lbState.activeIndex = nextIdx;

  const current = items[nextIdx];
  if (current.role === 'result') {
    _lbState.lastResultIndex = nextIdx;
  }

  // Commutation instantanée par classe CSS sur les images déjà décodées en mémoire
  stageImgs.forEach((imgEl, i) => {
    imgEl.classList.toggle('active', i === nextIdx);
  });
  thumbBtns.forEach((btnEl, i) => {
    btnEl.classList.toggle('active', i === nextIdx);
  });

  const badgeEl = $('#lb-badge');
  const counterEl = $('#lb-counter');
  const labelEl = $('#lb-label');
  const dlEl = $('#lb-download');
  const cmpBtn = $('#lb-compare-btn');

  if (badgeEl) {
    badgeEl.textContent = current.badge || '';
    badgeEl.hidden = !current.badge;
    badgeEl.className = 'lb-badge ' + (current.role === 'source' ? 'is-source' : 'is-result');
  }
  if (counterEl) {
    counterEl.textContent = count > 1 ? `${nextIdx + 1} / ${count}` : '';
    counterEl.hidden = count <= 1;
  }
  if (labelEl) {
    labelEl.textContent = current.label || '';
  }
  if (dlEl) {
    dlEl.href = current.downloadUrl || current.src;
  }
  if (cmpBtn && !cmpBtn.hidden) {
    const isSource = current.role === 'source';
    cmpBtn.classList.toggle('active-source', isSource);
    cmpBtn.innerHTML = isSource
      ? '⇄ Voir Modifiée <kbd>Espace</kbd>'
      : '⇄ Voir Source (Avant) <kbd>Espace</kbd>';
  }
}

function stepLightbox(delta) {
  if (_lbState.items.length <= 1) return;
  setLightboxIndex(_lbState.activeIndex + delta);
}

function toggleLightboxSourceCompare() {
  const { items, activeIndex, lastResultIndex, prevViewedIndex } = _lbState;
  if (items.length <= 1) return;
  const sourceIdx = items.findIndex(it => it.role === 'source');
  if (sourceIdx !== -1) {
    if (activeIndex === sourceIdx) {
      const target = (lastResultIndex !== sourceIdx && items[lastResultIndex])
        ? lastResultIndex
        : items.findIndex((_, i) => i !== sourceIdx);
      if (target >= 0) setLightboxIndex(target);
    } else {
      _lbState.lastResultIndex = activeIndex;
      setLightboxIndex(sourceIdx);
    }
    return;
  }
  const fallback = prevViewedIndex !== activeIndex ? prevViewedIndex : (activeIndex + 1) % items.length;
  setLightboxIndex(fallback);
}

function closeLightbox() {
  const lb = $('#lightbox');
  if (lb) lb.classList.remove('show');
  _lbState.pointerSession = null;
}

function openLightbox(first, second, third) {
  const lb = _ensureLightboxDom();
  const { items, startIndex, opts } = _normalizeLightboxArgs(first, second, third);
  if (!items.length) return;

  _lbState.items = items;
  _lbState.wheelAccum = 0;
  _lbState.pointerSession = null;
  _lbState.zoom = 1;
  _lbState.panX = 0;
  _lbState.panY = 0;

  const clampedStart = Math.max(0, Math.min(items.length - 1, startIndex || 0));
  _lbState.activeIndex = clampedStart;

  const firstResultIdx = items.findIndex(it => it.role === 'result');
  _lbState.lastResultIndex = typeof opts.lastResultIndex === 'number'
    ? opts.lastResultIndex
    : (items[clampedStart]?.role === 'result' ? clampedStart : (firstResultIdx >= 0 ? firstResultIdx : 0));
  _lbState.prevViewedIndex = clampedStart === 0 && items.length > 1 ? 1 : 0;

  const stage = $('#lb-stage', lb);
  const thumbs = $('#lb-thumbs', lb);
  stage.innerHTML = '';
  thumbs.innerHTML = '';
  _lbState.stageImgs = [];
  _lbState.thumbBtns = [];

  items.forEach((item, i) => {
    const img = document.createElement('img');
    img.className = 'lb-img' + (i === clampedStart ? ' active' : '');
    img.decoding = 'sync';
    img.loading = 'eager';
    img.draggable = false;
    img.alt = item.label || item.badge || '';
    img.src = item.src;
    if (typeof img.decode === 'function') {
      img.decode().catch(() => {});
    }
    stage.appendChild(img);
    _lbState.stageImgs.push(img);

    if (items.length > 1) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lb-thumb' + (i === clampedStart ? ' active' : '') + (item.role === 'source' ? ' is-source' : '');
      btn.title = item.label || item.badge || `Image ${i + 1}`;
      const tag = item.role === 'source' ? 'Avant' : (item.role === 'ref' ? `Réf ${i + 1}` : `#${i + (items[0]?.role === 'source' ? 0 : 1)}`);
      btn.innerHTML = `<img src="${item.src}" alt=""><span>${tag}</span>`;
      btn.addEventListener('click', e => {
        e.stopPropagation();
        setLightboxIndex(i);
      });
      thumbs.appendChild(btn);
      _lbState.thumbBtns.push(btn);
    }
  });

  const hasMultiple = items.length > 1;
  const hasSource = items.some(it => it.role === 'source') && hasMultiple;

  $('#lb-prev', lb).hidden = !hasMultiple;
  $('#lb-next', lb).hidden = !hasMultiple;
  $('#lb-bottombar', lb).hidden = false;
  $('#lb-thumbs', lb).hidden = !hasMultiple;
  $('#lb-compare-btn', lb).hidden = !hasSource;
  $('#lb-space-hint', lb).hidden = !hasMultiple;

  _applyLightboxTransform();
  setLightboxIndex(clampedStart);
  lb.classList.add('show');
}
