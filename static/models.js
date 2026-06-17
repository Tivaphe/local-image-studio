/* ===== Page Modèles ===== */
/* Robuste : feedback immediat au clic + auto-detection d une tache en cours */

// Fallback: $ et $$ en cas de chargement avant app.js
if (typeof window.$ === 'undefined') {
  window.$ = (s, el = document) => el.querySelector(s);
  window.$$ = (s, el = document) => [...el.querySelectorAll(s)];
}
const $ = window.$;
const $$ = window.$$;

let taskTimer = null;

// --- Affiche la banniere de progression ---
function showBanner(msg) {
  const banner = $('#task-banner');
  if (!banner) return;
  banner.hidden = false;
  if (msg) $('#banner-text').textContent = msg;
  $('#banner-fill').style.width = '0%';
}

// --- Boucle de suivi d une tache (download / engine) ---
function startPolling() {
  if (taskTimer) clearInterval(taskTimer);
  const fill = $('#banner-fill');
  const text = $('#banner-text');
  taskTimer = setInterval(async () => {
    try {
      const r = await fetch('/api/status');
      const j = await r.json();
      const pct = Math.round((j.progress || 0) * 100);
      if (fill) fill.style.width = pct + '%';
      if (text) text.textContent = j.log || (j.busy ? 'en cours…' : 'termine');
      // desactive les boutons pendant la tache
      document.querySelectorAll('.dl-btn, #install-engine').forEach(b => b.disabled = true);
      if (!j.busy) {
        clearInterval(taskTimer); taskTimer = null;
        if (j.error) {
          alert('Erreur : ' + j.error);
          setTimeout(() => location.reload(), 1200);
        } else {
          setTimeout(() => location.reload(), 1200); // rafraichit l etat des modeles
        }
      }
    } catch (e) { /* retry au prochain cycle */ }
  }, 1000);
}

// --- Au chargement : une tache est-elle deja en cours ? ---
(async function checkRunning() {
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    if (j.busy) { showBanner(j.log || 'reprise…'); startPolling(); }
  } catch (e) {}
})();

// --- Bouton : installer le moteur ---
const btnEngine = $('#install-engine');
if (btnEngine) {
  btnEngine.addEventListener('click', async () => {
    // feedback IMMEDIAT
    btnEngine.disabled = true;
    btnEngine.textContent = 'telechargement en cours…';
    showBanner('Demarrage du telechargement du moteur…');
    try {
      const r = await fetch('/api/download-engine', { method: 'POST' });
      const j = await r.json();
      if (!j.ok) {
        btnEngine.disabled = false;
        btnEngine.textContent = 'Installer le moteur';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      btnEngine.disabled = false;
      btnEngine.textContent = 'Installer le moteur';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
}

// --- Boutons : telecharger un modele ---
$$('.dl-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const card = btn.closest('.model-card');
    const model = btn.dataset.model;
    const quant = card.querySelector('.dl-quant').value;
    // feedback IMMEDIAT
    btn.disabled = true;
    btn.textContent = 'en cours…';
    showBanner('Telechargement de ' + model + ' (' + quant + ')…');
    try {
      const r = await fetch('/api/download-model', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: model, quant })
      });
      const j = await r.json();
      if (!j.ok) {
        btn.disabled = false;
        btn.textContent = 'Telecharger';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Telecharger';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
});
