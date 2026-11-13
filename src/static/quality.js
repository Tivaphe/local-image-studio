/* ===== Section « ✨ Qualité, Détails & Agrandissement » (partagée) =====
   - Rend un panneau repliable simple, avec une explication française pour chaque option.
   - Ne persiste QUE les préférences de présentation (échantillonneur / planificateur) dans
     localStorage (lis_quality_prefs_v1). Toutes les options avancées (UltraSharp, SageAttention,
     ADetailer, Hires Fix, mini-VAE, tuilage VAE, SLG, PuLID, aperçu) repartent désactivées à
     chaque actualisation — rien ne s'active tout seul.
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
  // Seules les préférences de présentation sont mémorisées (jamais les options avancées).
  function collectPersisted() {
    return {
      sampler: $("#q-sampler")?.value || "default",
      scheduler: $("#q-scheduler")?.value || "default",
    };
  }
  function savePrefs() {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(collectPersisted())); }
    catch (e) { /* stockage indisponible */ }
  }
  // Supprime les anciennes clés lourdes restées dans le navigateur (upscale_id, sage_attn…).
  function purgeStalePersistedPrefs() {
    try {
      const kept = {
        sampler: loadPrefs().sampler || "default",
        scheduler: loadPrefs().scheduler || "default",
      };
      localStorage.setItem(PREF_KEY, JSON.stringify(kept));
    } catch (e) { /* stockage indisponible */ }
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
          <div class="q-head"><span class="q-title">⚡ Performance — mini-VAE, SageAttention &amp; aperçu en direct</span></div>
          <label class="q-toggle">
            <input type="checkbox" id="q-taesd">
            <span>Mini-VAE rapide (TAE) <em>— décodage final quasi instantané</em></span>
          </label>
          <p class="hint">
            Utilise un décodeur allégé (~2 Mo, onglet Modèles → « ⚡ VAE rapide ») pour les modèles
            Qwen-Image (VAE Wan 2.1 / Qwen 2.1) : la toute fin de la génération passe de plusieurs
            secondes à une fraction de seconde. Très léger adoucissement possible. Sans effet sur les
            autres modèles.
          </p>
          <label class="q-toggle">
            <input type="checkbox" id="q-sage-attn">
            <span>SageAttention CUDA <em>— attention plus rapide, moins de VRAM</em></span>
          </label>
          <p class="hint">
            Active le noyau d'attention SageAttention via CUDA (aucune installation Python requise).
            Accélère l'échantillonnage et économise un peu de mémoire. Nécessite une carte
            <b>NVIDIA RTX 30/40/50 (ou Ampere SM80+)</b> avec des pilotes récents ; sinon sd-cli
            ignore l'option sans planter.
          </p>
          <label class="field">
            <span>Aperçu en direct pendant l'échantillonnage</span>
            <select id="q-preview">
              <option value="none">Désactivé</option>
              <option value="auto">✨ Auto (recommandé) — mini-VAE si installé, sinon projection</option>
              <option value="proj">Provisoire rapide (proj) — projection des latents, aucun modèle requis</option>
              <option value="tae">Mini-VAE (tae) — aperçu net, nécessite le mini-VAE installé</option>
            </select>
          </label>
          <label class="field" id="q-preview-interval-field">
            <span>Une image d'aperçu toutes les <b id="q-preview-interval-val">3</b> étapes</span>
            <input type="range" id="q-preview-interval" min="1" max="10" step="1" value="3">
          </label>
          <p class="hint">
            Pendant l'échantillonnage, une fenêtre « LIVE » apparaît au-dessus des résultats avec
            l'image qui se débruite pas à pas (pages Générer et Édition, sd-cli requis).
            <b>Désactivé par défaut</b> — sélectionnez « Auto » : mini-VAE si installé pour ce modèle,
            sinon projection des latents (instantanée). La projection est connue pour SD 1.x/XL, SD 3.5, FLUX (Dev/Schnell/
            FHDR/Chroma/Kontext), FLUX.2 et Qwen-Image-2.1 ; sur Qwen-Image 2512, seul le mini-VAE
            (onglet Modèles → ⚡ VAE rapide) affiche un aperçu. Avec le mini-VAE, le décodage final
            reste fait par le vrai VAE (un peu plus lent, plus net). Sans fichier ni projection connue,
            le moteur n'écrit aucun aperçu : c'est normal, l'image finale est inchangée.
          </p>
        </div>

        <div class="q-block" id="q-pulid-block">
          <div class="q-head"><span class="q-title">🎭 Visage fidèle (PuLID) — arch FLUX uniquement</span></div>
          <label class="field">
            <span>Portrait de référence</span>
            <select id="q-pulid-id"><option value="">— Aucun (génération libre) —</option></select>
          </label>
          <label class="field" id="q-pulid-weight-field">
            <span>Force de l'empreinte : <b id="q-pulid-weight-val">1,00</b></span>
            <input type="range" id="q-pulid-weight" min="0" max="2" step="0.05" value="1.0">
          </label>
          <p class="hint" id="q-pulid-hint">
            Conserve le visage d'une photo dans les images générées (FLUX.1 Schnell, Dev, FHDR).
            Téléchargez les poids PuLID (~1,14 Go) et créez une empreinte de portrait dans
            l'onglet <a href="/models">Modèles</a>, section « 🎭 Visage fidèle (PuLID) ».
          </p>
          <p class="hint warn" id="q-pulid-unsupported" hidden>
            ⚠️ Ce modèle ne prend pas en charge PuLID (il faut une architecture FLUX) : option désactivée.
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

    // -------- options avancées : toujours OFF au chargement (jamais restaurées) -------- //
    const setVal = (id, v) => {
      const el = $("#" + id);
      if (!el || v === undefined || v === null) return;
      const opt = el.querySelector(`option[value="${CSS.escape(String(v))}"]`);
      if (opt && !opt.disabled) el.value = v;
    };
    setVal("q-sampler", prefs.sampler || "default");
    setVal("q-scheduler", prefs.scheduler || "default");
    // Aperçu en direct : désactivé pour de bon à l'actualisation (l'utilisateur l'active lui-même).
    const savedPreview = "none";
    setVal("q-preview", savedPreview);
    if ($("#q-preview-interval")) $("#q-preview-interval").value = 3;
    const piFieldInit = $("#q-preview-interval-field");
    if (piFieldInit) piFieldInit.style.display = "none";
    // PuLID : peuple la liste des empreintes de portraits depuis /api/quality-info
    const pulidSel = $("#q-pulid-id");
    if (pulidSel) {
      const portraits = (info.pulid && info.pulid.portraits) || [];
      portraits.forEach(pt => {
        const o = document.createElement("option");
        o.value = pt.id;
        o.textContent = pt.name || pt.id;
        if (pt.size_mb) o.textContent += ` (${pt.size_mb} Mo)`;
        pulidSel.appendChild(o);
      });
    }
    purgeStalePersistedPrefs();

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
      savePrefs();
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
      const piLab = $("#q-preview-interval-val");
      if (piLab) piLab.textContent = String($("#q-preview-interval")?.value || 3);
      const piField = $("#q-preview-interval-field");
      if (piField) piField.style.display = ($("#q-preview")?.value || "none") === "none" ? "none" : "";
      const pwVal = parseFloat($("#q-pulid-weight")?.value || "1");
      const pwLab = $("#q-pulid-weight-val");
      if (pwLab) pwLab.textContent = pwVal.toFixed(2).replace(".", ",");
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
  // Grise aussi PuLID pour les architectures non-FLUX.
  Q.setModelCapabilities = function (model) {
    const block = $("#q-hires-block");
    if (block) {
      const can = !!(model && (model.input_modes || []).includes("init"));
      const chk = $("#q-hires-on");
      const warn = $("#q-hires-unsupported");
      if (chk) chk.disabled = !can;
      if (warn) warn.hidden = can;
      block.classList.toggle("q-disabled", !can);
    }
    const pulidBlock = $("#q-pulid-block");
    if (pulidBlock) {
      const arch = model && model.arch;
      const canPulid = arch === "flux" || arch === "flux_kontext";
      const warn = $("#q-pulid-unsupported");
      if (warn) warn.hidden = canPulid;
      pulidBlock.classList.toggle("q-disabled", !canPulid);
      const sel = $("#q-pulid-id");
      const w = $("#q-pulid-weight");
      if (sel) sel.disabled = !canPulid;
      if (w) w.disabled = !canPulid;
      if (!canPulid && sel) sel.value = "";
    }
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
    if ($("#q-taesd")?.checked) out.taesd_id = "auto";
    if ($("#q-sage-attn")?.checked) out.sage_attn = true;
    const preview = $("#q-preview")?.value || "none";
    out.preview = preview;
    if (preview !== "none") out.preview_interval = parseInt($("#q-preview-interval")?.value || "3", 10);
    const pulidSel = $("#q-pulid-id");
    if (pulidSel && !pulidSel.disabled && pulidSel.value) {
      out.pulid_id = pulidSel.value;
      out.pulid_id_weight = parseFloat($("#q-pulid-weight")?.value || "1");
    }
    const hires = $("#q-hires-on");
    if (hires && hires.checked && !hires.disabled) {
      out.hires_fix = true;
      out.hires_strength = parseFloat($("#q-hires-strength")?.value || "0.35");
    }
    return out;
  };

  // Copie texte avec repli textarea (navigator.clipboard exige un contexte sécurisé)
  Q.copyText = async function (text) {
    const s2 = String(text == null ? "" : text);
    try {
      await navigator.clipboard.writeText(s2);
      return true;
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = s2;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
      ta.remove();
      return ok;
    }
  };

  // Bouton « 📋 Copier le prompt » pour une carte image (résultat ou historique).
  // img.prompt est fourni par le moteur depuis les dernières versions ; sinon on retombe
  // sur le prompt courant du formulaire, sinon sur le texte de la carte.
  Q.bindCopyPrompt = function (btn, img) {
    if (!btn) return;
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card,.result");
      const fromCard = card ? (card.querySelector(".card-prompt") || {}).textContent : "";
      const fallbackPrompt = $("#prompt") ? $("#prompt").value : "";
      const prompt = (img && img.prompt) ? img.prompt : (fromCard && fromCard.trim() ? fromCard.trim() : fallbackPrompt);
      const ok = await Q.copyText(prompt);
      if (window.showToast) {
        window.showToast(ok ? "📋 Prompt copié ✓" : "Impossible de copier le prompt");
      }
      btn.textContent = ok ? "✓ copié" : "✕ échec";
      setTimeout(() => { btn.textContent = "📋 prompt"; }, 1400);
    });
  };

  // Modèle ×4 à utiliser pour les boutons « Agrandir » (choisi, sinon 1er installé).
  Q.chosenUpscaler = function () {
    const v = $("#q-upscale-model")?.value || "";
    if (v) return v;
    const first = downloadedUpscalers()[0];
    return first ? first.id : null;
  };
  Q.anyUpscalerDownloaded = () => downloadedUpscalers().length > 0;
  Q.chosenAdetailer = function () {
    const v = $("#q-ad-model")?.value || "";
    if (v) return v;
    const first = downloadedAdetailers()[0];
    return first ? first.id : null;
  };
  Q.anyAdetailerDownloaded = () => downloadedAdetailers().length > 0;

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
    window.__lisAwaitToken = j.task_token || null;
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

  // ------------------------------------------------------------------ //
  //  Réparation visages/mains d'une image existante (POST /api/repair)
  // ------------------------------------------------------------------ //
  Q.startRepair = async function ({ imageId = null, path = null } = {}) {
    const body = {};
    if (imageId != null) body.image_id = imageId;
    if (path) body.path = path;
    const chosen = Q.chosenAdetailer();
    if (chosen) body.detector_id = chosen;
    // Reprend le mini-VAE / SageAttention si la section Qualité en cours les active
    const perf = Q.collect();
    if (perf.sage_attn) body.sage_attn = true;
    if (perf.taesd_id) body.taesd_id = perf.taesd_id;
    let j;
    try {
      const r = await fetch("/api/repair", {
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
      if (window.showToast) window.showToast("❌ " + (j.error || "Réparation impossible."));
      return false;
    }
    window.__lisAwaitToken = j.task_token || null;
    if (j.queued) {
      if (window.showToast) window.showToast(`⏳ Réparation ajoutée à la file d'attente (position #${j.position}).`);
    } else if (window.showToast) {
      const nm = (Q.info?.adetailers || []).find(d => d.id === j.detector_id)?.name || "ADetailer";
      window.showToast(`🙂 Réparation en cours avec ${nm}…`);
    }
    ensurePolling();
    return true;
  };

  // Fabrique un bouton « 🙂 Réparer visages & mains » pour une carte image.
  Q.makeRepairButton = function ({ imageId = null, path = null } = {}) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small repair-mini";
    btn.textContent = "🙂 Réparer visages & mains";
    btn.title =
      "Détecte et re-détaille automatiquement les visages et mains de cette image. " +
      "Le détecteur utilisé est celui de la section Qualité, ou le premier installé. " +
      "La version réparée est enregistrée dans l'historique.";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "🙂 réparation…";
      Q._doneCbs.push(() => {
        btn.disabled = false;
        btn.textContent = "🙂 Réparer visages & mains";
      });
      const ok = await Q.startRepair({ imageId, path });
      if (!ok) {
        Q._doneCbs.pop();
        btn.disabled = false;
        btn.textContent = "🙂 Réparer visages & mains";
      }
    });
    return btn;
  };

  // ------------------------------------------------------------------ //
  //  Restauration ×2 par diffusion (POST /api/restore-x2, SeedVR2)
  // ------------------------------------------------------------------ //
  Q.startRestoreX2 = async function ({ imageId = null, path = null } = {}) {
    const body = {};
    if (imageId != null) body.image_id = imageId;
    if (path) body.path = path;
    let j;
    try {
      const r = await fetch("/api/restore-x2", {
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
      if (window.showToast) window.showToast("❌ " + (j.error || "Restauration impossible."));
      return false;
    }
    window.__lisAwaitToken = j.task_token || null;
    if (j.queued) {
      if (window.showToast) window.showToast(`⏳ Restauration ajoutée à la file d'attente (position #${j.position}).`);
    } else if (window.showToast) {
      window.showToast("🩹 Restauration ×2 en cours (SeedVR2, peut prendre plusieurs minutes)…");
    }
    ensurePolling();
    return true;
  };

  Q.makeRestoreX2Button = function ({ imageId = null, path = null } = {}) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small restore-mini";
    btn.textContent = "🩹 Restaurer ×2";
    btn.title =
      "Reconstruit la matière (peau, tissus) et double la résolution avec SeedVR2 (nécessite " +
      "les poids SeedVR2, ~6,8 Go, onglet Modèles). La version restaurée est enregistrée dans l'historique.";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "🩹 restauration…";
      Q._doneCbs.push(() => {
        btn.disabled = false;
        btn.textContent = "🩹 Restaurer ×2";
      });
      const ok = await Q.startRestoreX2({ imageId, path });
      if (!ok) {
        Q._doneCbs.pop();
        btn.disabled = false;
        btn.textContent = "🩹 Restaurer ×2";
      }
    });
    return btn;
  };

  // ------------------------------------------------------------------ //
  //  Super-résolution générative PiD ×4 (POST /api/pid-upscale, NVIDIA PiD)
  // ------------------------------------------------------------------ //
  Q.startPid = async function ({ imageId = null, path = null, backbone = null, prompt = null } = {}) {
    const body = {};
    if (imageId != null) body.image_id = imageId;
    if (path) body.path = path;
    if (backbone) body.backbone = backbone;
    if (prompt) body.prompt = prompt;
    let j;
    try {
      const r = await fetch("/api/pid-upscale", {
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
      if (window.showToast) window.showToast("❌ " + (j.error || "PiD impossible."));
      return false;
    }
    window.__lisAwaitToken = j.task_token || null;
    if (j.queued) {
      if (window.showToast) {
        window.showToast(`⏳ PiD ajouté à la file d'attente (position #${j.position}).`);
      }
    } else if (window.showToast) {
      window.showToast("⬆️ PiD ×4 en cours (sortie 4096×4096, 4 étapes, reconstruction conditionnée par le prompt confirmé)…");
    }
    ensurePolling();
    return true;
  };

  // Heuristique miroir de registry.prompt_looks_like_edit_instruction (JS)
  const PID_EDIT_MARKERS = ["<image", "{img", "image 1", "image 2", "image1", "image2",
    "keep the subject", "keep the face", "keep his", "keep her", "keep the pose",
    "keep the composition", "keep the identity", "garder le sujet", "garde le sujet",
    "garde le visage", "préserve le", "preserve the", "redraw", "redessine", "re-render",
    "replace the", "remplace le", "remplace la", "change the", "modifie le", "modifie la",
    "modifie les", "inpaint", "outpaint", "extend the frame", "étendre le cadre",
    "post-traitement", "post-processing", "postprocess", "post-process"];
  const looksLikeEditPrompt = txt =>
    PID_EDIT_MARKERS.some(mk => String(txt || "").toLowerCase().includes(mk));

  // Modale « ⬆️ PiD ×4 — prompt de reconstruction » (template _pid_prompt.html)
  // Retourne une Promise<boolean> : true si PiD a été lancé (boutons « Lancer » ou « Description générique »).
  Q.askPidPrompt = function ({ imageId = null, path = null, backbone = null } = {}) {
    Q._pendingPidImageId = imageId != null ? imageId : null;  // utilisé par « 🧠 Décrire l'image »
    return new Promise(async resolve => {
      const modal = document.getElementById("pid-prompt-modal");
      const ta = document.getElementById("pid-prompt-text");
      const warn = document.getElementById("pid-prompt-warn");
      if (!modal || !ta) { // repli : comportement historique côté serveur
        const ok = await Q.startPid({ imageId, path, backbone });
        resolve(ok);
        return;
      }
      ta.value = "";
      warn.hidden = true;
      if (imageId != null) {
        try {
          const r = await fetch(`/api/image/${imageId}`);
          const j = await r.json();
          if (j.ok && j.image && j.image.prompt) ta.value = j.image.prompt;
        } catch (e) { /* réseau : on part sur champ vide = description générique */ }
      }
      if (ta.value.trim()) warn.hidden = !looksLikeEditPrompt(ta.value);
      ta.addEventListener("input", () => { warn.hidden = !looksLikeEditPrompt(ta.value); });
      document.body.style.overflow = "hidden";
      modal.hidden = false;
      const close = () => { modal.hidden = true; document.body.style.overflow = ""; Q._pendingPidImageId = null; };
      const finish = async useGeneric => {
        close();
        const prompt = useGeneric ? null : (ta.value.trim() || null);
        const ok = await Q.startPid({ imageId, path, backbone, prompt });
        resolve(ok);
      };
      document.getElementById("pid-prompt-launch").onclick = () => finish(false);
      document.getElementById("pid-prompt-generic").onclick = () => finish(true);
      modal.querySelectorAll("[data-pidprompt-close]").forEach(el => {
        el.onclick = () => { close(); resolve(false); };
      });
      const esc = e => { if (e.key === "Escape") { document.removeEventListener("keydown", esc); close(); resolve(false); } };
      document.addEventListener("keydown", esc);
      ta.focus();
    });
  };

  Q.makePidButton = function ({ imageId = null, path = null, backbone = null } = {}) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small pid-mini";
    btn.textContent = "⬆️ PiD ×4";
    btn.title =
      "Super-résolution générative PiD (NVIDIA Pixel Diffusion) : l'image est ré-encodée avec le VAE " +
      "du backbone puis décodée en 4096×4096 en 4 étapes. Elle est conditionnée par un prompt que " +
      "vous confirmez (et pouvez modifier) juste avant le lancement — évitez les instructions " +
      "d'édition, PiD reconstruit à partir de ce texte. Backbone choisi automatiquement selon la " +
      "famille du modèle source (FLUX.1 / FLUX.2 / Qwen-Image). Licence NSCLv1 (non-commerciale).";
    btn.addEventListener("click", async () => {
      const prev = btn.textContent;
      btn.disabled = true;
      btn.textContent = "⬆️ pid…";
      Q._doneCbs.push(() => {
        btn.disabled = false;
        btn.textContent = "⬆️ PiD ×4";
      });
      const ok = await Q.askPidPrompt({ imageId, path, backbone });
      if (!ok) {
        Q._doneCbs.pop();
        btn.disabled = false;
        btn.textContent = prev;
      }
    });
    return btn;
  };

  // ------------------------------------------------------------------ //
  //  🔀 Variation façon Midjourney (POST /api/vary) : img2img + nouvelle graine
  // ------------------------------------------------------------------ //
  Q.startVary = async function ({ imageId = null, mode = "subtle" } = {}) {
    const body = { mode: mode === "strong" ? "strong" : "subtle" };
    if (imageId != null) body.image_id = imageId;
    let j;
    try {
      const r = await fetch("/api/vary", {
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
      if (window.showToast) window.showToast("❌ " + (j.error || "Variation impossible."));
      return false;
    }
    window.__lisAwaitToken = j.task_token || null;
    if (j.queued) {
      if (window.showToast) window.showToast(`⏳ Variation ajoutée à la file d'attente (position #${j.position}).`);
    } else if (window.showToast) {
      window.showToast(mode === "strong"
        ? "🔀 Variation forte en cours (img2img, force 0,75)…"
        : "🔀 Variation subtile en cours (img2img, force 0,35)…");
    }
    ensurePolling();
    return true;
  };

  // Fabrique les deux boutons « Varier · subtil / · fort » pour une carte image.
  Q.makeVaryButtons = function ({ imageId = null } = {}) {
    const frag = document.createDocumentFragment();
    const mk = (mode, text, title) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn small vary-mini vary-" + mode;
      btn.textContent = text;
      btn.title = title;
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "🔀 …";
        Q._doneCbs.push(() => {
          btn.disabled = false;
          btn.textContent = text;
        });
        const ok = await Q.startVary({ imageId, mode });
        if (!ok) {
          Q._doneCbs.pop();
          btn.disabled = false;
          btn.textContent = text;
        }
      });
      return btn;
    };
    frag.appendChild(mk(
      "subtle",
      "🔀 Varier · subtil",
      "Re-génère cette image avec une variation légère (img2img, force 0,35, nouvelle graine). " +
      "Nécessite un modèle img2img (SD 3.5, FLUX.1 Dev, Chroma). La variante est enregistrée dans l'historique."
    ));
    frag.appendChild(mk(
      "strong",
      "🔀 Varier · fort",
      "Re-génère cette image avec une variation franche (img2img, force 0,75, nouvelle graine). " +
      "Nécessite un modèle img2img (SD 3.5, FLUX.1 Dev, Chroma). La variante est enregistrée dans l'historique."
    ));
    return frag;
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

  // Réactive les boutons et prévient la page que l'op est terminée.
  Q._done = function (images, kind) {
    const cbs = Q._doneCbs;
    Q._doneCbs = [];
    cbs.forEach(cb => { try { cb(); } catch (e) {} });
    if (typeof window.__lisOnUpscaleDone === "function") {
      try { window.__lisOnUpscaleDone(images || []); } catch (e) {}
    }
    if (images && images.length && window.showToast) {
      if (kind === "repair") {
        window.showToast("🙂 Visages & mains réparés ✓ — enregistré dans l'historique.");
      } else if (kind === "restore_x2") {
        window.showToast("🩹 Restauration ×2 terminée ✓ — enregistré dans l'historique.");
      } else if (kind === "pid") {
        window.showToast("⬆️ PiD ×4 terminée ✓ — enregistré dans l'historique.");
      } else if (kind === "vary") {
        window.showToast("🔀 Variation terminée ✓ — enregistrée dans l'historique.");
      } else {
        const sc = images[0].scale || 4;
        const w = images[0].width ? ` (${images[0].width}×${images[0].height || "?"})` : "";
        window.showToast(`🔍 Agrandissement ×${sc} terminé ✓ — enregistré dans l'historique.`);
      }
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
        const expected = window.__lisAwaitToken || null;
        if (expected && j.task_token && j.task_token !== expected) return; // une autre tâche a fini entre-temps
        clearInterval(Q._poll);
        Q._poll = null;
        window.__lisAwaitToken = null;
        const type = j.result && j.result.type;
        if (j.result && ["upscale", "repair", "restore_x2", "pid"].includes(type)) {
          if (j.result.error || !(j.result.images || []).length) {
            if (window.showToast && j.result.error) {
              window.showToast("❌ " + String(j.result.error).split("\n")[0].slice(0, 160));
            }
            Q._done([], type);
            return;
          }
          if (j.result.images.length && !j.result.cancelled) {
            Q._done(j.result.images, type);
          } else {
            Q._done([], type);
          }
        } else {
          Q._done([], type);
        }
      } catch (e) { /* on réessaie au prochain cycle */ }
    }, 1200);
  }
})();
