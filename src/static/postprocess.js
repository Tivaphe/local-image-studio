/* ===== Post-traitement photo (Générer / Édition / Historique) =====
   Filtres appliqués en pixels dans un canvas — 100 % local, aucun envoi réseau
   (hors enregistrement explicite de l'image obtenue).
   API : window.LisPost.open({url, filename, id, prompt})
*/
(function () {
  const $ = (s, el = document) => el.querySelector(s);

  const SLIDERS = [
    { key: 'exposure',   id: 'pp-exposure',   fmt: v => (v > 0 ? '+' : '') + v.toFixed(2).replace('.', ',') + ' EV' },
    { key: 'contrast',   id: 'pp-contrast',   fmt: v => String(v) },
    { key: 'brightness', id: 'pp-brightness', fmt: v => String(v) },
    { key: 'warmth',     id: 'pp-warmth',     fmt: v => String(v) },
    { key: 'clarity',    id: 'pp-clarity',    fmt: v => String(v) },
    { key: 'saturation', id: 'pp-saturation', fmt: v => String(v) },
    { key: 'vibrance',   id: 'pp-vibrance',   fmt: v => String(v) },
  ];
  const DEFAULTS = Object.fromEntries(SLIDERS.map(s => [s.key, 0]));

  let state = { ...DEFAULTS };
  let sourceImg = null;                 // HTMLImageElement décodée
  let srcMeta = { url: '', filename: '', id: null, prompt: '' };
  let renderTimer = null;
  let busy = false;

  const modal = () => $('#postprocess-modal');
  const canvas = () => $('#pp-canvas');

  // ---------------------------------------------------------------- filtres
  function buildChannelLUTs(p) {
    // Combine exposition (lumière linéaire), luminosité, contraste, chaleur — en 3 LUT (R, G, B)
    const expMul = Math.pow(2, p.exposure);
    const bright = (p.brightness / 100) * 64;           // ±64 niveaux
    const k = 1 + (p.contrast / 100) * 0.9;             // facteur autour de 128
    const warm = p.warmth / 100;                        // -1..+1
    const factors = [1 + warm * 0.26, 1 + warm * 0.05, 1 - warm * 0.26];
    const luts = [new Float32Array(256), new Float32Array(256), new Float32Array(256)];
    for (let i = 0; i < 256; i++) {
      const v = i / 255;
      const lin = Math.pow(v, 2.2) * expMul;                        // exposition
      let out = Math.pow(Math.min(1, lin), 1 / 2.2) * 255;          // ré-encodage gamma
      out = out + bright;                                           // luminosité
      out = (out - 128) * k + 128;                                  // contraste
      for (let c = 0; c < 3; c++) luts[c][i] = out * factors[c];    // chaleur
    }
    return luts;
  }

  function boxBlurPass(src, dst, w, h, radius, horizontal) {
    const inv = 1 / (2 * radius + 1);
    if (horizontal) {
      for (let y = 0; y < h; y++) {
        const row = y * w;
        let sum = 0;
        for (let x = -radius; x <= radius; x++) {
          const cx = Math.min(w - 1, Math.max(0, x));
          sum += src[row + cx];
        }
        for (let x = 0; x < w; x++) {
          dst[row + x] = sum * inv;
          const xAdd = Math.min(w - 1, x + radius + 1);
          const xSub = Math.max(0, x - radius);
          sum += src[row + xAdd] - src[row + xSub];
        }
      }
    } else {
      for (let x = 0; x < w; x++) {
        let sum = 0;
        for (let y = -radius; y <= radius; y++) {
          const cy = Math.min(h - 1, Math.max(0, y));
          sum += src[cy * w + x];
        }
        for (let y = 0; y < h; y++) {
          dst[y * w + x] = sum * inv;
          const yAdd = Math.min(h - 1, y + radius + 1);
          const ySub = Math.max(0, y - radius);
          sum += src[yAdd * w + x] - src[ySub * w + x];
        }
      }
    }
  }

  function applyFilters(imageData, p) {
    const d = imageData.data;
    const w = imageData.width, h = imageData.height;
    const [rL, gL, bL] = buildChannelLUTs(p);
    const sat = p.saturation / 100;
    const vib = p.vibrance / 100;
    const kSat = 1 + sat;

    // Pass 1 : corrections globales + saturation/vibrance (luma)
    for (let i = 0; i < d.length; i += 4) {
      let r = rL[d[i]], g = gL[d[i + 1]], b = bL[d[i + 2]];
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      if (sat !== 0 || vib !== 0) {
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
        const satiness = (mx - mn) / 255;
        const k = kSat * (1 + vib * (1 - satiness));
        r = luma + (r - luma) * k;
        g = luma + (g - luma) * k;
        b = luma + (b - luma) * k;
      }
      d[i] = r; d[i + 1] = g; d[i + 2] = b;
    }

    // Pass 2 : clarté = micro-contraste local sur la luminance (unsharp sur 3 passes).
    // 2 tampons uniquement ; la luminance d'origine est relue depuis `d` (intacte à ce stade).
    if (Math.abs(p.clarity) >= 1) {
      const n = w * h;
      const bufA = new Float32Array(n);
      const bufB = new Float32Array(n);
      for (let i = 0, j = 0; i < d.length; i += 4, j++) {
        bufA[j] = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      }
      const radius = Math.max(3, Math.round(Math.min(w, h) / 28));
      let srcBuf = bufA, dstBuf = bufB;
      for (let pass = 0; pass < 3; pass++) {
        boxBlurPass(srcBuf, dstBuf, w, h, radius, true);
        boxBlurPass(dstBuf, srcBuf, w, h, radius, false);
      }
      // après 3 passes (impair), srcBuf === bufA contient le flou
      const blurred = srcBuf;
      const amt = (p.clarity / 100) * 0.85;
      for (let i = 0, j = 0; i < d.length; i += 4, j++) {
        const lumaNow = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        const delta = (lumaNow - blurred[j]) * amt;
        d[i] = d[i] + delta; d[i + 1] = d[i + 1] + delta; d[i + 2] = d[i + 2] + delta;
      }
    }
    return imageData;
  }

  // ------------------------------------------------------------- rendu UI
  function workingScale() {
    const maxSide = Math.max(sourceImg.naturalWidth, sourceImg.naturalHeight) || 1;
    return Math.min(1, 1440 / maxSide);
  }

  function render() {
    if (!sourceImg) return;
    const cv = canvas();
    const w = Math.max(1, Math.round(sourceImg.naturalWidth * workingScale()));
    const h = Math.max(1, Math.round(sourceImg.naturalHeight * workingScale()));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(sourceImg, 0, 0, w, h);
    const frame = ctx.getImageData(0, 0, w, h);
    applyFilters(frame, state);
    ctx.putImageData(frame, 0, 0);
  }

  function scheduleRender() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(render, 45);
  }

  function refreshLabels() {
    for (const s of SLIDERS) {
      const el = document.getElementById(s.id + '-val');
      if (el) el.textContent = s.fmt(Number(state[s.key]));
    }
  }

  function resetSliders() {
    state = { ...DEFAULTS };
    for (const s of SLIDERS) {
      const el = document.getElementById(s.id);
      if (el) el.value = '0';
    }
    refreshLabels();
    render();
  }

  async function exportBlob() {
    // Re-applique le même pipeline en pleine résolution
    const full = document.createElement('canvas');
    full.width = sourceImg.naturalWidth;
    full.height = sourceImg.naturalHeight;
    const ctx = full.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(sourceImg, 0, 0);
    const frame = ctx.getImageData(0, 0, full.width, full.height);
    applyFilters(frame, state);
    ctx.putImageData(frame, 0, 0);
    return new Promise(resolve => full.toBlob(resolve, 'image/png'));
  }

  const LABELS = { exposure: 'exposition', contrast: 'contraste', brightness: 'luminosité',
                   warmth: 'chaleur', clarity: 'clarté', saturation: 'saturation', vibrance: 'vibrance' };
  function settingsSummary() {
    const parts = [];
    for (const s of SLIDERS) {
      const v = state[s.key];
      if (!v) continue;
      const txt = s.key === 'exposure'
        ? `exposition ${v > 0 ? '+' : ''}${v.toFixed(2)} EV`
        : `${LABELS[s.key]} ${v > 0 ? '+' : ''}${v}`;
      parts.push(txt);
    }
    return parts.join(', ') || 'aucun ajustement';
  }

  async function saveAdjusted(openInEditor) {
    if (!sourceImg || busy) return;
    busy = true;
    const btnSave = $('#pp-save'), btnEdit = $('#pp-save-edit');
    if (btnSave) btnSave.disabled = true;
    if (btnEdit) btnEdit.disabled = true;
    try {
      const blob = await exportBlob();
      if (!blob) throw new Error('Export PNG impossible.');
      const fd = new FormData();
      fd.append('image', blob, 'postprocess.png');
      if (srcMeta.filename) fd.append('source', srcMeta.filename);
      if (srcMeta.prompt) fd.append('prompt', srcMeta.prompt);
      fd.append('settings', JSON.stringify(state));
      fd.append('summary', settingsSummary());
      const r = await fetch('/api/postprocess/save', { method: 'POST', body: fd });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || 'Enregistrement impossible.');
      if (openInEditor) {
        const r2 = await fetch('/api/use-output-as-source', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: j.id, filename: j.filename }),
        });
        const j2 = await r2.json();
        if (!j2.ok) throw new Error(j2.error || "Impossible d'envoyer l'image vers l'édition.");
        sessionStorage.setItem('edit_incoming_source', JSON.stringify({
          mode: 'canvas',
          file: { filename: j2.filename, url: j2.url, name: j2.name },
        }));
        window.location.href = '/edit';
        return;
      }
      if (window.showToast) window.showToast('💾 Image ajustée enregistrée dans l’historique ✓');
      closeModal();
    } catch (e) {
      alert(e.message || 'Erreur lors de l’enregistrement.');
    } finally {
      busy = false;
      if (btnSave) btnSave.disabled = false;
      if (btnEdit) btnEdit.disabled = false;
    }
  }

  function openModal() {
    const m = modal();
    if (!m) return;
    m.hidden = false;
    document.body.style.overflow = 'hidden';
  }
  function closeModal() {
    const m = modal();
    if (!m) return;
    m.hidden = true;
    document.body.style.overflow = '';
  }

  function open(opts) {
    srcMeta = {
      url: (opts && opts.url) || '',
      filename: (opts && opts.filename) || '',
      id: (opts && opts.id != null) ? opts.id : null,
      prompt: (opts && opts.prompt) || '',
    };
    if (!srcMeta.url) { alert('Aucune image sélectionnée.'); return; }
    state = { ...DEFAULTS };
    for (const s of SLIDERS) {
      const el = document.getElementById(s.id);
      if (el) el.value = '0';
    }
    refreshLabels();
    sourceImg = null;
    const loading = $('#pp-loading');
    if (loading) { loading.hidden = false; loading.textContent = 'Chargement de l’image…'; }
    openModal();
    const img = new Image();
    img.onload = () => {
      sourceImg = img;
      const p = $('#pp-src');
      if (p) p.textContent = srcMeta.filename || srcMeta.url;
      if (loading) loading.hidden = true;
      render();
    };
    img.onerror = () => {
      if (loading) { loading.hidden = false; loading.textContent = 'Impossible de charger cette image.'; }
    };
    img.src = srcMeta.url;
  }

  // ---------------------------------------------------------------- events
  document.addEventListener('DOMContentLoaded', () => {
    const m = modal();
    if (!m) return;
    for (const s of SLIDERS) {
      const el = document.getElementById(s.id);
      if (!el) continue;
      el.addEventListener('input', () => {
        state[s.key] = Number(el.value);
        refreshLabels();
        scheduleRender();
      });
    }
    $('#pp-reset')?.addEventListener('click', resetSliders);
    $('#pp-save')?.addEventListener('click', () => saveAdjusted(false));
    $('#pp-save-edit')?.addEventListener('click', () => saveAdjusted(true));
    $('#pp-close')?.addEventListener('click', closeModal);
    m.querySelectorAll('[data-pp-close]').forEach(el => el.addEventListener('click', closeModal));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && m && !m.hidden) closeModal();
    });
  });

  window.LisPost = { open, close: closeModal, _applyFilters: applyFilters };
})();
