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
      document.querySelectorAll('.dl-btn, .dl-upscale-btn, .dl-ad-btn, .dl-seedvr2-btn, .dl-taesd-btn, .dl-pulid-btn, #install-engine')
        .forEach(b => b.disabled = true);
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

// --- Mise à jour dynamique du bouton de téléchargement selon la quant sélectionnée ---
function updateDlBtn(card) {
  const sel = card.querySelector('.dl-quant');
  const btn = card.querySelector('.dl-btn');
  if (!sel || !btn) return;
  const opt = sel.selectedOptions[0];
  const haveQuant = opt && opt.dataset.have === '1';
  const hasMissDeps = card.querySelectorAll('.dep.miss').length > 0;
  if (haveQuant && hasMissDeps) {
    btn.textContent = 'Télécharger dépendances';
    btn.classList.add('primary');
    btn.classList.remove('ghost');
  } else if (haveQuant) {
    btn.textContent = 'Re-télécharger';
    btn.classList.remove('primary');
    btn.classList.add('ghost');
  } else {
    btn.textContent = 'Télécharger';
    btn.classList.add('primary');
    btn.classList.remove('ghost');
  }
}

$$('.model-card').forEach(card => {
  const sel = card.querySelector('.dl-quant');
  if (sel) {
    sel.addEventListener('change', () => updateDlBtn(card));
  }
});

// --- Boutons : telecharger un modele d'agrandissement ×4 ---
$$('.dl-upscale-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const uid = btn.dataset.upscaler;
    btn.disabled = true;
    btn.textContent = 'en cours…';
    showBanner('Téléchargement du modèle d\'agrandissement…');
    try {
      const r = await fetch('/api/download-upscaler', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upscaler_id: uid })
      });
      const j = await r.json();
      if (!j.ok) {
        btn.disabled = false;
        btn.textContent = 'Télécharger';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Télécharger';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
});

// --- Boutons : telecharger un detecteur ADetailer (visages/mains) ---
$$('.dl-ad-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const did = btn.dataset.detector;
    btn.disabled = true;
    btn.textContent = 'en cours…';
    showBanner('Téléchargement du détecteur ADetailer…');
    try {
      const r = await fetch('/api/download-adetailer', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detector_id: did })
      });
      const j = await r.json();
      if (!j.ok) {
        btn.disabled = false;
        btn.textContent = 'Télécharger';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Télécharger';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
});

// --- Bouton : telecharger SeedVR2 (restauration ×2 par diffusion, ~6,8 Go) ---
const dlSeedvr2 = $('.dl-seedvr2-btn');
if (dlSeedvr2) {
  dlSeedvr2.addEventListener('click', async () => {
    dlSeedvr2.disabled = true;
    dlSeedvr2.textContent = 'en cours…';
    showBanner('Téléchargement de SeedVR2 (~6,8 Go)…');
    try {
      const r = await fetch('/api/download-seedvr2', { method: 'POST' });
      const j = await r.json();
      if (!j.ok) {
        dlSeedvr2.disabled = false;
        dlSeedvr2.textContent = 'Télécharger (~6,8 Go)';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      dlSeedvr2.disabled = false;
      dlSeedvr2.textContent = 'Télécharger (~6,8 Go)';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
}

// --- Boutons : telecharger un mini-VAE TAE (~2 Mo) ---
$$('.dl-taesd-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const taId = btn.dataset.taesd;
    btn.disabled = true;
    btn.textContent = 'en cours…';
    showBanner('Téléchargement du mini-VAE…');
    try {
      const r = await fetch('/api/download-taesd', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ taesd_id: taId })
      });
      const j = await r.json();
      if (!j.ok) {
        btn.disabled = false;
        btn.textContent = 'Télécharger';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Télécharger';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
});

// --- Bouton : telecharger les poids PuLID-FLUX (~1,14 Go) ---
const dlPulid = $('.dl-pulid-btn');
if (dlPulid) {
  dlPulid.addEventListener('click', async () => {
    dlPulid.disabled = true;
    dlPulid.textContent = 'en cours…';
    showBanner('Téléchargement des poids PuLID (~1,14 Go)…');
    try {
      const r = await fetch('/api/download-pulid', { method: 'POST' });
      const j = await r.json();
      if (!j.ok) {
        dlPulid.disabled = false;
        dlPulid.textContent = 'Télécharger (~1,14 Go)';
        alert(j.error || 'Erreur');
        return;
      }
      startPolling();
    } catch (e) {
      dlPulid.disabled = false;
      dlPulid.textContent = 'Télécharger (~1,14 Go)';
      alert('Connexion au serveur impossible : ' + e.message);
    }
  });
}

// --- Bouton : copier la commande d'extraction PuLID ---
$$('.copy-extract-cmd').forEach(btn => {
  btn.addEventListener('click', async () => {
    const cmd = btn.dataset.cmd || '';
    try {
      await navigator.clipboard.writeText(cmd);
      btn.textContent = '✅ Copiée !';
      setTimeout(() => { btn.textContent = '📋 Copier la commande complète'; }, 1800);
    } catch (e) {
      // presse-papier indisponible : affiche la commande pour copie manuelle
      prompt('Copiez la commande :', cmd);
    }
  });
});

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
