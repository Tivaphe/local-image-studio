/* ===== Page « Studio d'édition » =====
   Edition par references multiples : 1 canvas (image 1) + jusqu'a N-1 references.
   Inclut :
     - Mode Outpainting avec déplacement interactif de l'image à la souris sur l'aperçu,
       grille d'ancrage 9 points, préréglages de ratio/dézoom et pré-prompts dédiés.
     - Bibliothèque de pré-prompts adaptés à chaque modèle + sauvegarde de pré-prompts perso.
     - Comparaison instantanée sans rechargement dans la Lightbox (flèches clavier, molette souris,
       touche Espace / clic maintenu pour basculer entre Image Source et Image Modifiée).
*/
if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

const RATIOS = window.RATIOS || { "1:1": [1024, 1024] };
const STORE_KEY = "lis_edit_prefs";
const EDIT_DRAFT_KEY = "lis_edit_draft_v1";
const CUSTOM_PREPROMPTS_KEY = "lis_edit_custom_preprompts";

let MODELS = {};
let editModels = {};
let canvas = null;          // {path, url, name, width, height, objectUrl, imgEl}
let refs = [];              // idem, dans l'ordre
let currentRatio = "1:1";
let ratioBeforeOriginal = "1:1";
let pollTimer = null;
let vramGb = 0;
let comparisonSource = null;
let generationSourceCount = 0;
let lastGeneratedResults = [];
let activeCompareResultIdx = 0;
let currentBatchStamp = Date.now();
let lastRunWasOutpaint = false;
let tempOutpaintItem = null;
let outpaintDragState = null;
let isRestoringEditDraft = false;

// --- État Recadrage / Rotation & Inpainting au pinceau ---
let originalCanvasBackup = null;
let cropState = {
  open: false,
  ratio: 'free',
  rect: null, // { x, y, w, h } en coordonnées image
  drag: null,
};
let inpaintState = {
  tool: 'brush', // 'brush' | 'eraser'
  size: 36,
  maskCanvas: null, // offscreen canvas binaire (alpha > 0 = zone peinte)
  undoStack: [],
  drawing: false,
  lastPt: null,
  cursorPt: null,
};
let tempInpaintCanvasItem = null;
let tempInpaintMaskItem = null;
let lastRunWasInpaint = false;
let lastInpaintMaskSnapshot = null; // offscreen canvas du masque au moment du lancement
let lastInpaintOrigImgEl = null;

// --------------------------------------------------- sauvegarde inter-pages --
function saveEditDraft() {
  if (isRestoringEditDraft) return;
  try {
    const serializeImg = item => item ? {
      path: item.path,
      url: item.url,
      name: item.name,
      width: item.width || 0,
      height: item.height || 0,
      fresh: Boolean(item.fresh),
    } : null;

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
      refBudget: $('#ref-budget')?.value || 'auto',
      currentRatio,
      ratioBeforeOriginal,
      canvas: serializeImg(canvas),
      refs: refs.map(serializeImg).filter(Boolean),
      outpaint: {
        enabled: Boolean($('#outpaint-enabled')?.checked),
        top: $('#outpaint-top')?.value || '25',
        bottom: $('#outpaint-bottom')?.value || '25',
        left: $('#outpaint-left')?.value || '25',
        right: $('#outpaint-right')?.value || '25',
        fill: $('#outpaint-fill')?.value || 'blur',
        autoPrompt: Boolean($('#outpaint-auto-prompt')?.checked),
      },
      lastGeneratedResults: (lastGeneratedResults || []).map(r => ({
        url: r.url,
        filename: r.filename,
        seed: r.seed,
        id: r.id,
        displayUrl: r.displayUrl,
      })),
      comparisonSource: (comparisonSource && !String(comparisonSource).startsWith('data:'))
        ? comparisonSource
        : null,
      lastRunWasOutpaint: Boolean(lastRunWasOutpaint),
      currentBatchStamp,
    };
    const json = JSON.stringify(draft);
    sessionStorage.setItem(EDIT_DRAFT_KEY, json);
    localStorage.setItem(EDIT_DRAFT_KEY, json);
  } catch (e) {}
}

async function restoreEditDraft() {
  let draft = null;
  try {
    const raw = sessionStorage.getItem(EDIT_DRAFT_KEY) || localStorage.getItem(EDIT_DRAFT_KEY);
    draft = raw ? JSON.parse(raw) : null;
  } catch (e) {
    draft = null;
  }
  if (!draft) return;

  isRestoringEditDraft = true;
  try {
    if (draft.model && editModels[draft.model]) {
      $('#model').value = draft.model;
      onModelChange();
    }
    const m = currentModel();
    if (draft.quant && m && m.quants.includes(draft.quant)) {
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
    if (draft.seed !== undefined && draft.seed !== null) $('#seed').value = draft.seed;
    if (draft.batch && $('#batch')) {
      $('#batch').value = draft.batch;
      const v = parseInt(draft.batch, 10) || 1;
      if ($('#batch-val')) $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
    }
    if (draft.refBudget && $('#ref-budget')) {
      $('#ref-budget').value = draft.refBudget;
    }
    if (draft.ratioBeforeOriginal && RATIOS[draft.ratioBeforeOriginal]) {
      ratioBeforeOriginal = draft.ratioBeforeOriginal;
    }
    if (draft.currentRatio && (draft.currentRatio === 'original' || RATIOS[draft.currentRatio])) {
      currentRatio = draft.currentRatio;
    }
    if (draft.outpaint) {
      if ($('#outpaint-enabled')) $('#outpaint-enabled').checked = Boolean(draft.outpaint.enabled);
      setOutpaintMargins(
        draft.outpaint.top ?? 25,
        draft.outpaint.bottom ?? 25,
        draft.outpaint.left ?? 25,
        draft.outpaint.right ?? 25
      );
      if (draft.outpaint.fill && $('#outpaint-fill')) $('#outpaint-fill').value = draft.outpaint.fill;
      if (draft.outpaint.autoPrompt !== undefined && $('#outpaint-auto-prompt')) {
        $('#outpaint-auto-prompt').checked = Boolean(draft.outpaint.autoPrompt);
      }
    }

    // Restauration du canvas et des références si les fichiers sont toujours accessibles
    const hydrateImg = async saved => {
      if (!saved || !saved.url || !saved.path) return null;
      try {
        const dims = await readImageDimensions(saved.url);
        return {
          path: saved.path,
          url: saved.url,
          name: saved.name || saved.path.split('/').pop(),
          width: dims.width || saved.width || 0,
          height: dims.height || saved.height || 0,
          imgEl: dims.imgEl,
          objectUrl: null,
          fresh: Boolean(saved.fresh),
        };
      } catch (e) {
        return null;
      }
    };

    if (draft.canvas) {
      canvas = await hydrateImg(draft.canvas);
    }
    if (Array.isArray(draft.refs) && draft.refs.length) {
      const loadedRefs = [];
      for (const r of draft.refs) {
        const item = await hydrateImg(r);
        if (item) loadedRefs.push(item);
      }
      refs = loadedRefs.slice(0, refsLimit());
    }
    if (currentRatio === 'original' && !canvas) {
      currentRatio = RATIOS[ratioBeforeOriginal] ? ratioBeforeOriginal : '1:1';
    }

    refreshAll();

    if (Array.isArray(draft.lastGeneratedResults) && draft.lastGeneratedResults.length) {
      currentBatchStamp = draft.currentBatchStamp || Date.now();
      lastRunWasOutpaint = Boolean(draft.lastRunWasOutpaint);
      if (lastRunWasOutpaint && canvas && canvas.imgEl) {
        const geom = computeOutpaintGeometry();
        comparisonSource = geom ? drawAlignedBeforeSurface(geom, canvas.imgEl) : canvas.url;
      } else {
        comparisonSource = draft.comparisonSource || (canvas && canvas.url) || null;
      }
      if (comparisonSource) $('#compare-before').src = comparisonSource;
      showResults(draft.lastGeneratedResults);
    }
  } finally {
    isRestoringEditDraft = false;
  }
}

// Applique une image envoyée depuis l'Historique ou la page Générer (« Utiliser en Édition »)
// sans effacer le prompt ni les réglages en cours !
async function applyIncomingSource() {
  let incoming = null;
  try { incoming = JSON.parse(sessionStorage.getItem('edit_incoming_source') || 'null'); } catch (e) {}
  if (!incoming || !incoming.file || !incoming.file.url) return;
  sessionStorage.removeItem('edit_incoming_source');

  try {
    const dims = await readImageDimensions(incoming.file.url);
    const newItem = {
      path: incoming.file.filename,
      url: incoming.file.url,
      name: incoming.file.name || incoming.file.filename.split('/').pop(),
      width: dims.width,
      height: dims.height,
      imgEl: dims.imgEl,
      objectUrl: null,
      fresh: true,
    };

    if (incoming.mode === 'ref' && canvas) {
      const limit = refsLimit();
      if (refs.length < limit) {
        refs.push(newItem);
      } else {
        showGenError(`Nombre maximum de références atteint (${maxImages()} images max).`);
      }
    } else {
      if (canvas) await removeUploaded(canvas);
      canvas = newItem;
      if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio;
      currentRatio = 'original';
    }
    showGenError('');
    refreshAll();
    saveEditDraft();
  } catch (e) {
    showGenError(e.message || "Impossible de charger l'image sélectionnée depuis l'historique.");
  }
}

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
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight, imgEl: img });
    img.onerror = () => reject(new Error("Impossible de lire les dimensions de l'image."));
    img.src = src;
  });
}

// ------------------------------------------- adaptation syntaxe & pré-prompts
function refTokenForModel(m, n) {
  if (!m) return `image ${n}`;
  if (m.ref_tag_syntax) return m.ref_tag_syntax.replace('{n}', String(n));
  return `image ${n}`;
}

function normalizePromptToPlaceholders(text) {
  return String(text || '')
    .replace(/<image_?(\d+)>/gi, '{img$1}')
    .replace(/\bimage\s+(\d+)\b/gi, '{img$1}');
}

function adaptPromptToModel(text, m) {
  if (!text || !m) return text || '';
  const normalized = normalizePromptToPlaceholders(text);
  return normalized.replace(/\{img(\d+)\}/g, (_, num) => refTokenForModel(m, num));
}

function loadCustomEditPreprompts() {
  try {
    const arr = JSON.parse(localStorage.getItem(CUSTOM_PREPROMPTS_KEY) || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    return [];
  }
}

function saveCustomEditPreprompts(list) {
  try {
    localStorage.setItem(CUSTOM_PREPROMPTS_KEY, JSON.stringify(list));
  } catch (e) {}
}

function renderEditPreprompts() {
  const m = currentModel();
  const sel = $('#edit-preprompt-select');
  const delBtn = $('#del-edit-preprompt-btn');
  const outpaintChips = $('#outpaint-prompt-chips');
  if (!sel || !m) return;

  const builtIn = m.edit_presets || [];
  const outpaintPresets = m.outpaint_presets || [];
  const custom = loadCustomEditPreprompts();

  sel.innerHTML = `<option value="">→ Choisir un pré-prompt adapté à ${esc(m.name)} ←</option>`;

  const addGroup = (label, items, prefix) => {
    if (!items.length) return;
    const grp = document.createElement('optgroup');
    grp.label = label;
    items.forEach(item => {
      const opt = document.createElement('option');
      opt.value = `${prefix}:${item.id}`;
      opt.textContent = item.label;
      opt.dataset.prompt = adaptPromptToModel(item.prompt, m);
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  };

  addGroup(`✂️ Édition sur 1 image (${m.name})`, builtIn.filter(x => x.category === 'canvas'), 'builtin');
  addGroup(`📚 Multi-images Canvas + Référence (${m.name})`, builtIn.filter(x => x.category === 'multi'), 'builtin');
  addGroup(`📐 Outpainting — Étendre le cadre (${m.name})`, builtIn.filter(x => x.category === 'outpaint'), 'builtin');
  addGroup(`⭐ Mes pré-prompts enregistrés (adaptés à ${m.name})`, custom, 'custom');

  if (delBtn) delBtn.hidden = true;

  // Chips de pré-prompts rapides dans le panneau Outpainting
  if (outpaintChips) {
    outpaintChips.innerHTML = '';
    const allOutpaint = [
      ...outpaintPresets,
      ...custom.filter(c => c.isOutpaint).map(c => ({
        id: c.id,
        label: `⭐ ${c.label}`,
        prompt: adaptPromptToModel(c.prompt, m),
      })),
    ];
    allOutpaint.forEach(item => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-tag outpaint-prompt-chip';
      btn.textContent = item.label;
      btn.title = item.prompt;
      btn.addEventListener('click', () => {
        $('#prompt').value = item.prompt;
        $$('.outpaint-prompt-chip', outpaintChips).forEach(b => b.classList.toggle('active', b === btn));
        updateTagWarning();
      });
      outpaintChips.appendChild(btn);
    });
  }
}

$('#edit-preprompt-select')?.addEventListener('change', e => {
  const sel = e.target;
  const opt = sel.selectedOptions[0];
  const delBtn = $('#del-edit-preprompt-btn');
  if (delBtn) {
    delBtn.hidden = !(sel.value && sel.value.startsWith('custom:'));
  }
  if (!opt || !opt.dataset.prompt) return;
  $('#prompt').value = opt.dataset.prompt;
  // Si l'utilisateur choisit un pré-prompt d'outpainting et que le modèle le supporte, activer le mode outpainting
  if (sel.value.includes('outpaint_') && modelSupportsOutpaint() && $('#outpaint-enabled') && !$('#outpaint-enabled').checked) {
    $('#outpaint-enabled').checked = true;
    updateOutpaintUI();
  }
  updateTagWarning();
  saveEditDraft();
});

$('#save-edit-preprompt-btn')?.addEventListener('click', () => {
  const txt = $('#prompt').value.trim();
  if (!txt) {
    alert("Écrivez d'abord une instruction dans le champ prompt avant de l'enregistrer.");
    return;
  }
  const defaultName = txt.slice(0, 36) + (txt.length > 36 ? '…' : '');
  const label = prompt("Nom de ce pré-prompt (il s'adaptera automatiquement à la syntaxe de chaque modèle) :", defaultName);
  if (!label || !label.trim()) return;
  const custom = loadCustomEditPreprompts();
  const id = 'cust_' + Date.now();
  custom.push({
    id,
    label: label.trim(),
    prompt: normalizePromptToPlaceholders(txt),
    isOutpaint: isOutpaintActive(),
  });
  saveCustomEditPreprompts(custom);
  renderEditPreprompts();
  $('#edit-preprompt-select').value = `custom:${id}`;
  if ($('#del-edit-preprompt-btn')) $('#del-edit-preprompt-btn').hidden = false;
});

$('#del-edit-preprompt-btn')?.addEventListener('click', () => {
  const sel = $('#edit-preprompt-select');
  if (!sel || !sel.value.startsWith('custom:')) return;
  const id = sel.value.slice('custom:'.length);
  const custom = loadCustomEditPreprompts().filter(x => x.id !== id);
  saveCustomEditPreprompts(custom);
  renderEditPreprompts();
});

// ------------------------------------------------------------ outpainting --
function modelSupportsOutpaint() {
  const m = currentModel();
  return Boolean(m && m.supports_outpainting);
}

function getOutpaintMargins() {
  return {
    top: parseInt($('#outpaint-top')?.value || '0', 10) || 0,
    bottom: parseInt($('#outpaint-bottom')?.value || '0', 10) || 0,
    left: parseInt($('#outpaint-left')?.value || '0', 10) || 0,
    right: parseInt($('#outpaint-right')?.value || '0', 10) || 0,
  };
}

function setOutpaintMargins(top, bottom, left, right) {
  const clamp = v => Math.max(0, Math.min(150, Math.round(v)));
  if ($('#outpaint-top')) $('#outpaint-top').value = clamp(top);
  if ($('#outpaint-bottom')) $('#outpaint-bottom').value = clamp(bottom);
  if ($('#outpaint-left')) $('#outpaint-left').value = clamp(left);
  if ($('#outpaint-right')) $('#outpaint-right').value = clamp(right);
}

function isOutpaintActive() {
  if (!modelSupportsOutpaint()) return false;
  const enabled = Boolean($('#outpaint-enabled')?.checked);
  if (!enabled) return false;
  const { top, bottom, left, right } = getOutpaintMargins();
  return (top + bottom + left + right) > 0;
}

function getOutpaintActiveDirections() {
  const m = getOutpaintMargins();
  return ['top', 'bottom', 'left', 'right'].filter(k => m[k] > 0);
}

function computeOutpaintGeometry() {
  if (!canvas || !canvas.width || !canvas.height) return null;
  const { top, bottom, left, right } = getOutpaintMargins();
  const padTop = Math.round(canvas.height * (top / 100));
  const padBottom = Math.round(canvas.height * (bottom / 100));
  const padLeft = Math.round(canvas.width * (left / 100));
  const padRight = Math.round(canvas.width * (right / 100));
  const expW = canvas.width + padLeft + padRight;
  const expH = canvas.height + padTop + padBottom;

  // Alignement sur 32 px (compatible Qwen-Image 2.1 en 32 px et FLUX/Fibo en 16 px)
  const scaleToArea = Math.sqrt((1024 * 1024) / (expW * expH));
  const scaleToMaxSide = 1344 / Math.max(expW, expH);
  const scale = Math.min(scaleToArea, scaleToMaxSide);
  const round32 = v => Math.max(64, Math.round(v / 32) * 32);
  const outW = round32(expW * scale);
  const outH = round32(expH * scale);

  const ix = Math.round((padLeft / expW) * outW);
  const iy = Math.round((padTop / expH) * outH);
  const iw = Math.max(1, Math.round((canvas.width / expW) * outW));
  const ih = Math.max(1, Math.round((canvas.height / expH) * outH));

  return {
    top, bottom, left, right,
    padTop, padBottom, padLeft, padRight,
    expW, expH, outW, outH,
    ix, iy, iw, ih,
  };
}

function drawOutpaintSurface(ctx, targetW, targetH, geom, imgEl, fillMode, showGuides = false) {
  const sx = targetW / geom.outW;
  const sy = targetH / geom.outH;
  const ix = Math.round(geom.ix * sx);
  const iy = Math.round(geom.iy * sy);
  const iw = Math.max(1, Math.round(geom.iw * sx));
  const ih = Math.max(1, Math.round(geom.ih * sy));

  ctx.save();
  ctx.clearRect(0, 0, targetW, targetH);

  if (fillMode === 'white') {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, targetW, targetH);
  } else if (fillMode === 'black') {
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, targetW, targetH);
  } else if (fillMode === 'neutral') {
    ctx.fillStyle = '#808080';
    ctx.fillRect(0, 0, targetW, targetH);
  } else if (fillMode === 'mirror' && imgEl) {
    ctx.fillStyle = '#404040';
    ctx.fillRect(0, 0, targetW, targetH);
    ctx.save();
    ctx.filter = `blur(${Math.max(4, Math.round(Math.min(targetW, targetH) * 0.015))}px)`;
    ctx.drawImage(imgEl, -targetW * 0.05, -targetH * 0.05, targetW * 1.1, targetH * 1.1);
    if (ix > 0) {
      ctx.save();
      ctx.translate(ix, iy);
      ctx.scale(-1, 1);
      ctx.drawImage(imgEl, 0, 0, ix, ih);
      ctx.restore();
    }
    if (ix + iw < targetW) {
      const rw = targetW - (ix + iw);
      ctx.save();
      ctx.translate(targetW, iy);
      ctx.scale(-1, 1);
      ctx.drawImage(imgEl, 0, 0, rw, ih);
      ctx.restore();
    }
    if (iy > 0) {
      ctx.save();
      ctx.translate(ix, iy);
      ctx.scale(1, -1);
      ctx.drawImage(imgEl, 0, 0, iw, iy);
      ctx.restore();
    }
    if (iy + ih < targetH) {
      const bh = targetH - (iy + ih);
      ctx.save();
      ctx.translate(ix, targetH);
      ctx.scale(1, -1);
      ctx.drawImage(imgEl, 0, 0, iw, bh);
      ctx.restore();
    }
    ctx.restore();
  } else if (imgEl) {
    ctx.fillStyle = '#2a2d36';
    ctx.fillRect(0, 0, targetW, targetH);
    ctx.save();
    const blurPx = Math.max(6, Math.round(Math.min(targetW, targetH) * 0.035));
    ctx.filter = `blur(${blurPx}px)`;
    ctx.drawImage(imgEl, -targetW * 0.08, -targetH * 0.08, targetW * 1.16, targetH * 1.16);
    ctx.restore();
  }

  // Image source positionnée à (ix, iy)
  if (imgEl) {
    ctx.drawImage(imgEl, ix, iy, iw, ih);
  }

  if (showGuides) {
    ctx.fillStyle = 'rgba(124, 92, 255, 0.16)';
    if (iy > 0) ctx.fillRect(0, 0, targetW, iy);
    if (iy + ih < targetH) ctx.fillRect(0, iy + ih, targetW, targetH - (iy + ih));
    if (ix > 0) ctx.fillRect(0, iy, ix, ih);
    if (ix + iw < targetW) ctx.fillRect(ix + iw, iy, targetW - (ix + iw), ih);

    ctx.strokeStyle = '#9d83ff';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(ix + 1, iy + 1, Math.max(2, iw - 2), Math.max(2, ih - 2));
    ctx.setLineDash([]);

    // Poignée visuelle centrale indiquant qu'on peut déplacer l'image
    const cx = ix + iw / 2;
    const cy = iy + ih / 2;
    ctx.fillStyle = 'rgba(14, 15, 19, 0.72)';
    ctx.beginPath();
    ctx.arc(cx, cy, 14, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#9d83ff';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('✥', cx, cy);
  }

  ctx.restore();
}

function drawAlignedBeforeSurface(geom, imgEl) {
  const off = document.createElement('canvas');
  off.width = geom.outW;
  off.height = geom.outH;
  const ctx = off.getContext('2d');
  ctx.fillStyle = '#12141b';
  ctx.fillRect(0, 0, geom.outW, geom.outH);
  const step = 24;
  ctx.fillStyle = '#1b1f2a';
  for (let y = 0; y < geom.outH; y += step) {
    for (let x = 0; x < geom.outW; x += step) {
      if (((x / step) + (y / step)) % 2 === 0) {
        ctx.fillRect(x, y, step, step);
      }
    }
  }
  if (imgEl) {
    ctx.drawImage(imgEl, geom.ix, geom.iy, geom.iw, geom.ih);
  }
  ctx.strokeStyle = 'rgba(157, 131, 255, 0.65)';
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 6]);
  ctx.strokeRect(geom.ix, geom.iy, geom.iw, geom.ih);
  return off.toDataURL('image/png');
}

async function createOutpaintFileAndBeforePreview() {
  const geom = computeOutpaintGeometry();
  if (!geom || !canvas) return null;
  let imgEl = canvas.imgEl;
  if (!imgEl) {
    const loaded = await readImageDimensions(canvas.url);
    imgEl = loaded.imgEl;
    canvas.imgEl = imgEl;
  }
  const fillMode = $('#outpaint-fill')?.value || 'blur';
  const off = document.createElement('canvas');
  off.width = geom.outW;
  off.height = geom.outH;
  const ctx = off.getContext('2d');
  drawOutpaintSurface(ctx, geom.outW, geom.outH, geom, imgEl, fillMode, false);

  const blob = await new Promise((resolve, reject) => {
    off.toBlob(b => (b ? resolve(b) : reject(new Error("Échec de génération du canevas étendu."))), 'image/png');
  });
  const file = new File([blob], `outpaint_${canvas.name || 'canvas'}.png`, { type: 'image/png' });
  const beforeDataUrl = drawAlignedBeforeSurface(geom, imgEl);
  return { file, geom, beforeDataUrl };
}

function updateAnchorHighlight() {
  const { top, bottom, left, right } = getOutpaintMargins();
  const totalH = left + right;
  const totalV = top + bottom;
  const hPos = totalH === 0 ? 'c' : (left <= 2 ? 'l' : (right <= 2 ? 'r' : (Math.abs(left - right) <= 4 ? 'c' : '')));
  const vPos = totalV === 0 ? 'm' : (top <= 2 ? 't' : (bottom <= 2 ? 'b' : (Math.abs(top - bottom) <= 4 ? 'm' : '')));
  const code = (vPos && hPos) ? (vPos + hPos) : '';
  $$('.anchor-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.opAnchor === code);
  });
}

function updateOutpaintUI() {
  const box = $('#outpaint-box');
  const controls = $('#outpaint-controls');
  const previewWrap = $('#outpaint-preview-wrap');
  if (!box || !controls) return;

  const supported = modelSupportsOutpaint();
  box.hidden = !supported;
  if (!supported) {
    controls.hidden = true;
    return;
  }

  const enabled = Boolean($('#outpaint-enabled')?.checked);
  controls.hidden = !enabled;

  const { top, bottom, left, right } = getOutpaintMargins();
  $('#op-top-val').textContent = `${top}%`;
  $('#op-bottom-val').textContent = `${bottom}%`;
  $('#op-left-val').textContent = `${left}%`;
  $('#op-right-val').textContent = `${right}%`;
  updateAnchorHighlight();

  if (!enabled || !canvas || !canvas.width || !canvas.height) {
    if (previewWrap) previewWrap.hidden = true;
    updateOriginalRatioInfo();
    return;
  }

  const geom = computeOutpaintGeometry();
  if (!geom) {
    if (previewWrap) previewWrap.hidden = true;
    return;
  }

  previewWrap.hidden = false;
  $('#outpaint-dims-info').textContent =
    `Source ${canvas.width}×${canvas.height} → Cadre ${geom.expW}×${geom.expH} (sortie ${geom.outW}×${geom.outH})`;

  const pvCanvas = $('#outpaint-preview-canvas');
  const maxPreviewSide = 260;
  const scale = maxPreviewSide / Math.max(geom.outW, geom.outH);
  pvCanvas.width = Math.max(70, Math.round(geom.outW * scale));
  pvCanvas.height = Math.max(70, Math.round(geom.outH * scale));
  const ctx = pvCanvas.getContext('2d');
  drawOutpaintSurface(ctx, pvCanvas.width, pvCanvas.height, geom, canvas.imgEl, $('#outpaint-fill')?.value || 'blur', true);
  updateOriginalRatioInfo();
  saveEditDraft();
}

function applyOutpaintAnchor(anchor) {
  let { top, bottom, left, right } = getOutpaintMargins();
  let totalH = left + right;
  let totalV = top + bottom;
  if (totalH === 0 && totalV === 0) {
    totalH = 50;
    totalV = 50;
  }
  const vChar = anchor[0]; // 't' | 'm' | 'b'
  const hChar = anchor[1]; // 'l' | 'c' | 'r'

  if (vChar === 't') {
    if (totalV === 0) totalV = 40;
    top = 0; bottom = totalV;
  } else if (vChar === 'b') {
    if (totalV === 0) totalV = 40;
    top = totalV; bottom = 0;
  } else {
    top = Math.round(totalV / 2);
    bottom = totalV - top;
  }

  if (hChar === 'l') {
    if (totalH === 0) totalH = 40;
    left = 0; right = totalH;
  } else if (hChar === 'r') {
    if (totalH === 0) totalH = 40;
    left = totalH; right = 0;
  } else {
    left = Math.round(totalH / 2);
    right = totalH - left;
  }

  setOutpaintMargins(top, bottom, left, right);
  updateOutpaintUI();
  updateTagWarning();
}

function applyOutpaintPreset(preset) {
  if (preset === 'zoom125') setOutpaintMargins(15, 15, 15, 15);
  else if (preset === 'zoom150') setOutpaintMargins(25, 25, 25, 25);
  else if (preset === 'zoom200') setOutpaintMargins(50, 50, 50, 50);
  else if (preset === 'horiz50') setOutpaintMargins(0, 0, 25, 25);
  else if (preset === 'vert50') setOutpaintMargins(25, 25, 0, 0);
  else if (preset === 'reset') setOutpaintMargins(0, 0, 0, 0);
  else if (preset === 'ratio16_9' || preset === 'ratio9_16' || preset === 'ratio1_1') {
    const w = (canvas && canvas.width) || 1024;
    const h = (canvas && canvas.height) || 1024;
    const targetRatio = preset === 'ratio16_9' ? (16 / 9) : (preset === 'ratio9_16' ? (9 / 16) : 1);
    const curRatio = w / h;
    if (curRatio < targetRatio) {
      const targetW = h * targetRatio;
      const sidePct = Math.round(((targetW - w) / 2 / w) * 100);
      setOutpaintMargins(0, 0, Math.max(5, sidePct), Math.max(5, sidePct));
    } else if (curRatio > targetRatio) {
      const targetH = w / targetRatio;
      const vertPct = Math.round(((targetH - h) / 2 / h) * 100);
      setOutpaintMargins(Math.max(5, vertPct), Math.max(5, vertPct), 0, 0);
    } else {
      setOutpaintMargins(20, 20, 20, 20);
    }
  }
  updateOutpaintUI();
  updateTagWarning();
}

// Déplacement interactif de l'image à la souris / au doigt sur le canvas d'aperçu Outpainting
function wireOutpaintCanvasDrag() {
  const pvCanvas = $('#outpaint-preview-canvas');
  if (!pvCanvas) return;

  pvCanvas.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !canvas) return;
    e.preventDefault();
    let { top, bottom, left, right } = getOutpaintMargins();
    if (top + bottom + left + right === 0) {
      top = 25; bottom = 25; left = 25; right = 25;
      setOutpaintMargins(top, bottom, left, right);
      updateOutpaintUI();
    }
    const geom = computeOutpaintGeometry();
    const rect = pvCanvas.getBoundingClientRect();
    const imgScreenW = Math.max(24, (geom.iw / geom.outW) * rect.width);
    const imgScreenH = Math.max(24, (geom.ih / geom.outH) * rect.height);

    outpaintDragState = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startTop: top,
      startBottom: bottom,
      startLeft: left,
      startRight: right,
      totalH: left + right,
      totalV: top + bottom,
      imgScreenW,
      imgScreenH,
    };
    pvCanvas.classList.add('dragging');
    if (typeof pvCanvas.setPointerCapture === 'function') {
      try { pvCanvas.setPointerCapture(e.pointerId); } catch (_) {}
    }
  });

  pvCanvas.addEventListener('pointermove', e => {
    if (!outpaintDragState || e.pointerId !== outpaintDragState.pointerId) return;
    e.preventDefault();
    const dx = e.clientX - outpaintDragState.startX;
    const dy = e.clientY - outpaintDragState.startY;
    const deltaPctX = Math.round((dx / outpaintDragState.imgScreenW) * 100);
    const deltaPctY = Math.round((dy / outpaintDragState.imgScreenH) * 100);

    let newLeft = outpaintDragState.startLeft;
    let newRight = outpaintDragState.startRight;
    if (outpaintDragState.totalH > 0) {
      newLeft = Math.max(0, Math.min(outpaintDragState.totalH, outpaintDragState.startLeft + deltaPctX));
      newRight = outpaintDragState.totalH - newLeft;
    } else if (Math.abs(deltaPctX) > 2) {
      if (deltaPctX > 0) { newLeft = Math.min(150, deltaPctX); newRight = 0; }
      else { newLeft = 0; newRight = Math.min(150, -deltaPctX); }
    }

    let newTop = outpaintDragState.startTop;
    let newBottom = outpaintDragState.startBottom;
    if (outpaintDragState.totalV > 0) {
      newTop = Math.max(0, Math.min(outpaintDragState.totalV, outpaintDragState.startTop + deltaPctY));
      newBottom = outpaintDragState.totalV - newTop;
    } else if (Math.abs(deltaPctY) > 2) {
      if (deltaPctY > 0) { newTop = Math.min(150, deltaPctY); newBottom = 0; }
      else { newTop = 0; newBottom = Math.min(150, -deltaPctY); }
    }

    setOutpaintMargins(newTop, newBottom, newLeft, newRight);
    updateOutpaintUI();
    updateTagWarning();
  });

  const stopDrag = e => {
    if (!outpaintDragState) return;
    if (typeof pvCanvas.releasePointerCapture === 'function' && e.pointerId !== undefined) {
      try { pvCanvas.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    outpaintDragState = null;
    pvCanvas.classList.remove('dragging');
  };
  pvCanvas.addEventListener('pointerup', stopDrag);
  pvCanvas.addEventListener('pointercancel', stopDrag);

  // Molette sur l'aperçu : ajuste proportionnellement les marges autour de l'image
  pvCanvas.addEventListener('wheel', e => {
    if (!canvas) return;
    e.preventDefault();
    const step = e.deltaY > 0 ? 5 : -5;
    const { top, bottom, left, right } = getOutpaintMargins();
    const totalH = left + right;
    const totalV = top + bottom;
    const ratioL = totalH > 0 ? (left / totalH) : 0.5;
    const ratioT = totalV > 0 ? (top / totalV) : 0.5;
    const nextH = Math.max(0, Math.min(300, totalH + step * 2));
    const nextV = Math.max(0, Math.min(300, totalV + step * 2));
    setOutpaintMargins(
      Math.round(nextV * ratioT),
      Math.round(nextV * (1 - ratioT)),
      Math.round(nextH * ratioL),
      Math.round(nextH * (1 - ratioL))
    );
    updateOutpaintUI();
    updateTagWarning();
  }, { passive: false });
}
wireOutpaintCanvasDrag();

$('#outpaint-enabled')?.addEventListener('change', () => {
  if ($('#outpaint-enabled').checked) {
    if ($('#inpaint-enabled')?.checked) {
      $('#inpaint-enabled').checked = false;
      updateInpaintUI();
    }
    if (canvas) {
      currentRatio = 'original';
      buildRatios();
    }
  }
  updateOutpaintUI();
  updateTagWarning();
});
['#outpaint-top', '#outpaint-bottom', '#outpaint-left', '#outpaint-right', '#outpaint-fill'].forEach(sel => {
  $(sel)?.addEventListener('input', () => {
    updateOutpaintUI();
    updateTagWarning();
  });
});
$$('[data-op-preset]').forEach(btn => {
  btn.addEventListener('click', () => applyOutpaintPreset(btn.dataset.opPreset));
});
$$('[data-op-anchor]').forEach(btn => {
  btn.addEventListener('click', () => applyOutpaintAnchor(btn.dataset.opAnchor));
});

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
  await restoreEditDraft();
  await applyIncomingSource();
  await applyReusePayload();
  saveEditDraft();
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
  const example = (m.ref_examples && m.ref_examples[0]) || '';
  $('#prompt').placeholder = example
    ? example
    : "décrivez ce qui doit changer, en français ou en anglais";

  // Si un prompt est déjà saisi avec des balises d'un autre modèle, l'adapter automatiquement
  const currentPrompt = $('#prompt').value;
  if (currentPrompt && (/<image_?\d+>/i.test(currentPrompt) || /\bimage\s+\d+\b/i.test(currentPrompt))) {
    $('#prompt').value = adaptPromptToModel(currentPrompt, m);
  }

  renderEditPreprompts();
  renderRefHint();
  renderTagChips();
  renderRefs();
  checkMmproj();
  updateVramAdvice();
  updateOutpaintUI();
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
function updateTagWarning() {
  const box = $('#tag-warning');
  const m = currentModel();
  const syntax = m && m.ref_tag_syntax;
  const images = orderedImages();
  const prompt = $('#prompt').value;
  const autoOutpaint = isOutpaintActive() && Boolean($('#outpaint-auto-prompt')?.checked);
  const needs = Boolean(syntax) && images.length >= 2 && prompt.trim().length > 0
                && !autoOutpaint && !/<image_?\d+>/i.test(prompt);
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
  if (isOutpaintActive()) {
    const geom = computeOutpaintGeometry();
    if (geom) return { width: geom.outW, height: geom.outH };
  }
  const { width, height } = canvas;
  const scaleToArea = Math.sqrt((1024 * 1024) / (width * height));
  const scaleToMaxSide = 1344 / Math.max(width, height);
  const scale = Math.min(scaleToArea, scaleToMaxSide);
  const roundDown16 = v => Math.max(16, Math.floor(v / 16) * 16);
  return { width: roundDown16(width * scale), height: roundDown16(height * scale) };
}

function updateOriginalRatioInfo() {
  const info = $('#original-ratio-info');
  if (!info) return;
  if (isOutpaintActive() && canvas) {
    const geom = computeOutpaintGeometry();
    if (geom) {
      info.textContent = `Outpainting actif : cadre étendu ${geom.expW} × ${geom.expH} — sortie ${geom.outW} × ${geom.outH}`;
      info.hidden = false;
      return;
    }
  }
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
    let dims = { width: 0, height: 0, imgEl: null };
    try { dims = await readImageDimensions(item.url); } catch (e) {}
    out.push({ path: item.filename, url: item.url, name: item.name,
               width: dims.width, height: dims.height, imgEl: dims.imgEl,
               objectUrl: null, fresh: true });
  }
  return out;
}

async function removeUploaded(item) {
  if (!item || !item.path || !item.fresh) return;
  try { await fetch('/api/delete-source-image', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filename: item.path }) }); }
  catch (e) {}
}

async function setCanvas(files) {
  let items;
  try { items = await uploadFiles(files); }
  catch (e) { showGenError(e.message); return false; }
  if (!items.length) { showGenError("Impossible de charger l'image."); return false; }
  if (canvas) await removeUploaded(canvas);
  if (canvas && canvas.objectUrl) URL.revokeObjectURL(canvas.objectUrl);
  canvas = items[0];
  originalCanvasBackup = { ...canvas };
  resetInpaintMask();
  closeCropPanel();
  showGenError('');
  if (items.length > 1) refs = [...items.slice(1), ...refs].slice(0, refsLimit());
  if (currentRatio !== 'original') ratioBeforeOriginal = currentRatio;
  currentRatio = 'original';
  refreshAll();
  return true;
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
  updateOutpaintUI();
  updateInpaintUI();
  updateTagWarning();
  const m = currentModel();
  if (m) $('#refs-order-hint').textContent = m.ref_tag_syntax
    ? "L'ordre définit <image1>, <image2>… — la image 1 est toujours le canvas (celle qui est modifiée)."
    : "L'ordre compte : « image 1 » désigne le canvas, « image 2 » la première référence.";
  saveEditDraft();
}

function renderCanvas() {
  const ph = $('#canvas-placeholder'), pv = $('#canvas-preview');
  const tfBar = $('#canvas-transform-bar');
  const restoreBtn = $('#tf-restore-orig');
  if (!canvas) {
    ph.classList.remove('hidden');
    pv.classList.add('hidden');
    $('#canvas-img').src = '';
    if (tfBar) tfBar.hidden = true;
    closeCropPanel();
    return;
  }
  ph.classList.add('hidden');
  pv.classList.remove('hidden');
  $('#canvas-img').src = canvas.url;
  $('#canvas-name').textContent = `${canvas.name} (${canvas.width} × ${canvas.height})`;
  if (tfBar) tfBar.hidden = false;
  if (restoreBtn) {
    restoreBtn.hidden = !originalCanvasBackup || originalCanvasBackup.path === canvas.path;
  }
}

function buildInputLightboxItems() {
  const all = orderedImages();
  return all.map((item, idx) => ({
    src: item.url,
    downloadUrl: item.url,
    label: `${idx === 0 ? 'Canvas (image 1)' : 'Référence ' + (idx + 1)} · ${item.name || ''}`,
    role: idx === 0 ? 'source' : 'ref',
    badge: idx === 0 ? 'IMAGE 1 (CANVAS)' : `IMAGE ${idx + 1} (RÉF)`,
  }));
}

function buildEditLightboxItems() {
  const list = [];
  const srcUrl = comparisonSource || (canvas && canvas.url);
  if (srcUrl) {
    list.push({
      src: srcUrl,
      downloadUrl: (canvas && canvas.url) || srcUrl,
      label: lastRunWasOutpaint
        ? 'Image source (positionnée dans le cadre étendu)'
        : 'Image source (Avant modification)',
      role: 'source',
      badge: 'AVANT (SOURCE)',
    });
  }
  const hasSource = list.length > 0;
  lastGeneratedResults.forEach((img, idx) => {
    const displayUrl = img.displayUrl || `${img.url}?t=${currentBatchStamp}`;
    list.push({
      src: displayUrl,
      downloadUrl: img.url,
      label: `Résultat ${idx + 1}/${lastGeneratedResults.length} · seed ${img.seed}`,
      role: 'result',
      badge: hasSource
        ? (lastGeneratedResults.length > 1 ? `APRÈS #${idx + 1}` : 'APRÈS (MODIFIÉE)')
        : `RÉSULTAT #${idx + 1}`,
    });
  });
  return list;
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
    d.querySelector('img').addEventListener('click', () => {
      const inputItems = buildInputLightboxItems();
      openLightbox(inputItems, canvas ? i + 1 : i);
    });
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
$('#canvas-img').addEventListener('click', () => {
  if (lastGeneratedResults.length > 0) {
    const items = buildEditLightboxItems();
    openLightbox(items, 0, { lastResultIndex: Math.min(items.length - 1, activeCompareResultIdx + 1) });
  } else {
    const inputItems = buildInputLightboxItems();
    openLightbox(inputItems, 0);
  }
});
$('#compare-before').addEventListener('click', () => {
  const items = buildEditLightboxItems();
  openLightbox(items, 0, { lastResultIndex: Math.min(items.length - 1, activeCompareResultIdx + 1) });
});
$('#compare-after').addEventListener('click', () => {
  const items = buildEditLightboxItems();
  const hasSource = Boolean(comparisonSource || (canvas && canvas.url));
  openLightbox(items, hasSource ? activeCompareResultIdx + 1 : activeCompareResultIdx);
});

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
wireDropzone($('.edit-panel'), files => (canvas ? addRefs(files) : setCanvas(files)));

// ===========================================================================
//  RECADRAGE & ROTATION RAPIDE (CROP / FLIP) AVANT ÉDITION
// ===========================================================================
async function replaceCanvasWithCanvasSurface(surfCanvas, labelSuffix = 'edit') {
  if (!canvas) return;
  if (!originalCanvasBackup) {
    originalCanvasBackup = { ...canvas };
  }
  const blob = await new Promise((resolve, reject) => {
    surfCanvas.toBlob(b => (b ? resolve(b) : reject(new Error('Échec export PNG'))), 'image/png');
  });
  const baseName = (canvas.name || 'canvas.png').replace(/\.[^.]+$/, '');
  const file = new File([blob], `${baseName}_${labelSuffix}.png`, { type: 'image/png' });
  const uploaded = await uploadFiles([file]);
  if (!uploaded.length) return;
  if (canvas && (!originalCanvasBackup || canvas.path !== originalCanvasBackup.path)) {
    await removeUploaded(canvas);
  }
  canvas = uploaded[0];
  resetInpaintMask();
  closeCropPanel();
  refreshAll();
}

async function rotateOrFlipCanvas(mode) {
  if (!canvas || !canvas.imgEl) return;
  const srcW = canvas.width;
  const srcH = canvas.height;
  const c = document.createElement('canvas');
  if (mode === 'rotLeft' || mode === 'rotRight') {
    c.width = srcH;
    c.height = srcW;
  } else {
    c.width = srcW;
    c.height = srcH;
  }
  const ctx = c.getContext('2d');
  ctx.save();
  if (mode === 'rotLeft') {
    ctx.translate(0, c.height);
    ctx.rotate(-Math.PI / 2);
  } else if (mode === 'rotRight') {
    ctx.translate(c.width, 0);
    ctx.rotate(Math.PI / 2);
  } else if (mode === 'flipH') {
    ctx.translate(c.width, 0);
    ctx.scale(-1, 1);
  } else if (mode === 'flipV') {
    ctx.translate(0, c.height);
    ctx.scale(1, -1);
  }
  ctx.drawImage(canvas.imgEl, 0, 0, srcW, srcH);
  ctx.restore();
  await replaceCanvasWithCanvasSurface(c, mode);
  if (window.showToast) window.showToast('✓ Transformation appliquée au Canvas');
}

$('#tf-rot-left')?.addEventListener('click', () => rotateOrFlipCanvas('rotLeft'));
$('#tf-rot-right')?.addEventListener('click', () => rotateOrFlipCanvas('rotRight'));
$('#tf-flip-h')?.addEventListener('click', () => rotateOrFlipCanvas('flipH'));
$('#tf-flip-v')?.addEventListener('click', () => rotateOrFlipCanvas('flipV'));

$('#tf-restore-orig')?.addEventListener('click', async () => {
  if (!originalCanvasBackup) return;
  if (canvas && canvas.path !== originalCanvasBackup.path) {
    await removeUploaded(canvas);
  }
  canvas = { ...originalCanvasBackup };
  resetInpaintMask();
  closeCropPanel();
  refreshAll();
  if (window.showToast) window.showToast("⟲ Image d'origine restaurée");
});

function closeCropPanel() {
  cropState.open = false;
  cropState.drag = null;
  const panel = $('#canvas-crop-panel');
  if (panel) panel.hidden = true;
}

function initCropRectForRatio(ratioStr) {
  if (!canvas) return;
  const W = canvas.width;
  const H = canvas.height;
  if (!ratioStr || ratioStr === 'free') {
    const padX = Math.round(W * 0.08);
    const padY = Math.round(H * 0.08);
    cropState.rect = { x: padX, y: padY, w: Math.max(32, W - 2 * padX), h: Math.max(32, H - 2 * padY) };
    return;
  }
  const [rw, rh] = ratioStr.split(':').map(Number);
  const target = rw / rh;
  let boxW = W * 0.86;
  let boxH = boxW / target;
  if (boxH > H * 0.86) {
    boxH = H * 0.86;
    boxW = boxH * target;
  }
  boxW = Math.max(32, Math.round(boxW));
  boxH = Math.max(32, Math.round(boxH));
  cropState.rect = {
    x: Math.round((W - boxW) / 2),
    y: Math.round((H - boxH) / 2),
    w: boxW,
    h: boxH,
  };
}

function renderCropCanvas() {
  const c = $('#canvas-crop-canvas');
  if (!c || !canvas || !canvas.imgEl || !cropState.rect) return;
  const maxSide = 340;
  const scale = Math.min(1, maxSide / Math.max(canvas.width, canvas.height));
  c.width = Math.max(80, Math.round(canvas.width * scale));
  c.height = Math.max(80, Math.round(canvas.height * scale));
  c.dataset.scale = String(scale);

  const ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  ctx.drawImage(canvas.imgEl, 0, 0, c.width, c.height);

  // Voile sombre autour de la zone recadrée
  ctx.fillStyle = 'rgba(8, 10, 16, 0.62)';
  ctx.fillRect(0, 0, c.width, c.height);

  const r = cropState.rect;
  const sx = r.x * scale, sy = r.y * scale, sw = r.w * scale, sh = r.h * scale;
  ctx.save();
  ctx.beginPath();
  ctx.rect(sx, sy, sw, sh);
  ctx.clip();
  ctx.drawImage(canvas.imgEl, 0, 0, c.width, c.height);
  ctx.restore();

  // Cadre + grille des tiers
  ctx.strokeStyle = '#7c5cff';
  ctx.lineWidth = 2;
  ctx.strokeRect(sx + 0.5, sy + 0.5, sw, sh);

  ctx.strokeStyle = 'rgba(255,255,255,0.28)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(sx + sw / 3, sy); ctx.lineTo(sx + sw / 3, sy + sh);
  ctx.moveTo(sx + (2 * sw) / 3, sy); ctx.lineTo(sx + (2 * sw) / 3, sy + sh);
  ctx.moveTo(sx, sy + sh / 3); ctx.lineTo(sx + sw, sy + sh / 3);
  ctx.moveTo(sx, sy + (2 * sh) / 3); ctx.lineTo(sx + sw, sy + (2 * sh) / 3);
  ctx.stroke();

  // Poignées aux 4 coins
  ctx.fillStyle = '#ffffff';
  const hs = 7;
  [[sx, sy], [sx + sw, sy], [sx, sy + sh], [sx + sw, sy + sh]].forEach(([hx, hy]) => {
    ctx.fillRect(hx - hs / 2, hy - hs / 2, hs, hs);
    ctx.strokeRect(hx - hs / 2, hy - hs / 2, hs, hs);
  });

  const lbl = $('#crop-dims-label');
  if (lbl) lbl.textContent = `${Math.round(r.w)} × ${Math.round(r.h)} px`;
}

$('#tf-crop-toggle')?.addEventListener('click', () => {
  if (!canvas) return;
  const panel = $('#canvas-crop-panel');
  if (!panel) return;
  if (!panel.hidden) {
    closeCropPanel();
    return;
  }
  cropState.open = true;
  cropState.ratio = 'free';
  $$('[data-crop-ratio]').forEach(b => b.classList.toggle('active', b.dataset.cropRatio === 'free'));
  initCropRectForRatio('free');
  panel.hidden = false;
  renderCropCanvas();
});

$$('[data-crop-ratio]').forEach(btn => {
  btn.addEventListener('click', () => {
    cropState.ratio = btn.dataset.cropRatio || 'free';
    $$('[data-crop-ratio]').forEach(b => b.classList.toggle('active', b === btn));
    initCropRectForRatio(cropState.ratio);
    renderCropCanvas();
  });
});

(function wireCropCanvasInteractions() {
  const c = $('#canvas-crop-canvas');
  if (!c) return;

  c.addEventListener('pointerdown', e => {
    if (!canvas || !cropState.rect || e.button !== 0) return;
    e.preventDefault();
    try { c.setPointerCapture(e.pointerId); } catch (_) {}
    const rectDom = c.getBoundingClientRect();
    const scale = parseFloat(c.dataset.scale || '1') * (rectDom.width / Math.max(1, c.width));
    const ix = (e.clientX - rectDom.left) / Math.max(0.0001, scale);
    const iy = (e.clientY - rectDom.top) / Math.max(0.0001, scale);
    const r = cropState.rect;
    const hitTol = 18 / Math.max(0.0001, scale);

    let mode = 'new';
    const nearL = Math.abs(ix - r.x) <= hitTol;
    const nearR = Math.abs(ix - (r.x + r.w)) <= hitTol;
    const nearT = Math.abs(iy - r.y) <= hitTol;
    const nearB = Math.abs(iy - (r.y + r.h)) <= hitTol;

    if (nearL && nearT) mode = 'nw';
    else if (nearR && nearT) mode = 'ne';
    else if (nearL && nearB) mode = 'sw';
    else if (nearR && nearB) mode = 'se';
    else if (ix >= r.x && ix <= r.x + r.w && iy >= r.y && iy <= r.y + r.h) mode = 'move';

    cropState.drag = {
      pointerId: e.pointerId,
      mode,
      startX: ix,
      startY: iy,
      startRect: { ...r },
      scale,
    };
  });

  c.addEventListener('pointermove', e => {
    const st = cropState.drag;
    if (!st || st.pointerId !== e.pointerId || !canvas) return;
    const rectDom = c.getBoundingClientRect();
    const ix = Math.max(0, Math.min(canvas.width, (e.clientX - rectDom.left) / Math.max(0.0001, st.scale)));
    const iy = Math.max(0, Math.min(canvas.height, (e.clientY - rectDom.top) / Math.max(0.0001, st.scale)));
    const dx = ix - st.startX;
    const dy = iy - st.startY;
    const sr = st.startRect;
    const minS = 32;
    let nx = sr.x, ny = sr.y, nw = sr.w, nh = sr.h;

    if (st.mode === 'move') {
      nx = Math.max(0, Math.min(canvas.width - nw, Math.round(sr.x + dx)));
      ny = Math.max(0, Math.min(canvas.height - nh, Math.round(sr.y + dy)));
    } else if (st.mode === 'new') {
      nx = Math.round(Math.min(st.startX, ix));
      ny = Math.round(Math.min(st.startY, iy));
      nw = Math.max(minS, Math.round(Math.abs(ix - st.startX)));
      nh = Math.max(minS, Math.round(Math.abs(iy - st.startY)));
    } else {
      if (st.mode.includes('w')) {
        nx = Math.max(0, Math.min(sr.x + sr.w - minS, Math.round(sr.x + dx)));
        nw = sr.x + sr.w - nx;
      }
      if (st.mode.includes('e')) {
        nw = Math.max(minS, Math.min(canvas.width - sr.x, Math.round(sr.w + dx)));
      }
      if (st.mode.includes('n')) {
        ny = Math.max(0, Math.min(sr.y + sr.h - minS, Math.round(sr.y + dy)));
        nh = sr.y + sr.h - ny;
      }
      if (st.mode.includes('s')) {
        nh = Math.max(minS, Math.min(canvas.height - sr.y, Math.round(sr.h + dy)));
      }
    }

    if (cropState.ratio && cropState.ratio !== 'free' && st.mode !== 'move') {
      const [rw, rh] = cropState.ratio.split(':').map(Number);
      const target = rw / rh;
      nh = Math.round(nw / target);
      if (ny + nh > canvas.height) {
        nh = canvas.height - ny;
        nw = Math.round(nh * target);
      }
    }

    cropState.rect = { x: nx, y: ny, w: Math.max(minS, nw), h: Math.max(minS, nh) };
    renderCropCanvas();
  });

  const endCropDrag = e => {
    if (!cropState.drag) return;
    try { c.releasePointerCapture(cropState.drag.pointerId); } catch (_) {}
    cropState.drag = null;
  };
  c.addEventListener('pointerup', endCropDrag);
  c.addEventListener('pointercancel', endCropDrag);
})();

$('#crop-cancel-btn')?.addEventListener('click', closeCropPanel);
$('#crop-apply-btn')?.addEventListener('click', async () => {
  if (!canvas || !canvas.imgEl || !cropState.rect) return;
  const r = cropState.rect;
  const out = document.createElement('canvas');
  out.width = Math.max(16, Math.round(r.w));
  out.height = Math.max(16, Math.round(r.h));
  out.getContext('2d').drawImage(
    canvas.imgEl,
    Math.round(r.x), Math.round(r.y), Math.round(r.w), Math.round(r.h),
    0, 0, out.width, out.height
  );
  await replaceCanvasWithCanvasSurface(out, 'crop');
  if (window.showToast) window.showToast(`✂️ Image recadrée (${out.width} × ${out.height})`);
});

// ===========================================================================
//  MODE INPAINTING AU PINCEAU (MASQUE DESSINÉ À LA SOURIS)
// ===========================================================================
function modelSupportsInpaint() {
  const m = currentModel();
  return Boolean(m && m.supports_inpainting !== false && m.supports_ref_images);
}

function isInpaintActive() {
  return modelSupportsInpaint() && Boolean($('#inpaint-enabled')?.checked) && Boolean(canvas);
}

function ensureInpaintMaskCanvas() {
  if (!canvas || !canvas.width || !canvas.height) return null;
  if (
    !inpaintState.maskCanvas ||
    inpaintState.maskCanvas.width !== canvas.width ||
    inpaintState.maskCanvas.height !== canvas.height
  ) {
    const mc = document.createElement('canvas');
    mc.width = canvas.width;
    mc.height = canvas.height;
    inpaintState.maskCanvas = mc;
    inpaintState.undoStack = [];
  }
  return inpaintState.maskCanvas;
}

function resetInpaintMask() {
  if (inpaintState.maskCanvas) {
    const ctx = inpaintState.maskCanvas.getContext('2d');
    ctx.clearRect(0, 0, inpaintState.maskCanvas.width, inpaintState.maskCanvas.height);
  }
  inpaintState.maskCanvas = null;
  inpaintState.undoStack = [];
  renderInpaintCanvas();
}

function pushInpaintUndo() {
  const mc = ensureInpaintMaskCanvas();
  if (!mc) return;
  const snap = document.createElement('canvas');
  snap.width = mc.width;
  snap.height = mc.height;
  snap.getContext('2d').drawImage(mc, 0, 0);
  inpaintState.undoStack.push(snap);
  if (inpaintState.undoStack.length > 15) inpaintState.undoStack.shift();
}

function computeInpaintBbox() {
  const mc = inpaintState.maskCanvas;
  if (!mc) return null;
  const w = mc.width, h = mc.height;
  const data = mc.getContext('2d').getImageData(0, 0, w, h).data;
  let minX = w, minY = h, maxX = -1, maxY = -1, count = 0;
  const step = Math.max(1, Math.floor(Math.min(w, h) / 256));
  for (let y = 0; y < h; y += step) {
    for (let x = 0; x < w; x += step) {
      if (data[(y * w + x) * 4 + 3] > 20) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        count++;
      }
    }
  }
  if (maxX < 0 || maxY < 0) return null;
  return {
    x1: Math.round((minX / w) * 1000) / 10,
    y1: Math.round((minY / h) * 1000) / 10,
    x2: Math.round((Math.min(w, maxX + step) / w) * 1000) / 10,
    y2: Math.round((Math.min(h, maxY + step) / h) * 1000) / 10,
    pxRect: { x: minX, y: minY, w: Math.max(1, maxX - minX + step), h: Math.max(1, maxY - minY + step) },
    coveragePct: Math.max(0.1, Math.round((count / ((w / step) * (h / step))) * 1000) / 10),
  };
}

function renderInpaintCanvas() {
  const disp = $('#inpaint-canvas');
  const infoEl = $('#inpaint-bbox-info');
  if (!disp || !canvas || !canvas.imgEl) return;

  const mc = ensureInpaintMaskCanvas();
  const maxSide = 360;
  const scale = Math.min(1, maxSide / Math.max(canvas.width, canvas.height));
  const dw = Math.max(80, Math.round(canvas.width * scale));
  const dh = Math.max(80, Math.round(canvas.height * scale));
  if (disp.width !== dw || disp.height !== dh) {
    disp.width = dw;
    disp.height = dh;
  }
  disp.dataset.scale = String(scale);

  const ctx = disp.getContext('2d');
  ctx.clearRect(0, 0, dw, dh);
  ctx.drawImage(canvas.imgEl, 0, 0, dw, dh);

  if (mc) {
    ctx.save();
    ctx.globalAlpha = 0.58;
    ctx.drawImage(mc, 0, 0, dw, dh);
    ctx.restore();
  }

  const bbox = computeInpaintBbox();
  if (bbox) {
    const rx = bbox.pxRect.x * scale;
    const ry = bbox.pxRect.y * scale;
    const rw = bbox.pxRect.w * scale;
    const rh = bbox.pxRect.h * scale;
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.restore();
    if (infoEl) {
      infoEl.textContent = `Zone masquée : [${Math.round(bbox.x1)}%, ${Math.round(bbox.y1)}%] → [${Math.round(bbox.x2)}%, ${Math.round(bbox.y2)}%] (${bbox.coveragePct}% de l'image)`;
    }
  } else if (infoEl) {
    infoEl.textContent = "Peignez en rose sur l'image la zone que vous souhaitez modifier ou effacer.";
  }

  // Aperçu du cercle du pinceau sous le curseur
  if (inpaintState.cursorPt) {
    const r = Math.max(3, (inpaintState.size * scale) / 2);
    ctx.save();
    ctx.beginPath();
    ctx.arc(inpaintState.cursorPt.x * scale, inpaintState.cursorPt.y * scale, r, 0, Math.PI * 2);
    ctx.strokeStyle = inpaintState.tool === 'eraser' ? '#38d996' : '#ff4da6';
    ctx.lineWidth = 1.8;
    ctx.stroke();
    ctx.restore();
  }
}

function updateInpaintUI() {
  const box = $('#inpaint-box');
  const controls = $('#inpaint-controls');
  if (!box || !controls) return;
  const sup = modelSupportsInpaint() && Boolean(canvas);
  box.hidden = !sup;
  if (!sup) return;
  const enabled = Boolean($('#inpaint-enabled')?.checked);
  controls.hidden = !enabled;
  if (enabled) {
    ensureInpaintMaskCanvas();
    renderInpaintCanvas();
  }
}

$('#inpaint-enabled')?.addEventListener('change', () => {
  if ($('#inpaint-enabled').checked && $('#outpaint-enabled')?.checked) {
    $('#outpaint-enabled').checked = false;
    updateOutpaintUI();
  }
  updateInpaintUI();
  updateTagWarning();
  saveEditDraft();
});

$('#inpaint-tool-brush')?.addEventListener('click', () => {
  inpaintState.tool = 'brush';
  $('#inpaint-tool-brush').className = 'btn small primary';
  $('#inpaint-tool-eraser').className = 'btn small ghost';
  renderInpaintCanvas();
});

$('#inpaint-tool-eraser')?.addEventListener('click', () => {
  inpaintState.tool = 'eraser';
  $('#inpaint-tool-eraser').className = 'btn small primary';
  $('#inpaint-tool-brush').className = 'btn small ghost';
  renderInpaintCanvas();
});

$('#inpaint-size')?.addEventListener('input', e => {
  inpaintState.size = parseInt(e.target.value, 10) || 36;
  if ($('#inpaint-size-val')) $('#inpaint-size-val').textContent = `${inpaintState.size} px`;
  renderInpaintCanvas();
});

$('#inpaint-undo-btn')?.addEventListener('click', () => {
  const mc = ensureInpaintMaskCanvas();
  if (!mc || !inpaintState.undoStack.length) return;
  const prev = inpaintState.undoStack.pop();
  const ctx = mc.getContext('2d');
  ctx.clearRect(0, 0, mc.width, mc.height);
  ctx.drawImage(prev, 0, 0);
  renderInpaintCanvas();
});

$('#inpaint-clear-btn')?.addEventListener('click', () => {
  pushInpaintUndo();
  const mc = ensureInpaintMaskCanvas();
  if (mc) mc.getContext('2d').clearRect(0, 0, mc.width, mc.height);
  renderInpaintCanvas();
});

$('#inpaint-invert-btn')?.addEventListener('click', () => {
  const mc = ensureInpaintMaskCanvas();
  if (!mc) return;
  pushInpaintUndo();
  const ctx = mc.getContext('2d');
  const imgData = ctx.getImageData(0, 0, mc.width, mc.height);
  const d = imgData.data;
  for (let i = 0; i < d.length; i += 4) {
    const painted = d[i + 3] > 20;
    if (painted) {
      d[i + 3] = 0;
    } else {
      d[i] = 255; d[i + 1] = 56; d[i + 2] = 152; d[i + 3] = 255;
    }
  }
  ctx.putImageData(imgData, 0, 0);
  renderInpaintCanvas();
});

(function wireInpaintCanvasDrawing() {
  const disp = $('#inpaint-canvas');
  if (!disp) return;

  const getImgCoords = e => {
    const rect = disp.getBoundingClientRect();
    const scale = parseFloat(disp.dataset.scale || '1') * (rect.width / Math.max(1, disp.width));
    return {
      x: Math.max(0, Math.min(canvas.width, (e.clientX - rect.left) / Math.max(0.0001, scale))),
      y: Math.max(0, Math.min(canvas.height, (e.clientY - rect.top) / Math.max(0.0001, scale))),
    };
  };

  const paintSegment = (p1, p2) => {
    const mc = ensureInpaintMaskCanvas();
    if (!mc) return;
    const ctx = mc.getContext('2d');
    const scaleFactor = Math.max(canvas.width, canvas.height) / 360;
    const radius = Math.max(2, (inpaintState.size * scaleFactor) / 2);
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = radius * 2;
    if (inpaintState.tool === 'eraser') {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = 'rgba(0,0,0,1)';
      ctx.fillStyle = 'rgba(0,0,0,1)';
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = '#ff3898';
      ctx.fillStyle = '#ff3898';
    }
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(p2.x, p2.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  };

  disp.addEventListener('pointerdown', e => {
    if (!canvas || e.button !== 0) return;
    e.preventDefault();
    try { disp.setPointerCapture(e.pointerId); } catch (_) {}
    pushInpaintUndo();
    inpaintState.drawing = true;
    const pt = getImgCoords(e);
    inpaintState.lastPt = pt;
    inpaintState.cursorPt = pt;
    paintSegment(pt, pt);
    renderInpaintCanvas();
  });

  disp.addEventListener('pointermove', e => {
    if (!canvas) return;
    const pt = getImgCoords(e);
    inpaintState.cursorPt = pt;
    if (inpaintState.drawing && inpaintState.lastPt) {
      paintSegment(inpaintState.lastPt, pt);
      inpaintState.lastPt = pt;
    }
    renderInpaintCanvas();
  });

  const stopDraw = e => {
    if (!inpaintState.drawing) return;
    inpaintState.drawing = false;
    inpaintState.lastPt = null;
    try { disp.releasePointerCapture(e.pointerId); } catch (_) {}
    renderInpaintCanvas();
  };
  disp.addEventListener('pointerup', stopDraw);
  disp.addEventListener('pointercancel', stopDraw);
  disp.addEventListener('pointerleave', () => {
    inpaintState.cursorPt = null;
    if (!inpaintState.drawing) renderInpaintCanvas();
  });

  disp.addEventListener('wheel', e => {
    if (!isInpaintActive()) return;
    e.preventDefault();
    const delta = e.deltaY < 0 ? 4 : -4;
    inpaintState.size = Math.max(6, Math.min(140, inpaintState.size + delta));
    if ($('#inpaint-size')) $('#inpaint-size').value = String(inpaintState.size);
    if ($('#inpaint-size-val')) $('#inpaint-size-val').textContent = `${inpaintState.size} px`;
    renderInpaintCanvas();
  }, { passive: false });
})();

async function prepareInpaintFiles() {
  const mc = ensureInpaintMaskCanvas();
  const bbox = computeInpaintBbox();
  if (!mc || !bbox || !canvas || !canvas.imgEl) return null;

  // 1) Masque binaire noir & blanc (blanc = zone à modifier, noir = conserver)
  const bin = document.createElement('canvas');
  bin.width = canvas.width;
  bin.height = canvas.height;
  const bctx = bin.getContext('2d');
  bctx.fillStyle = '#000000';
  bctx.fillRect(0, 0, bin.width, bin.height);
  const srcData = mc.getContext('2d').getImageData(0, 0, mc.width, mc.height).data;
  const binImg = bctx.getImageData(0, 0, bin.width, bin.height);
  const bd = binImg.data;
  for (let i = 0; i < srcData.length; i += 4) {
    if (srcData[i + 3] > 20) {
      bd[i] = 255; bd[i + 1] = 255; bd[i + 2] = 255; bd[i + 3] = 255;
    }
  }
  bctx.putImageData(binImg, 0, 0);
  const maskBlob = await new Promise(res => bin.toBlob(res, 'image/png'));
  const maskFile = new File([maskBlob], 'inpaint_mask.png', { type: 'image/png' });

  // 2) Optionnel : pré-adoucir la zone masquée sur le canvas envoyé au modèle
  let neutralizedFile = null;
  if ($('#inpaint-neutralize-zone')?.checked) {
    const nc = document.createElement('canvas');
    nc.width = canvas.width;
    nc.height = canvas.height;
    const nctx = nc.getContext('2d');
    nctx.drawImage(canvas.imgEl, 0, 0);

    // Couche floutée locale sous le masque
    const blurred = document.createElement('canvas');
    blurred.width = canvas.width;
    blurred.height = canvas.height;
    const blCtx = blurred.getContext('2d');
    blCtx.filter = 'blur(26px)';
    blCtx.drawImage(canvas.imgEl, 0, 0);
    blCtx.filter = 'none';
    blCtx.globalCompositeOperation = 'destination-in';
    blCtx.drawImage(mc, 0, 0);

    nctx.drawImage(blurred, 0, 0);
    const nBlob = await new Promise(res => nc.toBlob(res, 'image/png'));
    neutralizedFile = new File([nBlob], 'inpaint_canvas.png', { type: 'image/png' });
  }

  // Snapshot du masque pour le Seamless Blend au retour
  const snapMask = document.createElement('canvas');
  snapMask.width = mc.width;
  snapMask.height = mc.height;
  snapMask.getContext('2d').drawImage(mc, 0, 0);

  return { bbox, maskFile, neutralizedFile, snapMask };
}

async function createSeamlessBlendedDataUrl(resultUrl, origImgEl, maskSnapCanvas) {
  const resDims = await readImageDimensions(resultUrl);
  const W = resDims.width;
  const H = resDims.height;
  const out = document.createElement('canvas');
  out.width = W;
  out.height = H;
  const ctx = out.getContext('2d');

  // Dessine l'image d'origine intacte partout
  ctx.drawImage(origImgEl, 0, 0, W, H);

  // Crée une couche avec le résultat découpé par le masque adouci (feather)
  const feather = document.createElement('canvas');
  feather.width = W;
  feather.height = H;
  const fctx = feather.getContext('2d');
  fctx.filter = 'blur(10px)';
  fctx.drawImage(maskSnapCanvas, 0, 0, W, H);
  fctx.filter = 'none';
  fctx.globalCompositeOperation = 'source-in';
  fctx.drawImage(resDims.imgEl, 0, 0, W, H);

  ctx.drawImage(feather, 0, 0, W, H);
  return out.toDataURL('image/png');
}

// ===========================================================================
//  COLLER UNE IMAGE AVEC CTRL+V N'IMPORTE OÙ SUR LA PAGE
// ===========================================================================
window.addEventListener('paste', async e => {
  const items = e.clipboardData?.items ? [...e.clipboardData.items] : [];
  const imgItem = items.find(it => it.type && it.type.startsWith('image/'));
  if (!imgItem) return;
  const file = imgItem.getAsFile();
  if (!file) return;
  e.preventDefault();

  if (!canvas) {
    await setCanvas([file]);
    if (window.showToast) window.showToast('📋 Image collée comme Canvas (image 1)');
  } else {
    await addRefs([file]);
    if (window.showToast) {
      window.showToast(
        `📋 Image collée dans les Références (image ${refs.length + 1})`,
        'Mettre en Canvas',
        async () => {
          const popped = refs.pop();
          if (popped) {
            if (canvas) await removeUploaded(canvas);
            canvas = popped;
            originalCanvasBackup = { ...canvas };
            resetInpaintMask();
            refreshAll();
          }
        }
      );
    }
  }
});

// ===========================================================================
//  BOUTON « 🧹 NOUVEAU / VIDER LE BROUILLON »
// ===========================================================================
$('#reset-edit-draft-btn')?.addEventListener('click', async () => {
  try {
    sessionStorage.removeItem(EDIT_DRAFT_KEY);
    localStorage.removeItem(EDIT_DRAFT_KEY);
  } catch (e) {}
  isRestoringEditDraft = true;
  try {
    if (canvas) await removeUploaded(canvas);
    for (const r of refs) await removeUploaded(r);
    if (tempOutpaintItem) await removeUploaded(tempOutpaintItem);
    if (tempInpaintCanvasItem) await removeUploaded(tempInpaintCanvasItem);
    if (tempInpaintMaskItem) await removeUploaded(tempInpaintMaskItem);
    canvas = null;
    originalCanvasBackup = null;
    refs = [];
    tempOutpaintItem = null;
    tempInpaintCanvasItem = null;
    tempInpaintMaskItem = null;
    resetInpaintMask();
    closeCropPanel();
    $('#prompt').value = '';
    const m = currentModel();
    $('#negative').value = (m && m.supports_neg) ? (window.DEFAULT_NEG || '') : '';
    if ($('#seed')) $('#seed').value = '';
    if ($('#batch')) {
      $('#batch').value = '1';
      if ($('#batch-val')) $('#batch-val').textContent = '1 image';
    }
    if ($('#outpaint-enabled')) $('#outpaint-enabled').checked = false;
    if ($('#inpaint-enabled')) $('#inpaint-enabled').checked = false;
    setOutpaintMargins(25, 25, 25, 25);
    currentRatio = '1:1';
    ratioBeforeOriginal = '1:1';
    lastGeneratedResults = [];
    comparisonSource = null;
    if ($('#compare')) $('#compare').hidden = true;
    if ($('#results')) $('#results').innerHTML = '';
    if ($('#stats-box')) $('#stats-box').hidden = true;
    showGenError('');
    refreshAll();
  } finally {
    isRestoringEditDraft = false;
  }
  saveEditDraft();
  if (window.showToast) window.showToast('🧹 Studio d’édition réinitialisé');
});

// ===========================================================================
//  FILE D'ATTENTE (QUEUE)
// ===========================================================================
function renderEditQueue(queue) {
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
        <strong>${esc(item.model_name)} (${esc(item.quant)})</strong> · ${item.width}×${item.height} · ×${item.batch}
        <div class="queue-prompt">${esc(item.prompt || '')}</div>
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
      if (j.ok) renderEditQueue(j.queue);
    });
  });
}

$('#queue-clear-btn')?.addEventListener('click', async () => {
  const r = await fetch('/api/queue/clear', { method: 'POST' });
  const j = await r.json();
  if (j.ok) renderEditQueue([]);
});
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

  const outpaintOn = isOutpaintActive();
  const inpaintOn = !outpaintOn && isInpaintActive();
  const autoOutpaintPrompt = outpaintOn && Boolean($('#outpaint-auto-prompt')?.checked);
  const autoInpaintPrompt = inpaintOn && Boolean($('#inpaint-auto-prompt')?.checked);
  const prompt = $('#prompt').value.trim();

  if (inpaintOn && !computeInpaintBbox()) {
    showGenError("Peignez d'abord sur l'image la zone à modifier avec le pinceau Inpainting (ou décochez le mode Inpainting).");
    return;
  }
  if (!prompt && !autoOutpaintPrompt && !autoInpaintPrompt) {
    showGenError("Décrivez ce qui doit changer (étape 4) — ou activez l'adaptation automatique du prompt.");
    return;
  }

  const images = orderedImages();
  const limit = maxImages();
  if (images.length > limit) { showGenError(`${limit} images maximum avec ce modèle.`); return; }

  let refPaths = images.map(x => x.path);
  let customWidth = null;
  let customHeight = null;
  let nextComparisonSource = images[0].url;
  let inpaintPayload = null;
  let nextInpaintMaskSnap = null;
  let nextInpaintOrigImg = null;

  if (outpaintOn) {
    try {
      $('#generate-btn').disabled = true;
      const prepared = await createOutpaintFileAndBeforePreview();
      if (!prepared) throw new Error("Impossible de préparer le canevas d'outpainting.");
      if (tempOutpaintItem) {
        await removeUploaded(tempOutpaintItem);
        tempOutpaintItem = null;
      }
      const uploaded = await uploadFiles([prepared.file]);
      if (!uploaded.length) throw new Error("Échec de l'envoi du canevas étendu.");
      tempOutpaintItem = uploaded[0];
      refPaths = [tempOutpaintItem.path, ...refs.map(x => x.path)];
      customWidth = prepared.geom.outW;
      customHeight = prepared.geom.outH;
      nextComparisonSource = prepared.beforeDataUrl;
    } catch (e) {
      $('#generate-btn').disabled = false;
      showGenError(e.message || "Erreur lors de la préparation de l'outpainting.");
      return;
    } finally {
      $('#generate-btn').disabled = false;
    }
  } else if (inpaintOn) {
    try {
      $('#generate-btn').disabled = true;
      const prep = await prepareInpaintFiles();
      if (!prep) throw new Error("Impossible de préparer le masque d'inpainting.");
      if (tempInpaintMaskItem) { await removeUploaded(tempInpaintMaskItem); tempInpaintMaskItem = null; }
      if (tempInpaintCanvasItem) { await removeUploaded(tempInpaintCanvasItem); tempInpaintCanvasItem = null; }

      const upMask = await uploadFiles([prep.maskFile]);
      if (!upMask.length) throw new Error("Échec de l'envoi du masque.");
      tempInpaintMaskItem = upMask[0];

      if (prep.neutralizedFile) {
        const upCanvas = await uploadFiles([prep.neutralizedFile]);
        if (upCanvas.length) {
          tempInpaintCanvasItem = upCanvas[0];
          refPaths = [tempInpaintCanvasItem.path, ...refs.map(x => x.path)];
        }
      }
      const out = getOriginalOutputSize();
      customWidth = out.width;
      customHeight = out.height;
      inpaintPayload = {
        enabled: true,
        bbox: { x1: prep.bbox.x1, y1: prep.bbox.y1, x2: prep.bbox.x2, y2: prep.bbox.y2 },
        auto_prompt: autoInpaintPrompt,
        mask_image: tempInpaintMaskItem.path,
        use_cli_mask: true,
      };
      nextInpaintMaskSnap = prep.snapMask;
      nextInpaintOrigImg = canvas.imgEl;
    } catch (e) {
      $('#generate-btn').disabled = false;
      showGenError(e.message || "Erreur lors de la préparation de l'inpainting.");
      return;
    } finally {
      $('#generate-btn').disabled = false;
    }
  } else if (currentRatio === 'original' && canvas) {
    const out = getOriginalOutputSize();
    customWidth = out.width;
    customHeight = out.height;
  }

  const body = {
    model_id: m.id,
    quant: $('#quant').value,
    prompt,
    negative: $('#negative').value,
    ratio: (currentRatio === 'original' || outpaintOn || inpaintOn) ? '1:1' : currentRatio,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
    input_mode: 'ref',
    ref_images: refPaths,
    ref_max_pixels: $('#ref-budget').value === 'auto' ? null : parseInt($('#ref-budget').value, 10),
    allow_queue: true,
  };
  if (customWidth && customHeight) {
    body.width = customWidth;
    body.height = customHeight;
  }
  if (outpaintOn) {
    body.outpaint = {
      enabled: true,
      directions: getOutpaintActiveDirections(),
      auto_prompt: autoOutpaintPrompt,
    };
  }
  if (inpaintOn && inpaintPayload) {
    body.inpaint = inpaintPayload;
  }

  const r = await fetch('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const j = await r.json();
  if (!j.ok) {
    $('#generate-btn').disabled = false;
    showGenError(j.error || 'Erreur');
    return;
  }

  if (j.queued) {
    renderEditQueue(j.queue || []);
    if (window.showToast) {
      window.showToast(`⏳ Édition ajoutée à la file d'attente (position #${j.position})`);
    }
    if (!pollTimer) pollStatus();
    return;
  }

  comparisonSource = nextComparisonSource;
  lastRunWasOutpaint = outpaintOn;
  lastRunWasInpaint = inpaintOn && Boolean($('#inpaint-blend-result')?.checked);
  lastInpaintMaskSnapshot = nextInpaintMaskSnap;
  lastInpaintOrigImgEl = nextInpaintOrigImg;
  generationSourceCount = refPaths.length;
  lastGeneratedResults = [];
  activeCompareResultIdx = 0;
  currentBatchStamp = Date.now();
  $('#compare-before').src = comparisonSource;
  $('#compare').hidden = true;
  $('#generate-btn').textContent = '＋ Ajouter à la file d\'attente';
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
$('#prompt').addEventListener('input', () => { updateTagWarning(); saveEditDraft(); });
$('#negative')?.addEventListener('input', saveEditDraft);
['#steps', '#cfg', '#seed', '#ref-budget', '#outpaint-auto-prompt'].forEach(sel => {
  $(sel)?.addEventListener('input', saveEditDraft);
  $(sel)?.addEventListener('change', saveEditDraft);
});
$('#batch').addEventListener('input', e => {
  const v = parseInt(e.target.value);
  $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
  saveEditDraft();
});
window.addEventListener('beforeunload', saveEditDraft);
window.addEventListener('pagehide', saveEditDraft);

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

    renderEditQueue(j.queue || []);

    if (!j.busy && (!j.queue || j.queue.length === 0)) {
      clearInterval(pollTimer); pollTimer = null;
      $('#generate-btn').disabled = false;
      $('#generate-btn').textContent = '✂️ Lancer l\'édition';
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
    } else if (j.kind === 'generate' && j.result && j.result.images && j.result.images.length) {
      showResults(j.result.images);
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
  $('#st-refs').textContent = generationSourceCount + ' image(s)';
}

function showResults(images) {
  const box = $('#results');
  box.innerHTML = '';
  lastGeneratedResults = images.map(img => ({
    ...img,
    displayUrl: img.displayUrl || `${img.url}?t=${currentBatchStamp}`,
  }));
  activeCompareResultIdx = 0;

  // Si le mode Seamless Blend d'Inpainting est actif, fusionner la zone masquée avec l'image originale
  if (lastRunWasInpaint && lastInpaintMaskSnapshot && lastInpaintOrigImgEl) {
    Promise.all(lastGeneratedResults.map(async (item, i) => {
      try {
        const blended = await createSeamlessBlendedDataUrl(
          `${item.url}?t=${currentBatchStamp}`,
          lastInpaintOrigImgEl,
          lastInpaintMaskSnapshot
        );
        item.displayUrl = blended;
        const cardImgs = $$('.result img', box);
        if (cardImgs[i]) cardImgs[i].src = blended;
        if (i === activeCompareResultIdx && $('#compare-after')) {
          $('#compare-after').src = blended;
        }
      } catch (_) {}
    }));
  }

  lastGeneratedResults.forEach((img, idx) => {
    const d = document.createElement('div');
    d.className = 'result';
    d.innerHTML = `
      <img src="${img.displayUrl}" alt="">
      <div class="rbar"><span>seed ${img.seed}</span>
        <a class="link" href="${img.url}" download>télécharger</a></div>`;
    d.querySelector('img').addEventListener('click', () => {
      activeCompareResultIdx = idx;
      $('#compare-after').src = img.displayUrl;
      const items = buildEditLightboxItems();
      const hasSource = Boolean(comparisonSource || (canvas && canvas.url));
      openLightbox(items, hasSource ? idx + 1 : idx);
    });
    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'link';
    select.textContent = 'Comparer';
    select.addEventListener('click', () => {
      activeCompareResultIdx = idx;
      $('#compare-after').src = img.displayUrl;
      const items = buildEditLightboxItems();
      const hasSource = Boolean(comparisonSource || (canvas && canvas.url));
      openLightbox(items, hasSource ? idx + 1 : idx);
    });
    d.querySelector('.rbar').appendChild(select);
    const useAsSource = document.createElement('button');
    useAsSource.type = 'button';
    useAsSource.className = 'btn small result-use-source';
    useAsSource.textContent = 'Utiliser comme image à modifier';
    useAsSource.addEventListener('click', async () => {
      useAsSource.disabled = true;
      useAsSource.textContent = 'Chargement…';
      try {
        const response = await fetch(img.url);
        if (!response.ok) throw new Error("Image générée introuvable.");
        const blob = await response.blob();
        const file = new File([blob], img.filename.split('/').pop(), { type: 'image/png' });
        if (await setCanvas([file])) {
          $$('.result-use-source', box).forEach(button => {
            button.textContent = 'Utiliser comme image à modifier';
          });
          useAsSource.textContent = '✓ Image de départ remplacée';
          $('#canvas-drop').scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else {
          useAsSource.textContent = 'Utiliser comme image à modifier';
        }
      } catch (e) {
        showGenError(e.message || "Impossible d'utiliser cette image.");
        useAsSource.textContent = 'Utiliser comme image à modifier';
      } finally {
        useAsSource.disabled = false;
      }
    });
    d.appendChild(useAsSource);
    box.appendChild(d);
  });
  if (comparisonSource && lastGeneratedResults.length) {
    $('#compare').hidden = false;
    $('#compare-after').src = lastGeneratedResults[0].displayUrl;
  }
  saveEditDraft();
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
    saveEditDraft();
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
    let dims = { width: 0, height: 0, imgEl: null };
    try { dims = await readImageDimensions(src.url); } catch (e) {}
    const item = { path: src.filename, url: src.url, name: src.name || `image ${i + 1}`,
                   width: dims.width, height: dims.height, imgEl: dims.imgEl, objectUrl: null };
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
