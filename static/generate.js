/* ===== Page Generer =====
   Multi-images support :
   - ref_images : jusqu'à 10 pour Qwen-Image 2.1, 4 pour FLUX.2 Klein
   - init_image : img2img classique
   - control_image : pose / contrôle
   - mask_image : masque inpainting
   FIX 4 : memorise le modele selectionne (localStorage) et le restaure.
   FIX 3 : affiche les stats de generation (chrono live + stats finales).
*/

// Fallback: $ et $$ en cas de chargement avant app.js
if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

const RATIOS = window.RATIOS || { "1:1": [1024, 1024] };

let MODELS = {};
let currentRatio = "1:1";
let pollTimer = null;

// ---------- multi-images state ----------
let refImages = []; // {filename, url, name}
let initImage = null; // {filename, url, name}
let controlImage = null;
let maskImage = null;
// legacy single
let uploadedImagePath = null;

// ---------- memoire de la selection ----------
const STORE_KEY = "lis_generate_prefs";

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); }
  catch (e) { return {}; }
}
function savePrefs(p) {
  try {
    const cur = loadPrefs();
    localStorage.setItem(STORE_KEY, JSON.stringify({ ...cur, ...p }));
  } catch (e) {}
}

async function loadModels() {
  const r = await fetch('/api/models');
  MODELS = await r.json();
  const sel = $('#model');
  if (!sel) return;
  sel.innerHTML = '';

  const prefs = loadPrefs();
  let savedModel = prefs.model;
  if (!savedModel || !MODELS[savedModel]) savedModel = null;

  let firstReady = null;
  for (const [id, m] of Object.entries(MODELS)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.name + (m.status.ready ? ' ✓' : '  (à télécharger)');
    if (!m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
    if (m.status.ready && !firstReady) firstReady = id;
  }
  sel.value = savedModel || firstReady || Object.keys(MODELS)[0];
  sel.addEventListener('change', () => {
    savePrefs({ model: sel.value, quant: $('#quant')?.value });
    onModelChange();
  });

  const quantSelect = $('#quant');
  if (quantSelect) {
    quantSelect.addEventListener('change', () => {
      savePrefs({ model: sel.value, quant: quantSelect.value });
    });
  }

  const presetSelect = $('#preset');
  if (presetSelect) {
    presetSelect.addEventListener('change', () => {
      const modelId = sel.value;
      const m = MODELS[modelId];
      if (!m) return;
      const key = presetSelect.value;
      if (key === 'default') {
        $('#steps').value = m.defaults.steps;
        $('#cfg').value = m.defaults.cfg;
        if (quantSelect) quantSelect.value = m.default_quant;
        savePrefs({ model: modelId, preset: 'default', quant: quantSelect ? quantSelect.value : null });
      } else if (m.presets && m.presets[key]) {
        applyPreset(m.presets[key]);
        savePrefs({ model: modelId, preset: key, quant: quantSelect ? quantSelect.value : null });
      }
    });
  }

  buildRatios();
  if (prefs.ratio && RATIOS[prefs.ratio]) currentRatio = prefs.ratio;
    buildRatios();
  buildRatiosApply();

  // Restauration checkbox conserver format
  const keepChk = $('#keep-input-format');
  if (keepChk) {
    const prefsKeep = loadPrefs();
    if (prefsKeep.keep_input_format) keepChk.checked = true;
    if (currentRatio === 'source') keepChk.checked = true;
    keepChk.addEventListener('change', () => {
      savePrefs({ keep_input_format: keepChk.checked });
      if (keepChk.checked) {
        currentRatio = 'source';
        buildRatiosApply();
      } else {
        if (currentRatio === 'source') {
          currentRatio = '1:1';
          buildRatiosApply();
          savePrefs({ ratio: currentRatio });
        }
      }
      if (typeof updateSourceFormatHint === 'function') updateSourceFormatHint();
    });
  }

  onModelChange();;

  const reuse = sessionStorage.getItem('reuse');
  if (reuse) {
    const p = JSON.parse(reuse);
    sessionStorage.removeItem('reuse');
    if (MODELS[p.model]) sel.value = p.model;
    onModelChange();
    $('#prompt').value = p.prompt || '';
    $('#negative').value = p.neg || '';
    $('#steps').value = p.steps || '';
    $('#cfg').value = p.cfg || '';
    $('#seed').value = p.seed || '';
  }
}

function buildRatios() {
  const box = $('#ratios');
  if (!box) return;
  box.innerHTML = '';
  for (const [name, [w, h]] of Object.entries(RATIOS)) {
    const d = document.createElement('div');
    d.className = 'ratio' + (name === currentRatio ? ' sel' : '');
    d.dataset.name = name;
    if (name === 'source') {
      d.title = `Source - format de l'image d'entrée (auto)`;
      d.innerHTML = `<i style="width:26px;height:26px;display:grid;place-items:center;font-size:10px;font-weight:700;color:var(--accent2);background:transparent;border:1px dashed var(--accent2);">SRC</i>`;
    } else {
      d.title = `${name}  (${w}x${h})`;
      const max = 26;
      const sc = max / Math.max(w, h);
      const iw = Math.round(w * sc), ih = Math.round(h * sc);
      d.innerHTML = `<i style="width:${iw}px;height:${ih}px"></i>`;
    }
    d.addEventListener('click', () => {
      currentRatio = name;
      savePrefs({ ratio: name });
      $$('.ratio').forEach(x => x.classList.remove('sel'));
      d.classList.add('sel');
      if (name === 'source') {
        const keepChk = $('#keep-input-format');
        if (keepChk) keepChk.checked = true;
      }
    });
    box.appendChild(d);
  }
}
function buildRatiosApply() {
  $$('.ratio').forEach(x => {
    x.classList.toggle('sel', x.dataset.name === currentRatio);
  });
}

function onModelChange() {
  const modelId = $('#model').value;
  const m = MODELS[modelId];
  if (!m) return;
  const q = $('#quant');
  const presetSelect = $('#preset');
  if (!q || !presetSelect) return;
  q.innerHTML = '';
  presetSelect.innerHTML = '<option value="default">→ Config par défaut ←</option>';

  const prefs = loadPrefs();
  for (const qt of m.quants) {
    const opt = document.createElement('option');
    opt.value = qt;
    const have = m.status.quants[qt];
    const sz = m.size_gb && m.size_gb[qt] ? ` (${m.size_gb[qt]} Go)` : '';
    opt.textContent = `${qt}${sz} ${have ? '✓ prêt' : '· à télécharger'}`;
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

  const savedPreset = (prefs.model === modelId) ? prefs.preset : null;
  if (savedPreset && m.presets && m.presets[savedPreset]) {
    applyPreset(m.presets[savedPreset]);
    presetSelect.value = savedPreset;
  } else {
    $('#steps').value = m.defaults.steps;
    $('#cfg').value = m.defaults.cfg;
    if (prefs.quant && m.quants.includes(prefs.quant) && prefs.model === modelId) {
      q.value = prefs.quant;
    }
    presetSelect.value = 'default';
  }

  $('#steps').min = m.min_steps; $('#steps').max = m.max_steps;
  $('#negative').parentElement.style.display = m.supports_neg ? '' : 'none';
  const negEl = $('#negative');
  if (m.supports_neg && !negEl.value && window.DEFAULT_NEG) {
    negEl.value = window.DEFAULT_NEG;
  }
  let warn = '';
  if (!m.status.ready) {
    const missingDeps = Object.entries(m.status.deps || {})
      .filter(([_, ok]) => !ok)
      .map(([k, _]) => k);
    if (missingDeps.length > 0) {
      warn = `Dépendances manquantes pour ce modèle : ${missingDeps.join(', ')}. Rendez-vous dans l'onglet Modèles pour les télécharger.`;
    } else {
      warn = `Ce modèle n'est pas encore téléchargé. Rendez-vous dans l'onglet Modèles.`;
    }
  }
  $('#gen-error').textContent = warn;
  $('#gen-error').hidden = !warn;

  // --- Capacités multi-images ---
  const capHint = $('#model-capabilities-hint');
  if (capHint) {
    let caps = [];
    if (m.supports_ref) caps.push(`📎 ${m.max_ref_images || 4} images de référence`);
    if (m.supports_init) caps.push(`🎨 image initiale (img2img)`);
    if (m.supports_control) caps.push(`🧍 pose/contrôle`);
    if (m.supports_mask) caps.push(`🎭 masque`);
    if (m.supports_transparency) caps.push(`✨ transparence RGBA`);
    if (caps.length === 0) caps.push(`Texte seul (pas d'image d'entrée pour ce modèle)`);
    capHint.innerHTML = `<strong>${m.name}</strong> supporte : ${caps.join(' · ')}`;
  }

  // Visibilité des sections selon capacités
  const refDetails = $('#ref-images-details');
  const initDetails = $('#init-image-details');
  const controlDetails = $('#control-image-details');
  const maskDetails = $('#mask-image-details');

  if (refDetails) {
    // Toujours afficher ref pour Qwen et Flux2, mais griser si non supporté
    const showRef = m.supports_ref || modelId.includes('qwen') || modelId.includes('flux2') || m.arch === 'qwen_image' || m.arch === 'flux2';
    refDetails.style.display = showRef ? '' : 'none';
    // Mettre à jour le placeholder avec max
    const maxRef = m.max_ref_images || (m.supports_ref ? 4 : 0);
    if (maxRef) {
      const small = refDetails.querySelector('small.muted');
      if (small) small.textContent = `Jusqu'à ${maxRef} images - ${modelId === 'qwen-image-2.1' ? 'Qwen-Image 2.1 supporte jusqu\'à 10 images' : 'FLUX.2 Klein jusqu\'à 4'}`;
    }
    // Badge
    updateRefBadge();
  }

  if (initDetails) {
    initDetails.style.display = m.supports_init ? '' : 'none';
    const strengthField = $('#strength-field');
    if (strengthField) strengthField.style.display = m.supports_init ? '' : 'none';
  }

  if (controlDetails) {
    // Afficher control pour SD3 ou si support_control, mais aussi proposer pour tous en avancé
    // On affiche pour SD3 et on laisse visible en mode avancé pour autres
    if (m.supports_control) {
      controlDetails.style.display = '';
    } else {
      // Pour Qwen/Flux, on cache par défaut mais on peut laisser visible si l'utilisateur veut
      // On affiche quand même mais avec hint que c'est pour SD
      controlDetails.style.display = m.arch === 'sd3' || m.supports_control ? '' : 'none';
    }
    const csField = $('#control-strength-field');
    if (csField) csField.style.display = m.supports_control ? '' : 'none';
  }

  if (maskDetails) {
    maskDetails.style.display = m.supports_mask ? '' : 'none';
  }

  // Transparence RGBA pour Qwen-Image 2.1
  const transpField = $('#transparency-field');
  if (transpField) {
    transpField.style.display = m.supports_transparency ? '' : 'none';
  }

  checkMmproj();
}

function applyPreset(preset) {
  if (!preset) return;
  if (preset.steps !== undefined) $('#steps').value = preset.steps;
  if (preset.cfg !== undefined) $('#cfg').value = preset.cfg;
  if (preset.quant) {
    const q = $('#quant');
    if (q) {
      const opt = q.querySelector(`option[value="${preset.quant}"]`);
      if (opt) q.value = preset.quant;
    }
  }
}

$('#batch')?.addEventListener('input', e => {
  const v = parseInt(e.target.value);
  $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
});

// ---------- Gestion multi-images de référence ----------
function updateRefBadge() {
  const badge = $('#ref-count-badge');
  if (badge) badge.textContent = `${refImages.length}`;
}

function renderRefGrid() {
  const grid = $('#ref-images-grid');
  if (!grid) return;
  grid.innerHTML = '';
  refImages.forEach((img, idx) => {
    const div = document.createElement('div');
    div.className = 'ref-item';
    div.innerHTML = `
      <div class="ref-thumb"><img src="${img.url}" alt="ref ${idx+1}"></div>
      <div class="ref-meta">
        <span class="ref-index">Image ${idx+1}</span>
        <span class="ref-name">${img.name}</span>
        <button class="btn ghost small ref-remove" data-idx="${idx}">✕ Retirer</button>
      </div>
    `;
    grid.appendChild(div);
  });
  grid.querySelectorAll('.ref-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const i = parseInt(btn.dataset.idx);
      refImages.splice(i, 1);
      renderRefGrid();
      updateRefBadge();
      if (typeof updateSourceFormatHint === 'function') updateSourceFormatHint();
    });
  });
  updateRefBadge();
  if (typeof updateSourceFormatHint === 'function') updateSourceFormatHint();
}

function updateSourceFormatHint() {
  const hint = $('#model-capabilities-hint');
  if (!hint) return;
  let first = null;
  if (refImages.length > 0) first = refImages[0];
  else if (initImage) first = initImage;
  else if (controlImage) first = controlImage;
  const keepChk = $('#keep-input-format');
  const keepChecked = keepChk?.checked;
  if (first && first.url) {
    const img = new Image();
    img.onload = () => {
      const w = img.width, h = img.height;
      const roundedW = Math.floor(w/16)*16, roundedH = Math.floor(h/16)*16;
      const modelId = $('#model')?.value;
      const isQwen21 = modelId === 'qwen-image-2.1';
      const finalW = isQwen21 ? Math.floor(w/32)*32 : roundedW;
      const finalH = isQwen21 ? Math.floor(h/32)*32 : roundedH;
      const info = document.createElement('div');
      info.style.marginTop = '6px';
      info.style.fontSize = '12px';
      info.style.color = 'var(--muted)';
      info.innerHTML = `📐 Image d'entrée détectée : <strong>${w}x${h}</strong> → génération : <strong>${finalW}x${finalH}</strong> ${isQwen21 ? '(arrondi 32px pour Qwen-Image 2.1)' : '(arrondi 16px)'} ${keepChecked ? '✅ format conservé' : '⚠️ cocher \"Conserver le format\" pour utiliser'}`;
      const old = hint.querySelector('.source-dims-info');
      if (old) old.remove();
      info.className = 'source-dims-info';
      hint.appendChild(info);
    };
    img.src = first.url;
  }
}

async function handleRefFiles(files) {
  const modelId = $('#model')?.value;
  const m = MODELS[modelId];
  const maxRef = m?.max_ref_images || 10;
  const remaining = maxRef - refImages.length;
  if (files.length > remaining) {
    alert(`Ce modèle supporte max ${maxRef} images de référence. Vous avez déjà ${refImages.length}, vous essayez d'ajouter ${files.length}. Seulement ${remaining} seront ajoutées.`);
  }
  const toUpload = Array.from(files).slice(0, remaining);
  if (toUpload.length === 0) return;

  const formData = new FormData();
  toUpload.forEach(f => formData.append('images', f));

  try {
    const r = await fetch('/api/upload-images', { method: 'POST', body: formData });
    const j = await r.json();
    if (!j.ok) {
      alert(j.error || 'Erreur upload');
      return;
    }
    j.images.forEach((imgInfo, i) => {
      refImages.push({
        filename: imgInfo.filename,
        url: imgInfo.url,
        name: toUpload[i]?.name || `image_${refImages.length+1}`
      });
    });
    renderRefGrid();
  } catch (e) {
    alert('Erreur: ' + e.message);
  }
}

// Ref upload area events
const refInput = $('#ref-images-input');
const refArea = $('#ref-images-upload-area');
const refPlaceholder = $('#ref-upload-placeholder');

refInput?.addEventListener('change', e => {
  if (e.target.files.length > 0) handleRefFiles(e.target.files);
  e.target.value = '';
});
refPlaceholder?.addEventListener('click', () => refInput?.click());

if (refArea) {
  refArea.addEventListener('dragover', e => { e.preventDefault(); refArea.classList.add('dragover'); });
  refArea.addEventListener('dragleave', () => refArea.classList.remove('dragover'));
  refArea.addEventListener('drop', e => {
    e.preventDefault();
    refArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleRefFiles(e.dataTransfer.files);
  });
}

// ---------- Gestion image initiale (init) ----------
let initImagePath = null;
async function handleInitFile(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append('image', file);
  try {
    const r = await fetch('/api/upload-image?type=init', { method: 'POST', body: formData });
    const j = await r.json();
    if (!j.ok) { alert(j.error); return; }
    initImage = { filename: j.filename, url: j.url, name: file.name };
    initImagePath = j.filename;
    $('#init-image-path').value = j.filename;
    $('#init-preview-img').src = URL.createObjectURL(file);
    $('#init-preview-name').textContent = file.name;
    $('#init-upload-placeholder').classList.add('hidden');
    $('#init-upload-preview').classList.remove('hidden');
    // compat legacy
    uploadedImagePath = j.filename;
    $('#source-image-path').value = j.filename;
    if (typeof updateSourceFormatHint === 'function') updateSourceFormatHint();
  } catch (e) { alert(e.message); }
}

$('#init-image-input')?.addEventListener('change', e => {
  if (e.target.files.length > 0) handleInitFile(e.target.files[0]);
  e.target.value = '';
});
$('#init-upload-placeholder')?.addEventListener('click', () => $('#init-image-input').click());
const initArea = $('#init-upload-area');
if (initArea) {
  initArea.addEventListener('dragover', e => { e.preventDefault(); initArea.classList.add('dragover'); });
  initArea.addEventListener('dragleave', () => initArea.classList.remove('dragover'));
  initArea.addEventListener('drop', e => {
    e.preventDefault(); initArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleInitFile(e.dataTransfer.files[0]);
  });
}
$('#remove-init-image')?.addEventListener('click', () => {
  initImage = null; initImagePath = null;
  $('#init-image-path').value = ''; $('#init-image-input').value = '';
  $('#init-upload-placeholder').classList.remove('hidden');
  $('#init-upload-preview').classList.add('hidden');
  $('#init-preview-img').src = '';
  uploadedImagePath = null;
  $('#source-image-path').value = '';
});

// ---------- Gestion control image (pose) ----------
async function handleControlFile(file) {
  if (!file) return;
  const fd = new FormData(); fd.append('image', file);
  try {
    const r = await fetch('/api/upload-image?type=control', { method: 'POST', body: fd });
    const j = await r.json();
    if (!j.ok) { alert(j.error); return; }
    controlImage = { filename: j.filename, url: j.url, name: file.name };
    $('#control-image-path').value = j.filename;
    $('#control-preview-img').src = URL.createObjectURL(file);
    $('#control-preview-name').textContent = file.name;
    $('#control-upload-placeholder').classList.add('hidden');
    $('#control-upload-preview').classList.remove('hidden');
  } catch (e) { alert(e.message); }
}
$('#control-image-input')?.addEventListener('change', e => {
  if (e.target.files.length > 0) handleControlFile(e.target.files[0]);
  e.target.value = '';
});
$('#control-upload-placeholder')?.addEventListener('click', () => $('#control-image-input').click());
const controlArea = $('#control-upload-area');
if (controlArea) {
  controlArea.addEventListener('dragover', e => { e.preventDefault(); controlArea.classList.add('dragover'); });
  controlArea.addEventListener('dragleave', () => controlArea.classList.remove('dragover'));
  controlArea.addEventListener('drop', e => {
    e.preventDefault(); controlArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleControlFile(e.dataTransfer.files[0]);
  });
}
$('#remove-control-image')?.addEventListener('click', () => {
  controlImage = null;
  $('#control-image-path').value = ''; $('#control-image-input').value = '';
  $('#control-upload-placeholder').classList.remove('hidden');
  $('#control-upload-preview').classList.add('hidden');
  $('#control-preview-img').src = '';
});

// ---------- Gestion mask image ----------
async function handleMaskFile(file) {
  if (!file) return;
  const fd = new FormData(); fd.append('image', file);
  try {
    const r = await fetch('/api/upload-image?type=mask', { method: 'POST', body: fd });
    const j = await r.json();
    if (!j.ok) { alert(j.error); return; }
    maskImage = { filename: j.filename, url: j.url, name: file.name };
    $('#mask-image-path').value = j.filename;
    $('#mask-preview-img').src = URL.createObjectURL(file);
    $('#mask-preview-name').textContent = file.name;
    $('#mask-upload-placeholder').classList.add('hidden');
    $('#mask-upload-preview').classList.remove('hidden');
  } catch (e) { alert(e.message); }
}
$('#mask-image-input')?.addEventListener('change', e => {
  if (e.target.files.length > 0) handleMaskFile(e.target.files[0]);
  e.target.value = '';
});
$('#mask-upload-placeholder')?.addEventListener('click', () => $('#mask-image-input').click());
const maskArea = $('#mask-upload-area');
if (maskArea) {
  maskArea.addEventListener('dragover', e => { e.preventDefault(); maskArea.classList.add('dragover'); });
  maskArea.addEventListener('dragleave', () => maskArea.classList.remove('dragover'));
  maskArea.addEventListener('drop', e => {
    e.preventDefault(); maskArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleMaskFile(e.dataTransfer.files[0]);
  });
}
$('#remove-mask-image')?.addEventListener('click', () => {
  maskImage = null;
  $('#mask-image-path').value = ''; $('#mask-image-input').value = '';
  $('#mask-upload-placeholder').classList.remove('hidden');
  $('#mask-upload-preview').classList.add('hidden');
  $('#mask-preview-img').src = '';
});

// ---------- Legacy single source image (pour compat) ----------
let legacyUploadedPath = null;
async function handleLegacyFile(file) {
  if (!file) return;
  const fd = new FormData(); fd.append('image', file);
  try {
    const r = await fetch('/api/upload-source-image', { method: 'POST', body: fd });
    const j = await r.json();
    if (!j.ok) { alert(j.error); return; }
    legacyUploadedPath = j.filename;
    uploadedImagePath = j.filename;
    $('#source-image-path').value = j.filename;
    if (typeof updateSourceFormatHint === 'function') updateSourceFormatHint();
    const imgEl = $('#preview-img');
    if (imgEl) {
      imgEl.src = URL.createObjectURL(file);
      $('#preview-name').textContent = file.name;
      $('#upload-placeholder').classList.add('hidden');
      $('#upload-preview').classList.remove('hidden');
    }
  } catch (e) { alert(e.message); }
}
$('#source-image-input')?.addEventListener('change', e => {
  if (e.target.files.length > 0) handleLegacyFile(e.target.files[0]);
});
$('#upload-placeholder')?.addEventListener('click', () => $('#source-image-input').click());
const legacyArea = $('#file-upload-area');
if (legacyArea) {
  legacyArea.addEventListener('dragover', e => { e.preventDefault(); legacyArea.classList.add('dragover'); });
  legacyArea.addEventListener('dragleave', () => legacyArea.classList.remove('dragover'));
  legacyArea.addEventListener('drop', e => {
    e.preventDefault(); legacyArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleLegacyFile(e.dataTransfer.files[0]);
  });
}
$('#remove-image')?.addEventListener('click', () => {
  legacyUploadedPath = null; uploadedImagePath = null;
  $('#source-image-path').value = ''; $('#source-image-input').value = '';
  $('#upload-placeholder').classList.remove('hidden');
  $('#upload-preview').classList.add('hidden');
  $('#preview-img').src = '';
});

// ---------- generation ----------
$('#generate-btn')?.addEventListener('click', async () => {
  const model_id = $('#model').value;
  const m = MODELS[model_id];
  if (!m.status.ready) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = `Le modele << ${m.name} >> n'est pas pret. Telechargez-le dans l'onglet Modeles.`;
    return;
  }

  const presetSelect = $('#preset');
  const presetValue = presetSelect ? presetSelect.value : 'default';
  savePrefs({ model: model_id, preset: presetValue, quant: $('#quant')?.value });

  let finalPrompt = $('#prompt').value.trim();
  const loraPrompt = $('#lora-prompt')?.value.trim();
  if (loraPrompt) {
    finalPrompt = finalPrompt ? finalPrompt + ' ' + loraPrompt : loraPrompt;
  }
  // Transparence RGBA pour Qwen-Image 2.1
  const transpCheck = $('#transparency-check');
  if (transpCheck && transpCheck.checked && finalPrompt) {
    const hasTransp = finalPrompt.toLowerCase().includes('rgba') || finalPrompt.toLowerCase().includes('transparent');
    if (!hasTransp) {
      finalPrompt = `This is an RGBA image with transparency. ${finalPrompt}. The image has alpha channel and the background is transparent.`;
    }
  }

  const strengthVal = $('#strength')?.value || null;
  const controlStrengthVal = $('#control-strength')?.value || null;

  const body = {
    model_id,
    quant: $('#quant').value,
    prompt: finalPrompt,
    negative: $('#negative').value,
    ratio: currentRatio,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
    // legacy
    source_image: uploadedImagePath || legacyUploadedPath || null,
    // nouveau multi-images
    ref_images: refImages.length > 0 ? refImages.map(r => r.filename) : null,
    init_image: initImage ? initImage.filename : null,
    control_image: controlImage ? controlImage.filename : null,
    mask_image: maskImage ? maskImage.filename : null,
    lora_dir: $('#lora-dir').value || null,
    strength: (m.supports_init || m.arch === 'sd3' || m.supports_ref) && strengthVal ? parseFloat(strengthVal) : null,
    control_strength: controlStrengthVal ? parseFloat(controlStrengthVal) : null,
  };

  // Ajout format source
  const keepInputFormat = $('#keep-input-format')?.checked || currentRatio === 'source';
  body.ratio = keepInputFormat ? 'source' : currentRatio;
  body.use_source_format = keepInputFormat;
  body.keep_input_format = keepInputFormat;

  const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = j.error || 'Erreur';
    return;
  }
  $('#gen-error').hidden = true;
  $('#gen-error').textContent = '';
  $('#generate-btn').hidden = true;
  $('#cancel-btn').hidden = false;
  $('#results').innerHTML = '';
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
  $('#log').textContent = '';
  $('#log').hidden = false;
  pollStatus();
});

$('#cancel-btn')?.addEventListener('click', async () => {
  await fetch('/api/cancel', { method: 'POST' });
});
$('#log-toggle')?.addEventListener('click', () => { $('#log').hidden = !$('#log').hidden; });

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
    try {
      const r = await fetch('/api/status');
      j = await r.json();
    } catch (e) { return; }

    const pct = Math.round((j.progress || 0) * 100);
    $('#progress-fill').style.width = pct + '%';

    const elapsed = j.elapsed || 0;
    const eta = j.eta || 0;
    let txt;
    if (j.busy && j.kind === 'generate') {
      txt = `generation ${pct}%`;
      if (j.total_steps) txt += ` (${j.step}/${j.total_steps})`;
      txt += ` - ${fmtTime(elapsed)} ecoule`;
      if (eta > 0 && j.step > 1) txt += ` - ~${fmtTime(eta)} restant`;
    } else if (j.busy) {
      txt = j.log || 'en cours...';
    } else if (j.error) {
      txt = 'erreur';
    } else {
      txt = 'termine';
    }
    $('#progress-text').textContent = txt;

    if (j.log) $('#log').textContent = j.log + ($('#log').textContent ? '\n' + $('#log').textContent : '');

    if (j.kind === 'generate' && j.result && j.result.images && j.result.images.length > 0) {
      showResults(j.result.images);
    }

    if (!j.busy) {
      clearInterval(pollTimer); pollTimer = null;
      $('#generate-btn').hidden = false;
      $('#cancel-btn').hidden = true;
      if (j.error) {
        $('#gen-error').hidden = false;
        $('#gen-error').textContent = j.error;
        $('#log').hidden = false;
      } else if (j.kind === 'generate') {
        const imgs = (j.result && j.result.images) || [];
        if (imgs.length === 0 && !j.result?.cancelled) {
          $('#gen-error').hidden = false;
          $('#gen-error').textContent = j.log || "Aucune image n'a été produite.";
          $('#log').hidden = false;
        }
      }
      const stats = (j.result && j.result.stats) || j.stats;
      if (stats && j.result && j.result.images && j.result.images.length > 0) showStats(stats);
      refreshEngineBadge();
    }
  }, 1000);
}

function showStats(stats) {
  const box = $('#stats-box');
  if (!box) return;
  box.hidden = false;
  $('#st-total').textContent = fmtTime(stats.total_seconds);
  $('#st-denoise').textContent = fmtTime(stats.denoise_seconds);
  $('#st-perstep').textContent = stats.per_step_seconds + 's';
  $('#st-its').textContent = stats.it_s + ' it/s';
  $('#st-batch').textContent = stats.batch + ' image' + (stats.batch > 1 ? 's' : '');
  $('#st-perimg').textContent = fmtTime(stats.sec_per_image);
}

function showResults(images) {
  const box = $('#results');
  box.innerHTML = '';
  images.forEach(img => {
    const d = document.createElement('div');
    d.className = 'result';
    d.innerHTML = `
      <img src="${img.url}?t=${Date.now()}" alt="">
      <div class="rbar">
        <span>seed ${img.seed}</span>
        <a class="link" href="${img.url}" download>telecharger</a>
      </div>`;
    d.querySelector('img').addEventListener('click', e => openLightbox(e.target.src));
    box.appendChild(d);
  });
}

// ---------- enrichissement ----------
async function doEnhance(mode) {
  const btn = mode === 'rephrase' ? $('#rephrase-btn') : $('#enrich-btn');
  const status = $('#enrich-status');
  const promptEl = $('#prompt');
  const txt = promptEl.value.trim();
  if (!txt) { status.textContent = 'Ecrivez un prompt d abord.'; return; }
  const originalText = btn.textContent;
  btn.disabled = true; btn.textContent = '...'; status.textContent = 'en cours...';
  try {
    const r = await fetch('/api/enrich', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: txt, mode: mode })
    });
    const j = await r.json();
    if (!j.ok) { status.textContent = ''; alert(j.error || 'Erreur'); return; }
    promptEl.value = j.prompt;
    status.textContent = 'prompt enrichi - modifiable';
  } catch (e) { status.textContent = ''; alert('Erreur: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = originalText; }
}
$('#enrich-btn')?.addEventListener('click', () => doEnhance('enrich'));
$('#rephrase-btn')?.addEventListener('click', () => doEnhance('rephrase'));

(async function checkEnhancer() {
  try {
    const r = await fetch('/api/enhancer-status');
    const j = await r.json();
    if (!j.downloaded) {
      const status = $('#enrich-status');
      if (status) status.textContent = '(modele d\'enrichissement non installe - voir Parametres)';
    }
  } catch (e) {}
})();

// ---------- traduction ----------
async function doTranslate() {
  const btn = $('#translate-btn');
  const status = $('#enrich-status');
  const promptEl = $('#prompt');
  const txt = promptEl.value.trim();
  if (!txt) { status.textContent = 'Ecrivez un prompt d\'abord.'; return; }
  btn.disabled = true; btn.textContent = '...'; status.textContent = 'traduction...';
  try {
    const r = await fetch('/api/translate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: txt })
    });
    const j = await r.json();
    if (!j.ok) { status.textContent = ''; alert(j.error || 'Erreur'); return; }
    promptEl.value = j.prompt;
    status.textContent = 'traduit en anglais';
  } catch (e) { status.textContent = ''; alert(e.message); }
  finally { btn.disabled = false; btn.textContent = '🌐 Traduire EN'; }
}
$('#translate-btn')?.addEventListener('click', doTranslate);

// ---------- mmproj ----------
$('#mmproj-download-btn')?.addEventListener('click', async () => {
  const btn = $('#mmproj-download-btn');
  const msg = $('#mmproj-msg');
  btn.disabled = true; btn.textContent = '...';
  msg.textContent = 'Téléchargement en cours...'; msg.classList.remove('ok');
  try {
    const r = await fetch('/api/download-mmproj', { method: 'POST' });
    const j = await r.json();
    if (j.ok) {
      msg.textContent = '✓ mmproj téléchargé - prêt pour l\'édition !';
      msg.classList.add('ok');
      btn.textContent = '✓ Téléchargé'; btn.disabled = true;
    } else {
      msg.textContent = '✗ Erreur: ' + (j.error || 'Unknown');
      msg.innerHTML += '<br><a href="https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf" target="_blank">Télécharger manuellement (1.2 Go)</a>';
    }
  } catch (e) {
    msg.textContent = '✗ Erreur: ' + e.message;
    msg.innerHTML += '<br><a href="https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf" target="_blank">Télécharger manuellement (1.2 Go)</a>';
  } finally {
    if (!btn.disabled) { btn.textContent = 'Télécharger mmproj'; btn.disabled = false; }
  }
});

async function checkMmproj() {
  const currentModel = $('#model') ? $('#model').value : null;
  const isQwen21 = currentModel === 'qwen-image-2.1';
  const statusDiv = $('#mmproj-status');
  if (!statusDiv) return;
  if (!isQwen21) { statusDiv.classList.add('hidden'); return; }
  try {
    const r = await fetch('/api/mmproj-status');
    const j = await r.json();
    const btn = $('#mmproj-download-btn');
    const msg = $('#mmproj-msg');
    if (btn && msg) {
      statusDiv.classList.remove('hidden');
      if (j.downloaded) {
        msg.textContent = "✓ mmproj disponible — prêt pour l'édition !";
        msg.classList.add('ok');
        btn.hidden = true;
      } else {
        msg.textContent = "⚠️ mmproj manquant — requis pour l'édition (1.2 Go)";
        msg.classList.remove('ok');
        btn.hidden = false;
      }
    }
  } catch (e) {}
}

async function loadDefaultNegative() {
  try {
    const r = await fetch('/api/default-negative');
    const j = await r.json();
    window.DEFAULT_NEG = j.negative;
    const neg = $('#negative');
    if (neg && !neg.value && window.DEFAULT_NEG) {
      const m = MODELS[$('#model')?.value];
      if (m && m.supports_neg) neg.value = window.DEFAULT_NEG;
    }
  } catch (e) {}
}

loadModels();
loadDefaultNegative();
