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

let MODELS = {};
let currentRatio = "1:1";
let ratioBeforeOriginal = "1:1";
let sourceImageSize = null;
let sourcePreviewUrl = null;
let activeGenSourceUrl = null;
let currentBatchStamp = Date.now();
let pollTimer = null;

// ---------- memoire de la selection (FIX 4) ----------
const STORE_KEY = "lis_generate_prefs";
const GEN_DRAFT_KEY = "lis_generate_draft_v1";
const GEN_CUSTOM_PREPROMPTS_KEY = "lis_gen_custom_preprompts";
let isRestoringGenDraft = false;
let lastGeneratedImages = [];
let uploadedImageServerUrl = null;
let uploadedImageName = '';

// ===== Style Midjourney (approximations expliquées) =====
// Styles rapides : chaque chip bascule un suffixe visible dans le prompt.
const MJ_STYLE_CHIPS = [
  { id: 'cine',    label: '🎬 Cinéma',      suffix: 'cinematic still, dramatic lighting, film grain' },
  { id: 'photo',   label: '📷 Photo',       suffix: 'photograph, 85mm lens, natural light, high detail' },
  { id: 'oil',     label: '🖼️ Huile',       suffix: 'oil painting, rich brushstrokes, gallery piece' },
  { id: 'water',   label: '🎨 Aquarelle',   suffix: 'watercolor painting, soft washes, paper texture' },
  { id: 'anime',   label: '⛩️ Anime',       suffix: 'anime style, cel shading, vibrant colors' },
  { id: 'pixel',   label: '👾 Pixel art',   suffix: 'pixel art, 16-bit, retro game sprite' },
  { id: 'lowpoly', label: '🔺 Low-poly',    suffix: 'low-poly render, geometric facets, flat shading' },
  { id: 'cyber',   label: '🌆 Cyberpunk',   suffix: 'cyberpunk, neon lights, rainy street, dystopian city' },
  { id: 'steam',   label: '⚙️ Steampunk',   suffix: 'steampunk, brass gears, steam and goggles' },
  { id: 'mini',    label: '⬜ Minimaliste', suffix: 'minimalist composition, clean negative space, muted palette' },
  { id: 'neon',    label: '💡 Néon',        suffix: 'neon glow, vibrant saturated colors, dark background' },
  { id: 'noir',    label: '🕶️ Noir',        suffix: 'film noir, high contrast black and white, hard shadows' },
];
let mjActiveChips = new Set();

function mjPromptAddSuffix(suffix) {
  const ta = $('#prompt');
  if (!ta) return;
  const cur = ta.value.trim();
  ta.value = cur ? cur.replace(/[,\s]+$/, '') + ', ' + suffix : suffix;
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

function mjPromptRemoveSuffix(suffix) {
  const ta = $('#prompt');
  if (!ta) return;
  const cur = ta.value;
  const candidates = [', ' + suffix, suffix + ', ', suffix];
  for (const cand of candidates) {
    const idx = cur.indexOf(cand);
    if (idx !== -1) {
      ta.value = (cur.slice(0, idx) + cur.slice(idx + cand.length)).replace(/[,\s]{2,}/g, ', ').replace(/^[,\s]+|[,\s]+$/g, '');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
  }
}

function mjToggleChip(chip) {
  const ta = $('#prompt');
  if (mjActiveChips.has(chip.id)) {
    mjActiveChips.delete(chip.id);
    mjPromptRemoveSuffix(chip.suffix);
  } else {
    mjActiveChips.add(chip.id);
    mjPromptAddSuffix(chip.suffix);
  }
  $$('.mj-chip').forEach(b => b.classList.toggle('active', mjActiveChips.has(b.dataset.chip)));
}

function mjInitChips() {
  const box = $('#mj-style-chips');
  if (!box) return;
  box.innerHTML = MJ_STYLE_CHIPS.map(chip =>
    `<button type="button" class="mj-chip" data-chip="${chip.id}" title="Ajoute au prompt : ${chip.suffix}">${chip.label}</button>`
  ).join('');
  box.querySelectorAll('.mj-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const chip = MJ_STYLE_CHIPS.find(c => c.id === btn.dataset.chip);
      if (chip) mjToggleChip(chip);
    });
  });
  // Ré-hydrate l'état visuel des chips depuis le prompt restauré
  const promptText = $('#prompt')?.value || '';
  for (const chip of MJ_STYLE_CHIPS) {
    if (promptText.includes(chip.suffix)) mjActiveChips.add(chip.id);
  }
  box.querySelectorAll('.mj-chip').forEach(b => b.classList.toggle('active', mjActiveChips.has(b.dataset.chip)));
}

// Stylisation : 0-1000, 100 = présélection inchangée (≈ "stylize" MJ).
let stylizeBase = null;      // { steps, cfg } capturés à la dernière présélection / édition manuelle
let stylizeApplying = false; // évite de recapturer pendant l'écriture par le slider

function captureStylizeBase() {
  const s = parseFloat($('#steps')?.value);
  const c = parseFloat($('#cfg')?.value);
  if (!isNaN(s) || !isNaN(c)) {
    stylizeBase = {
      steps: isNaN(s) ? (stylizeBase ? stylizeBase.steps : 20) : s,
      cfg: isNaN(c) ? (stylizeBase ? stylizeBase.cfg : 4) : c,
    };
  }
  const slider = $('#mj-stylize');
  if (slider) { slider.value = 100; const v = $('#mj-stylize-val'); if (v) v.textContent = '100'; }
}

function mjClamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

function mjInitStylize() {
  const slider = $('#mj-stylize');
  if (!slider) return;
  slider.addEventListener('input', () => {
    const v = parseInt(slider.value, 10) || 0;
    const val = $('#mj-stylize-val'); if (val) val.textContent = String(v);
    const base = stylizeBase || {
      steps: parseFloat($('#steps')?.value) || 20,
      cfg: parseFloat($('#cfg')?.value) || 4,
    };
    const delta = (v - 100) / 100;   // 0 au neutre
    const steps = mjClamp(Math.round(base.steps * (1 + delta * 0.30)), 1, 50);
    const cfg = mjClamp(base.cfg * (1 + delta * 0.30), 0.5, 15);
    stylizeApplying = true;
    if ($('#steps')) $('#steps').value = steps;
    if ($('#cfg')) $('#cfg').value = (Math.round(cfg * 10) / 10).toFixed(1);
    stylizeApplying = false;
    if (typeof saveGenDraft === 'function') saveGenDraft();
  });
  ['#steps', '#cfg'].forEach(sel => {
    $(sel)?.addEventListener('input', () => { if (!stylizeApplying) captureStylizeBase(); });
  });
}

// Weirdness : 0-3000, règle échantillonneur + planificateur de la section Qualité (≈ "weird" MJ).
let weirdApplying = false;
const MJ_WEIRD_BANDS = [
  { max: 0,    sampler: null,       scheduler: null,          label: 'réglages Qualité inchangés (reprise tels quels)' },
  { max: 999,  sampler: 'euler_a',  scheduler: 'karras',      label: "Euler A + Karras — grain organique créatif" },
  { max: 1999, sampler: 'dpm++2m',  scheduler: 'beta',        label: 'DPM++ 2M + Beta — matières denses' },
  { max: 3000, sampler: 'lcm',      scheduler: 'sgm_uniform', label: 'LCM + SGM Uniform — ultra-courts, très chaotique' },
];

function mjInitWeird() {
  const slider = $('#mj-weird');
  if (!slider) return;
  const apply = v => {
    const band = MJ_WEIRD_BANDS.find(b => v <= b.max) || MJ_WEIRD_BANDS[MJ_WEIRD_BANDS.length - 1];
    weirdApplying = true;
    const s = $('#q-sampler'); if (s && band.sampler) s.value = band.sampler;
    const sc = $('#q-scheduler'); if (sc && band.scheduler) sc.value = band.scheduler;
    weirdApplying = false;
    const d = $('#mj-weird-desc'); if (d) d.textContent = band.label;
    const val = $('#mj-weird-val'); if (val) val.textContent = String(v);
  };
  slider.addEventListener('input', () => {
    apply(parseInt(slider.value, 10) || 0);
    if (typeof saveGenDraft === 'function') saveGenDraft();
  });
  ['#q-sampler', '#q-scheduler'].forEach(sel => {
    $(sel)?.addEventListener('change', () => {
      if (weirdApplying) return;
      slider.value = 0; apply(0); // l'utilisateur a repris la main : on repasse le slider à 0
    });
  });
}

// Chaos : 0-100, graines indépendantes dans le lot (≈ "chaos" MJ).
function mjInitChaos() {
  const slider = $('#mj-chaos');
  if (!slider) return;
  slider.addEventListener('input', () => {
    const val = $('#mj-chaos-val'); if (val) val.textContent = slider.value;
    if (typeof saveGenDraft === 'function') saveGenDraft();
  });
}

function saveGenDraft() {
  if (isRestoringGenDraft) return;
  try {
    const draft = {
      model: $('#model')?.value || null,
      quant: $('#quant')?.value || null,
      preset: $('#preset')?.value || 'default',
      prompt: $('#prompt')?.value || '',
      negative: $('#negative')?.value || '',
      steps: $('#steps')?.value || '',
      cfg: $('#cfg')?.value || '',
      seed: $('#seed')?.value || '',
      batch: $('#batch')?.value || '1',
      loraDir: $('#lora-dir')?.value || '',
      loraPrompt: $('#lora-prompt')?.value || '',
      strength: $('#strength')?.value || '0.75',
      currentRatio,
      ratioBeforeOriginal,
      chaos: $('#mj-chaos')?.value || '0',
      sourceImage: uploadedImagePath ? {
        path: uploadedImagePath,
        url: uploadedImageServerUrl || `/source-images/${uploadedImagePath.split('/').pop()}`,
        name: uploadedImageName,
        size: sourceImageSize,
      } : null,
      lastGeneratedImages,
      activeGenSourceUrl: (activeGenSourceUrl && !String(activeGenSourceUrl).startsWith('blob:'))
        ? activeGenSourceUrl
        : null,
      currentBatchStamp,
    };
    const json = JSON.stringify(draft);
    sessionStorage.setItem(GEN_DRAFT_KEY, json);
    localStorage.setItem(GEN_DRAFT_KEY, json);
  } catch (e) {}
}

async function restoreGenDraft() {
  let draft = null;
  try {
    const raw = sessionStorage.getItem(GEN_DRAFT_KEY) || localStorage.getItem(GEN_DRAFT_KEY);
    draft = raw ? JSON.parse(raw) : null;
  } catch (e) {
    draft = null;
  }
  if (!draft) return;

  isRestoringGenDraft = true;
  try {
    const sel = $('#model');
    if (draft.model && MODELS[draft.model] && sel) {
      sel.value = draft.model;
      onModelChange();
    }
    const m = MODELS[sel?.value];
    if (draft.quant && m && m.quants.includes(draft.quant) && $('#quant')) {
      $('#quant').value = draft.quant;
    }
    if (draft.preset && $('#preset')) {
      const opt = $('#preset').querySelector(`option[value="${draft.preset}"]`);
      if (opt) $('#preset').value = draft.preset;
    }
    if (typeof draft.prompt === 'string') $('#prompt').value = draft.prompt;
    if (typeof draft.negative === 'string' && draft.negative) $('#negative').value = draft.negative;
    if (draft.steps && !(m && m.fixed_steps != null)) $('#steps').value = draft.steps;
    if (draft.cfg && !(m && m.fixed_cfg != null)) $('#cfg').value = draft.cfg;
    // Les sliders Stylisation/Weirdness ne sont pas persistés tels quels : les contrôles
    // sous-jacents (étapes/CFG/échantillonneur/planificateur) le sont déjà. On les ramène
    // à leur état neutre et captureStylizeBase() réajuste la base relative à la présélection.
    if ($('#mj-stylize')) { $('#mj-stylize').value = 100; const v = $('#mj-stylize-val'); if (v) v.textContent = '100'; }
    if ($('#mj-weird')) { $('#mj-weird').value = 0; const v = $('#mj-weird-val'); if (v) v.textContent = '0'; const d = $('#mj-weird-desc'); if (d) d.textContent = 'réglages Qualité inchangés (reprise tels quels)'; }
    if (draft.chaos && $('#mj-chaos')) { $('#mj-chaos').value = draft.chaos; const v = $('#mj-chaos-val'); if (v) v.textContent = draft.chaos; }
    if (draft.seed !== undefined && draft.seed !== null) $('#seed').value = draft.seed;
    if (draft.batch && $('#batch')) {
      $('#batch').value = draft.batch;
      const v = parseInt(draft.batch, 10) || 1;
      if ($('#batch-val')) $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
    }
    if (typeof draft.loraDir === 'string' && $('#lora-dir')) $('#lora-dir').value = draft.loraDir;
    if (typeof draft.loraPrompt === 'string' && $('#lora-prompt')) $('#lora-prompt').value = draft.loraPrompt;
    if (draft.strength && $('#strength')) $('#strength').value = draft.strength;
    if (draft.ratioBeforeOriginal && RATIOS[draft.ratioBeforeOriginal]) {
      ratioBeforeOriginal = draft.ratioBeforeOriginal;
    }
    if (draft.currentRatio && (draft.currentRatio === 'original' || RATIOS[draft.currentRatio])) {
      currentRatio = draft.currentRatio;
    }

    // Restauration de l'image source img2img si le modèle l'accepte et qu'elle existe toujours
    const canInit = Boolean(m && (m.input_modes || []).includes('init'));
    if (canInit && draft.sourceImage && draft.sourceImage.path && draft.sourceImage.url) {
      try {
        const dims = await readImageDimensions(draft.sourceImage.url);
        uploadedImagePath = draft.sourceImage.path;
        uploadedImageServerUrl = draft.sourceImage.url;
        uploadedImageName = draft.sourceImage.name || draft.sourceImage.path.split('/').pop();
        sourceImageSize = dims;
        sourcePreviewUrl = draft.sourceImage.url;
        $('#source-image-path').value = uploadedImagePath;
        $('#preview-img').src = sourcePreviewUrl;
        $('#preview-name').textContent = `${uploadedImageName} (${dims.width} × ${dims.height})`;
        $('#upload-placeholder').classList.add('hidden');
        $('#upload-preview').classList.remove('hidden');
      } catch (e) {}
    }
    if (currentRatio === 'original' && !sourceImageSize) {
      currentRatio = RATIOS[ratioBeforeOriginal] ? ratioBeforeOriginal : '1:1';
    }
    buildRatios();
    buildRatiosApply();

    if (Array.isArray(draft.lastGeneratedImages) && draft.lastGeneratedImages.length) {
      currentBatchStamp = draft.currentBatchStamp || Date.now();
      activeGenSourceUrl = draft.activeGenSourceUrl || null;
      showResults(draft.lastGeneratedImages);
    }
  } finally {
    isRestoringGenDraft = false;
  }
}

function loadCustomGenPreprompts() {
  try {
    const arr = JSON.parse(localStorage.getItem(GEN_CUSTOM_PREPROMPTS_KEY) || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    return [];
  }
}

function saveCustomGenPreprompts(list) {
  try {
    localStorage.setItem(GEN_CUSTOM_PREPROMPTS_KEY, JSON.stringify(list));
  } catch (e) {}
}

function renderGenPreprompts() {
  const modelId = $('#model')?.value;
  const m = MODELS[modelId];
  const sel = $('#gen-preprompt-select');
  const delBtn = $('#del-gen-preprompt-btn');
  if (!sel || !m) return;

  sel.innerHTML = `<option value="">→ Choisir un pré-prompt adapté à ${m.name} ←</option>`;
  const builtIn = m.gen_presets || [];
  const recommended = builtIn.filter(x => (x.category || 'general') !== 'style');
  const styles = builtIn.filter(x => x.category === 'style');
  const userStyles = USER_STYLES.filter(st => st.models === 'all' || (Array.isArray(st.models) && st.models.includes(modelId)));
  const custom = loadCustomGenPreprompts();

  const addGroup = (label, items, prefix) => {
    if (!items.length) return;
    const grp = document.createElement('optgroup');
    grp.label = label;
    items.forEach(item => {
      const opt = document.createElement('option');
      opt.value = `${prefix}:${item.id}`;
      opt.textContent = item.label;
      opt.dataset.prompt = item.prompt;
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  };

  addGroup(`✨ Pré-prompts recommandés (${m.name})`, recommended, 'builtin');
  addGroup(`🎭 Styles & rendus (adaptés à ${m.name})`, styles, 'builtin');
  addGroup('⭐ Mes styles (page Styles)', userStyles.map(st => ({ id: st.id, label: st.name, prompt: st.prompt })), 'user');
  addGroup('⭐ Mes pré-prompts enregistrés', custom, 'custom');
  if (delBtn) delBtn.hidden = true;
}

$('#gen-preprompt-select')?.addEventListener('change', e => {
  const sel = e.target;
  const opt = sel.selectedOptions[0];
  const delBtn = $('#del-gen-preprompt-btn');
  if (delBtn) {
    delBtn.hidden = !(sel.value && sel.value.startsWith('custom:'));
  }
  if (!opt || !opt.dataset.prompt) return;
  $('#prompt').value = opt.dataset.prompt;
  saveGenDraft();
});

$('#save-gen-preprompt-btn')?.addEventListener('click', () => {
  const txt = $('#prompt').value.trim();
  if (!txt) {
    alert("Écrivez d'abord un prompt avant de l'enregistrer.");
    return;
  }
  const defaultName = txt.slice(0, 36) + (txt.length > 36 ? '…' : '');
  const label = prompt("Nom de ce pré-prompt :", defaultName);
  if (!label || !label.trim()) return;
  const custom = loadCustomGenPreprompts();
  const id = 'cust_' + Date.now();
  custom.push({ id, label: label.trim(), prompt: txt });
  saveCustomGenPreprompts(custom);
  renderGenPreprompts();
  $('#gen-preprompt-select').value = `custom:${id}`;
  if ($('#del-gen-preprompt-btn')) $('#del-gen-preprompt-btn').hidden = false;
});

$('#del-gen-preprompt-btn')?.addEventListener('click', () => {
  const sel = $('#gen-preprompt-select');
  if (!sel || !sel.value.startsWith('custom:')) return;
  const id = sel.value.slice('custom:'.length);
  const custom = loadCustomGenPreprompts().filter(x => x.id !== id);
  saveCustomGenPreprompts(custom);
  renderGenPreprompts();
});

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

// Styles personnalisés (page /styles) applicables à la génération
let USER_STYLES = [];

async function loadUserStyles() {
  try {
    const r = await fetch('/api/styles?applies_to=gen');
    const j = await r.json();
    USER_STYLES = (j.styles || []).filter(st => st.applies_to === 'gen' || st.applies_to === 'both');
  } catch (e) {
    USER_STYLES = [];
  }
}

async function loadModels() {
  const r = await fetch('/api/models');
  MODELS = await r.json();
  await loadUserStyles();
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
        if (typeof captureStylizeBase === 'function') captureStylizeBase();
        savePrefs({ model: modelId, preset: 'default', quant: quantSelect ? quantSelect.value : null });
      } else if (m.presets && m.presets[key]) {
        applyPreset(m.presets[key]);
        savePrefs({ model: modelId, preset: key, quant: quantSelect ? quantSelect.value : null });
      }
    });
  }

  buildRatios();
  // restauration du ratio
  if (prefs.ratio && RATIOS[prefs.ratio]) {
    currentRatio = prefs.ratio;
    ratioBeforeOriginal = prefs.ratio;
  }
  buildRatiosApply();
  onModelChange();
  await restoreGenDraft();
  mjInitChips();
  mjInitStylize();
  mjInitWeird();
  mjInitChaos();
  captureStylizeBase();

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
  }
  populateCompareSelect();
  saveGenDraft();
}

function getOriginalOutputSize() {
  if (!sourceImageSize) return null;
  const { width, height } = sourceImageSize;
  // Garde les proportions de la source sans demander une résolution démesurée.
  const scaleToArea = Math.sqrt((1024 * 1024) / (width * height));
  const scaleToMaxSide = 1344 / Math.max(width, height);
  const scale = Math.min(scaleToArea, scaleToMaxSide);
  const roundDown16 = value => Math.max(16, Math.floor(value / 16) * 16);
  return {
    width: roundDown16(width * scale),
    height: roundDown16(height * scale),
  };
}

function updateOriginalRatioInfo() {
  const info = $('#original-ratio-info');
  if (!info) return;
  if (currentRatio !== 'original' || !sourceImageSize) {
    info.hidden = true;
    info.textContent = '';
    return;
  }
  const outputSize = getOriginalOutputSize();
  info.textContent = `Proportions source ${sourceImageSize.width} × ${sourceImageSize.height} — sortie ${outputSize.width} × ${outputSize.height}`;
  info.hidden = false;
}

function buildRatios() {
  const box = $('#ratios');
  box.innerHTML = '';
  const options = Object.entries(RATIOS).map(([id, [width, height]]) => ({
    id, label: id, width, height,
  }));
  if (sourceImageSize) {
    const outputSize = getOriginalOutputSize();
    options.unshift({
      id: 'original',
      label: 'Original',
      width: outputSize.width,
      height: outputSize.height,
      title: `Format source ${sourceImageSize.width} × ${sourceImageSize.height} — sortie ${outputSize.width} × ${outputSize.height}`,
    });
  }

  for (const option of options) {
    const { id, label, width, height } = option;
    const d = document.createElement('div');
    d.className = 'ratio' + (id === currentRatio ? ' sel' : '');
    if (id === 'original') d.classList.add('ratio-original');
    d.title = option.title || `${label} (${width} × ${height})`;
    d.dataset.name = id;
    d.setAttribute('role', 'button');
    d.setAttribute('aria-label', d.title);
    d.setAttribute('aria-pressed', id === currentRatio ? 'true' : 'false');
    d.tabIndex = 0;
    const max = 26;
    const scale = max / Math.max(width, height);
    const iconWidth = Math.round(width * scale), iconHeight = Math.round(height * scale);
    d.innerHTML = `<i style="width:${iconWidth}px;height:${iconHeight}px"></i>${id === 'original' ? '<span>Original</span>' : ''}`;

    const selectRatio = () => {
      pendingRestoreSize = null;   // on repart sur les formats proposés
      if (id === 'original') {
        if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio;
      } else {
        ratioBeforeOriginal = id;
        savePrefs({ ratio: id });
      }
      currentRatio = id;
      $$('.ratio').forEach(x => {
        const selected = x === d;
        x.classList.toggle('sel', selected);
        x.setAttribute('aria-pressed', selected ? 'true' : 'false');
      });
      updateOriginalRatioInfo();
    };
    d.addEventListener('click', selectRatio);
    d.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectRatio();
      }
    });
    box.appendChild(d);
  }
  updateOriginalRatioInfo();
}
function buildRatiosApply() {
  $$('.ratio').forEach(x => {
    const selected = x.dataset.name === currentRatio;
    x.classList.toggle('sel', selected);
    x.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
  updateOriginalRatioInfo();
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
    if (typeof captureStylizeBase === 'function') captureStylizeBase();
    if (prefs.quant && m.quants.includes(prefs.quant) && prefs.model === modelId) {
      q.value = prefs.quant;
    }
    presetSelect.value = 'default';
  }

  $('#steps').min = m.min_steps; $('#steps').max = m.max_steps;
  const hasFixedSteps = m.fixed_steps !== null && m.fixed_steps !== undefined;
  const hasFixedCfg = m.fixed_cfg !== null && m.fixed_cfg !== undefined;
  $('#steps').readOnly = hasFixedSteps;
  $('#cfg').readOnly = hasFixedCfg;
  if (hasFixedSteps) $('#steps').value = m.fixed_steps;
  if (hasFixedCfg) $('#cfg').value = m.fixed_cfg;
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

  // Img2img (image de depart unique + force) : active seulement si le modele le declare.
  // L'edition par references multiples se passe sur la page /edit.
  const modes = m.input_modes || [];
  const canInit = modes.includes('init');
  const box = $('#img2img-box');
  if (box) {
    box.hidden = !canInit;
    if (canInit) box.open = true;   // le bloc est replie par defaut : on l'ouvre pour les modeles concernes
  }
  if (!canInit && uploadedImagePath) clearSourceImage();

  // Afficher le champ strength pour les modeles SD
  const strengthField = $('#strength-field');
  if (strengthField) {
    strengthField.style.display = canInit ? '' : 'none';
  }

  renderGenPreprompts();
  checkMmproj();
  // Section Qualité/Agrandissement : grise le Hires Fix si le modèle ne fait pas d'img2img
  if (window.LisQuality) LisQuality.setModelCapabilities(m);
}

// Appliquer un preset aux champs
function applyPreset(preset) {
  if (!preset) return;
  if (preset.steps !== undefined) $('#steps').value = preset.steps;
  if (preset.cfg !== undefined) $('#cfg').value = preset.cfg;
  if (typeof captureStylizeBase === 'function') captureStylizeBase();
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
  saveGenDraft();
});
['#prompt', '#negative', '#steps', '#cfg', '#seed', '#lora-dir', '#lora-prompt', '#strength', '#quant', '#preset', '#model', '#q-sampler', '#q-scheduler'].forEach(sel => {
  $(sel)?.addEventListener('input', saveGenDraft);
  $(sel)?.addEventListener('change', saveGenDraft);
});
window.addEventListener('beforeunload', saveGenDraft);
window.addEventListener('pagehide', saveGenDraft);

// ---------- Gestion de l'upload d'image source (img2img) ----------
let uploadedImagePath = null;

function readImageDimensions(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error("Impossible de lire les dimensions de l'image."));
    image.src = src;
  });
}

async function handleFileSelect(file) {
  if (!file) return;
  const validTypes = ['image/png', 'image/jpeg', 'image/webp'];
  if (!validTypes.includes(file.type)) {
    alert('Format non supporté. Utilisez PNG, JPG ou WEBP.');
    return;
  }

  const previewUrl = URL.createObjectURL(file);
  let dimensions;
  try {
    dimensions = await readImageDimensions(previewUrl);
  } catch (e) {
    URL.revokeObjectURL(previewUrl);
    alert(e.message);
    return;
  }

  // Upload vers le serveur
  const formData = new FormData();
  formData.append('image', file);
  const modelId = $('#model') ? $('#model').value : null;
  if (modelId) { formData.append('model_id', modelId); formData.append('input_mode', 'init'); }
  let uploaded = false;

  try {
    const r = await fetch('/api/upload-source-image', { method: 'POST', body: formData });
    const j = await r.json();
    if (!j.ok) {
      alert(j.error || 'Erreur lors de l\'upload');
      return;
    }
    uploadedImagePath = j.filename;
    uploadedImageServerUrl = j.url;
    uploadedImageName = file.name;
    sourceImageSize = dimensions;
    $('#source-image-path').value = j.filename;

    if (sourcePreviewUrl && sourcePreviewUrl.startsWith('blob:')) URL.revokeObjectURL(sourcePreviewUrl);
    sourcePreviewUrl = previewUrl;
    $('#preview-img').src = sourcePreviewUrl;
    $('#preview-name').textContent = `${file.name} (${dimensions.width} × ${dimensions.height})`;
    $('#upload-placeholder').classList.add('hidden');
    $('#upload-preview').classList.remove('hidden');

    // À l'upload, sélectionner le format de la source par défaut.
    if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio;
    currentRatio = 'original';
    buildRatios();
    saveGenDraft();
    uploaded = true;
    if (window.LisQuality) LisQuality.setSourceImageActive(true);
  } catch (e) {
    alert('Erreur: ' + e.message);
  } finally {
    if (!uploaded) URL.revokeObjectURL(previewUrl);
  }
}

// Click sur la zone d'upload
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

// Retirer l'image (et la supprimer cote serveur pour ne pas encombrer source_images/)
function clearSourceImage(unlink = true) {
  const gone = uploadedImagePath;
  uploadedImagePath = null;
  uploadedImageServerUrl = null;
  uploadedImageName = '';
  sourceImageSize = null;
  if (sourcePreviewUrl && sourcePreviewUrl.startsWith('blob:')) URL.revokeObjectURL(sourcePreviewUrl);
  sourcePreviewUrl = null;
  $('#source-image-path').value = '';
  $('#source-image-input').value = '';
  $('#upload-placeholder').classList.remove('hidden');
  $('#upload-preview').classList.add('hidden');
  $('#preview-img').src = '';
  if (currentRatio === 'original') {
    currentRatio = RATIOS[ratioBeforeOriginal] ? ratioBeforeOriginal : '1:1';
  }
  buildRatios();
  saveGenDraft();
  if (window.LisQuality) LisQuality.setSourceImageActive(false);
  if (gone && unlink) {
    fetch('/api/delete-source-image', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: gone })
    }).catch(() => {});
  }
}

$('#remove-image')?.addEventListener('click', () => clearSourceImage());

// ---------- Bouton « 🧹 Nouveau / Vider le brouillon » ----------
$('#reset-gen-draft-btn')?.addEventListener('click', () => {
  try {
    sessionStorage.removeItem(GEN_DRAFT_KEY);
    localStorage.removeItem(GEN_DRAFT_KEY);
  } catch (e) {}
  isRestoringGenDraft = true;
  try {
    $('#prompt').value = '';
    const m = MODELS[$('#model')?.value];
    $('#negative').value = (m && m.supports_neg) ? (window.DEFAULT_NEG || '') : '';
    if ($('#seed')) $('#seed').value = '';
    if ($('#batch')) {
      $('#batch').value = '1';
      if ($('#batch-val')) $('#batch-val').textContent = '1 image';
    }
    if ($('#lora-prompt')) $('#lora-prompt').value = '';
    if ($('#gen-preprompt-select')) $('#gen-preprompt-select').value = '';
    clearSourceImage(true);
    currentRatio = '1:1';
    ratioBeforeOriginal = '1:1';
    buildRatios();
    buildRatiosApply();
    lastGeneratedImages = [];
    activeGenSourceUrl = null;
    pendingRestoreSize = null;
    if ($('#original-ratio-info')) $('#original-ratio-info').hidden = true;
    if ($('#results')) $('#results').innerHTML = '';
    if ($('#stats-box')) $('#stats-box').hidden = true;
    if ($('#gen-error')) { $('#gen-error').hidden = true; $('#gen-error').textContent = ''; }
  } finally {
    isRestoringGenDraft = false;
  }
  saveGenDraft();
  if (window.showToast) window.showToast('🧹 Brouillon réinitialisé');
});

// ---------- Coller une image avec Ctrl+V n'importe où sur la page ----------
window.addEventListener('paste', async e => {
  const items = e.clipboardData?.items ? [...e.clipboardData.items] : [];
  const imgItem = items.find(it => it.type && it.type.startsWith('image/'));
  if (!imgItem) return;
  const file = imgItem.getAsFile();
  if (!file) return;
  e.preventDefault();

  const m = MODELS[$('#model')?.value];
  const canInit = Boolean(m && (m.input_modes || []).includes('init'));
  if (canInit) {
    const details = $('#img2img-box');
    if (details) details.open = true;
    await handleImageUpload(file);
    if (window.showToast) {
      window.showToast('📋 Image collée comme Image de départ (img2img)');
    }
  } else {
    // Si le modèle actuel ne fait pas d'img2img sur /generate, proposer d'ouvrir directement dans /edit
    if (window.showToast) {
      window.showToast(
        "📋 Image détectée dans le presse-papiers",
        "✂️ Ouvrir dans Studio d'édition",
        async () => {
          const fd = new FormData();
          fd.append('image', file, file.name || 'clipboard.png');
          const r = await fetch('/api/upload-source-image', { method: 'POST', body: fd });
          const j = await r.json();
          if (j.ok) {
            sessionStorage.setItem('edit_incoming_source', JSON.stringify({
              mode: 'canvas',
              file: { filename: j.filename, url: j.url, name: file.name || 'clipboard.png' },
            }));
            window.location.href = '/edit';
          }
        }
      );
    }
  }
});

// ---------- File d'attente (Queue) ----------
function renderGenQueue(queue) {
  const box = $('#queue-box');
  const list = $('#queue-list');
  const countEl = $('#queue-count');
  if (!box || !list) return;
  const arr = Array.isArray(queue) ? queue : [];
  if (countEl) countEl.textContent = String(arr.length);
  if (!arr.length) {
    box.hidden = true;
    list.innerHTML = '';
    return;
  }
  box.hidden = false;
  list.innerHTML = arr.map(item => `
    <div class="queue-item" data-qid="${item.queue_id}">
      <span class="queue-pos">#${item.position}</span>
      <div class="queue-info">
        <strong>${item.model_name}${item.quant ? ' (' + item.quant + ')' : ''}</strong>${item.width && item.height ? ` · ${item.width}×${item.height}` : ''}${item.batch > 1 ? ` · ×${item.batch}` : ''}
        <div class="queue-prompt">${(item.prompt || '').replace(/</g, '&lt;')}</div>
      </div>
      <button type="button" class="x queue-del" data-qid="${item.queue_id}" title="Retirer de la file">×</button>
    </div>
  `).join('');
  $$('.queue-del', list).forEach(btn => {
    btn.addEventListener('click', async () => {
      const r = await fetch('/api/queue/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_id: btn.dataset.qid }),
      });
      const j = await r.json();
      if (j.ok) renderGenQueue(j.queue);
    });
  });
}

$('#queue-clear-btn')?.addEventListener('click', async () => {
  const r = await fetch('/api/queue/clear', { method: 'POST' });
  const j = await r.json();
  if (j.ok) renderGenQueue([]);
});

// ---------- construction du payload (partagé : Générer / Lot / Duel / Compare) ----------
let pendingRestoreSize = null;  // {width, height} restauré depuis un PNG
function finalizeGenerationPayload(model_id) {
  const m = MODELS[model_id];
  if (!m) return null;
  // Sauvegarder le preset sélectionné
  const presetSelect = $('#preset');
  const presetValue = presetSelect ? presetSelect.value : 'default';
  savePrefs({ model: model_id, preset: presetValue, quant: $('#quant')?.value });

  // Construction du prompt final (combine prompt principal + syntaxe LoRA si présente)
  let finalPrompt = $('#prompt').value.trim();
  const loraPrompt = $('#lora-prompt').value.trim();
  if (loraPrompt) {
    finalPrompt = finalPrompt ? finalPrompt + ' ' + loraPrompt : loraPrompt;
  }

  const canInit = (m.input_modes || []).includes('init');
  const strengthVal = canInit ? ($('#strength') ? $('#strength').value || null : null) : null;

  const body = {
    model_id,
    quant: $('#quant').value,
    prompt: finalPrompt,
    negative: $('#negative').value,
    ratio: currentRatio === 'original' ? '1:1' : currentRatio,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
    chaos: $('#mj-chaos') ? (parseInt($('#mj-chaos').value, 10) || 0) : 0,
    input_mode: canInit ? 'init' : null,
    ref_images: uploadedImagePath ? [uploadedImagePath] : [],
    lora_dir: $('#lora-dir').value || null,
    strength: strengthVal ? parseFloat(strengthVal) : null,
    allow_queue: true,
  };
  if (window.LisQuality) Object.assign(body, LisQuality.collect());
  if (pendingRestoreSize) {
    body.width = pendingRestoreSize.width;
    body.height = pendingRestoreSize.height;
    delete body.ratio;
  } else if (currentRatio === 'original' && sourceImageSize) {
    const outputSize = getOriginalOutputSize();
    body.width = outputSize.width;
    body.height = outputSize.height;
  }
  return body;
}

// ---------- generation ----------
// Ctrl/Cmd + Entrée depuis le prompt lance la génération (comme un vrai Studio)
const promptEl = $('#prompt');
if (promptEl) {
  promptEl.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      $('#generate-btn').click();
    }
  });
}

$('#generate-btn').addEventListener('click', async () => {
  const model_id = $('#model').value;
  const m = MODELS[model_id];
  const canInit = Boolean(m && (m.input_modes || []).includes('init'));
  if (!m.status.ready) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = `Le modele << ${m.name} >> n'est pas pret. Telechargez-le dans l'onglet Modeles.`;
    return;
  }

  const body = finalizeGenerationPayload(model_id);

  const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = j.error || 'Erreur';
    return;
  }
  $('#gen-error').hidden = true;
  $('#gen-error').textContent = '';

  if (j.queued) {
    renderGenQueue(j.queue || []);
    if (window.showToast) {
      window.showToast(`⏳ Ajouté à la file d'attente (position #${j.position})`);
    }
    if (!pollTimer) pollStatus();
    return;
  }

  $('#generate-btn').textContent = '＋ Ajouter à la file d\'attente';
  $('#cancel-btn').hidden = false;
  $('#results').innerHTML = '';
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
  $('#log').textContent = '';
  $('#log').hidden = false;
  activeGenSourceUrl = (canInit && uploadedImagePath)
    ? (uploadedImageServerUrl || sourcePreviewUrl)
    : null;
  currentBatchStamp = Date.now();
  saveGenDraft();
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

// ---------- aperçu en direct (pendant l'échantillonnage) ----------
let livePreviewTimer = null;
let livePreviewShown = false;
function updateLivePreview(j) {
  const wrap = $('#live-preview-wrap');
  if (!wrap) return;
  const wants = j && j.busy && j.kind === 'generate' && !!j.preview_batch_id;
  if (wants) {
    wrap.hidden = false;
    livePreviewShown = true;
    if (!livePreviewTimer) {
      const waiting = $('#live-preview-waiting');
      const imgEl = $('#live-preview-img');
      if (waiting) waiting.hidden = false;
      if (imgEl) { imgEl.hidden = true; imgEl.removeAttribute('src'); }
      const tick = async () => {
        try {
          const r = await fetch('/api/preview');
          if (!r.ok) return;
          const p = await r.json();
          if (p.ok && p.url) {
            const img = $('#live-preview-img');
            const wEl = $('#live-preview-waiting');
            if (img) {
              img.src = p.url + '?t=' + Math.floor((p.mtime || 0) * 1000);
              img.hidden = false;
            }
            if (wEl) wEl.hidden = true;
          }
        } catch (e) { /* aperçu indisponible tant que le moteur ne produit rien */ }
      };
      tick();
      livePreviewTimer = setInterval(tick, 1500);
    }
  } else if (livePreviewShown) {
    // fin de génération : on masque l'aperçu (les résultats prennent le relais)
    clearInterval(livePreviewTimer);
    livePreviewTimer = null;
    livePreviewShown = false;
    wrap.hidden = true;
    const img = $('#live-preview-img');
    if (img) { img.removeAttribute('src'); img.hidden = true; }
    const wEl = $('#live-preview-waiting');
    if (wEl) wEl.hidden = false;
  } else {
    clearInterval(livePreviewTimer);
    livePreviewTimer = null;
    wrap.hidden = true;
  }
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

    renderGenQueue(j.queue || []);
    updateLivePreview(j);

    // Op terminée : agrandissement ×4, réparation ou restauration ×2
    const AUX_KINDS = ['upscale', 'repair', 'restore_x2', 'pid', 'vary'];
    if (AUX_KINDS.includes(j.kind) && j.busy) window.__auxDonePending = j.kind;
    if (window.__auxDonePending && !j.busy) {
      const auxKind = window.__auxDonePending;
      window.__auxDonePending = false;
      if (j.result && j.result.type === auxKind && window.LisQuality) {
        if (j.result.error && window.showToast) {
          window.showToast("❌ " + String(j.result.error).split("\n")[0].slice(0, 160));
        }
        LisQuality._done(j.result.error || j.result.cancelled ? [] : (j.result.images || []), auxKind);
      }
    }
    // Compatibilité avec l'ancien nom utilisé par le bouton « Agrandir ×4 »
    if (window.__upscaleDonePending) window.__upscaleDonePending = false;

    // affichage des images au fur et a mesure
    if (j.kind === 'generate' && j.result && j.result.images && j.result.images.length > 0) {
      showResults(j.result.images);
    }

    if (!j.busy && (!j.queue || j.queue.length === 0)) {
      clearInterval(pollTimer); pollTimer = null;
      $('#generate-btn').hidden = false;
      $('#generate-btn').textContent = '✨ Générer';
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
  lastGeneratedImages = images;
  const lbItems = [];
  if (activeGenSourceUrl) {
    lbItems.push({
      src: activeGenSourceUrl,
      downloadUrl: activeGenSourceUrl,
      label: 'Image source (img2img)',
      role: 'source',
      badge: 'AVANT (SOURCE)',
    });
  }
  const hasSource = lbItems.length > 0;
  images.forEach((img, idx) => {
    const displayUrl = `${img.url}?t=${currentBatchStamp}`;
    lbItems.push({
      src: displayUrl,
      downloadUrl: img.url,
      label: `Image ${idx + 1}/${images.length} · seed ${img.seed}`,
      role: 'result',
      badge: hasSource
        ? (images.length > 1 ? `APRÈS #${idx + 1}` : 'APRÈS (MODIFIÉE)')
        : (images.length > 1 ? `IMAGE ${idx + 1}/${images.length}` : 'IMAGE GÉNÉRÉE'),
    });
  });

  images.forEach((img, idx) => {
    const displayUrl = `${img.url}?t=${currentBatchStamp}`;
    const d = document.createElement('div');
    d.className = 'result';
    d.innerHTML = `
      <img src="${displayUrl}" alt="">
      <div class="rbar">
        <span>seed ${img.seed}</span>
        <a class="link" href="${img.url}" download>telecharger</a>
        <button type="button" class="link copy-prompt-link" title="Copier le prompt utilisé pour cette image">📋 prompt</button>
      </div>`;
    d.querySelector('img').addEventListener('click', () => {
      openLightbox(lbItems, hasSource ? idx + 1 : idx);
    });
    if (window.LisQuality && typeof LisQuality.bindCopyPrompt === 'function') {
      LisQuality.bindCopyPrompt(d.querySelector('.copy-prompt-link'), img);
    }
    const sendToEdit = document.createElement('button');
    sendToEdit.type = 'button';
    sendToEdit.className = 'btn small result-use-source';
    sendToEdit.textContent = '✂️ Utiliser comme source (Édition)';
    sendToEdit.addEventListener('click', async () => {
      sendToEdit.disabled = true;
      sendToEdit.textContent = 'Envoi…';
      try {
        const r = await fetch('/api/use-output-as-source', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: img.id, filename: img.filename }),
        });
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || "Impossible d'envoyer l'image.");
        sessionStorage.setItem('edit_incoming_source', JSON.stringify({
          mode: 'canvas',
          file: { filename: j.filename, url: j.url, name: j.name },
        }));
        window.location.href = '/edit';
      } catch (e) {
        alert(e.message || 'Erreur');
        sendToEdit.disabled = false;
        sendToEdit.textContent = '✂️ Utiliser comme source (Édition)';
      }
    });
    d.appendChild(sendToEdit);
    // Boutons 1-clic « 🔍 Agrandir ×4 » et « 🙂 Réparer visages & mains »
    if (window.LisQuality && typeof LisQuality.makeUpscaleButton === 'function') {
      d.appendChild(LisQuality.makeUpscaleButton({ imageId: img.id }));
    }
    if (window.LisQuality && typeof LisQuality.makeRepairButton === 'function') {
      d.appendChild(LisQuality.makeRepairButton({ imageId: img.id }));
    }
    if (window.LisQuality && typeof LisQuality.makeRestoreX2Button === 'function') {
      d.appendChild(LisQuality.makeRestoreX2Button({ imageId: img.id }));
    }
    if (window.LisQuality && typeof LisQuality.makePidButton === 'function') {
      d.appendChild(LisQuality.makePidButton({ imageId: img.id }));
    }
    if (window.LisQuality && typeof LisQuality.makeVaryButtons === 'function') {
      d.appendChild(LisQuality.makeVaryButtons({ imageId: img.id }));
    }
    box.appendChild(d);
  });
  saveGenDraft();
}

// ---------- Agrandissement ×4 : affichage du résultat dans la grille ----------
function auxResultBadge(img) {
  if (img.vary) return { text: '🔀 VARIANTE', title: 'Variation façon Midjourney (img2img + nouvelle graine), enregistrée dans l\'historique', label: 'Variante' };
  if (img.repaired) return { text: '🙂 RÉPARÉE', title: 'Visages & mains re-détaillés (ADetailer), enregistrée dans l\'historique', label: 'Image réparée' };
  if ((img.scale || 4) === 2 && /restore/.test(img.filename || '')) return { text: '🩹 RESTAURÉE ×2', title: 'Restaurée ×2 par diffusion (SeedVR2), enregistrée dans l\'historique', label: 'Image restaurée ×2' };
  if (/^pid_/.test(img.filename || '')) return { text: '⬆️ PID ×4', title: 'Super-résolution générative (NVIDIA PiD, sortie 4096px), enregistrée dans l\'historique', label: 'Image PiD ×4' };
  const sc = img.scale || 4;
  return { text: `🔍 AGRANDIE ×${sc}`, title: `Version agrandie ×${sc}, enregistrée dans l'historique`, label: `Version agrandie ×${sc}` };
}

function appendUpscaledResults(images) {
  const box = $('#results');
  if (!box || !Array.isArray(images)) return;
  images.forEach(img => {
    const displayUrl = `${img.url}?u=${Date.now()}`;
    const badge = auxResultBadge(img);
    const d = document.createElement('div');
    d.className = 'result result-upscaled';
    d.innerHTML = `
      <span class="upscaled-badge" title="${badge.title}">${badge.text}</span>
      <img src="${displayUrl}" alt="">
      <div class="rbar">
        <span>${badge.label}</span>
        <a class="link" href="${img.url}" download>telecharger</a>
        <button type="button" class="link copy-prompt-link" title="Copier le prompt de l'image source">📋 prompt</button>
      </div>`;
    d.querySelector('img').addEventListener('click', () => {
      openLightbox([{
        src: displayUrl,
        downloadUrl: img.url,
        label: badge.label,
        role: 'result',
        badge: badge.text,
      }], 0);
    });
    if (window.LisQuality && typeof LisQuality.bindCopyPrompt === 'function') {
      LisQuality.bindCopyPrompt(d.querySelector('.copy-prompt-link'), img);
    }
    const sendToEdit = document.createElement('button');
    sendToEdit.type = 'button';
    sendToEdit.className = 'btn small result-use-source';
    sendToEdit.textContent = '✂️ Utiliser comme source (Édition)';
    sendToEdit.addEventListener('click', async () => {
      sendToEdit.disabled = true;
      sendToEdit.textContent = 'Envoi…';
      try {
        const r = await fetch('/api/use-output-as-source', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: img.id, filename: img.filename }),
        });
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || "Impossible d'envoyer l'image.");
        sessionStorage.setItem('edit_incoming_source', JSON.stringify({
          mode: 'canvas',
          file: { filename: j.filename, url: j.url, name: j.name },
        }));
        window.location.href = '/edit';
      } catch (e) {
        alert(e.message || 'Erreur');
        sendToEdit.disabled = false;
        sendToEdit.textContent = '✂️ Utiliser comme source (Édition)';
      }
    });
    d.appendChild(sendToEdit);
    if (window.LisQuality) {
      if (LisQuality.makeUpscaleButton) d.appendChild(LisQuality.makeUpscaleButton({ imageId: img.id }));
      if (LisQuality.makeRepairButton) d.appendChild(LisQuality.makeRepairButton({ imageId: img.id }));
      if (LisQuality.makeRestoreX2Button) d.appendChild(LisQuality.makeRestoreX2Button({ imageId: img.id }));
      if (LisQuality.makePidButton) d.appendChild(LisQuality.makePidButton({ imageId: img.id }));
      if (LisQuality.makeVaryButtons) d.appendChild(LisQuality.makeVaryButtons({ imageId: img.id }));
    }
    box.appendChild(d);
  });
}

// Branche la section Qualité sur le poller de la page (un seul timer partagé)
window.__lisPagePoll = pollStatus;
window.__lisOnUpscaleDone = appendUpscaledResults;


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
    saveGenDraft();
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
    saveGenDraft();
  } catch (e) { status.textContent = ''; alert(e.message); }
  finally { btn.disabled = false; btn.textContent = '🌐 Traduire EN'; }
}
$('#translate-btn')?.addEventListener('click', doTranslate);

// ---------- vérification mmproj pour les modèles Qwen-Image ----------
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

// Vérification du statut mmproj pour les modèles qui déclarent cette dépendance
async function checkMmproj() {
  const currentModel = $('#model') ? $('#model').value : null;
  const model = MODELS[currentModel];
  const needsMmproj = Boolean(model && model.mmproj_dep);
  const statusDiv = $('#mmproj-status');
  if (!statusDiv) return;
  if (!needsMmproj) {
    statusDiv.classList.add('hidden');
    return;
  }
  try {
    const r = await fetch(`/api/mmproj-status?model_id=${encodeURIComponent(currentModel || '')}`);
    const j = await r.json();
    const btn = $('#mmproj-download-btn');
    const msg = $('#mmproj-msg');
    if (btn && msg) {
      statusDiv.classList.remove('hidden');
      if (j.downloaded) {
        msg.innerHTML = "✓ mmproj disponible — prêt pour l'édition. "
          + "<a href=\"/edit\">Ouvrir le Studio d'édition →</a>";
        msg.classList.add('ok');
        btn.hidden = true;
      } else {
        msg.innerHTML = "⚠️ mmproj manquant — requis pour l'édition (1.2 Go). "
          + "<a href=\"/edit\">Le télécharger depuis le Studio d'édition</a>";
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
if (window.LisQuality) {
  LisQuality.initSection({ container: '#quality-section', withHires: true });
}

// ===== Lot de prompts (une image par ligne) =====
function buildBatchPayload(model_id) {
  const body = finalizeGenerationPayload(model_id);
  if (body) delete body.prompt;
  return body;
}

$('#batch-run-btn')?.addEventListener('click', async () => {
  const model_id = $('#model').value;
  const m = MODELS[model_id];
  if (!m || !m.status.ready) {
    if (window.showToast) window.showToast('❌ Le modèle sélectionné n’est pas installé.');
    return;
  }
  const ta = $('#batch-prompts');
  const lines = (ta?.value || '').split('\n').map(s => s.trim()).filter(Boolean);
  if (!lines.length) {
    if (window.showToast) window.showToast('⚠️ Écrivez au moins un prompt (une ligne par image).');
    return;
  }
  const status = $('#batch-status');
  if (status) status.textContent = 'envoi…';
  const body = buildBatchPayload(model_id) || {};
  body.prompts = lines.join('\n');
  try {
    const r = await fetch('/api/batch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!j.ok && !(j.queued > 0)) {
      const msg = (j.errors && j.errors[0] && j.errors[0].error) || j.error || 'Lot refusé.';
      if (status) status.textContent = '';
      if (window.showToast) window.showToast('❌ ' + msg);
      return;
    }
    if (status) status.textContent = `${j.queued} job(s) en file`;
    if (window.showToast) {
      window.showToast(j.errors && j.errors.length
        ? `🗂️ ${j.queued} génération(s) en file — ${j.errors.length} ligne(s) ignorée(s).`
        : `🗂️ Lot de ${j.queued} génération(s) ajouté à la file d'attente.`);
    }
    pollStatus();
  } catch (e) {
    if (status) status.textContent = '';
    if (window.showToast) window.showToast('❌ Connexion au serveur impossible.');
  }
});

// ===== Duel de seeds & comparaison de modèles =====
function randomSeed32() {
  return Math.floor(Math.random() * 2147483647);
}

async function postGenerate(body) {
  const r = await fetch('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

$('#duel-seeds-btn')?.addEventListener('click', async () => {
  const model_id = $('#model').value;
  const m = MODELS[model_id];
  if (!m || !m.status.ready) {
    if (window.showToast) window.showToast('❌ Le modèle sélectionné n’est pas installé.');
    return;
  }
  const body = finalizeGenerationPayload(model_id);
  if (!body || !body.prompt) {
    if (window.showToast) window.showToast('⚠️ Le prompt est vide.');
    return;
  }
  const s1 = randomSeed32();
  const s2 = s1 + 1;
  const j1 = await postGenerate({ ...body, seed: s1 });
  const j2 = await postGenerate({ ...body, seed: s2 });
  const okCount = [j1, j2].filter(j => j && j.ok).length;
  if (window.showToast) {
    window.showToast(okCount
      ? `⚔️ Duel lancé avec les seeds ${s1} et ${s2} — les deux images iront dans l'historique.`
      : '❌ Duel refusé par le moteur.');
  }
  if (okCount) pollStatus();
});

function populateCompareSelect() {
  const sel = $('#compare-model');
  if (!sel || !Object.keys(MODELS).length) return;
  const current = $('#model')?.value;
  sel.innerHTML = '';
  for (const [id, m] of Object.entries(MODELS)) {
    if (id === current) continue;
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.name + (m.status && m.status.ready ? ' ✓' : '  (à télécharger)');
    if (!m.status || !m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
  }
}

$('#model')?.addEventListener('change', populateCompareSelect);
$('#compare-models-btn')?.addEventListener('click', async () => {
  const model_id = $('#model').value;
  const other_id = $('#compare-model')?.value;
  const m = MODELS[model_id];
  const other = MODELS[other_id];
  if (!m || !m.status.ready) {
    if (window.showToast) window.showToast('❌ Le modèle courant n’est pas installé.');
    return;
  }
  if (!other) {
    if (window.showToast) window.showToast('⚠️ Choisissez un second modèle à comparer.');
    return;
  }
  if (!other.status.ready) {
    if (window.showToast) window.showToast(`❌ « ${other.name} » n'est pas installé (onglet Modèles).`);
    return;
  }
  const body = finalizeGenerationPayload(model_id);
  if (!body || !body.prompt) {
    if (window.showToast) window.showToast('⚠️ Le prompt est vide.');
    return;
  }
  const seed = randomSeed32();
  const j1 = await postGenerate({ ...body, seed });
  const j2 = await postGenerate({ ...body, model_id: other_id, quant: other.default_quant, seed });
  const msgs = [];
  if (j1 && j1.ok) msgs.push(m.name);
  if (j2 && j2.ok) msgs.push(other.name);
  const err = (!j1 || !j1.ok) && j2 && j2.error ? j2.error : (!j2 || !j2.ok) && j1 && j1.error ? j1.error : null;
  if (window.showToast) {
    window.showToast(msgs.length
      ? `🥊 Comparaison lancée (seed ${seed}) : ${msgs.join(' vs ')} — résultats dans l'historique.`
      : '❌ Comparaison refusée : ' + (err || 'erreur inconnue'));
  }
  if (msgs.length) pollStatus();
});

// ===== Restaurer les réglages depuis un PNG généré =====
async function restoreFromPngFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('image', file, file.name || 'capture.png');
  let j;
  try {
    const r = await fetch('/api/image-meta', { method: 'POST', body: fd });
    j = await r.json();
  } catch (e) {
    if (window.showToast) window.showToast('❌ Lecture du PNG impossible (connexion serveur).');
    return;
  }
  if (!j.ok) {
    if (window.showToast) window.showToast('❌ ' + (j.error || 'Aucune métadonnée lisible.'));
    return;
  }
  applyFormSettings(j.form || {});
}

function applyFormSettings(form) {
  const setVal = (id, v) => { const el = $(id); if (el && v !== undefined && v !== null) el.value = v; };
  if (form.model && MODELS[form.model]) {
    $('#model').value = form.model;
    onModelChange();
  }
  setVal('#prompt', form.prompt || '');
  setVal('#negative', form.negative || '');
  if (form.steps) setVal('#steps', form.steps);
  if (form.cfg !== undefined) setVal('#cfg', form.cfg);
  if (form.seed !== undefined) setVal('#seed', form.seed);
  // taille : on garde les pixels exacts via pendingRestoreSize
  const w = parseInt(form.width, 10), h = parseInt(form.height, 10);
  if (Number.isFinite(w) && Number.isFinite(h) && w >= 64 && h >= 64) {
    const clamp16 = v => Math.max(256, Math.min(2112, Math.round(v / 16) * 16));
    pendingRestoreSize = { width: clamp16(w), height: clamp16(h) };
    const info = $('#original-ratio-info');
    if (info) {
      info.hidden = false;
      info.textContent = `Taille restaurée depuis le PNG : ${pendingRestoreSize.width}×${pendingRestoreSize.height}`;
    }
  }
  // Sampler / scheduler de la section Qualité si présents
  if (form.sampler) {
    const sel = $('#q-sampler');
    if (sel) {
      const opt = sel.querySelector(`option[value="${CSS.escape(String(form.sampler))}"]`);
      if (opt) sel.value = form.sampler;
    }
  }
  if (form.scheduler) {
    const sel = $('#q-scheduler');
    if (sel) {
      const opt = sel.querySelector(`option[value="${CSS.escape(String(form.scheduler))}"]`);
      if (opt) sel.value = form.scheduler;
    }
  }
  if (window.showToast) {
    window.showToast('📥 Réglages restaurés depuis le PNG (prompt, seed, modèle…).');
  }
  saveGenDraft();
}

$('#restore-png-btn')?.addEventListener('click', () => $('#restore-png-input')?.click());
$('#restore-png-input')?.addEventListener('change', e => {
  const f = e.target.files && e.target.files[0];
  if (f) restoreFromPngFile(f);
  e.target.value = '';
});

// Drag-drop d'un PNG n'importe où sur le panneau de réglages
(() => {
  const panel = document.querySelector('.form-panel');
  if (!panel) return;
  let dragDepth = 0;
  const hasPng = e => {
    const items = e.dataTransfer && e.dataTransfer.items ? [...e.dataTransfer.items] : [];
    return items.some(it => it.kind === 'file' && (it.type === 'image/png' || it.type === ''));
  };
  panel.addEventListener('dragenter', e => {
    if (e.target.closest('#file-upload-area, #img2img-box')) return;
    if (hasPng(e)) { dragDepth++; panel.classList.add('drop-restore-active'); e.preventDefault(); }
  });
  panel.addEventListener('dragover', e => {
    if (e.target.closest('#file-upload-area, #img2img-box')) return;
    if (hasPng(e)) e.preventDefault();
  });
  panel.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) panel.classList.remove('drop-restore-active');
  });
  panel.addEventListener('drop', e => {
    const files = e.dataTransfer && e.dataTransfer.files ? [...e.dataTransfer.files] : [];
    const png = files.find(f => /\.png$/i.test(f.name || '') || f.type === 'image/png');
    panel.classList.remove('drop-restore-active');
    dragDepth = 0;
    // Ne pas voler les drops destinés à la zone img2img (ou à un champ de saisie)
    if (e.target.closest('#file-upload-area, #img2img-box, input, textarea, select')) {
      return;
    }
    if (png) {
      e.preventDefault();
      e.stopPropagation();
      restoreFromPngFile(png);
    }
    // sinon : on laisse le handler img2img habituel prendre le relais
  }, true);
})();

// Peupler le comparateur au chargement (après loadModels)
setTimeout(populateCompareSelect, 1200);
