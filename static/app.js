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

// ===========================================================================
//  Lightbox plein écran avec préchargement & navigation instantanée (0 reload)
//  - Flèches ← / → (ou ↑ / ↓) et Molette souris : défilement sans rechargement
//  - Espace / bouton « Avant / Après » / clic maintenu sur l'image :
//    bascule instantanée entre l'image source (Avant) et l'image modifiée (Après)
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
  holdState: null,
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
        <span><kbd>←</kbd> <kbd>→</kbd> ou <strong>Molette</strong> : défiler sans rechargement</span>
        <span id="lb-space-hint" hidden>· <kbd>Espace</kbd> ou <strong>clic sur l'image</strong> : basculer Source ↔ Modifiée</span>
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

  // Clic ou clic maintenu sur l'image pour comparer instantanément Avant / Après
  const stage = lb.querySelector('#lb-stage');
  stage.addEventListener('pointerdown', e => {
    if (e.button !== 0 || _lbState.items.length <= 1) return;
    e.stopPropagation();
    const sourceIdx = _lbState.items.findIndex(it => it.role === 'source');
    if (sourceIdx !== -1 && _lbState.activeIndex !== sourceIdx) {
      _lbState.holdState = {
        fromIndex: _lbState.activeIndex,
        downAt: performance.now(),
      };
      setLightboxIndex(sourceIdx);
    } else {
      _lbState.holdState = {
        fromIndex: null,
        downAt: performance.now(),
      };
    }
  });

  const endHold = e => {
    if (!_lbState.holdState) return;
    const { fromIndex, downAt } = _lbState.holdState;
    _lbState.holdState = null;
    const elapsed = performance.now() - downAt;
    if (fromIndex !== null) {
      // Si l'utilisateur a maintenu le clic (> 180 ms), on revient à l'image modifiée au relâchement.
      // Si c'était un clic court, on reste sur la source (bascule).
      if (elapsed > 180) {
        setLightboxIndex(fromIndex);
      }
    } else if (e.type === 'pointerup' && elapsed <= 250) {
      toggleLightboxSourceCompare();
    }
  };
  stage.addEventListener('pointerup', endHold);
  stage.addEventListener('pointercancel', endHold);

  // Navigation à la molette de la souris (sans rechargement ni scroll de la page)
  lb.addEventListener('wheel', e => {
    if (!lb.classList.contains('show') || _lbState.items.length <= 1) return;
    e.preventDefault();
    const rawDelta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
    if (!rawDelta) return;

    const now = performance.now();
    // Molette crantée classique (delta >= 40 ou mode ligne/page)
    if (e.deltaMode !== 0 || Math.abs(rawDelta) >= 40) {
      if (now - _lbState.lastWheelStepAt < 35) return;
      _lbState.lastWheelStepAt = now;
      _lbState.wheelAccum = 0;
      stepLightbox(rawDelta > 0 ? +1 : -1);
      return;
    }

    // Pavé tactile fluide : accumulation du delta
    _lbState.wheelAccum += rawDelta;
    if (Math.abs(_lbState.wheelAccum) >= 45) {
      const dir = _lbState.wheelAccum > 0 ? +1 : -1;
      _lbState.wheelAccum = 0;
      _lbState.lastWheelStepAt = now;
      stepLightbox(dir);
    }
  }, { passive: false });

  // Navigation au clavier (flèches + Espace + Échap)
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
  // Sans image source (ex: batch de plusieurs générations) : bascule entre les 2 dernières vues
  const fallback = prevViewedIndex !== activeIndex ? prevViewedIndex : (activeIndex + 1) % items.length;
  setLightboxIndex(fallback);
}

function closeLightbox() {
  const lb = $('#lightbox');
  if (lb) lb.classList.remove('show');
  _lbState.holdState = null;
}

function openLightbox(first, second, third) {
  const lb = _ensureLightboxDom();
  const { items, startIndex, opts } = _normalizeLightboxArgs(first, second, third);
  if (!items.length) return;

  _lbState.items = items;
  _lbState.wheelAccum = 0;
  _lbState.holdState = null;

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

  // Préchargement et décodage de toutes les images dans le DOM pour un passage à 0 ms
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
  $('#lb-bottombar', lb).hidden = !hasMultiple;
  $('#lb-compare-btn', lb).hidden = !hasSource;
  $('#lb-space-hint', lb).hidden = !hasMultiple;

  setLightboxIndex(clampedStart);
  lb.classList.add('show');
}
