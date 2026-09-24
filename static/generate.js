/* ===== Page Generer =====
   FIX 4 : memorise le modele selectionne (localStorage) et le restaure.
   FIX 3 : affiche les stats de generation (chrono live + stats finales).
   IMG2IMG + LORA : support de l'upload d'image et des LoRA.
*/
// Fallback: $ et $$ en cas de chargement avant app.js
if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

const RATIOS = window.RATIOS || { "1:1": [1024, 1024] };
const SOURCE_RATIO = window.SOURCE_RATIO || "source";
const SOURCE_MODES = window.SOURCE_MODES || {};
const SOURCE_DEFAULT_MODE = window.SOURCE_DEFAULT_MODE || "adapted";
const SIZE_LIMITS = window.SIZE_LIMITS || { multiple: 16, min_side: 256, max_side: 2048, max_pixels: 4194304 };
const CUSTOM_RATIO = "custom";

let MODELS = {};
let currentRatio = "1:1";
let lastPresetRatio = "1:1";       // dernier preset choisi (retour apres « Image »)
let sourceSizeMode = SOURCE_DEFAULT_MODE;   // "adapted" | "exact"
let sourceImage = null;   // {filename,width,height,ratio,megapixels,sizes}
let pollTimer = null;

// ---------- memoire de la selection (FIX 4) ----------
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

  // restauration du modele choisi precedemment
  const prefs = loadPrefs();
  let savedModel = prefs.model;
  // verifie que le modele sauvegarde existe encore
  if (!savedModel || !MODELS[savedModel]) savedModel = null;

  let firstReady = null;
  for (const [id, m] of Object.entries(MODELS)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.name + (m.status.ready ? ' ✓' : '  (à télécharger)');
    if (!m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
    if (m.status.ready && !firstReady) firstReady = id; // 1er modele pret par defaut
  }
  // ordre de priorite : modele sauvegarde > 1er pret > 1er de la liste
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

  // restauration du format choisi precedemment (etat pose AVANT la construction
  // des puces pour eviter les doubles ecouteurs)
  if (prefs.size_mode && SOURCE_MODES[prefs.size_mode]) sourceSizeMode = prefs.size_mode;
  if (prefs.ratio === CUSTOM_RATIO) {
    currentRatio = CUSTOM_RATIO;
    if (prefs.custom_w) $('#custom-w').value = prefs.custom_w;
    if (prefs.custom_h) $('#custom-h').value = prefs.custom_h;
  } else if (prefs.ratio && RATIOS[prefs.ratio]) {
    currentRatio = prefs.ratio;
    lastPresetRatio = prefs.ratio;
  }
  // le format « Image » ne se restaure pas : il faut re-uploader le fichier
  buildRatios();
  applyRatioUI();
  onModelChange();

  // reuse depuis l'historique
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
    // format de l'image historique : preset connu sinon taille libre
    const rw = parseInt(p.w, 10), rh = parseInt(p.h, 10);
    if (rw > 0 && rh > 0) {
      const match = Object.entries(RATIOS).find(([_, wh]) => wh[0] === rw && wh[1] === rh);
      if (match) {
        currentRatio = match[0];
        lastPresetRatio = match[0];
      } else {
        $('#custom-w').value = snapSize(rw);
        $('#custom-h').value = snapSize(rh);
        currentRatio = CUSTOM_RATIO;
      }
      savePrefs({ ratio: currentRatio,
                  custom_w: parseInt($('#custom-w').value, 10),
                  custom_h: parseInt($('#custom-h').value, 10) });
      applyRatioUI();
    }
  }
}

function ratioIcon(w, h, max = 26) {
  const sc = max / Math.max(w, h);
  const iw = Math.max(4, Math.round(w * sc));
  const ih = Math.max(4, Math.round(h * sc));
  return `<i style="width:${iw}px;height:${ih}px"></i>`;
}

function buildRatios() {
  const box = $('#ratios');
  box.innerHTML = '';

  // presets (1:1, 3:4, ...)
  for (const [name, [w, h]] of Object.entries(RATIOS)) {
    const d = document.createElement('div');
    d.className = 'ratio';
    d.title = `${name}  (${w}x${h})`;
    d.dataset.name = name;
    d.innerHTML = ratioIcon(w, h);
    d.addEventListener('click', () => selectRatio(name));
    box.appendChild(d);
  }

  // format « Original » : garde le format de l'image uploadee (img2img / edition)
  const src = document.createElement('div');
  src.className = 'ratio wide';
  src.dataset.name = SOURCE_RATIO;
  src.innerHTML = '<b>🖼</b><span>Original</span>';
  src.addEventListener('click', () => selectRatio(SOURCE_RATIO));
  box.appendChild(src);

  // format libre (largeur x hauteur)
  const cus = document.createElement('div');
  cus.className = 'ratio wide';
  cus.dataset.name = CUSTOM_RATIO;
  cus.title = 'Taille libre : largeur et hauteur personnalisées';
  cus.innerHTML = '<b>✂</b><span>Libre</span>';
  cus.addEventListener('click', () => selectRatio(CUSTOM_RATIO));
  box.appendChild(cus);

  bindSourceSizeToggle();
  bindCustomSize();
  refreshSourceChip();
}

// ----- selection du format -------------------------------------------------
function selectRatio(name) {
  if (name === SOURCE_RATIO && !sourceImage) {
    setFormatHint("Uploadez d'abord une image dans « Image source (img2img / édition) » " +
                  "pour pouvoir garder son format d'origine.");
    return;
  }
  if (name !== SOURCE_RATIO) lastPresetRatio = (RATIOS[name] ? name : lastPresetRatio);
  currentRatio = name;
  savePrefs({ ratio: name });
  setFormatHint('');
  applyRatioUI();
}

function applyRatioUI() {
  $$('.ratio').forEach(x => x.classList.toggle('sel', x.dataset.name === currentRatio));
  const srcBox = $('#source-size-box');
  const cusBox = $('#custom-size-box');
  if (srcBox) srcBox.classList.toggle('hidden', currentRatio !== SOURCE_RATIO);
  if (cusBox) cusBox.classList.toggle('hidden', currentRatio !== CUSTOM_RATIO);
  const useBtn = $('#use-source-format');
  if (useBtn) useBtn.classList.toggle('hidden', !sourceImage || currentRatio === SOURCE_RATIO);
  if (currentRatio === SOURCE_RATIO) renderSourceSize();
  if (currentRatio === CUSTOM_RATIO) renderCustomHint();
}

function setFormatHint(txt) {
  const el = $('#format-hint');
  if (!el) return;
  el.textContent = txt || '';
  el.classList.toggle('warn', !!txt);
}

// ----- puce « Original » : reflete le format du fichier uploade -------------
function refreshSourceChip() {
  const chip = $(`.ratio[data-name="${SOURCE_RATIO}"]`);
  if (!chip) return;
  if (sourceImage) {
    chip.classList.remove('off');
    chip.title = `Format d'origine — ${sourceImage.width}×${sourceImage.height} (${sourceImage.ratio})`;
    chip.innerHTML = ratioIcon(sourceImage.width, sourceImage.height, 20) + '<span>Original</span>';
  } else {
    chip.classList.add('off');
    chip.classList.remove('sel');
    chip.title = "Uploadez une image source pour garder son format d'origine";
    chip.innerHTML = '<b>🖼</b><span>Original</span>';
  }
  applyRatioUI();
}

// ----- resolution : adaptee (defaut) ou taille exacte du fichier ------------
function bindSourceSizeToggle() {
  const cb = $('#source-exact-size');
  if (!cb) return;
  if (!SOURCE_MODES[sourceSizeMode]) sourceSizeMode = SOURCE_DEFAULT_MODE;
  cb.checked = (sourceSizeMode === 'exact');
  cb.addEventListener('change', () => {
    sourceSizeMode = cb.checked ? 'exact' : SOURCE_DEFAULT_MODE;
    savePrefs({ size_mode: sourceSizeMode });
    renderSourceSize();
  });
}

function renderSourceSize() {
  if (!sourceImage) return;
  const det = $('#source-size-detected');
  const tgt = $('#source-size-target');
  const hint = $('#source-size-hint');
  const sizes = sourceImage.sizes || {};
  const opt = sizes[sourceSizeMode] || sizes[SOURCE_DEFAULT_MODE] || {};

  if (det) det.textContent = `${sourceImage.width} × ${sourceImage.height} px · ` +
                             `${sourceImage.ratio} · ${sourceImage.megapixels} Mpx`;
  if (tgt) tgt.textContent = opt.width ? `${opt.width} × ${opt.height} px` : '—';
  const cb = $('#source-exact-size');
  const cbLabel = $('#source-exact-label');
  const exact = sizes['exact'] || {};
  if (cb) cb.checked = (sourceSizeMode === 'exact');
  if (cbLabel) {
    cbLabel.textContent = exact.width
      ? `Taille exacte du fichier — ${exact.width} × ${exact.height} px (plus lent, plus de VRAM)`
      : 'Taille exacte du fichier';
  }
  if (hint) {
    let txt = (SOURCE_MODES[sourceSizeMode] || {}).desc || '';
    const out = opt.width ? `${opt.width}×${opt.height}` : '';
    if (opt.downscaled) {
      txt += ` Votre fichier (${sourceImage.width}×${sourceImage.height}) est ramené à ` +
             `${out} : même cadrage, génération plus rapide et moins de VRAM.`;
    } else if (opt.upscaled) {
      txt += ` Votre fichier est agrandi à ${out} (les modèles travaillent autour de 1 Mpx).`;
    } else if (opt.exact_pixels) {
      txt += ` La taille de votre fichier est conservée telle quelle (${out}).`;
    } else if (out) {
      txt += ` Cadrage conservé, taille alignée sur un multiple de 16 px (${out}).`;
    }
    hint.textContent = txt;
  }
  const dimsTxt = $('#source-dims-text');
  if (dimsTxt) {
    dimsTxt.textContent = `Format détecté : ${sourceImage.width} × ${sourceImage.height} px ` +
                          `(${sourceImage.ratio}, ${sourceImage.megapixels} Mpx)`;
  }
}

// ----- format libre ---------------------------------------------------------
function snapSize(v) {
  const mult = SIZE_LIMITS.multiple || 16;
  const lo = SIZE_LIMITS.min_side || 256;
  const hi = SIZE_LIMITS.max_side || 2048;
  let n = Math.round((parseInt(v, 10) || lo) / mult) * mult;
  return Math.min(Math.max(n, lo), hi);
}

function bindCustomSize() {
  ['#custom-w', '#custom-h'].forEach(selId => {
    const el = $(selId);
    if (!el) return;
    el.min = SIZE_LIMITS.min_side || 256;
    el.max = SIZE_LIMITS.max_side || 2048;
    el.step = SIZE_LIMITS.multiple || 16;
    el.addEventListener('change', () => {
      el.value = snapSize(el.value);
      savePrefs({ custom_w: parseInt($('#custom-w').value, 10),
                  custom_h: parseInt($('#custom-h').value, 10) });
      renderCustomHint();
    });
  });
  renderCustomHint();
}

function renderCustomHint() {
  const hint = $('#custom-size-hint');
  if (!hint) return;
  const w = snapSize($('#custom-w').value);
  const h = snapSize($('#custom-h').value);
  const mp = (w * h) / 1e6;
  let warn = '';
  if (mp > 1.6) warn = ' ⚠ grande image : génération lente et VRAM élevée.';
  hint.textContent = `${w} × ${h} px · ${(w / h).toFixed(2)}:1 · ${mp.toFixed(2)} Mpx` +
                     ` — multiple de ${SIZE_LIMITS.multiple || 16}, ` +
                     `entre ${SIZE_LIMITS.min_side || 256} et ${SIZE_LIMITS.max_side || 2048} px.${warn}`;
}

function onModelChange() {
  const modelId = $('#model').value;
  const m = MODELS[modelId];
  if (!m) return;
  const q = $('#quant');
  const presetSelect = $('#preset');
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
  // Quant par défaut
  q.value = m.default_quant;

  // Remplir les presets
  if (m.presets) {
    for (const [key, preset] of Object.entries(m.presets)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = preset.label || key;
      presetSelect.appendChild(opt);
    }
  }

  // Appliquer le preset sauvegardé ou par défaut
  const savedPreset = (prefs.model === modelId) ? prefs.preset : null;
  if (savedPreset && m.presets && m.presets[savedPreset]) {
    applyPreset(m.presets[savedPreset]);
    presetSelect.value = savedPreset;
  } else {
    // Valeurs par défaut
    $('#steps').value = m.defaults.steps;
    $('#cfg').value = m.defaults.cfg;
    if (prefs.quant && m.quants.includes(prefs.quant) && prefs.model === modelId) {
      q.value = prefs.quant;
    }
    presetSelect.value = 'default';
  }

  $('#steps').min = m.min_steps; $('#steps').max = m.max_steps;
  $('#negative').parentElement.style.display = m.supports_neg ? '' : 'none';
  // pre-remplir le negative par defaut si vide
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

  // Activer l'upload pour les modeles avec support d'edition/img2img
  const isEditModel = modelId === 'qwen-image-2.1' 
    || m.arch === 'flux2' 
    || m.arch === 'sd3';
  const uploadArea = $('#file-upload-area');
  if (uploadArea) {
    uploadArea.style.opacity = isEditModel ? '1' : '0.5';
    uploadArea.style.pointerEvents = isEditModel ? 'auto' : 'none';
  }
  
  // Afficher le champ strength pour les modeles SD
  const strengthField = $('#strength-field');
  if (strengthField) {
    strengthField.style.display = (m.arch === 'sd3') ? '' : 'none';
  }

  // Vérifier mmproj pour Qwen-Image-2.1
  checkMmproj();
}

// Appliquer un preset aux champs
function applyPreset(preset) {
  if (!preset) return;
  if (preset.steps !== undefined) $('#steps').value = preset.steps;
  if (preset.cfg !== undefined) $('#cfg').value = preset.cfg;
  if (preset.quant) {
    const q = $('#quant');
    if (q) {
      const opt = q.querySelector(`option[value="${preset.quant}"]`);
      if (opt) {
        q.value = preset.quant;
      }
    }
  }
}

$('#batch').addEventListener('input', e => {
  const v = parseInt(e.target.value);
  $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
});

// ---------- Gestion de l'upload d'image source (img2img) ----------
let uploadedImagePath = null;

async function handleFileSelect(file) {
  if (!file) return;
  const validTypes = ['image/png', 'image/jpeg', 'image/webp'];
  if (!validTypes.includes(file.type)) {
    alert('Format non supporté. Utilisez PNG, JPG ou WEBP.');
    return;
  }

  // Upload vers le serveur
  const formData = new FormData();
  formData.append('image', file);

  try {
    const r = await fetch('/api/upload-source-image', { method: 'POST', body: formData });
    const j = await r.json();
    if (!j.ok) {
      alert(j.error || 'Erreur lors de l\'upload');
      return;
    }
    uploadedImagePath = j.filename;
    $('#source-image-path').value = j.filename;

    // Afficher l'aperçu
    $('#preview-img').src = URL.createObjectURL(file);
    $('#preview-name').textContent = file.name;
    $('#upload-placeholder').classList.add('hidden');
    $('#upload-preview').classList.remove('hidden');

    // dimensions detectees cote serveur -> format « image »
    setSourceImage(j);
  } catch (e) {
    alert('Erreur: ' + e.message);
  }
}

// Le serveur renvoie width/height/ratio + les deux tailles proposees
function setSourceImage(info) {
  if (!info || !info.width || !info.height) return;
  sourceImage = {
    filename: info.filename,
    width: info.width,
    height: info.height,
    ratio: info.ratio,
    megapixels: info.megapixels,
    sizes: info.sizes || {},
  };
  // on garde le choix de resolution de l'utilisateur (defaut : adapte ~1 Mpx)
  if (!SOURCE_MODES[sourceSizeMode]) sourceSizeMode = SOURCE_DEFAULT_MODE;
  const dimsBox = $('#source-dims');
  if (dimsBox) dimsBox.classList.remove('hidden');
  refreshSourceChip();
  renderSourceSize();
  // le format de l'image uploadee devient le format courant (modifiable ensuite)
  selectRatio(SOURCE_RATIO);
  ensureSourceSizes();
}

// Filet de securite : si la reponse d'upload ne contient pas les tailles
// proposees, on les redemande au serveur.
async function ensureSourceSizes() {
  if (!sourceImage || (sourceImage.sizes && Object.keys(sourceImage.sizes).length)) return;
  try {
    const r = await fetch('/api/source-size', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_image: sourceImage.filename, size_mode: sourceSizeMode })
    });
    const j = await r.json();
    if (j.ok) {
      sourceImage.sizes = j.sizes || {};
      if (j.ratio) sourceImage.ratio = j.ratio;
      renderSourceSize();
      refreshSourceChip();
    }
  } catch (e) {}
}

function clearSourceImage() {
  sourceImage = null;
  uploadedImagePath = null;
  const dimsBox = $('#source-dims');
  if (dimsBox) dimsBox.classList.add('hidden');
  if (currentRatio === SOURCE_RATIO) {
    currentRatio = RATIOS[lastPresetRatio] ? lastPresetRatio : Object.keys(RATIOS)[0];
    savePrefs({ ratio: currentRatio });
  }
  refreshSourceChip();
}

// Clic sur la zone d'upload
$('#source-image-input')?.addEventListener('change', e => {
  if (e.target.files.length > 0) {
    handleFileSelect(e.target.files[0]);
  }
});

// Clic sur la zone placeholder
$('#upload-placeholder')?.addEventListener('click', () => {
  $('#source-image-input').click();
});

// Drag & Drop
const uploadArea = $('#file-upload-area');
if (uploadArea) {
  uploadArea.addEventListener('dragover', e => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
  });
  uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
  });
  uploadArea.addEventListener('drop', e => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileSelect(files[0]);
      // Synchroniser l'input file
      const dt = new DataTransfer();
      dt.items.add(files[0]);
      $('#source-image-input').files = dt.files;
    }
  });
}

// Retirer l'image
$('#remove-image')?.addEventListener('click', () => {
  $('#source-image-path').value = '';
  $('#source-image-input').value = '';
  $('#upload-placeholder').classList.remove('hidden');
  $('#upload-preview').classList.add('hidden');
  $('#preview-img').src = '';
  clearSourceImage();
});

// « Garder ce format » : revient au format de l'image uploadee
$('#use-source-format')?.addEventListener('click', () => {
  if (sourceImage) selectRatio(SOURCE_RATIO);
});

// ---------- generation ----------
$('#generate-btn').addEventListener('click', async () => {
  const model_id = $('#model').value;
  const m = MODELS[model_id];
  if (!m.status.ready) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = `Le modele << ${m.name} >> n'est pas pret. Telechargez-le dans l'onglet Modeles.`;
    return;
  }

  // Sauvegarder le preset sélectionné
  const presetSelect = $('#preset');
  const presetValue = presetSelect ? presetSelect.value : 'default';
  savePrefs({ model: model_id, preset: presetValue, quant: $('#quant')?.value });

  // Construction du prompt final (combine prompt principal + syntaxe LoRA si présente)
  let finalPrompt = $('#prompt').value.trim();
  const loraPrompt = $('#lora-prompt').value.trim();

  // Si le prompt LoRA est défini, l'ajouter au prompt principal (tous modèles)
  if (loraPrompt) {
    if (finalPrompt) {
      finalPrompt = finalPrompt + ' ' + loraPrompt;
    } else {
      finalPrompt = loraPrompt;
    }
  }

  // Récupérer le strength pour les modèles SD
  const strengthVal = $('#strength').value || null;

  // Format : preset / image uploadee / libre
  if (currentRatio === SOURCE_RATIO && !sourceImage) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = "Le format « Original » demande une image source : uploadez-en une ou choisissez un autre format.";
    return;
  }
  const isCustom = currentRatio === CUSTOM_RATIO;
  const customW = isCustom ? snapSize($('#custom-w').value) : null;
  const customH = isCustom ? snapSize($('#custom-h').value) : null;

  const body = {
    model_id,
    quant: $('#quant').value,
    prompt: finalPrompt,
    negative: $('#negative').value,
    ratio: currentRatio,
    size_mode: sourceSizeMode,
    width: customW,
    height: customH,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
    source_image: uploadedImagePath || null,
    lora_dir: $('#lora-dir').value || null,
    strength: (m.arch === 'sd3' && strengthVal) ? parseFloat(strengthVal) : null,
  };

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
  const metaBox = $('#result-meta');
  if (metaBox) { metaBox.textContent = ''; metaBox.classList.add('hidden'); }
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
  $('#log').textContent = '';
  $('#log').hidden = false;
  pollStatus();
});

$('#cancel-btn').addEventListener('click', async () => {
  await fetch('/api/cancel', { method: 'POST' });
});
$('#log-toggle').addEventListener('click', () => { $('#log').hidden = !$('#log').hidden; });

// ---------- helper de formatage du temps ----------
function fmtTime(s) {
  if (!s || s < 0) return '0s';
  if (s < 60) return s.toFixed(1) + 's';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m + 'min ' + r + 's';
}

// ---------- suivi live (FIX 3 : chrono + stats) ----------
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

    // chronometre live
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

    // affichage des images au fur et a mesure
    if (j.kind === 'generate' && j.result && j.result.images && j.result.images.length > 0) {
      showResults(j.result.images);
      renderResultMeta(j.result);
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
      // stats finales (FIX 3)
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

// Rappel du format reellement utilise (surtout utile en format « image »)
function renderResultMeta(result) {
  const box = $('#result-meta');
  if (!box) return;
  const w = result && result.width;
  const h = result && result.height;
  if (!w || !h) { box.classList.add('hidden'); box.textContent = ''; return; }
  const si = result.size_info || {};
  let txt = `📐 Sortie : ${w} × ${h} px`;
  if (si.mode === 'source') {
    const label = (SOURCE_MODES[si.size_mode] || {}).label || si.size_mode || '';
    txt += ` · format de l'image uploadée ${si.source_width} × ${si.source_height} ` +
           `(${si.source_ratio}) · ${label}`;
  } else if (si.mode === 'custom') {
    txt += ' · format libre';
  } else if (si.ratio) {
    txt += ` · preset ${si.ratio}`;
  }
  box.textContent = txt;
  box.classList.remove('hidden');
}


// ---------- enrichissement de prompt (LLM) ----------
async function doEnhance(mode) {
  const btn = mode === 'rephrase' ? $('#rephrase-btn') : $('#enrich-btn');
  const status = $('#enrich-status');
  const promptEl = $('#prompt');
  const txt = promptEl.value.trim();
  if (!txt) {
    status.textContent = 'Ecrivez un prompt d abord.';
    return;
  }
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '...';
  status.textContent = 'en cours...';
  try {
    const r = await fetch('/api/enrich', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: txt, mode: mode })
    });
    const j = await r.json();
    if (!j.ok) {
      status.textContent = '';
      alert(j.error || 'Erreur');
      return;
    }
    promptEl.value = j.prompt;
    status.textContent = 'prompt enrichi - modifiable';
  } catch (e) {
    status.textContent = '';
    alert('Erreur: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}
$('#enrich-btn')?.addEventListener('click', () => doEnhance('enrich'));
$('#rephrase-btn')?.addEventListener('click', () => doEnhance('rephrase'));

// verifie si l'enrichisseur est disponible au chargement
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


// ---------- traduction de prompt (LLM) ----------
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

// ---------- vérification mmproj pour Qwen-Image-2.1 ----------
function checkMmprojStatus() {
  const btn = $('#mmproj-download-btn');
  const msg = $('#mmproj-msg');
  if (!btn || !msg) return;

  // Vérifier si mmproj est disponible via l'API
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      // L'API /api/status ne donne pas directement le statut mmproj
      // On vérifie via un endpoint dédié ou on utilise le manifeste
    })
    .catch(() => {});
}

// Bouton de téléchargement mmproj
$('#mmproj-download-btn')?.addEventListener('click', async () => {
  const btn = $('#mmproj-download-btn');
  const msg = $('#mmproj-msg');
  btn.disabled = true;
  btn.textContent = '...';
  msg.textContent = 'Téléchargement en cours...';
  msg.classList.remove('ok');

  try {
    const r = await fetch('/api/download-mmproj', { method: 'POST' });
    const j = await r.json();
    if (j.ok) {
      msg.textContent = '✓ mmproj téléchargé - prêt pour l\'édition !';
      msg.classList.add('ok');
      btn.textContent = '✓ Téléchargé';
      btn.disabled = true;
    } else {
      msg.textContent = '✗ Erreur: ' + (j.error || 'Unknown');
      msg.innerHTML += '<br><a href="https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf" target="_blank">Télécharger manuellement (1.2 Go)</a>';
    }
  } catch (e) {
    msg.textContent = '✗ Erreur: ' + e.message;
    msg.innerHTML += '<br><a href="https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf" target="_blank">Télécharger manuellement (1.2 Go)</a>';
  } finally {
    if (!btn.disabled) {
      btn.textContent = 'Télécharger mmproj';
      btn.disabled = false;
    }
  }
});

// Vérification du statut mmproj (uniquement Qwen-Image-2.1)
async function checkMmproj() {
  const currentModel = $('#model') ? $('#model').value : null;
  const isQwen21 = currentModel === 'qwen-image-2.1';
  const statusDiv = $('#mmproj-status');
  if (!statusDiv) return;
  if (!isQwen21) {
    statusDiv.classList.add('hidden');
    return;
  }
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
    // pre-remplir si vide et le modele supporte le negatif
    const neg = $('#negative');
    if (neg && !neg.value && window.DEFAULT_NEG) {
      const m = MODELS[$('#model')?.value];
      if (m && m.supports_neg) neg.value = window.DEFAULT_NEG;
    }
  } catch (e) {}
}

loadModels();
loadDefaultNegative();
