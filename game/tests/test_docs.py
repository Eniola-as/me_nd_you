from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .utils import load_settings

ROOT = Path(settings.BASE_DIR)


def read_env_example():
    pairs = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


class SetupDocsTests(SimpleTestCase):
    def test_env_example_values_produce_working_settings(self):
        env = read_env_example()
        self.assertIn("SECRET_KEY", env)
        values = load_settings(env, ["DEBUG", "ALLOWED_HOSTS"])
        self.assertTrue(values["DEBUG"])
        self.assertIn("127.0.0.1", values["ALLOWED_HOSTS"])

    def test_readme_explains_env_setup_for_both_shells(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(".env.example", readme)
        self.assertIn(".venv\\Scripts\\Activate.ps1", readme)
        self.assertIn("source .venv/bin/activate", readme)

    def test_readme_license_matches_license_file(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        self.assertNotIn("License-Unlicensed", readme)
