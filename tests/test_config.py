from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantverify.core.config import ConfigError, load_experiment_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(TestCase):
    def test_loads_versioned_example(self) -> None:
        config = load_experiment_config(ROOT / "configs/experiments/sma_fixture.yaml")
        self.assertEqual(config.strategy.strategy_id, "ma_cross")
        self.assertTrue(config.experiment_id.startswith("exp_"))

    def test_rejects_unknown_schema_version(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.yaml"
            path.write_text("schema_version: 999\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Unsupported experiment schema_version"):
                load_experiment_config(path)

    def test_rejects_unknown_fields(self) -> None:
        source = (ROOT / "configs/experiments/sma_fixture.yaml").read_text(encoding="utf-8")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.yaml"
            path.write_text(f"{source}\nunknown_field: true\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "unknown_field"):
                load_experiment_config(path)
