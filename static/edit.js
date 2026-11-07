/* ===== Studio d'édition & Outpainting ===== */
/* Édition par références multiples + Outpainting (extension de cadre) + Comparaison instantanée */

if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

let MODELS = {};
let studioMode = 'edit';       // 'edit' | 'outpaint'
let currentRatio = 'canvas';   // 'canvas' = reprend les dimensions de @image1
let pollTimer = null;

// État des images d'entrée :
//  - canvas : { path, url, name, width, height } | null   -> index 0 (@image1)
//  - refs   : Array<{ path, url, name, width, height }>   -> index 1..N (@image2..)
let canvas = null;
let canvasImgEl = null;        // HTMLImageElement décodée pour l'aperçu outpainting
let refs = [];

// État du dernier run pour comparaison instantanée sans rechargement
let activeRunBeforeUrl = null;
let activeRunMode = 'edit';
let alignedOutpaintObjectUrl = null;
let lastRenderedSig = '';
let selectedResultIdx = 0;
let currentLbItems = [];

const PREF_KEY = 'lis_edit_prefs';
const MAX_OUTPAINT_SIDE = 1792;

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); }
  catch (e) { return {}; }
}
function savePrefs(patch) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ ...loadPrefs(), ...patch })); }
  catch (e) {}
}

function round16(x) {
  return Math.max(64, Math.round(x / 16) * 16);
}
function round32(x) {
  return Math.max(64, Math.round(x / 32) * 32);
}

// ===========================================================================
//  Chargement & filtrage des modèles selon le sous-mode (Édition vs Outpaint)
// ===========================================================================
function getModelsForMode(mode) {
  const entries = Object.entries(MODELS);
  if (mode === 'outpaint') {
    const rank = m => (m.outpaint_mode === 'fill' ? 0 : (m.outpaint_mode === 'ref_mask' ? 1 : 2));
    return entries
      .filter(([, m]) => Boolean(m.supports_outpaint))
      .sort(([, a], [, b]) => rank(a) - rank(b));
  }
  return entries.filter(
    ([, m]) => m.supports_ref_images && (m.input_modes || []).includes('ref') && !m.inpaint_only
  );
}

function populateModelSelect() {
  const sel = $('#model');
  sel.innerHTML = '';
  const compatible = getModelsForMode(studioMode);
  const prefs = loadPrefs();
  const prefField = studioMode === 'outpaint' ? 'outpaintModel' : 'model';
  let saved = prefs[prefField];
  if (!compatible.some(([id]) => id === saved)) saved = null;

  let firstReady = null;
  for (const [id, m] of compatible) {
    const opt = document.createElement('option');
    opt.value = id;
    const star = (studioMode === 'outpaint' && m.outpaint_mode === 'fill') ? ' ★ Dédié Outpaint' : '';
    const tag = m.status.ready ? ' ✓' : '  (à télécharger)';
    opt.textContent = `${m.name}${star}${tag}`;
    if (!m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
    if (m.status.ready && !firstReady) firstReady = id;
  }
  if (compatible.length) {
    sel.value = saved || firstReady || compatible[0][0];
  }
}

async function loadModels() {
  const r = await fetch('/api/models');
  MODELS = await r.json();

  const urlParams = new URLSearchParams(window.location.search);
  const modeParam = urlParams.get('mode');
  const prefs = loadPrefs();
  if (modeParam === 'outpaint' || modeParam === 'edit') {
    studioMode = modeParam;
  } else if (prefs.studioMode === 'outpaint' || prefs.studioMode === 'edit') {
    studioMode = prefs.studioMode;
  }

  $('#model').addEventListener('change', () => {
    const patch = { quant: $('#quant')?.value };
    if (studioMode === 'outpaint') patch.outpaintModel = $('#model').value;
    else patch.model = $('#model').value;
    savePrefs(patch);
    onModelChange();
  });
  $('#quant')?.addEventListener('change', () => {
    savePrefs({ quant: $('#quant').value });
  });
  $('#preset')?.addEventListener('change', applyPreset);

  syncStudioModeUI();

  if (window.PRELOAD_SOURCE) {
    await adoptExistingSource(window.PRELOAD_SOURCE);
  }
}

function setStudioMode(mode) {
  if (mode !== 'edit' && mode !== 'outpaint') return;
  if (studioMode === mode) return;
  studioMode = mode;
  savePrefs({ studioMode });
  syncStudioModeUI();
}

function syncStudioModeUI() {
  $$('.studio-mode-tab').forEach(btn => {
    const active = btn.dataset.studioMode === studioMode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  const isOutpaint = studioMode === 'outpaint';
  $('#model-select-label').textContent = isOutpaint ? 'Modèle d\'outpainting' : 'Modèle d\'édition';
  $('#prompt-label').textContent = isOutpaint ? 'Description de la scène étendue' : 'Instruction d\'édition';
  $('#prompt').placeholder = isOutpaint
    ? 'Décrivez la scène complète une fois élargie (ex : vaste paysage alpin ensoleillé avec lac cristallin et sapins, lumière dorée)…'
    : 'Décrivez précisément la modification : remplacer le fond par…, transférer la tenue de @image2 sur le sujet, corriger le texte…';
  $('#edit-btn').textContent = isOutpaint ? '🖼️ Étendre l\'image' : '✂️ Appliquer l\'édition';
  $('#canvas-empty-title').innerHTML = isOutpaint
    ? '<strong>Glissez l\'image à étendre</strong> ou cliquez pour parcourir'
    : '<strong>Glissez l\'image à modifier</strong> ou cliquez pour parcourir';

  $('#outpaint-controls').hidden = !isOutpaint;
  $('#outpaint-preview-wrap').hidden = !isOutpaint;
  $('#format-section').hidden = isOutpaint;

  populateModelSelect();
  onModelChange();
  drawOutpaintPreview();
}

function applyPreset() {
  const m = MODELS[$('#model').value];
  if (!m) return;
  const key = $('#preset').value;
  const p = key === 'default'
    ? { steps: m.defaults.steps, cfg: m.defaults.cfg, quant: m.default_quant }
    : m.presets?.[key];
  if (!p) return;
  $('#steps').value = p.steps; $('#steps-val').textContent = p.steps;
  $('#cfg').value = p.cfg;     $('#cfg-val').textContent = p.cfg;
  if (p.quant && m.quants.includes(p.quant)) $('#quant').value = p.quant;
  savePrefs({ preset: key, quant: $('#quant').value });
}

function maxRefsForCurrentMode(m) {
  if (!m) return 1;
  if (studioMode === 'outpaint') {
    return m.outpaint_mode === 'ref_mask' ? (m.max_ref_images || 1) : 1;
  }
  return m.max_ref_images || 1;
}

function onModelChange() {
  const m = MODELS[$('#model').value];
  if (!m) return;
  const prefs = loadPrefs();

  // Quantifications
  const q = $('#quant');
  q.innerHTML = '';
  for (const qt of m.quants) {
    const have = m.status.quants[qt];
    const o = document.createElement('option');
    o.value = qt;
    o.textContent = `${qt} (${m.size_gb[qt] || '?'} Go)` + (have ? ' ✓' : '');
    q.appendChild(o);
  }
  const savedQuant = prefs.quant && m.quants.includes(prefs.quant) ? prefs.quant : null;
  const dlQuant = m.quants.find(x => m.status.quants[x]);
  q.value = savedQuant || dlQuant || m.default_quant;

  // Préréglages
  const ps = $('#preset');
  ps.innerHTML = '<option value="default">Par défaut</option>';
  for (const [k, p] of Object.entries(m.presets || {})) {
    const o = document.createElement('option');
    o.value = k; o.textContent = p.label;
    ps.appendChild(o);
  }
  ps.hidden = Object.keys(m.presets || {}).length === 0;

  // Sliders bornés / verrouillés
  const s = $('#steps');
  s.min = m.min_steps || 1; s.max = m.max_steps || 50;
  s.value = m.fixed_steps ?? m.defaults.steps;
  s.disabled = m.fixed_steps != null;
  $('#steps-val').textContent = s.value;

  const c = $('#cfg');
  c.value = m.fixed_cfg ?? m.defaults.cfg;
  c.disabled = m.fixed_cfg != null;
  $('#cfg-val').textContent = c.value;

  $('#neg-wrap').hidden = !m.supports_neg;
  $('#not-installed').hidden = m.status.ready;
  $('#token-warning').hidden = !(m.needs_token && !m.status.ready);

  // Alerte mmproj (encodeur visuel VLM requis pour Qwen-Image / FIBO / Klein)
  const usesVisionRefs = studioMode === 'edit' || m.outpaint_mode === 'ref_mask';
  const needMmproj = Boolean(m.mmproj_dep) && usesVisionRefs && !m.status.deps?.[m.mmproj_dep];
  $('#mmproj-warning').hidden = !needMmproj;

  // Aide contextuelle selon le mode
  if (studioMode === 'outpaint') {
    if (m.outpaint_hint) {
      $('#model-hint').textContent = m.outpaint_hint;
    } else if (m.outpaint_mode === 'ref_mask') {
      $('#model-hint').textContent =
        'Outpainting guidé par référence + masque : préserve l\'image centrale et prolonge naturellement le décor autour. Décrivez la scène complète.';
    } else {
      $('#model-hint').textContent =
        'Outpainting latent masqué (--mask) : génère les bords ajoutés autour de l\'image d\'origine. Décrivez la scène complète.';
    }
    $('#examples-wrap').hidden = true;
  } else {
    $('#model-hint').textContent = m.ref_hint || m.desc || '';
    const ex = $('#examples');
    ex.innerHTML = '';
    const examples = m.ref_examples || [];
    $('#examples-wrap').hidden = examples.length === 0;
    for (const txt of examples) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip example-chip';
      b.textContent = txt.length > 56 ? txt.slice(0, 54) + '…' : txt;
      b.title = txt;
      b.addEventListener('click', () => { $('#prompt').value = txt; $('#prompt').focus(); });
      ex.appendChild(b);
    }
  }

  // Titre du slot principal & budget VRAM refs
  const titleBase = studioMode === 'outpaint' ? 'Image à étendre' : 'Image à éditer';
  const showTag = studioMode === 'edit' && Boolean(m.ref_tag_syntax);
  $('#canvas-slot-title').innerHTML = showTag
    ? `${titleBase} <span class="tag" id="canvas-tag">@image1</span>`
    : `${titleBase} <span class="tag" id="canvas-tag" hidden>@image1</span>`;
  $('#ref-pixels-wrap').hidden = !(studioMode === 'edit' || m.outpaint_mode === 'ref_mask');

  // Quota de références additionnelles
  const maxExtra = Math.max(0, maxRefsForCurrentMode(m) - 1);
  if (refs.length > maxExtra) {
    const dropped = refs.splice(maxExtra);
    dropped.forEach(r => unlinkServerFile(r.path));
  }
  $('#refs-section').hidden = maxExtra === 0;
  renderRefs();
  refreshPromptChips();
}

$$('.studio-mode-tab').forEach(btn => {
  btn.addEventListener('click', () => setStudioMode(btn.dataset.studioMode));
});

// ===========================================================================
//  Gestion des images : upload, drag-drop, collage, suppression
// ===========================================================================
function readDimensions(url) {
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => resolve({ width: im.naturalWidth, height: im.naturalHeight, imgEl: im });
    im.onerror = () => reject(new Error('Image illisible'));
    im.src = url;
  });
}

async function uploadFiles(fileList) {
  const files = [...fileList].filter(f => f && f.type.startsWith('image/'));
  if (!files.length) return [];
  const fd = new FormData();
  files.forEach(f => fd.append('images', f));
  const m = MODELS[$('#model').value];
  if ($('#model').value) {
    fd.append('model_id', $('#model').value);
    fd.append('input_mode', studioMode === 'outpaint' && m?.outpaint_mode !== 'ref_mask' ? 'outpaint' : 'ref');
  }
  const r = await fetch('/api/upload-source-image', { method: 'POST', body: fd });
  const j = await r.json();
  if (!j.ok) { alert(j.error || 'Erreur d\'upload'); return []; }
  if (j.error) console.warn(j.error);

  const out = [];
  for (const info of j.files) {
    try {
      const d = await readDimensions(info.url);
      out.push({ path: info.filename, url: info.url, name: info.name, width: d.width, height: d.height, imgEl: d.imgEl });
    } catch (e) {
      out.push({ path: info.filename, url: info.url, name: info.name, width: 0, height: 0, imgEl: null });
    }
  }
  return out;
}

function unlinkServerFile(path) {
  if (!path) return;
  fetch('/api/delete-source-image', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: path }),
  }).catch(() => {});
}

async function setCanvasFromFiles(fileList) {
  const uploaded = await uploadFiles([fileList[0]]);
  if (!uploaded.length) return;
  if (canvas) unlinkServerFile(canvas.path);
  const { imgEl, ...rest } = uploaded[0];
  canvas = rest;
  canvasImgEl = imgEl;
  renderCanvas();
  if (fileList.length > 1) await addRefFiles([...fileList].slice(1));
}

async function adoptExistingSource(relPath) {
  const url = '/' + relPath.replace(/^source_images\//, 'source-images/');
  try {
    const d = await readDimensions(url);
    canvas = { path: relPath, url, name: relPath.split('/').pop(), width: d.width, height: d.height };
    canvasImgEl = d.imgEl;
    renderCanvas();
  } catch (e) { /* fichier absent */ }
}

async function useOutputAsCanvas(outputUrl) {
  const res = await fetch(outputUrl);
  const blob = await res.blob();
  const file = new File([blob], 'iteration.png', { type: blob.type || 'image/png' });
  await setCanvasFromFiles([file]);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function clearCanvas(unlink = true) {
  if (canvas && unlink) unlinkServerFile(canvas.path);
  canvas = null;
  canvasImgEl = null;
  renderCanvas();
}

function renderCanvas() {
  const empty = $('#canvas-empty');
  const filled = $('#canvas-filled');
  const info = $('#canvas-info');
  if (!canvas) {
    empty.hidden = false; filled.hidden = true;
    $('#canvas-img').src = '';
    info.textContent = '';
  } else {
    empty.hidden = true; filled.hidden = false;
    $('#canvas-img').src = canvas.url;
    info.textContent = canvas.width ? `${canvas.width} × ${canvas.height}` : canvas.name;
  }
  refreshPromptChips();
  updateCanvasRatioLabel();
  drawOutpaintPreview();
}

function updateCanvasRatioLabel() {
  const btn = $('#ratios .ratio[data-ratio="canvas"]');
  if (!btn) return;
  if (canvas && canvas.width) {
    const w = round16(Math.min(canvas.width, 1536));
    const h = round16(Math.min(canvas.height, 1536));
    btn.innerHTML = `Format du canvas<small>${w}×${h}</small>`;
  } else {
    btn.innerHTML = 'Format du canvas';
  }
}

async function addRefFiles(fileList) {
  const m = MODELS[$('#model').value];
  const maxExtra = Math.max(0, maxRefsForCurrentMode(m) - 1);
  const room = maxExtra - refs.length;
  if (room <= 0) {
    alert(`${m ? m.name : 'Ce modèle'} accepte au maximum ${maxRefsForCurrentMode(m)} image(s) au total.`);
    return;
  }
  const uploaded = await uploadFiles([...fileList].slice(0, room));
  refs.push(...uploaded.map(({ imgEl, ...rest }) => rest));
  renderRefs();
  refreshPromptChips();
}

function removeRef(idx) {
  const [gone] = refs.splice(idx, 1);
  if (gone) unlinkServerFile(gone.path);
  renderRefs();
  refreshPromptChips();
}

function promoteRefToCanvas(idx) {
  if (idx < 0 || idx >= refs.length) return;
  const picked = refs.splice(idx, 1)[0];
  if (canvas) refs.unshift(canvas);
  canvas = picked;
  readDimensions(canvas.url)
    .then(d => { canvasImgEl = d.imgEl; drawOutpaintPreview(); })
    .catch(() => { canvasImgEl = null; drawOutpaintPreview(); });
  renderCanvas();
  renderRefs();
  refreshPromptChips();
}

function renderRefs() {
  const m = MODELS[$('#model').value];
  const maxExtra = Math.max(0, maxRefsForCurrentMode(m) - 1);
  const strip = $('#refs-strip');
  strip.innerHTML = '';

  $('#refs-quota').textContent = maxExtra > 0 ? `(${refs.length}/${maxExtra})` : '';
  $('#add-ref-btn').disabled = refs.length >= maxExtra;
  const useTags = Boolean(m?.ref_tag_syntax);
  $('#refs-help').innerHTML = useTags
    ? 'Optionnel : ajoutez tenue, style, visage ou décor et citez-les avec <code>@image2</code>, <code>@image3</code>…'
    : 'Optionnel : ajoutez des images de style/sujet et décrivez leur rôle dans le prompt.';

  refs.forEach((r, i) => {
    const tag = `@image${i + 2}`;
    const card = document.createElement('div');
    card.className = 'ref-card';
    card.innerHTML = `
      <img src="${r.url}" alt="${r.name}">
      <div class="ref-card-bar">
        <span class="tag">${useTags ? tag : '#' + (i + 2)}</span>
        <div class="ref-card-btns">
          <button type="button" class="icon-btn promote" title="Définir comme image principale">↑</button>
          <button type="button" class="icon-btn remove" title="Retirer">×</button>
        </div>
      </div>`;
    card.querySelector('img').addEventListener('click', () => openLightbox(r.url));
    card.querySelector('.remove').addEventListener('click', () => removeRef(i));
    card.querySelector('.promote').addEventListener('click', () => promoteRefToCanvas(i));
    strip.appendChild(card);
  });
}

function refreshPromptChips() {
  const m = MODELS[$('#model').value];
  const bar = $('#ref-chips-bar');
  const box = $('#ref-chips');
  box.innerHTML = '';
  const total = (canvas ? 1 : 0) + refs.length;
  if (!m?.ref_tag_syntax || total === 0) { bar.hidden = true; return; }
  bar.hidden = false;
  for (let i = 1; i <= total; i++) {
    const tag = `@image${i}`;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip tag-chip';
    b.textContent = tag + (i === 1 ? ' (principale)' : ` (réf. ${i - 1})`);
    b.addEventListener('click', () => insertAtCursor($('#prompt'), tag + ' '));
    box.appendChild(b);
  }
}

function insertAtCursor(ta, txt) {
  const s = ta.selectionStart ?? ta.value.length;
  const e = ta.selectionEnd ?? ta.value.length;
  ta.value = ta.value.slice(0, s) + txt + ta.value.slice(e);
  ta.selectionStart = ta.selectionEnd = s + txt.length;
  ta.focus();
}

// ===========================================================================
//  Outpainting : géométrie, préréglages, aperçu interactif & génération PNG
// ===========================================================================
function computeOutpaintGeometry() {
  const srcW = (canvas && canvas.width) ? canvas.width : 1024;
  const srcH = (canvas && canvas.height) ? canvas.height : 1024;
  const scalePct = parseInt($('#op-scale').value, 10) || 100;
  const reqL = parseInt($('#op-left').value, 10) || 0;
  const reqR = parseInt($('#op-right').value, 10) || 0;
  const reqT = parseInt($('#op-top').value, 10) || 0;
  const reqB = parseInt($('#op-bottom').value, 10) || 0;
  const overlap = parseInt($('#op-overlap').value, 10) || 0;

  let scaledW = Math.max(64, Math.round(srcW * scalePct / 100));
  let scaledH = Math.max(64, Math.round(srcH * scalePct / 100));
  let padL = reqL, padR = reqR, padT = reqT, padB = reqB;

  let rawW = scaledW + padL + padR;
  let rawH = scaledH + padT + padB;

  // Garde-fou VRAM : plafonner le grand côté à MAX_OUTPAINT_SIDE (1792 px)
  const maxDim = Math.max(rawW, rawH);
  if (maxDim > MAX_OUTPAINT_SIDE) {
    const k = MAX_OUTPAINT_SIDE / maxDim;
    scaledW = Math.max(64, Math.round(scaledW * k));
    scaledH = Math.max(64, Math.round(scaledH * k));
    padL = Math.round(padL * k);
    padR = Math.round(padR * k);
    padT = Math.round(padT * k);
    padB = Math.round(padB * k);
    rawW = scaledW + padL + padR;
    rawH = scaledH + padT + padB;
  }

  // Aligner sur un multiple de 32 (compatible Qwen-Image 32px ET FLUX/SD3/FIBO 16px)
  const targetW = Math.max(128, round32(rawW));
  const targetH = Math.max(128, round32(rawH));

  // Ajuster finement les marges pour que padL + scaledW + padR === targetW au pixel près
  const diffW = targetW - (scaledW + padL + padR);
  if (padL > 0 || padR > 0) {
    const addL = padL > 0 && padR > 0 ? Math.floor(diffW / 2) : (padL > 0 ? diffW : 0);
    padL = Math.max(0, padL + addL);
    padR = Math.max(0, targetW - scaledW - padL);
  } else {
    scaledW = targetW;
  }

  const diffH = targetH - (scaledH + padT + padB);
  if (padT > 0 || padB > 0) {
    const addT = padT > 0 && padB > 0 ? Math.floor(diffH / 2) : (padT > 0 ? diffH : 0);
    padT = Math.max(0, padT + addT);
    padB = Math.max(0, targetH - scaledH - padT);
  } else {
    scaledH = targetH;
  }

  const hasExpansion = (reqL > 0 || reqR > 0 || reqT > 0 || reqB > 0);
  return {
    srcW, srcH, scalePct,
    scaledW, scaledH,
    padL, padR, padT, padB,
    targetW, targetH,
    overlap,
    hasExpansion,
  };
}

function syncOutpaintSliderLabels() {
  $('#op-left-val').textContent = $('#op-left').value;
  $('#op-right-val').textContent = $('#op-right').value;
  $('#op-top-val').textContent = $('#op-top').value;
  $('#op-bottom-val').textContent = $('#op-bottom').value;
  $('#op-scale-val').textContent = $('#op-scale').value;
  $('#op-overlap-val').textContent = $('#op-overlap').value;
}

function setOutpaintSliders({ left, right, top, bottom, scale, overlap }) {
  const clampPad = v => Math.max(0, Math.min(768, Math.round(v / 32) * 32));
  if (left != null) $('#op-left').value = clampPad(left);
  if (right != null) $('#op-right').value = clampPad(right);
  if (top != null) $('#op-top').value = clampPad(top);
  if (bottom != null) $('#op-bottom').value = clampPad(bottom);
  if (scale != null) $('#op-scale').value = Math.max(50, Math.min(100, Math.round(scale / 5) * 5));
  if (overlap != null) $('#op-overlap').value = Math.max(0, Math.min(64, Math.round(overlap / 8) * 8));
  syncOutpaintSliderLabels();
  drawOutpaintPreview();
}

function applyOutpaintPreset(kind) {
  const srcW = (canvas && canvas.width) ? canvas.width : 1024;
  const srcH = (canvas && canvas.height) ? canvas.height : 1024;
  if (kind === 'lr') {
    setOutpaintSliders({ left: 256, right: 256, top: 0, bottom: 0, scale: 100 });
  } else if (kind === 'tb') {
    setOutpaintSliders({ left: 0, right: 0, top: 256, bottom: 256, scale: 100 });
  } else if (kind === 'zoom15') {
    const scale = Math.max(srcW, srcH) > 1024 ? 75 : 85;
    const sw = srcW * scale / 100;
    const sh = srcH * scale / 100;
    const px = (sw * 0.5) / 2;
    const py = (sh * 0.5) / 2;
    setOutpaintSliders({ left: px, right: px, top: py, bottom: py, scale });
  } else if (kind === 'zoom20') {
    const scale = Math.max(srcW, srcH) >= 960 ? 60 : 75;
    const sw = srcW * scale / 100;
    const sh = srcH * scale / 100;
    const px = sw / 2;
    const py = sh / 2;
    setOutpaintSliders({ left: px, right: px, top: py, bottom: py, scale });
  } else if (kind === 'r16_9') {
    const targetRatio = 16 / 9;
    const curRatio = srcW / srcH;
    if (curRatio < targetRatio) {
      const neededW = srcH * targetRatio;
      const side = (neededW - srcW) / 2;
      setOutpaintSliders({ left: side, right: side, top: 0, bottom: 0, scale: 100 });
    } else {
      const neededH = srcW / targetRatio;
      const side = (neededH - srcH) / 2;
      setOutpaintSliders({ left: 0, right: 0, top: side, bottom: side, scale: 100 });
    }
  } else if (kind === 'r9_16') {
    const targetRatio = 9 / 16;
    const curRatio = srcW / srcH;
    if (curRatio > targetRatio) {
      const neededH = srcW / targetRatio;
      const side = (neededH - srcH) / 2;
      setOutpaintSliders({ left: 0, right: 0, top: side, bottom: side, scale: 100 });
    } else {
      const neededW = srcH * targetRatio;
      const side = (neededW - srcW) / 2;
      setOutpaintSliders({ left: side, right: side, top: 0, bottom: 0, scale: 100 });
    }
  } else if (kind === 'reset') {
    setOutpaintSliders({ left: 256, right: 256, top: 0, bottom: 0, scale: 100, overlap: 16 });
  }
}

$$('.op-preset').forEach(btn => {
  btn.addEventListener('click', () => applyOutpaintPreset(btn.dataset.op));
});

['#op-left', '#op-right', '#op-top', '#op-bottom', '#op-scale', '#op-overlap'].forEach(id => {
  $(id)?.addEventListener('input', () => {
    syncOutpaintSliderLabels();
    drawOutpaintPreview();
  });
});

// État d'aperçu pour permettre le glisser-déposer de l'image dans le cadre
let _previewLayout = null;

function drawOutpaintPreview() {
  const cv = $('#outpaint-preview-canvas');
  if (!cv || studioMode !== 'outpaint') return;
  const g = computeOutpaintGeometry();

  $('#outpaint-size-summary').textContent = `${g.targetW} × ${g.targetH}`;
  const addedPct = Math.max(0, Math.round((1 - (g.scaledW * g.scaledH) / (g.targetW * g.targetH)) * 100));
  $('#outpaint-preview-meta').textContent = canvas
    ? `${g.srcW}×${g.srcH} → ${g.targetW}×${g.targetH} (${addedPct}% généré)`
    : `Cible ${g.targetW}×${g.targetH}`;

  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);

  const margin = 16;
  const fit = Math.min((W - margin * 2) / g.targetW, (H - margin * 2) / g.targetH);
  const frameW = Math.round(g.targetW * fit);
  const frameH = Math.round(g.targetH * fit);
  const frameX = Math.round((W - frameW) / 2);
  const frameY = Math.round((H - frameH) / 2);

  const innerX = frameX + Math.round(g.padL * fit);
  const innerY = frameY + Math.round(g.padT * fit);
  const innerW = Math.round(g.scaledW * fit);
  const innerH = Math.round(g.scaledH * fit);

  _previewLayout = { fit, frameX, frameY, frameW, frameH, innerX, innerY, innerW, innerH, geom: g };

  // Damier + teinte violette dans la zone à générer (outpaint)
  const tile = 12;
  ctx.save();
  ctx.beginPath();
  ctx.rect(frameX, frameY, frameW, frameH);
  ctx.clip();
  for (let y = frameY; y < frameY + frameH; y += tile) {
    for (let x = frameX; x < frameX + frameW; x += tile) {
      const odd = ((Math.floor((x - frameX) / tile) + Math.floor((y - frameY) / tile)) % 2) === 1;
      ctx.fillStyle = odd ? '#1b1f2d' : '#131722';
      ctx.fillRect(x, y, tile, tile);
    }
  }
  ctx.fillStyle = 'rgba(124, 92, 255, 0.16)';
  ctx.fillRect(frameX, frameY, frameW, frameH);

  // Hachures diagonales discrètes pour identifier clairement la zone générée
  ctx.strokeStyle = 'rgba(124, 92, 255, 0.22)';
  ctx.lineWidth = 1;
  for (let d = -frameH; d < frameW + frameH; d += 18) {
    ctx.beginPath();
    ctx.moveTo(frameX + d, frameY);
    ctx.lineTo(frameX + d - frameH, frameY + frameH);
    ctx.stroke();
  }
  ctx.restore();

  // Image source conservée au centre / à sa position
  if (canvasImgEl && canvasImgEl.complete && canvasImgEl.naturalWidth > 0) {
    ctx.drawImage(canvasImgEl, innerX, innerY, innerW, innerH);
  } else {
    ctx.fillStyle = '#222738';
    ctx.fillRect(innerX, innerY, innerW, innerH);
    ctx.fillStyle = '#9aa3b8';
    ctx.font = '13px Segoe UI, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Image source', innerX + innerW / 2, innerY + innerH / 2);
  }

  // Zone de couture (overlap) en pointillés fins côté image conservée
  if (g.overlap > 0 && g.hasExpansion) {
    const ox = innerX + (g.padL > 0 ? Math.round(g.overlap * fit) : 0);
    const oy = innerY + (g.padT > 0 ? Math.round(g.overlap * fit) : 0);
    const ow = innerW - (g.padL > 0 ? Math.round(g.overlap * fit) : 0) - (g.padR > 0 ? Math.round(g.overlap * fit) : 0);
    const oh = innerH - (g.padT > 0 ? Math.round(g.overlap * fit) : 0) - (g.padB > 0 ? Math.round(g.overlap * fit) : 0);
    if (ow > 8 && oh > 8) {
      ctx.save();
      ctx.strokeStyle = 'rgba(46, 204, 113, 0.75)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(ox + 0.5, oy + 0.5, ow - 1, oh - 1);
      ctx.restore();
    }
  }

  // Contour net de l'image source et du cadre final
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(innerX + 0.5, innerY + 0.5, innerW - 1, innerH - 1);

  ctx.strokeStyle = '#7c5cff';
  ctx.lineWidth = 2;
  ctx.strokeRect(frameX + 1, frameY + 1, frameW - 2, frameH - 2);
}

// Glisser-déposer de l'image à l'intérieur du cadre d'aperçu Outpainting
(function setupOutpaintPreviewDrag() {
  const cv = $('#outpaint-preview-canvas');
  if (!cv) return;
  let dragging = false;
  let startX = 0, startY = 0;
  let totalPadX = 0, totalPadY = 0;
  let initPadL = 0, initPadT = 0;

  cv.addEventListener('pointerdown', e => {
    if (!_previewLayout) return;
    const rect = cv.getBoundingClientRect();
    const scaleX = cv.width / rect.width;
    const scaleY = cv.height / rect.height;
    const px = (e.clientX - rect.left) * scaleX;
    const py = (e.clientY - rect.top) * scaleY;
    totalPadX = (parseInt($('#op-left').value, 10) || 0) + (parseInt($('#op-right').value, 10) || 0);
    totalPadY = (parseInt($('#op-top').value, 10) || 0) + (parseInt($('#op-bottom').value, 10) || 0);
    if (totalPadX === 0 && totalPadY === 0) return;

    dragging = true;
    startX = px;
    startY = py;
    initPadL = parseInt($('#op-left').value, 10) || 0;
    initPadT = parseInt($('#op-top').value, 10) || 0;
    cv.setPointerCapture(e.pointerId);
  });

  cv.addEventListener('pointermove', e => {
    if (!dragging || !_previewLayout) return;
    const rect = cv.getBoundingClientRect();
    const scaleX = cv.width / rect.width;
    const scaleY = cv.height / rect.height;
    const px = (e.clientX - rect.left) * scaleX;
    const py = (e.clientY - rect.top) * scaleY;

    const dxImg = (px - startX) / _previewLayout.fit;
    const dyImg = (py - startY) / _previewLayout.fit;

    if (totalPadX > 0) {
      const maxL = Math.min(768, totalPadX);
      const minL = Math.max(0, totalPadX - 768);
      const newL = Math.max(minL, Math.min(maxL, Math.round((initPadL + dxImg) / 32) * 32));
      const newR = Math.max(0, Math.min(768, totalPadX - newL));
      $('#op-left').value = newL;
      $('#op-right').value = newR;
    }
    if (totalPadY > 0) {
      const maxT = Math.min(768, totalPadY);
      const minT = Math.max(0, totalPadY - 768);
      const newT = Math.max(minT, Math.min(maxT, Math.round((initPadT + dyImg) / 32) * 32));
      const newB = Math.max(0, Math.min(768, totalPadY - newT));
      $('#op-top').value = newT;
      $('#op-bottom').value = newB;
    }
    syncOutpaintSliderLabels();
    drawOutpaintPreview();
  });

  const endDrag = () => { dragging = false; };
  cv.addEventListener('pointerup', endDrag);
  cv.addEventListener('pointercancel', endDrag);
})();

function canvasToBlob(cv, type = 'image/png') {
  return new Promise((resolve, reject) => {
    cv.toBlob(b => (b ? resolve(b) : reject(new Error('Échec d\'encodage PNG'))), type);
  });
}

async function buildAndUploadOutpaintInputs(geom) {
  if (!canvasImgEl || !canvasImgEl.naturalWidth) {
    const d = await readDimensions(canvas.url);
    canvasImgEl = d.imgEl;
  }
  const { targetW, targetH, padL, padR, padT, padB, scaledW, scaledH, overlap } = geom;

  // 1. Canvas étendu (padded.png) :
  //    On prolonge les couleurs des bords par étirement flouté afin d'éviter toute
  //    bordure noire/grise artificielle au niveau du VAE ou de l'encodeur visuel,
  //    puis on dépose l'image source parfaitement nette à ses coordonnées exactes.
  const padCv = document.createElement('canvas');
  padCv.width = targetW;
  padCv.height = targetH;
  const pctx = padCv.getContext('2d');

  pctx.save();
  pctx.filter = 'blur(28px)';
  pctx.drawImage(canvasImgEl, -32, -32, targetW + 64, targetH + 64);
  pctx.filter = 'blur(14px)';
  const sw = canvasImgEl.naturalWidth, sh = canvasImgEl.naturalHeight;
  const edgeSampleX = Math.max(1, Math.round(sw * 0.03));
  const edgeSampleY = Math.max(1, Math.round(sh * 0.03));
  if (padL > 0) pctx.drawImage(canvasImgEl, 0, 0, edgeSampleX, sh, 0, padT, padL + 8, scaledH);
  if (padR > 0) pctx.drawImage(canvasImgEl, sw - edgeSampleX, 0, edgeSampleX, sh, padL + scaledW - 8, padT, padR + 8, scaledH);
  if (padT > 0) pctx.drawImage(canvasImgEl, 0, 0, sw, edgeSampleY, padL, 0, scaledW, padT + 8);
  if (padB > 0) pctx.drawImage(canvasImgEl, 0, sh - edgeSampleY, sw, edgeSampleY, padL, padT + scaledH - 8, scaledW, padB + 8);
  pctx.restore();

  pctx.drawImage(canvasImgEl, padL, padT, scaledW, scaledH);

  // 2. Masque binaire (mask.png) :
  //    Blanc (#FFFFFF) = zone à générer par le modèle
  //    Noir  (#000000) = zone originale préservée intacte
  //    La marge `overlap` ne mord que sur les côtés effectivement étendus (pad > 0).
  const maskCv = document.createElement('canvas');
  maskCv.width = targetW;
  maskCv.height = targetH;
  const mctx = maskCv.getContext('2d');
  mctx.fillStyle = '#ffffff';
  mctx.fillRect(0, 0, targetW, targetH);

  const inL = padL > 0 ? Math.min(overlap, Math.floor(scaledW * 0.25)) : 0;
  const inR = padR > 0 ? Math.min(overlap, Math.floor(scaledW * 0.25)) : 0;
  const inT = padT > 0 ? Math.min(overlap, Math.floor(scaledH * 0.25)) : 0;
  const inB = padB > 0 ? Math.min(overlap, Math.floor(scaledH * 0.25)) : 0;
  const keepX = padL + inL;
  const keepY = padT + inT;
  const keepW = Math.max(16, scaledW - inL - inR);
  const keepH = Math.max(16, scaledH - inT - inB);
  mctx.fillStyle = '#000000';
  mctx.fillRect(keepX, keepY, keepW, keepH);

  // 3. Aperçu "Avant" aligné au pixel près sur targetW × targetH :
  //    Permet une bascule Avant ↔ Après (touche Espace / molette) sans aucun saut d'échelle !
  const beforeCv = document.createElement('canvas');
  beforeCv.width = targetW;
  beforeCv.height = targetH;
  const bctx = beforeCv.getContext('2d');
  bctx.fillStyle = '#0c0f16';
  bctx.fillRect(0, 0, targetW, targetH);
  bctx.drawImage(canvasImgEl, padL, padT, scaledW, scaledH);
  bctx.strokeStyle = 'rgba(124, 92, 255, 0.55)';
  bctx.lineWidth = Math.max(2, Math.round(Math.max(targetW, targetH) / 512));
  bctx.setLineDash([10, 8]);
  bctx.strokeRect(padL + 1, padT + 1, scaledW - 2, scaledH - 2);

  const [paddedBlob, maskBlob, beforeBlob] = await Promise.all([
    canvasToBlob(padCv),
    canvasToBlob(maskCv),
    canvasToBlob(beforeCv),
  ]);

  if (alignedOutpaintObjectUrl) URL.revokeObjectURL(alignedOutpaintObjectUrl);
  alignedOutpaintObjectUrl = URL.createObjectURL(beforeBlob);

  // Upload simultané du canvas étendu et du masque temporaires
  const fd = new FormData();
  fd.append('images', new File([paddedBlob], 'outpaint_padded.png', { type: 'image/png' }));
  fd.append('images', new File([maskBlob], 'outpaint_mask.png', { type: 'image/png' }));
  const upRes = await fetch('/api/upload-source-image', { method: 'POST', body: fd });
  const upJson = await upRes.json();
  if (!upJson.ok || !upJson.files || upJson.files.length < 2) {
    throw new Error(upJson.error || 'Échec de préparation du masque d\'outpainting.');
  }

  return {
    paddedPath: upJson.files[0].filename,
    maskPath: upJson.files[1].filename,
    alignedBeforeUrl: alignedOutpaintObjectUrl,
  };
}

// ===========================================================================
//  Câblage des zones de drop, collage presse-papiers, sliders & ratios
// ===========================================================================
const canvasDrop = $('#canvas-drop');
$('#canvas-empty')?.addEventListener('click', () => $('#canvas-input').click());
$('#canvas-replace')?.addEventListener('click', () => $('#canvas-input').click());
$('#canvas-clear')?.addEventListener('click', () => clearCanvas(true));
$('#canvas-img')?.addEventListener('click', () => canvas && openLightbox(canvas.url));
$('#canvas-input')?.addEventListener('change', e => {
  if (e.target.files.length) setCanvasFromFiles(e.target.files);
  e.target.value = '';
});

canvasDrop?.addEventListener('dragover', e => { e.preventDefault(); canvasDrop.classList.add('dragover'); });
canvasDrop?.addEventListener('dragleave', () => canvasDrop.classList.remove('dragover'));
canvasDrop?.addEventListener('drop', e => {
  e.preventDefault(); canvasDrop.classList.remove('dragover');
  if (e.dataTransfer.files.length) setCanvasFromFiles(e.dataTransfer.files);
});

$('#add-ref-btn')?.addEventListener('click', () => $('#ref-input').click());
$('#ref-input')?.addEventListener('change', e => {
  if (e.target.files.length) addRefFiles(e.target.files);
  e.target.value = '';
});
const refsStrip = $('#refs-strip');
refsStrip?.addEventListener('dragover', e => { e.preventDefault(); refsStrip.classList.add('dragover'); });
refsStrip?.addEventListener('dragleave', () => refsStrip.classList.remove('dragover'));
refsStrip?.addEventListener('drop', e => {
  e.preventDefault(); refsStrip.classList.remove('dragover');
  if (e.dataTransfer.files.length) addRefFiles(e.dataTransfer.files);
});

window.addEventListener('paste', e => {
  const tag = document.activeElement?.tagName;
  const items = [...(e.clipboardData?.items || [])];
  const imgFiles = items
    .filter(it => it.type.startsWith('image/'))
    .map(it => it.getAsFile())
    .filter(Boolean);
  if (!imgFiles.length) return;
  if (tag !== 'TEXTAREA' && tag !== 'INPUT') e.preventDefault();
  if (!canvas) setCanvasFromFiles(imgFiles);
  else addRefFiles(imgFiles);
});

$('#steps')?.addEventListener('input', e => $('#steps-val').textContent = e.target.value);
$('#cfg')?.addEventListener('input', e => $('#cfg-val').textContent = e.target.value);
$$('#ratios .ratio').forEach(b => {
  b.addEventListener('click', () => {
    $$('#ratios .ratio').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    currentRatio = b.dataset.ratio;
  });
});

// Téléchargement du mmproj
$('#download-mmproj-btn')?.addEventListener('click', async e => {
  const btn = e.currentTarget;
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳ Téléchargement (~800 Mo)…';
  try {
    const r = await fetch('/api/download-mmproj', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: $('#model').value }),
    });
    const j = await r.json();
    if (j.ok) { await loadModels(); }
    else { alert('Erreur : ' + (j.error || 'échec')); btn.disabled = false; btn.textContent = orig; }
  } catch (err) {
    alert('Erreur : ' + err.message); btn.disabled = false; btn.textContent = orig;
  }
});

// ===========================================================================
//  Lancement de l'édition / de l'outpainting & suivi
// ===========================================================================
$('#edit-btn').addEventListener('click', async () => {
  $('#edit-error').hidden = true;
  if (!canvas) {
    $('#edit-error').hidden = false;
    $('#edit-error').textContent = studioMode === 'outpaint'
      ? 'Ajoutez d\'abord l\'image à étendre dans la zone à droite.'
      : 'Ajoutez d\'abord une image à éditer dans la zone à droite.';
    return;
  }
  const prompt = $('#prompt').value.trim();
  if (!prompt) {
    $('#edit-error').hidden = false;
    $('#edit-error').textContent = studioMode === 'outpaint'
      ? 'Décrivez la scène étendue souhaitée dans le champ de prompt.'
      : 'Décrivez la modification souhaitée dans le champ « Instruction d\'édition ».';
    return;
  }

  const m = MODELS[$('#model').value];
  let body;

  if (studioMode === 'outpaint') {
    const geom = computeOutpaintGeometry();
    if (!geom.hasExpansion) {
      $('#edit-error').hidden = false;
      $('#edit-error').textContent = 'Ajoutez au moins une marge d\'extension (Gauche, Droite, Haut ou Bas > 0 px).';
      return;
    }

    const editBtn = $('#edit-btn');
    const prevLabel = editBtn.textContent;
    editBtn.disabled = true;
    editBtn.textContent = '⏳ Préparation du masque…';
    let prepared;
    try {
      prepared = await buildAndUploadOutpaintInputs(geom);
    } catch (err) {
      editBtn.disabled = false;
      editBtn.textContent = prevLabel;
      $('#edit-error').hidden = false;
      $('#edit-error').textContent = err.message || 'Erreur lors de la préparation de l\'outpainting.';
      return;
    }
    editBtn.disabled = false;
    editBtn.textContent = prevLabel;

    const extraPaths = (m?.outpaint_mode === 'ref_mask') ? refs.map(r => r.path) : [];
    activeRunBeforeUrl = prepared.alignedBeforeUrl;
    activeRunMode = 'outpaint';

    body = {
      model_id: $('#model').value,
      quant: $('#quant').value,
      prompt,
      negative: $('#negative').value,
      ratio: '1:1',
      width: geom.targetW,
      height: geom.targetH,
      steps: $('#steps').value,
      cfg: $('#cfg').value,
      seed: $('#seed').value || null,
      batch: $('#batch').value,
      input_mode: 'outpaint',
      ref_images: [prepared.paddedPath, ...extraPaths],
      mask_image: prepared.maskPath,
      history_sources: [canvas.path, ...extraPaths],
      temp_sources: [prepared.paddedPath, prepared.maskPath],
      ref_max_pixels: parseInt($('#ref-max-pixels').value, 10) || 0,
      lora_dir: $('#lora-dir').value || null,
    };
  } else {
    activeRunBeforeUrl = canvas.url;
    activeRunMode = 'edit';
    const refPaths = [canvas.path, ...refs.map(r => r.path)];
    body = {
      model_id: $('#model').value,
      quant: $('#quant').value,
      prompt,
      negative: $('#negative').value,
      ratio: currentRatio === 'canvas' ? '1:1' : currentRatio,
      steps: $('#steps').value,
      cfg: $('#cfg').value,
      seed: $('#seed').value || null,
      batch: $('#batch').value,
      input_mode: 'ref',
      ref_images: refPaths,
      ref_max_pixels: parseInt($('#ref-max-pixels').value, 10) || 0,
      lora_dir: $('#lora-dir').value || null,
    };
    if (currentRatio === 'canvas' && canvas.width) {
      const scale = Math.min(1, 1536 / Math.max(canvas.width, canvas.height));
      body.width = round16(canvas.width * scale);
      body.height = round16(canvas.height * scale);
    }
  }

  const r = await fetch('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!j.ok) {
    $('#edit-error').hidden = false;
    $('#edit-error').textContent = j.error || 'Erreur';
    return;
  }

  lastRenderedSig = '';
  selectedResultIdx = 0;
  currentLbItems = [];
  $('#edit-btn').hidden = true;
  $('#cancel-btn').hidden = false;
  $('#results').innerHTML = '';
  $('#compare').hidden = true;
  $('#compare-modes').hidden = true;
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
  $('#log').textContent = '';
  pollStatus();
});

$('#cancel-btn').addEventListener('click', () => fetch('/api/cancel', { method: 'POST' }));
$('#log-toggle').addEventListener('click', () => { $('#log').hidden = !$('#log').hidden; });

function fmtTime(s) {
  if (!s || s < 0) return '0s';
  if (s < 60) return s.toFixed(1) + 's';
  return Math.floor(s / 60) + 'min ' + Math.round(s % 60) + 's';
}

function pollStatus() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    let j;
    try { j = await (await fetch('/api/status')).json(); } catch (e) { return; }

    const pct = Math.round((j.progress || 0) * 100);
    $('#progress-fill').style.width = pct + '%';
    let txt = j.busy ? `édition ${pct}%` : (j.error ? 'erreur' : 'terminé');
    if (j.busy && j.total_steps) txt += ` (${j.step}/${j.total_steps}) · ${fmtTime(j.elapsed)}`;
    if (j.busy && j.eta > 0 && j.step > 1) txt += ` · ~${fmtTime(j.eta)} restant`;
    $('#progress-text').textContent = txt;
    if (j.log) $('#log').textContent = j.log + ($('#log').textContent ? '\n' + $('#log').textContent : '');

    if (j.kind === 'generate' && j.result?.images?.length) showResults(j.result.images);

    if (!j.busy) {
      clearInterval(pollTimer); pollTimer = null;
      $('#edit-btn').hidden = false;
      $('#cancel-btn').hidden = true;
      if (j.error) {
        $('#edit-error').hidden = false;
        $('#edit-error').textContent = j.error;
        $('#log').hidden = false;
      } else if (j.result?.stats && j.result.images?.length) {
        const st = j.result.stats;
        $('#stats-box').hidden = false;
        $('#st-total').textContent = fmtTime(st.total_seconds);
        $('#st-denoise').textContent = fmtTime(st.denoise_seconds);
        $('#st-perstep').textContent = st.per_step_seconds + 's';
        $('#st-its').textContent = st.it_s + ' it/s';
      }
      refreshEngineBadge();
    }
  }, 1000);
}

// ===========================================================================
//  Affichage des résultats & Comparaison Avant / Après zéro rechargement
// ===========================================================================
function selectResultForCompare(idx, images) {
  selectedResultIdx = Math.max(0, Math.min(images.length - 1, idx));
  const chosen = images[selectedResultIdx];
  $('#compare-after').src = chosen.url;
  const cap = $('#compare-after-cap');
  if (cap) {
    cap.textContent = images.length > 1
      ? `Après (#${selectedResultIdx + 1}/${images.length}) · 🔍 cliquer`
      : 'Après · 🔍 cliquer';
  }
  $$('#results .result').forEach((el, i) => {
    el.classList.toggle('selected', i === selectedResultIdx);
  });
}

function showResults(images) {
  const sig = images.map(x => x.url).join('|');
  if (sig === lastRenderedSig) return;
  lastRenderedSig = sig;

  const beforeSrc = activeRunBeforeUrl || (canvas ? canvas.url : null);
  const preloadList = images.map(x => x.url);
  if (beforeSrc) preloadList.unshift(beforeSrc);
  if (typeof window.preloadImages === 'function') window.preloadImages(preloadList);

  currentLbItems = [];
  if (beforeSrc) {
    currentLbItems.push({
      src: beforeSrc,
      label: activeRunMode === 'outpaint'
        ? 'Avant (cadre d\'origine aligné)'
        : 'Avant (image source)',
      kind: 'source',
    });
  }
  images.forEach((img, idx) => {
    currentLbItems.push({
      src: img.url,
      label: `${images.length > 1 ? `Variante ${idx + 1}/${images.length} · ` : ''}seed ${img.seed}`,
      kind: 'result',
      seed: img.seed,
      downloadUrl: img.url,
    });
  });

  if (beforeSrc && images.length > 0) {
    $('#compare-before').src = beforeSrc;
    selectResultForCompare(0, images);
    $('#compare').hidden = false;
    $('#compare-modes').hidden = false;
  }

  const box = $('#results');
  box.innerHTML = '';

  if (currentLbItems.length > 1) {
    const bar = document.createElement('div');
    bar.className = 'results-nav-banner';
    bar.innerHTML = `
      <span>💡 Cliquez sur l'aperçu ou une variante : <strong>◀ ▶ / molette</strong> pour défiler, <strong>Espace</strong> pour basculer Avant ↔ Après instantanément.</span>
    `;
    box.appendChild(bar);
  }

  images.forEach((img, idx) => {
    const d = document.createElement('div');
    d.className = 'result' + (idx === selectedResultIdx ? ' selected' : '');
    d.innerHTML = `
      <img src="${img.url}" alt="">
      <div class="rbar">
        <span>${images.length > 1 ? `#${idx + 1} · ` : ''}seed ${img.seed}</span>
        <div class="rbar-actions">
          <button type="button" class="link iterate" title="Réutiliser ce résultat comme nouvelle image principale">↻ Continuer l'édition</button>
          <a class="link" href="${img.url}" download>télécharger</a>
        </div>
      </div>`;
    d.querySelector('img').addEventListener('click', () => {
      selectResultForCompare(idx, images);
      const lbStart = beforeSrc ? idx + 1 : idx;
      openLightbox(currentLbItems, lbStart);
    });
    d.querySelector('.iterate').addEventListener('click', () => useOutputAsCanvas(img.url));
    box.appendChild(d);
  });
}

// Modes d'affichage avant/après dans le panneau + ouverture plein écran zéro rechargement
$$('#compare-modes .chip[data-view]').forEach(b => {
  b.addEventListener('click', () => {
    $$('#compare-modes .chip[data-view]').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    const cmp = $('#compare');
    cmp.className = 'compare ' + b.dataset.view;
  });
});

$('#open-fullscreen-compare')?.addEventListener('click', () => {
  if (!currentLbItems.length) return;
  const hasSource = currentLbItems[0]?.kind === 'source';
  openLightbox(currentLbItems, hasSource ? selectedResultIdx + 1 : selectedResultIdx);
});

const cmpEl = $('#compare');
cmpEl?.addEventListener('mousedown', () => {
  if (cmpEl.classList.contains('hold')) cmpEl.classList.add('holding');
});
window.addEventListener('mouseup', () => cmpEl?.classList.remove('holding'));

$('#compare-before')?.addEventListener('click', () => {
  if (!currentLbItems.length) return;
  const hasSource = currentLbItems[0]?.kind === 'source';
  openLightbox(currentLbItems, 0, {
    lastResultIndex: hasSource ? selectedResultIdx + 1 : 0,
  });
});

$('#compare-after')?.addEventListener('click', () => {
  if (!currentLbItems.length) return;
  if (cmpEl.classList.contains('hold')) return;
  const hasSource = currentLbItems[0]?.kind === 'source';
  openLightbox(currentLbItems, hasSource ? selectedResultIdx + 1 : selectedResultIdx);
});

syncOutpaintSliderLabels();
loadModels();
