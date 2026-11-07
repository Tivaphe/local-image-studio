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

// Cache mémoire global pour précharger et décoder les images (zéro rechargement)
const _imagePreloadCache = new Map();

function preloadImages(urls) {
  for (const url of urls || []) {
    if (!url || _imagePreloadCache.has(url)) continue;
    const im = new Image();
    im.decoding = 'sync';
    im.src = url;
    if (typeof im.decode === 'function') {
      im.decode().catch(() => {});
    }
    _imagePreloadCache.set(url, im);
  }
}
window.preloadImages = preloadImages;

// ============================================================================
//  Lightbox interactive sans rechargement :
//   - Navigation instantanée avec flèches clavier (◀ / ▶) et molette souris
//   - Bascule instantanée Avant (source) ↔ Après (modifiée) via Espace ou bouton
//   - Toutes les images de la série sont empilées et décodées en mémoire
// ============================================================================
const _lbState = {
  items: [],
  idx: 0,
  sourceIdx: -1,
  lastResultIdx: 0,
  showingItemBefore: false,
  prevBodyOverflow: '',
};

function _normalizeLbItems(itemsOrSrc) {
  if (!itemsOrSrc) return [];
  if (typeof itemsOrSrc === 'string') {
    return [{ src: itemsOrSrc, label: '', kind: 'result', downloadUrl: itemsOrSrc }];
  }
  if (!Array.isArray(itemsOrSrc)) return [];
  return itemsOrSrc
    .filter(it => it && (typeof it === 'string' || it.src))
    .map(it => {
      if (typeof it === 'string') {
        return { src: it, label: '', kind: 'result', downloadUrl: it };
      }
      return {
        src: it.src,
        label: it.label || '',
        kind: it.kind || 'result',
        seed: it.seed ?? null,
        downloadUrl: it.downloadUrl || (it.kind === 'source' ? null : it.src),
        sourceSrc: it.sourceSrc || null,
        sourceLabel: it.sourceLabel || 'Avant (image source)',
      };
    });
}

function _ensureLightbox() {
  let lb = $('#lightbox');
  if (lb) return lb;

  lb = document.createElement('div');
  lb.id = 'lightbox';
  lb.className = 'lightbox';
  lb.setAttribute('role', 'dialog');
  lb.setAttribute('aria-modal', 'true');
  lb.innerHTML = `
    <div class="lb-topbar">
      <div class="lb-meta">
        <span class="lb-counter" id="lb-counter"></span>
        <span class="lb-kind-badge" id="lb-kind-badge"></span>
        <span class="lb-label" id="lb-label"></span>
      </div>
      <div class="lb-actions">
        <button type="button" class="btn small lb-ba-btn" id="lb-ba-btn" hidden
                title="Basculer instantanément entre l'image source et l'image modifiée (touche Espace)">
          ⇄ Avant / Après <kbd>Espace</kbd>
        </button>
        <a class="btn small ghost lb-dl-btn" id="lb-dl-btn" download hidden>⬇ Télécharger</a>
        <button type="button" class="lb-close x" id="lb-close" aria-label="Fermer">×</button>
      </div>
    </div>

    <div class="lb-stage-wrap" id="lb-stage-wrap">
      <button type="button" class="lb-nav lb-prev" id="lb-prev" aria-label="Image précédente" title="Image précédente (◀ ou molette haut)">‹</button>
      <div class="lb-stage" id="lb-stage"></div>
      <button type="button" class="lb-nav lb-next" id="lb-next" aria-label="Image suivante" title="Image suivante (▶ ou molette bas)">›</button>
    </div>

    <div class="lb-bottom" id="lb-bottom">
      <div class="lb-thumbs" id="lb-thumbs"></div>
      <div class="lb-hint" id="lb-hint"></div>
    </div>
  `;

  // Fermeture en cliquant sur le fond sombre ou la croix
  lb.addEventListener('click', e => {
    if (
      e.target === lb ||
      e.target.id === 'lb-stage-wrap' ||
      e.target.id === 'lb-stage' ||
      e.target.closest('#lb-close')
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
    stepLightbox(1);
  });
  lb.querySelector('#lb-ba-btn').addEventListener('click', e => {
    e.stopPropagation();
    toggleLightboxBeforeAfter();
  });

  // Navigation à la molette de la souris (sans scroller la page derrière)
  let wheelAccum = 0;
  let lastStepAt = 0;
  let lastWheelAt = 0;
  lb.addEventListener('wheel', e => {
    if (!lb.classList.contains('show') || _lbState.items.length <= 1) return;
    e.preventDefault();
    const now = performance.now();
    if (now - lastWheelAt > 200) wheelAccum = 0;
    lastWheelAt = now;

    const raw = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
    if (!raw) return;
    if ((raw > 0 && wheelAccum < 0) || (raw < 0 && wheelAccum > 0)) wheelAccum = 0;

    const deltaPx = e.deltaMode === 1 ? raw * 36 : (e.deltaMode === 2 ? raw * 300 : raw);
    wheelAccum += deltaPx;

    if (Math.abs(wheelAccum) >= 45) {
      if (now - lastStepAt >= 85) {
        stepLightbox(wheelAccum > 0 ? 1 : -1);
        lastStepAt = now;
      }
      wheelAccum = 0;
    }
  }, { passive: false });

  document.body.appendChild(lb);
  return lb;
}

function _hasBeforeAfterCapability() {
  if (_lbState.sourceIdx >= 0 && _lbState.items.length > 1) return true;
  const cur = _lbState.items[_lbState.idx];
  return Boolean(cur && cur.sourceSrc);
}

function _renderLightboxActive() {
  const lb = $('#lightbox');
  if (!lb || !_lbState.items.length) return;
  const n = _lbState.items.length;
  const idx = _lbState.idx;
  const item = _lbState.items[idx];

  // Bascule instantanée des slides pré-chargées (aucun rechargement réseau ni re-décodage)
  $$('.lb-slide', lb).forEach(img => {
    const slideIdx = parseInt(img.dataset.idx, 10);
    const role = img.dataset.role; // 'main' | 'before'
    let show = false;
    if (slideIdx === idx) {
      if (item.sourceSrc && _lbState.showingItemBefore) {
        show = role === 'before';
      } else {
        show = role === 'main';
      }
    }
    img.classList.toggle('active', show);
  });

  // Vignettes actives
  $$('.lb-thumb', lb).forEach((th, i) => {
    const active = i === idx;
    th.classList.toggle('active', active);
    if (active && typeof th.scrollIntoView === 'function') {
      th.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  });

  // Compteur & badges
  const counterEl = $('#lb-counter', lb);
  counterEl.textContent = n > 1 ? `${idx + 1} / ${n}` : '';
  counterEl.hidden = n <= 1;

  const isSourceView = item.kind === 'source' || (item.sourceSrc && _lbState.showingItemBefore);
  const badgeEl = $('#lb-kind-badge', lb);
  if (isSourceView) {
    badgeEl.textContent = 'Avant · Source';
    badgeEl.className = 'lb-kind-badge is-source';
    badgeEl.hidden = false;
  } else if (_hasBeforeAfterCapability()) {
    badgeEl.textContent = 'Après · Modifiée';
    badgeEl.className = 'lb-kind-badge is-result';
    badgeEl.hidden = false;
  } else {
    badgeEl.hidden = true;
  }

  const labelEl = $('#lb-label', lb);
  labelEl.textContent = (item.sourceSrc && _lbState.showingItemBefore)
    ? item.sourceLabel
    : (item.label || '');

  // Bouton Avant / Après
  const baBtn = $('#lb-ba-btn', lb);
  const canBA = _hasBeforeAfterCapability();
  baBtn.hidden = !canBA;
  baBtn.classList.toggle('is-active-source', isSourceView);
  if (canBA) {
    baBtn.innerHTML = isSourceView
      ? '⇄ Voir l\'image modifiée <kbd>Espace</kbd>'
      : '⇄ Voir l\'image source <kbd>Espace</kbd>';
  }

  // Lien télécharger
  const dlBtn = $('#lb-dl-btn', lb);
  const dlHref = (!isSourceView && item.downloadUrl) ? item.downloadUrl : null;
  if (dlHref) {
    dlBtn.href = dlHref;
    dlBtn.hidden = false;
  } else {
    dlBtn.hidden = true;
  }

  // Flèches & légende raccourcis
  $('#lb-prev', lb).hidden = n <= 1;
  $('#lb-next', lb).hidden = n <= 1;
  $('#lb-thumbs', lb).hidden = n <= 1;

  const hintParts = [];
  if (n > 1) hintParts.push('◀ ▶ Clavier ou molette souris : passer d\'une image à l\'autre');
  if (canBA) hintParts.push('Espace : basculer Avant ↔ Après');
  hintParts.push('Échap : fermer');
  $('#lb-hint', lb).textContent = hintParts.join('  ·  ');
}

function stepLightbox(delta) {
  const n = _lbState.items.length;
  if (n <= 1) return;
  _lbState.showingItemBefore = false;
  _lbState.idx = (_lbState.idx + delta + n) % n;
  if (_lbState.items[_lbState.idx].kind !== 'source') {
    _lbState.lastResultIdx = _lbState.idx;
  }
  _renderLightboxActive();
}

function toggleLightboxBeforeAfter() {
  if (!_lbState.items.length) return;
  const cur = _lbState.items[_lbState.idx];
  // Cas 1 : l'image source fait partie de la liste (Générer img2img / Studio d'édition)
  if (_lbState.sourceIdx >= 0 && _lbState.items.length > 1) {
    if (_lbState.idx === _lbState.sourceIdx) {
      let target = _lbState.lastResultIdx;
      if (target === _lbState.sourceIdx || target < 0 || target >= _lbState.items.length) {
        target = _lbState.items.findIndex((_, i) => i !== _lbState.sourceIdx);
      }
      if (target >= 0) _lbState.idx = target;
    } else {
      _lbState.lastResultIdx = _lbState.idx;
      _lbState.idx = _lbState.sourceIdx;
    }
    _renderLightboxActive();
    return;
  }
  // Cas 2 : une entrée (ex. Historique) possède sa propre source associée
  if (cur && cur.sourceSrc) {
    _lbState.showingItemBefore = !_lbState.showingItemBefore;
    _renderLightboxActive();
  }
}

function closeLightbox() {
  const lb = $('#lightbox');
  if (!lb || !lb.classList.contains('show')) return;
  lb.classList.remove('show');
  document.body.style.overflow = _lbState.prevBodyOverflow || '';
}

function openLightbox(itemsOrSrc, startIndex = 0, options = {}) {
  const items = _normalizeLbItems(itemsOrSrc);
  if (!items.length) return;

  const lb = _ensureLightbox();
  _lbState.items = items;
  _lbState.idx = Math.max(0, Math.min(items.length - 1, Number(startIndex) || 0));
  _lbState.sourceIdx = items.findIndex(it => it.kind === 'source');
  _lbState.showingItemBefore = false;

  if (typeof options.lastResultIndex === 'number' &&
      options.lastResultIndex >= 0 &&
      options.lastResultIndex < items.length &&
      options.lastResultIndex !== _lbState.sourceIdx) {
    _lbState.lastResultIdx = options.lastResultIndex;
  } else if (items[_lbState.idx].kind !== 'source') {
    _lbState.lastResultIdx = _lbState.idx;
  } else {
    const firstRes = items.findIndex(it => it.kind !== 'source');
    _lbState.lastResultIdx = firstRes >= 0 ? firstRes : 0;
  }

  // Précharger toutes les URLs en mémoire
  const allUrls = [];
  items.forEach(it => {
    allUrls.push(it.src);
    if (it.sourceSrc) allUrls.push(it.sourceSrc);
  });
  preloadImages(allUrls);

  // Construire les slides empilées dans la scène
  const stage = $('#lb-stage', lb);
  stage.innerHTML = '';
  items.forEach((it, i) => {
    const mainImg = document.createElement('img');
    mainImg.className = 'lb-slide';
    mainImg.dataset.idx = String(i);
    mainImg.dataset.role = 'main';
    mainImg.decoding = 'sync';
    mainImg.draggable = false;
    mainImg.src = it.src;
    mainImg.alt = it.label || '';
    stage.appendChild(mainImg);

    if (it.sourceSrc) {
      const beforeImg = document.createElement('img');
      beforeImg.className = 'lb-slide';
      beforeImg.dataset.idx = String(i);
      beforeImg.dataset.role = 'before';
      beforeImg.decoding = 'sync';
      beforeImg.draggable = false;
      beforeImg.src = it.sourceSrc;
      beforeImg.alt = it.sourceLabel || 'Avant';
      stage.appendChild(beforeImg);
    }
  });

  // Construire la barre de miniatures
  const thumbs = $('#lb-thumbs', lb);
  thumbs.innerHTML = '';
  if (items.length > 1) {
    items.forEach((it, i) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lb-thumb' + (it.kind === 'source' ? ' is-source' : '');
      btn.title = it.label || (it.kind === 'source' ? 'Image source (Avant)' : `Image ${i + 1}`);
      const badgeText = it.kind === 'source'
        ? 'Avant'
        : String(_lbState.sourceIdx >= 0 ? i : i + 1);
      btn.innerHTML = `<img src="${it.src}" alt="" draggable="false"><span>${badgeText}</span>`;
      btn.addEventListener('click', e => {
        e.stopPropagation();
        _lbState.showingItemBefore = false;
        _lbState.idx = i;
        if (it.kind !== 'source') _lbState.lastResultIdx = i;
        _renderLightboxActive();
      });
      thumbs.appendChild(btn);
    });
  }

  if (!lb.classList.contains('show')) {
    _lbState.prevBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  lb.classList.add('show');
  _renderLightboxActive();
}

window.openLightbox = openLightbox;
window.closeLightbox = closeLightbox;

// Navigation clavier globale quand la Lightbox est ouverte
window.addEventListener('keydown', e => {
  const lb = $('#lightbox');
  if (!lb || !lb.classList.contains('show')) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    closeLightbox();
  } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
    if (_lbState.items.length > 1) {
      e.preventDefault();
      stepLightbox(1);
    }
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
    if (_lbState.items.length > 1) {
      e.preventDefault();
      stepLightbox(-1);
    }
  } else if (e.code === 'Space' || e.key === ' ') {
    if (_hasBeforeAfterCapability()) {
      e.preventDefault();
      toggleLightboxBeforeAfter();
    }
  }
});
