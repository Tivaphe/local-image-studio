/* ===== Page « Studio d'édition » =====
   Edition par references multiples : 1 canvas (image 1) + jusqu'a N-1 references.

   Contraintes heritees du moteur (sd-cli, cf. docs/ADD_MODEL_*.md) :
     - l'edition se fait avec `-r` (repetable), une fois par image ;
     - l'ORDRE des images definit <image1>, <image2>, … -> le canvas est toujours 1 ;
     - Qwen-Image 2.1 : le moteur annote les images pour le VLM, le prompt doit utiliser
       ces balises ; FLUX.2 Klein : pas de balise, designation par la position.
*/
if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

const RATIOS = window.RATIOS || { "1:1": [1024, 1024] };
const STORE_KEY = "lis_edit_prefs";

let MODELS = {};
let editModels = {};
let canvas = null;          // {path, url, name, width, height, objectUrl}
let refs = [];              // idem, dans l'ordre
let currentRatio = "1:1";
let ratioBeforeOriginal = "1:1";
let pollTimer = null;
let vramGb = 0;

// ---------------------------------------------------------------- prefs ----
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); }
  catch (e) { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify({ ...loadPrefs(), ...p })); }
  catch (e) {}
}

const currentModel = () => MODELS[$('#model').value];
const maxImages = () => {
  const m = currentModel();
  return Math.max(1, (m && m.max_ref_images) || 10);
};
const refsLimit = () => Math.max(0, maxImages() - (canvas ? 1 : 0));

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function readImageDimensions(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error("Impossible de lire les dimensions de l'image."));
    img.src = src;
  });
}

// ------------------------------------------------------------ modeles ------
async function loadModels() {
  const r = await fetch('/api/models');
  MODELS = await r.json();
  editModels = Object.fromEntries(Object.entries(MODELS)
    .filter(([, m]) => m.supports_ref_images && (m.input_modes || []).includes('ref')));

  const sel = $('#model');
  sel.innerHTML = '';
  if (Object.keys(editModels).length === 0) {
    sel.innerHTML = '<option>Aucun modèle d\'édition au registre</option>';
    return;
  }
  const prefs = loadPrefs();
  let saved = prefs.model && editModels[prefs.model] ? prefs.model : null;
  let firstReady = null;
  for (const [id, m] of Object.entries(editModels)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.name + (m.status.ready ? ' ✓' : '  (à télécharger)');
    if (!m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
    if (m.status.ready && !firstReady) firstReady = id;
  }
  sel.value = saved || firstReady || Object.keys(editModels)[0];
  sel.addEventListener('change', () => { savePrefs({ model: sel.value }); onModelChange(); });

  if (prefs.ratio && RATIOS[prefs.ratio]) { currentRatio = prefs.ratio; ratioBeforeOriginal = prefs.ratio; }
  buildRatios();
  onModelChange();
  await applyReusePayload();
}

function onModelChange() {
  const m = currentModel();
  if (!m) return;
  const q = $('#quant');
  const presetSelect = $('#preset');
  const prefs = loadPrefs();

  q.innerHTML = '';
  presetSelect.innerHTML = '<option value="default">→ Config par défaut ←</option>';
  for (const qt of m.quants) {
    const opt = document.createElement('option');
    opt.value = qt;
    const sz = m.size_gb && m.size_gb[qt] ? ` (${m.size_gb[qt]} Go)` : '';
    opt.textContent = `${qt}${sz} ${m.status.quants[qt] ? '✓ prêt' : '· à télécharger'}`;
    q.appendChild(opt);
  }
  q.value = m.default_quant;
  if (m.presets) {
    for (const [key, preset] of Object.entries(m.presets)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = preset.label || key;
      presetSelect.appendChild(opt);
    }
  }
  if (prefs.model === m.id && prefs.preset && m.presets && m.presets[prefs.preset]) {
    applyPreset(m.presets[prefs.preset]);
    presetSelect.value = prefs.preset;
  } else {
    $('#steps').value = m.defaults.steps;
    $('#cfg').value = m.defaults.cfg;
  }
  if (prefs.model === m.id && prefs.quant && m.quants.includes(prefs.quant)) q.value = prefs.quant;

  $('#steps').min = m.min_steps; $('#steps').max = m.max_steps;
  const fixedSteps = m.fixed_steps !== null && m.fixed_steps !== undefined;
  const fixedCfg = m.fixed_cfg !== null && m.fixed_cfg !== undefined;
  $('#steps').readOnly = fixedSteps;
  $('#cfg').readOnly = fixedCfg;
  if (fixedSteps) $('#steps').value = m.fixed_steps;
  if (fixedCfg) $('#cfg').value = m.fixed_cfg;
  $('#negative-box').hidden = !m.supports_neg;
  if (m.supports_neg && !$('#negative').value && window.DEFAULT_NEG) $('#negative').value = window.DEFAULT_NEG;

  $('#max-label').textContent = maxImages();
  // Exemple de reformulation dans l'index vide : le placeholder guide le debutant.
  const example = (m.ref_examples && m.ref_examples[0]) || '';
  $('#prompt').placeholder = example
    ? example
    : "décrivez ce qui doit changer, en français ou en anglais";

  renderRefHint();
  renderTagChips();
  renderRefs();
  checkMmproj();
  updateVramAdvice();
  updateTagWarning();
  updateWarn();
}

$('#quant').addEventListener('change', () => savePrefs({ model: $('#model').value, quant: $('#quant').value }));
$('#preset').addEventListener('change', e => {
  const m = currentModel();
  const key = e.target.value;
  if (key === 'default') {
    $('#steps').value = m.defaults.steps;
    $('#cfg').value = m.defaults.cfg;
  } else if (m.presets && m.presets[key]) {
    applyPreset(m.presets[key]);
  }
  savePrefs({ model: m.id, preset: key, quant: $('#quant').value });
});

function applyPreset(preset) {
  if (!preset) return;
  if (preset.steps !== undefined) $('#steps').value = preset.steps;
  if (preset.cfg !== undefined) $('#cfg').value = preset.cfg;
  if (preset.quant) {
    const opt = $('#quant').querySelector(`option[value="${preset.quant}"]`);
    if (opt) $('#quant').value = preset.quant;
  }
}

// ---------------------------------------------------------------- indices --
const orderedImages = () => (canvas ? [canvas, ...refs] : refs.slice());

function updateWarn() {
  const m = currentModel();
  const el = $('#model-warn');
  let warn = '';
  if (m && !m.status.ready) {
    const missing = Object.entries(m.status.deps || {}).filter(([, ok]) => !ok).map(([k]) => k);
    warn = missing.length
      ? `Dépendances manquantes : ${missing.join(', ')}. Téléchargez le modèle dans l'onglet Modèles.`
      : `Ce modèle n'est pas encore téléchargé. Rendez-vous dans l'onglet Modèles.`;
  }
  el.textContent = warn;
  el.hidden = !warn;
}

function renderRefHint() {
  const m = currentModel();
  const box = $('#ref-hint');
  if (!m) { box.innerHTML = ''; return; }
  const parts = [];
  if (m.ref_hint) parts.push(`<strong>${m.name} :</strong> ${m.ref_hint}`);
  if (m.ref_examples && m.ref_examples[1]) {
    parts.push(`<button class="link" id="use-example">⤷ Insérer l'exemple « ${m.ref_examples[1].slice(0, 48)}… »</button>`);
  }
  box.innerHTML = parts.join('<br>');
  const btn = $('#use-example');
  if (btn) btn.addEventListener('click', () => {
    $('#prompt').value = m.ref_examples[1];
    $('#prompt').focus();
  });
}

function renderTagChips() {
  const m = currentModel();
  const box = $('#tag-chips');
  const syntax = m && m.ref_tag_syntax;
  const images = orderedImages();
  if (!syntax || images.length < 2) { box.hidden = true; box.innerHTML = ''; return; }
  box.hidden = false;
  // La balise contient des < > : passage par innerHTML obligatoire avec echappement,
  // sinon le navigateur avalerait "<image2>" comme une balise inconnue.
  box.innerHTML = `<span class="chips-label">Citer une image :</span>` + images.map((item, i) => {
    const tag = syntax.replace('{n}', i + 1);
    const label = `${esc(tag)}${i === 0 ? ' (canvas)' : ''}`;
    return `<button class="chip chip-tag" data-tag="${esc(tag)}" title="${esc(item.name)}">${label}</button>`;
  }).join('') + `<span class="muted small">le moteur place déjà ces balises devant chaque image — elles servent à dire laquelle fait quoi</span>`;
  $$('.chip-tag', box).forEach(b => b.addEventListener('click', () => insertAtCursor(b.dataset.tag)));
}

function insertAtCursor(text) {
  const el = $('#prompt');
  const start = el.selectionStart || el.value.length;
  const end = el.selectionEnd || start;
  el.value = el.value.slice(0, start) + text + el.value.slice(end);
  el.focus();
  const pos = start + text.length;
  el.setSelectionRange(pos, pos);
}

// ----------------------------------------------- rappel des balises <imageN> --
// Pour les modeles Qwen, la syntaxe <imageN> est exigee des qu'il y a 2 images :
// sans elle le modele ne sait pas laquelle est le canvas. Rappel non bloquant.
function updateTagWarning() {
  const box = $('#tag-warning');
  const m = currentModel();
  const syntax = m && m.ref_tag_syntax;
  const images = orderedImages();
  const prompt = $('#prompt').value;
  const needs = Boolean(syntax) && images.length >= 2 && prompt.trim().length > 0
                && !/<image\d+>/i.test(prompt);
  if (!needs) { box.hidden = true; box.innerHTML = ''; return; }
  const tag = n => syntax.replace('{n}', n);
  box.hidden = false;
  box.innerHTML = `⚠️ Avec ${esc(m.name)}, dès qu'il y a plusieurs images, citez-les avec `
    + `${esc(tag(1))}, ${esc(tag(2))}… (sinon le modèle ne sait pas laquelle éditer). `
    + `<button class="link" id="fix-tags">Insérer pour moi</button>`;
  const btn = box.querySelector('#fix-tags');
  if (btn) btn.addEventListener('click', () => {
    const lines = images.map((item, i) =>
      `${tag(i + 1)} : ${i === 0 ? 'image à modifier' : 'référence ' + i}`).join('\n');
    $('#prompt').value = `${prompt.trim()}\n\n${lines}`;
    updateTagWarning();
  });
}

// ---------------------------------------------------------------- VRAM -----
async function loadGpu() {
  try {
    const r = await fetch('/api/gpu-info');
    const j = await r.json();
    vramGb = j.vram_gb || 0;
  } catch (e) {}
  updateVramAdvice();
}

function updateVramAdvice() {
  const box = $('#vram-advice');
  const total = orderedImages().length;
  if (!vramGb || total < 2) { box.hidden = true; box.textContent = ''; return; }
  const m = currentModel();
  const heavy = (m && m.vram_min_gb) || 8;
  let msg = '';
  if (vramGb < heavy) {
    msg = `⚠️ ${vramGb} Go de VRAM pour un modèle qui en recommande ${heavy} Go : avec ${total} images, `
        + `passez le budget pixels des références à 0,25 MP, ou reducez à 2-3 images.`;
  } else if (total >= 5) {
    msg = `ℹ️ ${total} images = beaucoup de tokens en plus à chaque étape. Si vous manquez de VRAM, `
        + `baissez le budget pixels des références.`;
  } else if (total >= 3) {
    msg = `ℹ️ ${total} images fournies : la génération sera plus lente et plus gourmande qu'avec une seule.`;
  }
  box.textContent = msg;
  box.hidden = !msg;
}

// ---------------------------------------------------------------- ratios ----
function getOriginalOutputSize() {
  if (!canvas) return null;
  const { width, height } = canvas;
  const scaleToArea = Math.sqrt((1024 * 1024) / (width * height));
  const scaleToMaxSide = 1344 / Math.max(width, height);
  const scale = Math.min(scaleToArea, scaleToMaxSide);
  const roundDown16 = v => Math.max(16, Math.floor(v / 16) * 16);
  return { width: roundDown16(width * scale), height: roundDown16(height * scale) };
}

function updateOriginalRatioInfo() {
  const info = $('#original-ratio-info');
  if (currentRatio !== 'original' || !canvas) { info.hidden = true; info.textContent = ''; return; }
  const out = getOriginalOutputSize();
  info.textContent = `Proportions du canvas ${canvas.width} × ${canvas.height} — sortie ${out.width} × ${out.height}`;
  info.hidden = false;
}

function buildRatios() {
  const box = $('#ratios');
  box.innerHTML = '';
  const options = Object.entries(RATIOS).map(([id, [width, height]]) => ({ id, label: id, width, height }));
  if (canvas) {
    const out = getOriginalOutputSize();
    options.unshift({ id: 'original', label: 'Original', width: out.width, height: out.height,
      title: `Format du canvas ${canvas.width} × ${canvas.height} — sortie ${out.width} × ${out.height}` });
  }
  for (const option of options) {
    const { id, label, width, height } = option;
    const d = document.createElement('div');
    d.className = 'ratio' + (id === currentRatio ? ' sel' : '');
    if (id === 'original') d.classList.add('ratio-original');
    d.title = option.title || `${label} (${width} × ${height})`;
    d.dataset.name = id;
    d.tabIndex = 0;
    const max = 26, scale = max / Math.max(width, height);
    d.innerHTML = `<i style="width:${Math.round(width * scale)}px;height:${Math.round(height * scale)}px"></i>`
                + (id === 'original' ? '<span>Original</span>' : '');
    const select = () => {
      if (id === 'original') { if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio; }
      else { ratioBeforeOriginal = id; savePrefs({ ratio: id }); }
      currentRatio = id;
      $$('.ratio').forEach(x => x.classList.toggle('sel', x === d));
      updateOriginalRatioInfo();
    };
    d.addEventListener('click', select);
    d.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
    box.appendChild(d);
  }
  updateOriginalRatioInfo();
}

// ---------------------------------------------------------------- upload ----
async function uploadFiles(files) {
  const list = [...files].filter(f => ['image/png', 'image/jpeg', 'image/webp'].includes(f.type));
  if (list.length === 0) return [];
  const fd = new FormData();
  for (const f of list) fd.append('images', f);
  const m = currentModel();
  if (m) { fd.append('model_id', m.id); fd.append('input_mode', 'ref'); }
  const r = await fetch('/api/upload-source-image', { method: 'POST', body: fd });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "Échec de l'upload");
  if (j.error) showGenError(j.error);

  const out = [];
  for (const item of j.files) {
    let dims = { width: 0, height: 0 };
    try { dims = await readImageDimensions(item.url); } catch (e) {}
    out.push({ path: item.filename, url: item.url, name: item.name,
               width: dims.width, height: dims.height, objectUrl: null, fresh: true });
  }
  return out;
}

// Ne supprime du disque que ce qui a ete uploade dans cette session :
// une image restauree depuis l'historique doit rester disponible pour les autres generations.
async function removeUploaded(item) {
  if (!item || !item.path || !item.fresh) return;
  try { await fetch('/api/delete-source-image', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: item.path }) }); }
  catch (e) {}
}

async function setCanvas(files) {
  let items;
  try { items = await uploadFiles(files); }
  catch (e) { showGenError(e.message); return; }
  if (!items.length) return;
  if (canvas) await removeUploaded(canvas);
  if (canvas && canvas.objectUrl) URL.revokeObjectURL(canvas.objectUrl);
  canvas = items[0];
  showGenError('');
  // Les fichiers surnumeritaires d'un drop sur le canvas deviennent des references.
  if (items.length > 1) refs = [...items.slice(1), ...refs].slice(0, refsLimit());
  if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio;
  currentRatio = 'original';
  refreshAll();
}

async function addRefs(files) {
  const limit = maxImages() - (canvas ? 1 : 0);
  if (limit <= 0) {
    showGenError(`Ce modèle accepte ${maxImages()} images au total : retirez des références.`);
    return;
  }
  let items;
  try { items = await uploadFiles([...files].slice(0, limit)); }
  catch (e) { showGenError(e.message); return; }
  if (!items.length) return;
  refs = [...refs, ...items].slice(0, Math.max(0, limit));
  showGenError('');
  refreshAll();
}

function removeRef(i) {
  const [gone] = refs.splice(i, 1);
  if (gone) removeUploaded(gone);
  if (currentRatio === 'original' && !canvas) currentRatio = '1:1';
  refreshAll();
}

function moveRef(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= refs.length) return;
  [refs[i], refs[j]] = [refs[j], refs[i]];
  refreshAll();
}

function refreshAll() {
  renderCanvas();
  renderRefs();
  buildRatios();
  renderTagChips();
  updateVramAdvice();
  updateTagWarning();
  const m = currentModel();
  if (m) $('#refs-order-hint').textContent = m.ref_tag_syntax
    ? "L'ordre définit <image1>, <image2>… — la image 1 est toujours le canvas (celle qui est modifiée)."
    : "L'ordre compte : « image 1 » désigne le canvas, « image 2 » la première référence.";
}

function renderCanvas() {
  const ph = $('#canvas-placeholder'), pv = $('#canvas-preview');
  if (!canvas) { ph.classList.remove('hidden'); pv.classList.add('hidden'); $('#canvas-img').src = ''; return; }
  ph.classList.add('hidden');
  pv.classList.remove('hidden');
  $('#canvas-img').src = canvas.url;
  $('#canvas-name').textContent = `${canvas.name} (${canvas.width} × ${canvas.height})`;
}

function renderRefs() {
  const grid = $('#ref-grid');
  grid.parentElement.classList.toggle('has-refs', refs.length > 0);
  const total = orderedImages().length;
  $('#refs-count').textContent = `${refs.length} / ${Math.max(0, maxImages() - 1)} référence(s)`
    + (total ? ` — ${total} image(s) au total` : '');
  $('#clear-refs-btn').hidden = refs.length === 0;
  grid.innerHTML = '';
  refs.forEach((item, i) => {
    const d = document.createElement('div');
    d.className = 'ref-card';
    d.innerHTML = `
      <img src="${esc(item.url)}" alt="">
      <span class="idx-badge">${i + 2}</span>
      <div class="ref-card-name" title="${esc(item.name)}">${esc(item.name)}</div>
      <div class="ref-card-actions">
        <button class="link" data-act="left" ${i === 0 ? 'disabled' : ''}>◀</button>
        <button class="link" data-act="right" ${i === refs.length - 1 ? 'disabled' : ''}>▶</button>
        <button class="link danger" data-act="del">✕</button>
      </div>`;
    d.querySelector('img').addEventListener('click', e => openLightbox(e.target.src));
    d.querySelector('[data-act=left]').addEventListener('click', () => moveRef(i, -1));
    d.querySelector('[data-act=right]').addEventListener('click', () => moveRef(i, +1));
    d.querySelector('[data-act=del]').addEventListener('click', () => removeRef(i));
    grid.appendChild(d);
  });
  const add = document.createElement('button');
  add.className = 'ref-card ref-add';
  add.innerHTML = `<span>＋</span><small>référence</small>`;
  add.addEventListener('click', () => $('#refs-input').click());
  if (refs.length >= Math.max(0, maxImages() - (canvas ? 1 : 0))) add.disabled = true;
  grid.appendChild(add);
}

function showGenError(msg) {
  const el = $('#gen-error');
  el.textContent = msg;
  el.hidden = !msg;
}

// ------- branchements upload (canvas) -------
$('#canvas-img').addEventListener('click', e => openLightbox(e.target.src));

$('#canvas-input').addEventListener('change', e => {
  if (e.target.files.length) setCanvas(e.target.files).finally(() => { e.target.value = ''; });
});
$('#canvas-placeholder').addEventListener('click', () => $('#canvas-input').click());
$('#canvas-replace').addEventListener('click', e => { e.stopPropagation(); $('#canvas-input').click(); });
$('#canvas-remove').addEventListener('click', async e => {
  e.stopPropagation();
  if (canvas) { await removeUploaded(canvas); if (canvas.objectUrl) URL.revokeObjectURL(canvas.objectUrl); }
  canvas = null;
  if (currentRatio === 'original') currentRatio = RATIOS[ratioBeforeOriginal] ? ratioBeforeOriginal : '1:1';
  refreshAll();
});

// ------- branchements upload (references) -------
$('#refs-input').addEventListener('change', e => {
  if (e.target.files.length) addRefs(e.target.files).finally(() => { e.target.value = ''; });
});
$('#add-refs-btn').addEventListener('click', () => $('#refs-input').click());
$('#refs-drop')?.querySelector('.upload-placeholder')?.addEventListener('click', () => $('#refs-input').click());
$('#clear-refs-btn').addEventListener('click', async () => {
  for (const item of refs) await removeUploaded(item);
  refs = [];
  refreshAll();
});

function wireDropzone(el, handler) {
  if (!el) return;
  el.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); el.classList.add('dragover'); });
  el.addEventListener('dragleave', () => el.classList.remove('dragover'));
  el.addEventListener('drop', e => {
    e.preventDefault();
    e.stopPropagation();
    el.classList.remove('dragover');
    if (e.dataTransfer.files.length) handler(e.dataTransfer.files);
  });
}
wireDropzone($('#canvas-drop'), setCanvas);
wireDropzone($('#refs-drop'), addRefs);
// Un drop n'importe où sur le panneau va dans les references si le canvas est deja plein.
wireDropzone($('.edit-panel'), files => (canvas ? addRefs(files) : setCanvas(files)));

// ---------------------------------------------------------------- mmproj ----
async function checkMmproj() {
  const m = currentModel();
  const box = $('#mmproj-status');
  if (!m || !m.mmproj_dep) { box.classList.add('hidden'); return; }
  try {
    const r = await fetch(`/api/mmproj-status?model_id=${encodeURIComponent(m.id)}`);
    const j = await r.json();
    const btn = $('#mmproj-download-btn'), msg = $('#mmproj-msg');
    box.classList.remove('hidden');
    if (j.downloaded) {
      msg.textContent = "✓ mmproj disponible — prêt pour l'édition !";
      msg.classList.add('ok');
      btn.hidden = true;
    } else {
      msg.textContent = "⚠️ mmproj manquant — sans lui, l'édition par référence échoue (1,2 Go)";
      msg.classList.remove('ok');
      btn.hidden = false;
    }
  } catch (e) {}
}

$('#mmproj-download-btn')?.addEventListener('click', async e => {
  const btn = e.currentTarget, msg = $('#mmproj-msg');
  btn.disabled = true; btn.textContent = '…'; msg.textContent = 'Téléchargement en cours (1,2 Go)…';
  try {
    const r = await fetch('/api/download-mmproj', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: $('#model').value })
    });
    const j = await r.json();
    if (j.ok) { msg.textContent = '✓ mmproj téléchargé'; msg.classList.add('ok'); btn.hidden = true; }
    else { msg.textContent = '✗ ' + (j.error || 'Erreur'); btn.disabled = false; btn.textContent = 'Réessayer'; }
  } catch (err) {
    msg.textContent = '✗ ' + err.message; btn.disabled = false; btn.textContent = 'Réessayer';
  }
});

// ---------------------------------------------------------------- generation
$('#generate-btn').addEventListener('click', async () => {
  const m = currentModel();
  showGenError('');
  if (!m) return;
  if (!canvas) { showGenError('Ajoutez d\u2019abord l\u2019image \u00e0 modifier (\u00e9tape 2).'); return; }
  if (!m.status.ready) { showGenError(`Le modèle « ${m.name} » n'est pas prêt. Téléchargez-le dans l'onglet Modèles.`); return; }
  const prompt = $('#prompt').value.trim();
  if (!prompt) { showGenError("Décrivez ce qui doit changer (étape 4) — l'instruction est obligatoire."); return; }

  const images = orderedImages();
  const limit = maxImages();
  if (images.length > limit) { showGenError(`${limit} images maximum avec ce modèle.`); return; }

  const body = {
    model_id: m.id,
    quant: $('#quant').value,
    prompt,
    negative: $('#negative').value,
    ratio: currentRatio === 'original' ? '1:1' : currentRatio,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
    input_mode: 'ref',
    ref_images: images.map(x => x.path),
    ref_max_pixels: $('#ref-budget').value === 'auto' ? null : parseInt($('#ref-budget').value, 10),
  };
  if (currentRatio === 'original' && canvas) {
    const out = getOriginalOutputSize();
    body.width = out.width; body.height = out.height;
  }

  const r = await fetch('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const j = await r.json();
  if (!j.ok) { showGenError(j.error || 'Erreur'); return; }
  $('#compare-before').src = canvas.url;
  $('#compare').hidden = true;
  $('#generate-btn').disabled = true;
  $('#cancel-btn').hidden = false;
  $('#results').innerHTML = '';
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
  $('#log').textContent = '';
  $('#log').hidden = false;
  pollStatus();
});

$('#cancel-btn').addEventListener('click', async () => { await fetch('/api/cancel', { method: 'POST' }); });
$('#log-toggle').addEventListener('click', () => { $('#log').hidden = !$('#log').hidden; });
$('#prompt').addEventListener('input', updateTagWarning);
$('#batch').addEventListener('input', e => {
  const v = parseInt(e.target.value);
  $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
});

// ---------------------------------------------------------------- suivi -----
function fmtTime(s) {
  if (!s || s < 0) return '0s';
  if (s < 60) return s.toFixed(1) + 's';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m + 'min ' + r + 's';
}

function pollStatus() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    let j;
    try { j = await (await fetch('/api/status')).json(); } catch (e) { return; }

    const pct = Math.round((j.progress || 0) * 100);
    $('#progress-fill').style.width = pct + '%';
    const elapsed = j.elapsed || 0, eta = j.eta || 0;
    let txt;
    if (j.busy && j.kind === 'generate') {
      txt = `édition ${pct}%`;
      if (j.total_steps) txt += ` (${j.step}/${j.total_steps})`;
      txt += ` — ${fmtTime(elapsed)} écoulé`;
      if (eta > 0 && j.step > 1) txt += ` — ~${fmtTime(eta)} restants`;
    } else if (j.busy) txt = j.log || 'en cours…';
    else if (j.error) txt = 'erreur';
    else txt = 'terminé';
    $('#progress-text').textContent = txt;
    if (j.log) $('#log').textContent = j.log + ($('#log').textContent ? '\n' + $('#log').textContent : '');

    if (!j.busy) {
      clearInterval(pollTimer); pollTimer = null;
      $('#generate-btn').disabled = false;
      $('#cancel-btn').hidden = true;
      const imgs = (j.result && j.result.images) || [];
      if (j.error) { showGenError(j.error); $('#log').hidden = false; }
      else if (j.kind === 'generate') {
        if (imgs.length) {
          showResults(imgs);
          const stats = (j.result && j.result.stats) || j.stats;
          if (stats) showStats(stats);
        } else if (!(j.result && j.result.cancelled)) {
          showGenError(j.log || "Aucune image n'a été produite.");
          $('#log').hidden = false;
        }
      }
    }
  }, 1000);
}

function showStats(stats) {
  const box = $('#stats-box');
  box.hidden = false;
  $('#st-total').textContent = fmtTime(stats.total_seconds);
  $('#st-denoise').textContent = fmtTime(stats.denoise_seconds);
  $('#st-perstep').textContent = stats.per_step_seconds + 's';
  $('#st-its').textContent = stats.it_s + ' it/s';
  $('#st-refs').textContent = orderedImages().length + ' image(s)';
}

function showResults(images) {
  const box = $('#results');
  box.innerHTML = '';
  images.forEach(img => {
    const d = document.createElement('div');
    d.className = 'result';
    d.innerHTML = `
      <img src="${img.url}?t=${Date.now()}" alt="">
      <div class="rbar"><span>seed ${img.seed}</span>
        <a class="link" href="${img.url}" download>télécharger</a></div>`;
    d.querySelector('img').addEventListener('click', e => openLightbox(e.target.src));
    box.appendChild(d);
  });
  if (canvas && images.length) {
    $('#compare').hidden = false;
    $('#compare-after').src = images[0].url;
  }
}

// ---------------------------------------------------------------- enrichir --
async function doLlm(mode) {
  const btn = mode === 'rephrase' ? $('#rephrase-btn') : $('#enrich-btn');
  const status = $('#enrich-status'), el = $('#prompt');
  const txt = el.value.trim();
  if (!txt) { status.textContent = 'Écrivez d\u2019abord une instruction.'; return; }
  const original = btn.textContent;
  btn.disabled = true; btn.textContent = '…'; status.textContent = 'en cours…';
  try {
    const r = await fetch(mode === 'translate' ? '/api/translate' : '/api/enrich', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: txt, mode })
    });
    const j = await r.json();
    if (!j.ok) { status.textContent = ''; alert(j.error || 'Erreur'); return; }
    el.value = j.prompt;
    status.textContent = mode === 'translate' ? 'traduit en anglais' : 'instruction enrichie — modifiable';
  } catch (e) { status.textContent = ''; alert('Erreur: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = original; }
}
$('#enrich-btn').addEventListener('click', () => doLlm('enrich'));
$('#rephrase-btn').addEventListener('click', () => doLlm('rephrase'));
$('#translate-btn').addEventListener('click', () => doLlm('translate'));

// ------------------------------------------------------------- prompt neg --
(async function loadDefaultNegative() {
  try {
    const j = await (await fetch('/api/default-negative')).json();
    window.DEFAULT_NEG = j.negative;
    const m = currentModel();
    if (m && m.supports_neg && !$('#negative').value) $('#negative').value = j.negative;
  } catch (e) {}
})();

// ------------------------------------------------- reprise depuis l'historique
async function applyReusePayload() {
  let payload = null;
  try { payload = JSON.parse(sessionStorage.getItem('edit_reuse') || 'null'); } catch (e) {}
  if (!payload) return;
  sessionStorage.removeItem('edit_reuse');
  if (payload.model && MODELS[payload.model]) {
    $('#model').value = payload.model;
    onModelChange();
  }
  if (payload.prompt !== undefined) $('#prompt').value = payload.prompt || '';
  if (payload.negative !== undefined) $('#negative').value = payload.negative || '';
  if (payload.steps) $('#steps').value = payload.steps;
  if (payload.cfg) $('#cfg').value = payload.cfg;
  if (payload.seed) $('#seed').value = payload.seed;
  const sources = payload.source_images || [];
  for (const [i, src] of sources.entries()) {
    let dims = { width: 0, height: 0 };
    try { dims = await readImageDimensions(src.url); } catch (e) {}
    const item = { path: src.filename, url: src.url, name: src.name || `image ${i + 1}`,
                   width: dims.width, height: dims.height, objectUrl: null };
    if (i === 0) canvas = item; else refs.push(item);
  }
  if (sources.length) {
    currentRatio = 'original';
    showGenError('');
  }
  refreshAll();
}

loadModels();
loadGpu();
