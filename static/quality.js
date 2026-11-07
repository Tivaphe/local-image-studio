/* ===== Section « ✨ Qualité, Détails & Agrandissement » (partagée) =====
   - Rend un panneau repliable simple, avec une explication française pour chaque option.
   - Persiste les choix dans localStorage (lis_quality_prefs_v1), commun à toutes les pages.
   - Q.collect() retourne les paramètres à fusionner dans le corps de /api/generate.
   - Fournit les boutons « 🔍 Agrandir ×4 » (génération, édition, historique).
*/
(function () {
  const PREF_KEY = "lis_quality_prefs_v1";
  const Q = window.LisQuality = {
    info: null,
    _initialized: false,
    _doneCbs: [],
    _poll: null,
  };

  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function savePrefs(p) {
    try { localStorage.setItem(PREF_KEY, JSON.stringify({ ...loadPrefs(), ...p })); }
    catch (e) { /* stockage indisponible */ }
  }

  async function loadInfo(force = false) {
    if (Q.info && !force) return Q.info;
    try {
      const r = await fetch("/api/quality-info");
      const j = await r.json();
      if (j.ok) Q.info = j;
    } catch (e) { /* réseau : on retentera au prochain appel */ }
    return Q.info;
  }

  function downloadedUpscalers() {
    return (Q.info?.upscalers || []).filter(u => u.status && u.status.downloaded);
  }
  function downloadedAdetailers() {
    return (Q.info?.adetailers || []).filter(d => d.status && d.status.downloaded);
  }

  // ------------------------------------------------------------------ //
  //  Construction du panneau
  // ------------------------------------------------------------------ //
  Q.initSection = async function ({ container, withHires = true } = {}) {
    const host = typeof container === "string" ? $(container) : container;
    if (!host) return;
    await loadInfo();
    const info = Q.info || { samplers: [], schedulers: [], upscalers: [], adetailers: [] };
    const prefs = loadPrefs();

    const upscalerOptions = ['<option value="">— Désactivé — (image à la taille demandée)</option>']
      .concat(info.upscalers.map(u => {
        const ok = u.status && u.status.downloaded;
        const suffix = ok ? "" : "  · à télécharger (onglet Modèles)";
        return `<option value="${esc(u.id)}" ${ok ? "" : "disabled"} data-desc="${esc(u.desc)}">${esc(u.short_label)}${suffix}</option>`;
      })).join("");
    const adetailerOptions = ['<option value="">— Désactivé —</option>']
      .concat(info.adetailers.map(d => {
        const ok = d.status && d.status.downloaded;
        const suffix = ok ? "" : "  · à télécharger (onglet Modèles)";
        return `<option value="${esc(d.id)}" ${ok ? "" : "disabled"} data-desc="${esc(d.desc)}">${esc(d.short_label)}${suffix}</option>`;
      })).join("");
    const samplerOptions = info.samplers.map(s =>
      `<option value="${esc(s.id)}" data-desc="${esc(s.desc)}">${esc(s.label)}</option>`).join("");
    const schedulerOptions = info.schedulers.map(s =>
      `<option value="${esc(s.id)}" data-desc="${esc(s.desc)}">${esc(s.label)}</option>`).join("");

    host.innerHTML = `
      <details class="advanced quality-details" id="quality-box">
        <summary>✨ Qualité, Détails &amp; Agrandissement — options avancées expliquées</summary>

        <div class="q-block">
          <div class="q-head"><span class="q-title">🔍 Agrandissement ×4 (super-résolution)</span></div>
          <label class="field">
            <span>Modèle d'agrandissement</span>
            <select id="q-upscale-model">${upscalerOptions}</select>
          </label>
          <p class="hint" id="q-upscale-desc">
            Multiplie la résolution finale par 4 (ex. 1024×1024 → 4096×4096) avec un modèle
            spécialisé de super-résolution. Idéal pour l'impression ou l'affichage écran large.
            Vous pouvez aussi agrandir n'importe quelle image après coup avec le bouton
            « 🔍 Agrandir ×4 » des résultats et de l'historique.
          </p>
        </div>

        ${withHires ? `
        <div class="q-block" id="q-hires-block">
          <div class="q-head"><span class="q-title">🏗️ Hires Fix — deux passes (composition → détails)</span></div>
          <label class="q-toggle" id="q-hires-toggle">
            <input type="checkbox" id="q-hires-on">
            <span>Activer la passe haute résolution <em>(jusqu'à ×2, max ~2048 px)</em></span>
          </label>
          <label class="field q-indent" id="q-hires-strength-field">
            <span>Intensité de la passe de détails : <b id="q-hires-strength-val">0,35</b></span>
            <input type="range" id="q-hires-strength" min="0.2" max="0.6" step="0.05" value="0.35">
          </label>
          <p class="hint">
            1ʳᵉ passe : le modèle compose l'image à la taille choisie. 2ᵉ passe : chaque image est
            re-détallée doucement en haute résolution (cheveux, tissus, arrière-plans) — le temps de
            génération double environ. <b>Nécessite un modèle compatible img2img</b> (Stable Diffusion
            3.5, FLUX.1 Dev, Chroma…) et aucune image de départ.
          </p>
          <p class="hint warn" id="q-hires-unsupported" hidden>
            ⚠️ Ce modèle ne permet pas le Hires Fix (il ne fait pas d'img2img) : l'option est ignorée.
          </p>
        </div>` : ""}

        <div class="q-block">
          <div class="q-head"><span class="q-title">🙂 ADetailer — retouche automatique visages &amp; mains</span></div>
          <label class="field">
            <span>Détecteur à appliquer après génération</span>
            <select id="q-ad-model">${adetailerOptions}</select>
          </label>
          <p class="hint" id="q-ad-desc">
            Un détecteur YOLOv8 repère chaque visage (ou main) puis le re-détaille avec votre modèle :
            fini les yeux flous et les doigts déformés. Si rien n'est détecté, l'image reste identique.
          </p>
        </div>

        <div class="q-block">
          <div class="q-head"><span class="q-title">🎛️ Échantillonneur &amp; planificateur</span></div>
          <div class="row">
            <label class="field grow">
              <span>Échantillonneur (sampler)</span>
              <select id="q-sampler">${samplerOptions}</select>
            </label>
            <label class="field grow">
              <span>Planificateur (scheduler)</span>
              <select id="q-scheduler">${schedulerOptions}</select>
            </label>
          </div>
          <p class="hint" id="q-sampler-desc">L'échantillonneur pilote la façon dont le bruit est retiré à chaque étape.</p>
          <p class="hint" id="q-scheduler-desc">Le planificateur règle la répartition du bruit sur les étapes.</p>
        </div>

        <details class="q-sub">
          <summary>⚙️ Réglages experts (VRAM &amp; guidage)</summary>
          <label class="q-toggle">
            <input type="checkbox" id="q-vae-tiling">
            <span>Décodage VAE par tuiles <em>(--vae-tiling)</em></span>
          </label>
          <p class="hint">
            Découpe le décodage en tuiles pour les grandes images (agrands formats, Hires Fix) :
            économise beaucoup de VRAM. Peut créer de très légers raccords entre tuiles sur de
            rares images. Recommandé si votre carte a 8 Go de VRAM ou moins.
          </p>
          <label class="field">
            <span>Skip Layer Guidance — SLG : <b id="q-slg-val">désactivé</b></span>
            <input type="range" id="q-slg" min="0" max="5" step="0.25" value="0">
          </label>
          <p class="hint">
            Améliore le respect du prompt (mains, objets oubliés, comptage) sur les modèles DiT
            (FLUX, Qwen-Image…) en ignorant une couche interne pendant le guidage. Valeur conseillée :
            3. Laissez sur 0 pour le comportement standard.
          </p>
        </details>
        <p class="hint q-foot" id="q-foot-note"></p>
      </details>`;

    // ----------------- restauration des préférences ----------------- //
    const setVal = (id, v) => {
      const el = $("#" + id);
      if (!el || v === undefined || v === null) return;
      const opt = el.querySelector(`option[value="${CSS.escape(String(v))}"]`);
      if (opt && !opt.disabled) el.value = v;
    };
    setVal("q-upscale-model", prefs.upscale_id);
    setVal("q-ad-model", prefs.adetailer_id);
    setVal("q-sampler", prefs.sampler || "default");
    setVal("q-scheduler", prefs.scheduler || "default");
    if ($("#q-vae-tiling")) $("#q-vae-tiling").checked = !!prefs.vae_tiling;
    if ($("#q-slg")) $("#q-slg").value = prefs.slg_scale ?? 0;
    if ($("#q-hires-on")) $("#q-hires-on").checked = !!prefs.hires_fix;
    if ($("#q-hires-strength")) $("#q-hires-strength").value = prefs.hires_strength ?? 0.35;

    Q._sectionEls = { withHires };
    updateDesc();
    updateFootNote();

    // ----------------- interactions ----------------- //
    $("#quality-box")?.addEventListener("change", onAnyChange);
    $("#quality-box")?.addEventListener("input", onAnyChange);
    function onAnyChange(e) {
      const t = e.target;
      if (!t || !t.id) return;
      updateDesc();
      updateFootNote();
      savePrefs(Q.collect());
    }

    function updateDesc() {
      const bindDesc = (selId, descId, fallback) => {
        const sel = $("#" + selId);
        const p = $("#" + descId);
        if (!sel || !p) return;
        const opt = sel.selectedOptions && sel.selectedOptions[0];
        const d = opt && opt.dataset ? opt.dataset.desc : "";
        if (d) p.textContent = d;
        else if (fallback) p.textContent = fallback;
      };
      bindDesc("q-upscale-model", "q-upscale-desc",
        null); // laisse le texte explicatif par défaut (multiplie ×4…)
      bindDesc("q-ad-model", "q-ad-desc",
        "Un détecteur YOLOv8 repère chaque visage (ou main) puis le re-détaille avec votre modèle : fini les yeux flous et les doigts déformés. Si rien n'est détecté, l'image reste identique.");
      bindDesc("q-sampler", "q-sampler-desc",
        "L'échantillonneur pilote la façon dont le bruit est retiré à chaque étape.");
      bindDesc("q-scheduler", "q-scheduler-desc",
        "Le planificateur règle la répartition du bruit sur les étapes.");

      const sVal = parseFloat($("#q-slg")?.value || "0");
      const sLab = $("#q-slg-val");
      if (sLab) sLab.textContent = sVal > 0 ? String(sVal).replace(".", ",") : "désactivé";
      const hVal = parseFloat($("#q-hires-strength")?.value || "0.35");
      const hLab = $("#q-hires-strength-val");
      if (hLab) hLab.textContent = String(hVal).replace(".", ",");
    }

    function updateFootNote() {
      const foot = $("#q-foot-note");
      if (!foot) return;
      if (!downloadedUpscalers().length) {
        foot.innerHTML = "💡 Aucun modèle ×4 installé pour l'instant — téléchargez-en un (35–64 Mo) "
          + "dans l'onglet <a href=\"/models\">Modèles</a>, section « 🔍 Upscaling ×4 ». "
          + "Le bouton « 🔍 Agrandir ×4 » apparaîtra alors sur toutes vos images.";
      } else {
        foot.textContent = "";
      }
    }

    Q._initialized = true;
  };

  // Active/grise le Hires Fix selon le modèle choisi (img2img requis).
  Q.setModelCapabilities = function (model) {
    const block = $("#q-hires-block");
    if (!block) return;
    const can = !!(model && (model.input_modes || []).includes("init"));
    const chk = $("#q-hires-on");
    const warn = $("#q-hires-unsupported");
    if (chk) chk.disabled = !can;
    if (warn) warn.hidden = can;
    block.classList.toggle("q-disabled", !can);
  };

  // Quand une image de départ est fournie (img2img), le Hires Fix ne s'applique pas.
  Q.setSourceImageActive = function (active) {
    const block = $("#q-hires-block");
    if (!block || block.classList.contains("q-disabled")) return;
    const chk = $("#q-hires-on");
    if (chk) {
      chk.disabled = !!active;
      if (active) chk.checked = false;
    }
    const warn = $("#q-hires-unsupported");
    if (warn) {
      warn.hidden = !active;
      warn.textContent = active
        ? "⚠️ Le Hires Fix est réservé à la génération pure (sans image de départ) : option désactivée pour ce lancement."
        : "";
    }
  };

  // ------------------------------------------------------------------ //
  //  Collecte des paramètres pour POST /api/generate
  // ------------------------------------------------------------------ //
  Q.collect = function () {
    const out = {};
    if (!Q._initialized) return out;
    out.sampler = $("#q-sampler")?.value || "default";
    out.scheduler = $("#q-scheduler")?.value || "default";
    out.vae_tiling = !!$("#q-vae-tiling")?.checked;
    const slg = parseFloat($("#q-slg")?.value || "0");
    if (slg > 0) out.slg_scale = slg;
    const up = $("#q-upscale-model")?.value || "";
    if (up) out.upscale_id = up;
    const ad = $("#q-ad-model")?.value || "";
    if (ad) out.adetailer_id = ad;
    const hires = $("#q-hires-on");
    if (hires && hires.checked && !hires.disabled) {
      out.hires_fix = true;
      out.hires_strength = parseFloat($("#q-hires-strength")?.value || "0.35");
    }
    return out;
  };

  // Modèle ×4 à utiliser pour les boutons « Agrandir » (choisi, sinon 1er installé).
  Q.chosenUpscaler = function () {
    const v = $("#q-upscale-model")?.value || "";
    if (v) return v;
    const first = downloadedUpscalers()[0];
    return first ? first.id : null;
  };
  Q.anyUpscalerDownloaded = () => downloadedUpscalers().length > 0;

  // ------------------------------------------------------------------ //
  //  Agrandissement ×4 d'une image existante (POST /api/upscale)
  // ------------------------------------------------------------------ //
  Q.startUpscale = async function ({ imageId = null, path = null } = {}) {
    const body = {};
    if (imageId != null) body.image_id = imageId;
    if (path) body.path = path;
    const chosen = Q.chosenUpscaler();
    if (chosen) body.upscaler_id = chosen;
    let j;
    try {
      const r = await fetch("/api/upscale", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      j = await r.json();
    } catch (e) {
      if (window.showToast) window.showToast("❌ Connexion au serveur impossible : " + e.message);
      return false;
    }
    if (!j.ok) {
      if (window.showToast) window.showToast("❌ " + (j.error || "Agrandissement impossible."));
      return false;
    }
    if (j.queued) {
      if (window.showToast) {
        window.showToast(`⏳ Agrandissement ajouté à la file d'attente (position #${j.position}).`);
      }
    } else if (window.showToast) {
      const nm = (Q.info?.upscalers || []).find(u => u.id === j.upscaler_id)?.name || "×4";
      window.showToast(`🔍 Agrandissement en cours avec ${nm}…`);
    }
    ensurePolling();
    return true;
  };

  // Fabrique un bouton « 🔍 Agrandir ×4 » prêt à poser sur une carte image.
  Q.makeUpscaleButton = function ({ imageId = null, path = null } = {}) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small upscale-mini";
    btn.textContent = "🔍 Agrandir ×4";
    btn.title =
      "Agrandit cette image ×4 par super-résolution (≈ 4096 px de côté). " +
      "Le modèle utilisé est celui de la section Qualité, ou le premier installé. " +
      "La grande version est enregistrée dans l'historique.";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "🔍 en cours…";
      Q._doneCbs.push(() => {
        btn.disabled = false;
        btn.textContent = "🔍 Agrandir ×4";
      });
      const ok = await Q.startUpscale({ imageId, path });
      if (!ok) {
        Q._doneCbs.pop();
        btn.disabled = false;
        btn.textContent = "🔍 Agrandir ×4";
      }
    });
    return btn;
  };

  // Réactive les boutons et prévient la page que l'agrandissement est terminé.
  Q._done = function (images) {
    const cbs = Q._doneCbs;
    Q._doneCbs = [];
    cbs.forEach(cb => { try { cb(); } catch (e) {} });
    if (typeof window.__lisOnUpscaleDone === "function") {
      try { window.__lisOnUpscaleDone(images || []); } catch (e) {}
    }
    if (images && images.length && window.showToast) {
      const sc = images[0].scale || 4;
      const w = images[0].width ? ` (${images[0].width}×${images[0].height || "?"})` : "";
      window.showToast(`🔍 Agrandissement ×${sc} terminé ✓ — enregistré dans l'historique.`);
    }
  };

  // Si la page a son propre poller (génération/édition), on s'y branche ;
  // sinon (historique) on démarre un mini-suivi dédié.
  function ensurePolling() {
    if (typeof window.__lisPagePoll === "function") {
      window.__lisPagePoll();
      return;
    }
    if (Q._poll) return;
    Q._poll = setInterval(async () => {
      try {
        const r = await fetch("/api/status");
        const j = await r.json();
        if (j.busy) return;
        clearInterval(Q._poll);
        Q._poll = null;
        if (j.result && j.result.type === "upscale") {
          if (j.result.error) {
            Q._done([]);
            return;
          }
          if (j.result.images && j.result.images.length && !j.result.cancelled) {
            Q._done(j.result.images);
          } else {
            Q._done([]);
          }
        } else {
          Q._done([]);
        }
      } catch (e) { /* on réessaie au prochain cycle */ }
    }, 1200);
  }
})();
