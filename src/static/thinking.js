/* ===== Local Image Studio — 🧠 Thinking (partagé Générer / Édition) =====
 * Le prompt passe d'abord par un modèle de raisonnement local (llama.cpp).
 * La modale affiche le raisonnement (repliable) et le prompt final (éditable).
 * Rien n'est généré tant que l'utilisateur n'a pas cliqué « Générer avec ce prompt ».
 * État mémorisé dans localStorage (lis_thinking), défaut : OFF.
 */
window.LisThinking = (function () {
  "use strict";

  const KEY = 'lis_thinking';
  const $ = id => document.getElementById(id);
  let elapsedTimer = null;
  let startedAt = 0;
  let onAcceptCb = null;

  const isEnabled = () => localStorage.getItem(KEY) === '1';
  const setEnabled = (v) => { localStorage.setItem(KEY, v ? '1' : '0'); syncToggle(); };

  // ---------- bouton bascule (présent sur les deux pages) ----------
  function syncToggle() {
    const btn = $('thinking-toggle');
    if (!btn) return;
    const on = isEnabled();
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = on ? '🧠 Thinking ✓' : '🧠 Thinking';
    btn.title = on
      ? 'À chaque « Générer », le prompt passe d\u2019abord par un modèle de raisonnement local (aperçu obligatoire avant génération). Cliquez pour désactiver.'
      : 'Activez pour laisser un modèle local raisonner sur votre prompt avant la génération (aperçu obligatoire, modèle choisi dans Paramètres).';
  }

  function bindToggle() {
    const btn = $('thinking-toggle');
    if (btn) btn.addEventListener('click', () => setEnabled(!isEnabled()));
  }

  // ---------- modale ----------
  function fmtElapsed(ms) {
    const s = Math.floor(ms / 1000);
    return s < 60 ? s + 's' : Math.floor(s / 60) + 'min ' + String(s % 60).padStart(2, '0') + 's';
  }
  function startElapsed() {
    startedAt = Date.now();
    const el = $('thinking-elapsed');
    if (el) el.textContent = '0s';
    clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => { const e = $('thinking-elapsed'); if (e) e.textContent = fmtElapsed(Date.now() - startedAt); }, 250);
  }
  function stopElapsed() { clearInterval(elapsedTimer); elapsedTimer = null; }

  function setLoading(loading) {
    const box = $('thinking-loading');
    if (box) box.hidden = !loading;
    const fw = $('thinking-final-wrap'); if (fw) fw.hidden = loading;
    const ft = $('thinking-final'); if (ft) ft.hidden = loading;
    const wrap = $('thinking-reasoning-wrap');
    if (wrap && loading) { wrap.hidden = true; wrap.open = false; }
    $('thinking-go').hidden = loading;
    $('thinking-copy').hidden = loading;
    $('thinking-error').hidden = true;
    $('thinking-backend').hidden = true;
  }

  function openModal() {
    const m = $('thinking-modal');
    if (!m) return;
    m.hidden = false;
    document.body.classList.add('thinking-open');
  }
  function closeModal() {
    const m = $('thinking-modal');
    if (!m) return;
    m.hidden = true;
    document.body.classList.remove('thinking-open');
    stopElapsed();
  }

  function showResult(j) {
    stopElapsed();
    setLoading(false);
    const finalEl = $('thinking-final');
    if (finalEl) finalEl.value = j.prompt || '';
    const wrap = $('thinking-reasoning-wrap');
    const reasoning = (j.reasoning || '').trim();
    if (reasoning && wrap) {
      wrap.hidden = false;
      wrap.open = false;
      $('thinking-reasoning').textContent = reasoning;
    } else if (wrap) {
      wrap.hidden = true;
    }
    const be = $('thinking-backend');
    if (be) {
      be.hidden = false;
      be.textContent = `Modèle : ${j.model_name || j.model_id} — moteur : ${j.backend || 'llama.cpp'}`
        + (j.degraded ? ' — ⚠️ mode dégradé (sans raisonnement)' : '')
        + (j.elapsed ? ` — ${j.elapsed}s` : '');
    }
    const go = $('thinking-go');
    if (go) {
      // libellé selon la page (URL)
      go.textContent = (location.pathname || '').startsWith('/edit')
        ? '✏️ Éditer avec ce prompt'
        : '✨ Générer avec ce prompt';
    }
    $('thinking-final')?.focus();
  }

  function showError(msg) {
    stopElapsed();
    setLoading(false);
    const err = $('thinking-error');
    err.hidden = false;
    err.textContent = msg;
    const finalWrap = $('thinking-final-wrap');
    if (finalWrap) finalWrap.hidden = true;
    const wrap = $('thinking-reasoning-wrap');
    if (wrap) wrap.hidden = true;
    $('thinking-go').hidden = true;
    $('thinking-copy').hidden = true;
  }

  async function requestThink({ kind, text, image, onAccept, cta }) {
    openModal();
    setLoading(true);
    startElapsed();
    onAcceptCb = onAccept || null;
    $('thinking-error').hidden = true;
    try {
      const r = await fetch('/api/think', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, text, image: image || null }),
      });
      const j = await r.json();
      if (!j.ok) { showError(j.error || 'Échec du thinking.'); return; }
      showResult(j);
    } catch (e) {
      showError('Erreur réseau pendant le thinking : ' + e.message);
    }
  }

  // Appelée par les gestionnaires « Générer » des deux pages.
  // Retourne true si la génération normale doit être interrompue (modale affichée).
  async function maybeIntercept({ kind, text, image, onAccept }) {
    if (window.__lisThinkingSkip) { window.__lisThinkingSkip = false; return false; }
    if (!isEnabled()) return false;
    if (!text) return false;   // les validations régulières afficheront l'erreur
    await requestThink({ kind, text, image, onAccept });
    return true;
  }

  function bindModal() {
    document.querySelector('#thinking-modal [data-thinking-close]')?.addEventListener('click', async () => {
      await fetch('/api/think-cancel', { method: 'POST' }).catch(() => {});
      closeModal();
    });
    $('thinking-close')?.addEventListener('click', async () => {
      await fetch('/api/think-cancel', { method: 'POST' }).catch(() => {});
      closeModal();
    });
    $('thinking-cancel')?.addEventListener('click', async () => {
      await fetch('/api/think-cancel', { method: 'POST' }).catch(() => {});
      closeModal();
    });
    $('thinking-copy')?.addEventListener('click', async () => {
      const text = ($('thinking-final')?.value || '').trim();
      if (!text) return;
      try { await navigator.clipboard.writeText(text); if (window.showToast) window.showToast('📋 Prompt copié.'); }
      catch (e) {
        const ta = $('thinking-final'); ta.select(); try { document.execCommand('copy'); } catch (_) {}
        if (window.showToast) window.showToast('📋 Prompt copié.');
      }
    });
    $('thinking-go')?.addEventListener('click', () => {
      const text = ($('thinking-final')?.value || '').trim();
      const cb = onAcceptCb;
      closeModal();
      if (text && cb) cb(text);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const m = $('thinking-modal');
        if (m && !m.hidden) {
          fetch('/api/think-cancel', { method: 'POST' }).catch(() => {});
          closeModal();
        }
      }
    });
  }

  function init() { bindToggle(); bindModal(); syncToggle(); }

  return { isEnabled, setEnabled, maybeIntercept, requestThink, init };
})();
document.addEventListener('DOMContentLoaded', () => window.LisThinking && window.LisThinking.init());
