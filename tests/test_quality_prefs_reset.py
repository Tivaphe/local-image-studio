"""Le panneau Qualité doit repart à options avancées OFF à chaque actualisation.

Régression : les valeurs persistées dans localStorage (lis_quality_prefs_v1) étaient
restaurées au chargement — UltraSharp et SageAttention se réactivaient tout seuls.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QJS = (ROOT / "src/static/quality.js").read_text(encoding="utf-8")


class QualityPrefsResetTests(unittest.TestCase):
    def test_advanced_options_are_not_restored_from_prefs(self):
        for frag in (
            'setVal("q-upscale-model"',   # UltraSharp réapparaîtrait
            'setVal("q-ad-model"',
            '$("#q-sage-attn").checked = !!prefs',
            '$("#q-taesd").checked = !!prefs',
            '$("#q-hires-on").checked = !!prefs',
            '$("#q-vae-tiling").checked = !!prefs',
            '$("#q-slg").value = prefs',
            'setVal("q-pulid-id"',        # empreinte PuLID réapparaîtrait
            'preview_interval ?? 3',      # l'intervalle ne doit pas être restauré non plus
        ):
            self.assertNotIn(frag, QJS, f"fragment interdit (restauration auto) : {frag}")

    def test_only_presentation_prefs_are_persisted(self):
        self.assertIn("function collectPersisted()", QJS)
        self.assertIn("function purgeStalePersistedPrefs()", QJS)
        self.assertNotIn("savePrefs(Q.collect())", QJS)  # plus de sauvegarde en vrac

    def test_preview_defaults_to_off_on_reload(self):
        self.assertIn('const savedPreview = "none";', QJS)

    def test_generate_and_edit_still_send_expanded_payload(self):
        # Q.collect() reste la source des paramètres à l'envoi (il opère sur le DOM courant).
        self.assertIn("Q.collect = function ()", QJS)
        self.assertIn('if ($("#q-sage-attn")?.checked) out.sage_attn = true;', QJS)
        self.assertIn('if (up) out.upscale_id = up;', QJS)


if __name__ == "__main__":
    unittest.main()
