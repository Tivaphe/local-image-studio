/* ===== Local Image Studio — 🔎 Image → Prompt & 🧠 Décrire l'image =====
 * Légende locale de l'image par un VLM (llama.cpp officiel + modèle au choix).
 * Rien n'est envoyé ailleurs qu'à votre propre machine.
 */
(function () {
  "use strict";

  const L = {};
  let captionState = null;   // { imageId } quand ouvert depuis PiD — sinon null (outil libre)
  const state = {
    file: null,            // File choisi dans l'outil
    target: null,          // fonction d'insertion (par défaut : #prompt de la page)
    busy: false,
    modelsLoaded: false,
    ready: false,
  };

  const $ = id => document.getElementById(id);
  const modal = () => $("caption-modal");

  // ---------- chargement des légendeurs (partage entre modales) ----------
  async function fetchCaptioners() {
    try {
      const r = await fetch("/api/captioners");
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function fillModelSelect(sel) {
    const pidBtn = document.getElementById("pid-caption-btn");
    if (!sel) return false;
    const data = await fetchCaptioners();
    sel.innerHTML = "";
    if (!data) {
      const o = document.createElement("option");
      o.textContent = "serveur injoignable";
      sel.appendChild(o);
      return false;
    }
    const ready = (data.captioners || []).filter(c => c.ready);
    if (!ready.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "aucun légendeur installé — voir Modèles → « 🧠 Légendeurs »";
      sel.appendChild(o);
      sel.disabled = true;
      if (pidBtn) { pidBtn.disabled = true; pidBtn.title = "Installez un légendeur d'image (Modèles → « 🧠 Légendeurs d'image ») pour activer la description automatique."; }
      return false;
    }
    sel.disabled = false;
    if (pidBtn) pidBtn.disabled = false;
    for (const c of ready) {
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = c.name + (c.recommended ? " ⭐" : "") + (c.license_warn ? " ⚠️ licence custom" : "");
      sel.appendChild(o);
    }
    if (data.selected && ready.some(c => c.id === data.selected)) sel.value = data.selected;
    return true;
  }

  // ---------- outil libre 🔎 Image → Prompt ----------
  function openModal(targetSetter) {
    state.target = typeof targetSetter === "function" ? targetSetter : defaultTarget;
    state.file = null;
    setStatus("");
    const drop = $("caption-drop");
    const prev = $("caption-preview");
    const label = $("caption-drop-label");
    prev.hidden = true; prev.removeAttribute("src");
    label.hidden = false;
    $("caption-result").value = "";
    const m = modal();
    if (!m) return;
    document.body.style.overflow = "hidden";
    m.hidden = false;
    fillModelSelect($("caption-model")).then(ready => {
      state.ready = ready;
      $("caption-generate").disabled = !ready;
      if (!ready) setStatus("Un légendeur doit être installé (Modèles → « 🧠 Légendeurs d'image »).", true);
    });
  }

  function closeModal() {
    const m = modal();
    if (m) { m.hidden = true; }
    document.body.style.overflow = "";
  }

  function defaultTarget(text) {
    const p = document.querySelector("#prompt");
    if (p) { p.value = text; p.dispatchEvent(new Event("input", { bubbles: true })); }
  }

  function setStatus(msg, isError) {
    const el = $("caption-status");
    if (el) {
      el.textContent = msg || "";
      el.classList.toggle("caption-status-error", !!isError);
    }
  }

  function updateGenerateBtn() {
    $("caption-generate").disabled = !(state.file && state.ready && !state.busy);
  }

  function acceptFile(file) {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
      setStatus("Format non supporté (PNG, JPEG, WebP ou GIF).", true);
      return;
    }
    if (file.size > 12 * 1024 * 1024) { setStatus("Image trop lourde (12 Mo max).", true); return; }
    state.file = file;
    const prev = $("caption-preview");
    prev.src = URL.createObjectURL(file);
    prev.hidden = false;
    $("caption-drop-label").hidden = true;
    setStatus("Image prête — cliquez « 🧠 Générer le prompt ».");
    updateGenerateBtn();
  }

  async function captionUpload() {
    if (!state.file || state.busy) return;
    state.busy = true; updateGenerateBtn();
    $("caption-generate").textContent = "🧠 légende en cours…";
    setStatus("Un VLM local analyse l'image…");
    try {
      const fd = new FormData();
      fd.append("image", state.file);
      const sel = $("caption-model");
      if (sel && sel.value) fd.append("captioner", sel.value);
      const r = await fetch("/api/caption-upload", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok || !j.ok) { setStatus("Erreur : " + (j.error || r.status), true); return; }
      $("caption-result").value = j.caption || "";
      setStatus("Prompt généré par " + (j.name || "le VLM") + " ✓ — relisez-le, corrigez, puis « Utiliser ce prompt ».");
    } catch (e) {
      setStatus("Connexion au serveur impossible : " + e.message, true);
    } finally {
      state.busy = false;
      $("caption-generate").textContent = "🧠 Générer le prompt";
      updateGenerateBtn();
    }
  }

  // ---------- PiD : légender une image de l'historique ----------
  async function pidDescribe(imageId) {
    const btn = $("pid-caption-btn");
    const ta = $("pid-prompt-text");
    const sel = $("pid-captioner");
    if (!btn || !ta) return;
    if (btn.disabled) return;
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = "🧠 description…";
    try {
      const body = { image_id: imageId };
      if (sel && sel.value) body.captioner = sel.value;
      const r = await fetch("/api/caption", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok || !j.ok) {
        window.showToast ? window.showToast("⚠️ " + (j.error || "description impossible")) : alert(j.error || "description impossible");
        return;
      }
      ta.value = j.caption || "";
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      window.showToast && window.showToast("Prompt rédigé par " + (j.name || "le VLM") + " ✓ — relisez-le avant de lancer PiD.");
    } catch (e) {
      window.showToast ? window.showToast("⚠️ " + e.message) : alert(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }

  // ---------- init (délégation, sûr quel que soit l'ordre de chargement) ----------
  function init() {
    // outil libre : boutons sur Générer / Édition
    for (const id of ["imagetoprompt-btn"]) {
      const b = $(id);
      if (b) b.addEventListener("click", () => openModal());
    }
    // modale globale
    const m = modal();
    if (m) {
      m.querySelectorAll("[data-caption-close]").forEach(el => el.addEventListener("click", closeModal));
      document.addEventListener("keydown", e => { if (e.key === "Escape" && !m.hidden) closeModal(); });
      const drop = $("caption-drop");
      const fileInput = $("caption-file");
      drop.addEventListener("click", () => fileInput.click());
      drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
      drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("caption-drop-over"); });
      drop.addEventListener("dragleave", () => drop.classList.remove("caption-drop-over"));
      drop.addEventListener("drop", e => {
        e.preventDefault(); drop.classList.remove("caption-drop-over");
        acceptFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
      });
      fileInput.addEventListener("change", () => acceptFile(fileInput.files && fileInput.files[0]));
      $("caption-generate").addEventListener("click", captionUpload);
      $("caption-use").addEventListener("click", () => {
        const text = ($("caption-result").value || "").trim();
        if (!text) { setStatus("Rien à insérer — générez d'abord un prompt.", true); return; }
        (state.target || defaultTarget)(text);
        window.showToast && window.showToast("Prompt inséré ✓");
        closeModal();
      });
      $("caption-copy").addEventListener("click", async () => {
        const text = ($("caption-result").value || "").trim();
        if (!text) return;
        try { await navigator.clipboard.writeText(text); window.showToast && window.showToast("Prompt copié ✓"); }
        catch (e) { /* clipboard indisponible */ }
      });
    }
    // PiD : pré-charger le sélecteur de légendeurs (modale déjà incluse)
    const sel = $("pid-captioner");
    if (sel) fillModelSelect(sel);
    document.addEventListener("click", e => {
      const btn = e.target && e.target.closest ? e.target.closest("#pid-caption-btn") : null;
      if (!btn) return;
      let imageId = null;
      try { imageId = window.LisQuality && window.LisQuality._pendingPidImageId; } catch (_e) {}
      if (imageId == null) imageId = btn.getAttribute("data-image-id") || null;
      if (imageId == null) {
        window.showToast ? window.showToast("⚠️ Image source inconnue") : null;
        return;
      }
      pidDescribe(parseInt(imageId, 10));
    });
  }

  window.LisCaption = {
    open: openModal,
    close: closeModal,
    fillModelSelect,
    captionImage: pidDescribe,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
