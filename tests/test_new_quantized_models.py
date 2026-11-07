# -*- coding: utf-8 -*-
"""Tests des modèles GGUF ajoutés : Fibo 2.0 (Dev / Edit Turbo), MOSS-Image (Base / SFT), Krea 2 Turbo."""
import unittest
from pathlib import Path
from unittest.mock import patch

import registry
from registry import (MODELS, DEPS, build_command, resolve_dep_gguf,
                      _is_valid_dep, supports_outpainting, build_outpaint_prompt,
                      outpaint_prompt_presets, edit_prompt_presets, gen_prompt_presets)

NEW_MODELS = ["fibo2-dev", "fibo2-edit-turbo", "moss-image-sft", "moss-image-base", "krea2-turbo"]
OUTPAINT_MODELS = [
    "qwen-image-2.1", "qwen-image-2.1-turbo",
    "flux2-klein-4b", "flux2-klein-9b", "flux3-image-klein",
    "fibo2-dev", "fibo2-edit-turbo",
]

# Listings réels des dépôts Hugging Face (noms de fichiers uniquement).
REPO_FILES = {
    "unsloth/Qwen3.5-9B-GGUF": [
        "Qwen3.5-9B-BF16.gguf", "Qwen3.5-9B-Q4_K_M.gguf", "Qwen3.5-9B-Q8_0.gguf",
        "Qwen3.5-9B-UD-Q4_K_XL.gguf", "mmproj-BF16.gguf", "mmproj-F16.gguf", "README.md",
    ],
    "Qwen/Qwen3-VL-4B-Instruct-GGUF": [
        "Qwen3VL-4B-Instruct-F16.gguf", "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "Qwen3VL-4B-Instruct-Q8_0.gguf", "mmproj-Qwen3VL-4B-Instruct-F16.gguf",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
    ],
}


class RegistryEntriesTests(unittest.TestCase):
    def test_all_new_models_are_registered_with_their_files(self):
        for mid in NEW_MODELS:
            with self.subTest(model=mid):
                m = MODELS[mid]
                self.assertTrue(m["quants"])
                self.assertEqual(set(m["quants"]), set(m["file_for_quant"]))
                self.assertEqual(set(m["quants"]), set(m["size_gb"]))
                self.assertIn(m["default_quant"], m["quants"])
                for dep in m["deps"]:
                    self.assertIn(dep, DEPS, f"dépendance inconnue : {dep}")
                for preset in m.get("presets", {}).values():
                    self.assertIn(preset["quant"], m["quants"])

    def test_remote_names_match_local_names_after_flattening(self):
        m = MODELS["krea2-turbo"]
        for q, local in m["file_for_quant"].items():
            self.assertTrue(m["remote_file_for_quant"][q].endswith(local))

    def test_mmproj_4b_and_8b_do_not_collide(self):
        p4 = Path("mmproj-Qwen3VL-4B-Instruct-F16.gguf")
        p8 = Path("mmproj-Qwen3VL-8B-Instruct-F16.gguf")
        self.assertTrue(_is_valid_dep("mmproj_qwen3vl_4b", p4))
        self.assertFalse(_is_valid_dep("mmproj_qwen3vl_8b", p4))
        self.assertTrue(_is_valid_dep("mmproj_qwen3vl_8b", p8))
        self.assertFalse(_is_valid_dep("mmproj_qwen3vl_4b", p8))

    def test_qwen35_resolution_prefers_q4_km_and_skips_mmproj(self):
        picked = resolve_dep_gguf("qwen35_9b", REPO_FILES["unsloth/Qwen3.5-9B-GGUF"])
        self.assertEqual(picked, "Qwen3.5-9B-Q4_K_M.gguf")

    def test_qwen3vl_4b_still_resolves_to_the_llm_not_the_mmproj(self):
        picked = resolve_dep_gguf("qwen3vl_4b", REPO_FILES["Qwen/Qwen3-VL-4B-Instruct-GGUF"])
        self.assertEqual(picked, "Qwen3VL-4B-Instruct-Q4_K_M.gguf")

    def test_outpainting_support_and_prompt_builder(self):
        for mid in OUTPAINT_MODELS:
            self.assertTrue(supports_outpainting(mid), f"{mid} devrait supporter l'outpainting")
        self.assertFalse(supports_outpainting("flux-schnell"))
        self.assertFalse(supports_outpainting("z-image"))
        self.assertFalse(supports_outpainting("krea2-turbo"))

        qwen_prompt = build_outpaint_prompt("qwen-image-2.1", "a sunny beach", ["left", "right"])
        self.assertIn("<image1>", qwen_prompt)
        self.assertIn("left, right borders", qwen_prompt)
        self.assertTrue(qwen_prompt.endswith("a sunny beach"))

        fibo_prompt = build_outpaint_prompt("fibo2-dev", "", ["top"])
        self.assertIn("<image_1>", fibo_prompt)
        self.assertIn("top border", fibo_prompt)

        klein_prompt = build_outpaint_prompt("flux3-image-klein", "mountain horizon")
        self.assertIn("image 1", klein_prompt)
        self.assertNotIn("<image", klein_prompt)

    def test_model_adapted_preprompts(self):
        # Les pré-prompts d'édition et d'outpainting respectent la syntaxe propre à chaque modèle
        qwen_edit = edit_prompt_presets("qwen-image-2.1")
        self.assertTrue(len(qwen_edit) >= 8)
        self.assertTrue(all("<image1>" in p["prompt"] for p in qwen_edit))

        fibo_edit = edit_prompt_presets("fibo2-dev")
        self.assertTrue(len(fibo_edit) >= 8)
        self.assertTrue(all("<image_1>" in p["prompt"] for p in fibo_edit))

        klein_edit = edit_prompt_presets("flux3-image-klein")
        self.assertTrue(len(klein_edit) >= 8)
        self.assertTrue(all("image 1" in p["prompt"] and "<image" not in p["prompt"] for p in klein_edit))

        # Tous les modèles du registre disposent de pré-prompts de génération
        for mid in MODELS:
            gen_presets = gen_prompt_presets(mid)
            self.assertTrue(len(gen_presets) >= 5, f"{mid} devrait avoir des pré-prompts de génération")


class BuildCommandTests(unittest.TestCase):
    """Vérifie les arguments sd-cli produits pour chaque nouveau modèle, sans rien télécharger."""

    def _cmd(self, model_id, quant=None, ref_images=None, manifest=None):
        m = MODELS[model_id]
        quant = quant or m["default_quant"]
        # Chemins factices pour toutes les dépendances : on teste uniquement la construction.
        fake = {d: f"/fake/{d}.file" for d in DEPS}
        manifest = manifest if manifest is not None else {d: {"path": fake[d]} for d in DEPS}
        with patch.object(registry, "_dep_path", lambda mf, d: mf.get(d, {}).get("path")):
            return build_command(model_id, quant, "a prompt", "bad", 1024, 1024,
                                 m["defaults"]["steps"], m["defaults"]["cfg"], 42, 1,
                                 "out.png", "sd-cli", manifest,
                                 ref_images=ref_images,
                                 input_mode="ref" if ref_images else None)

    @staticmethod
    def _val(args, flag):
        return args[args.index(flag) + 1] if flag in args else None

    def test_fibo_dev_text_to_image_uses_vl_projector(self):
        args = self._cmd("fibo2-dev")
        self.assertEqual(self._val(args, "--diffusion-model"), str(registry.DIFFUSION_DIR / "fibo2-dev-Q6_K.gguf"))
        self.assertEqual(self._val(args, "--llm"), "/fake/qwen3vl_4b.file")
        self.assertEqual(self._val(args, "--llm_vision"), "/fake/mmproj_qwen3vl_4b.file")
        self.assertEqual(self._val(args, "--vae"), "/fake/vae_flux2.file")
        self.assertEqual(self._val(args, "--cfg-scale"), "5.0")
        self.assertIn("-n", args)  # négatif supporté

    def test_fibo_edit_turbo_fixed_four_steps_and_refs(self):
        args = self._cmd("fibo2-edit-turbo", ref_images=["a.png", "b.png"])
        self.assertEqual(self._val(args, "--steps"), "4")
        self.assertEqual(self._val(args, "--cfg-scale"), "1.0")
        self.assertEqual(args.count("-r"), 2)
        self.assertNotIn("-n", args)  # pas de négatif en Turbo
        self.assertEqual(self._val(args, "--llm_vision"), "/fake/mmproj_qwen3vl_4b.file")

    def test_moss_passes_external_tokenizer_and_qwen35(self):
        for mid in ("moss-image-sft", "moss-image-base"):
            with self.subTest(model=mid):
                args = self._cmd(mid)
                self.assertEqual(self._val(args, "--llm"), "/fake/qwen35_9b.file")
                self.assertEqual(self._val(args, "--tokenizer"), "/fake/moss_tokenizer.file")
                self.assertEqual(self._val(args, "--vae"), "/fake/vae_flux2.file")
                self.assertNotIn("--llm_vision", args)

    def test_krea_uses_wan_vae_and_qwen3vl_without_negative(self):
        args = self._cmd("krea2-turbo")
        self.assertEqual(self._val(args, "--vae"), "/fake/vae_wan21.file")
        self.assertEqual(self._val(args, "--llm"), "/fake/qwen3vl_4b.file")
        self.assertNotIn("--llm_vision", args)
        self.assertNotIn("-n", args)
        self.assertEqual(self._val(args, "--steps"), "8")


if __name__ == "__main__":
    unittest.main()
