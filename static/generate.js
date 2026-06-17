/* ===== Page Generer =====
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

  // restauration du modele choisit precedemment
  const prefs = loadPrefs();
  let savedModel = prefs.model;
  // verifie que le modele sauvegarde existe encore
  if (!savedModel || !MODELS[savedModel]) savedModel = null;

  let firstReady = null;
  for (const [id, m] of Object.entries(MODELS)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = m.name + (m.status.ready ? '' : '  (a telecharger)');
    if (!m.status.ready) opt.style.color = '#9aa0ad';
    sel.appendChild(opt);
    if (m.status.ready && !firstReady) firstReady = id; // 1er modele pret par defaut
  }
  // ordre de priorite : modele sauvegarde > 1er pret > 1er de la liste
  sel.value = savedModel || firstReady || Object.keys(MODELS)[0];
  sel.addEventListener('change', () => {
    savePrefs({ model: sel.value, quant: $('#quant').value });
    onModelChange();
  });
  buildRatios();
  // restauration du ratio
  if (prefs.ratio && RATIOS[prefs.ratio]) currentRatio = prefs.ratio;
  buildRatiosApply();
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
  }
}

function buildRatios() {
  const box = $('#ratios');
  box.innerHTML = '';
  for (const [name, [w, h]] of Object.entries(RATIOS)) {
    const d = document.createElement('div');
    d.className = 'ratio' + (name === currentRatio ? ' sel' : '');
    d.title = `${name}  (${w}x${h})`;
    d.dataset.name = name;
    const max = 26;
    const sc = max / Math.max(w, h);
    const iw = Math.round(w * sc), ih = Math.round(h * sc);
    d.innerHTML = `<i style="width:${iw}px;height:${ih}px"></i>`;
    d.addEventListener('click', () => {
      currentRatio = name;
      savePrefs({ ratio: name });
      $$('.ratio').forEach(x => x.classList.remove('sel'));
      d.classList.add('sel');
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
  const m = MODELS[$('#model').value];
  if (!m) return;
  const q = $('#quant');
  q.innerHTML = '';
  const prefs = loadPrefs();
  for (const qt of m.quants) {
    const opt = document.createElement('option');
    opt.value = qt;
    const have = m.status.quants[qt];
    opt.textContent = qt + (have ? ' OK' : '  (a telecharger)');
    q.appendChild(opt);
  }
  // restaure la quant sauvegardee si valide pour ce modele
  if (prefs.quant && m.quants.includes(prefs.quant) && prefs.model === $('#model').value) {
    q.value = prefs.quant;
  } else {
    q.value = m.default_quant;
  }
  $('#steps').value = m.defaults.steps;
  $('#steps').min = m.min_steps; $('#steps').max = m.max_steps;
  $('#cfg').value = m.defaults.cfg;
  $('#negative').parentElement.style.display = m.supports_neg ? '' : 'none';
  // pre-remplir le negative par defaut si vide
  const negEl = $('#negative');
  if (m.supports_neg && !negEl.value && window.DEFAULT_NEG) {
    negEl.value = window.DEFAULT_NEG;
  }
  const warn = !m.status.ready ? `Ce modele n'est pas telecharge. Allez dans l'onglet Modeles.` : '';
  $('#gen-error').textContent = warn;
  $('#gen-error').hidden = !warn;
}

$('#batch').addEventListener('input', e => {
  const v = parseInt(e.target.value);
  $('#batch-val').textContent = v + ' image' + (v > 1 ? 's' : '');
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
  const body = {
    model_id,
    quant: $('#quant').value,
    prompt: $('#prompt').value,
    negative: $('#negative').value,
    ratio: currentRatio,
    steps: $('#steps').value,
    cfg: $('#cfg').value,
    seed: $('#seed').value || null,
    batch: $('#batch').value,
  };
  const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) {
    $('#gen-error').hidden = false;
    $('#gen-error').textContent = j.error || 'Erreur';
    return;
  }
  $('#gen-error').hidden = true;
  $('#generate-btn').hidden = true;
  $('#cancel-btn').hidden = false;
  $('#results').innerHTML = '';
  $('#stats-box').hidden = true;
  $('#progress-wrap').hidden = false;
  $('#progress-fill').style.width = '0%';
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
    } else {
      txt = 'termine';
    }
    $('#progress-text').textContent = txt;

    if (j.log) $('#log').textContent = j.log + ($('#log').textContent ? '\n' + $('#log').textContent : '');

    // affichage des images au fur et a mesure
    if (j.kind === 'generate' && j.result && j.result.images) {
      showResults(j.result.images);
    }

    if (!j.busy) {
      clearInterval(pollTimer); pollTimer = null;
      $('#generate-btn').hidden = false;
      $('#cancel-btn').hidden = true;
      if (j.error) {
        $('#gen-error').hidden = false;
        $('#gen-error').textContent = j.error;
      }
      // stats finales (FIX 3)
      const stats = (j.result && j.result.stats) || j.stats;
      if (stats) showStats(stats);
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

// ---------- negative prompt par defaut ----------
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
