/* ===== Local Image Studio — JS partagé ===== */

// Raccourcis utilitaires (globaux pour tous les scripts de page)
window.$ = (s, el = document) => el.querySelector(s);
window.$$ = (s, el = document) => [...el.querySelectorAll(s)];

// Badge d'état du moteur (présent sur toutes les pages via la topbar)
async function refreshEngineBadge() {
  const badge = $('#engine-badge');
  if (!badge) return;
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    if (j.engine_ready) {
      badge.textContent = 'moteur ✓';
      badge.className = 'badge badge-ok';
    } else {
      badge.textContent = 'moteur absent';
      badge.className = 'badge badge-warn';
    }
  } catch (e) {}
}
refreshEngineBadge();

// Lightbox pour agrandir les images
function openLightbox(src) {
  let lb = $('#lightbox');
  if (!lb) {
    lb = document.createElement('div');
    lb.id = 'lightbox';
    lb.className = 'lightbox';
    lb.innerHTML = '<button class="x">×</button><img>';
    lb.addEventListener('click', e => { if (e.target === lb || e.target.classList.contains('x')) lb.classList.remove('show'); });
    document.body.appendChild(lb);
  }
  lb.querySelector('img').src = src;
  lb.classList.add('show');
}
