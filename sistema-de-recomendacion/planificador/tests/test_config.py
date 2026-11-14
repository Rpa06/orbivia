"""Configuración: valores por defecto, fichero, entorno y versión."""

import pytest

from crew_planner.config import DEFAULT_FILE, PlannerConfig, load_config
from crew_planner.model import ValidationError


def test_default_file_matches_dataclass_defaults(config):
    # El fichero por defecto y los valores del código no deben divergir
    defaults = PlannerConfig()
    for section in ("weights", "stages", "importance", "repetition", "adequacy",
                    "workload", "limits", "low_load", "solver", "alternatives"):
        assert getattr(config, section) == getattr(defaults, section), section
    assert "sleep_duration_h" in config.parameters
    assert config.parameters["pvt_lapses"].normalization == "baseline_z"


def test_env_overrides_file():
    config = load_config(env={"CP_WEIGHTS_ALPHA_EQUITY": "0.9", "CP_STAGES_MODE": "weighted", "CP_SOLVER_SEED": "7"})
    assert config.weights.alpha_equity == 0.9
    assert config.stages.mode == "weighted"
    assert config.solver.seed == 7


def test_invalid_values_are_rejected():
    with pytest.raises(ValidationError, match="numérico"):
        load_config(env={"CP_WEIGHTS_ALPHA_EQUITY": "mucho"})
    with pytest.raises(ValidationError, match=">= 0"):
        load_config(env={"CP_WEIGHTS_BETA_SPREAD": "-1"})
    with pytest.raises(ValidationError, match="entero"):
        load_config(env={"CP_SOLVER_WORKERS": "1.5"})
    with pytest.raises(ValidationError, match="mode"):
        load_config(env={"CP_STAGES_MODE": "social"})


def test_unknown_keys_in_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[weights]\ngama = 1.0\n")
    with pytest.raises(ValidationError, match="desconocidas"):
        load_config(path, env={})
    path.write_text("[pesos]\n")
    with pytest.raises(ValidationError, match="Secciones"):
        load_config(path, env={})


def test_partial_file_keeps_defaults(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[weights]\nalpha_equity = 0.0\n")
    config = load_config(path, env={})
    assert config.weights.alpha_equity == 0.0
    assert config.weights.beta_spread == PlannerConfig().weights.beta_spread
    assert config.parameters == {}


def test_config_file_from_env(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(DEFAULT_FILE.read_text().replace("alpha_equity = 0.5", "alpha_equity = 0.4"))
    assert load_config(env={"CP_CONFIG_FILE": str(path)}).weights.alpha_equity == 0.4


def test_version_changes_with_weights(config):
    assert config.version == load_config(env={}).version
    assert config.version != load_config(env={"CP_WEIGHTS_ALPHA_EQUITY": "0.51"}).version


def test_importance_normalization(config):
    assert config.importance.normalize(5) == 1.0
    assert config.importance.normalize(1) == pytest.approx(0.2)
    with pytest.raises(ValidationError):
        config.importance.normalize(6)


def test_social_weights_and_section_do_not_exist(tmp_path):
    path = tmp_path / "c.toml"
    for text in ("[weights]\ngamma = 0.3\n", "[weights]\nmu = 0.2\n"):
        path.write_text(text)
        with pytest.raises(ValidationError, match="desconocidas"):
            load_config(path, env={})
    path.write_text("[social]\nmax_age_days = 2\n")
    with pytest.raises(ValidationError, match="Secciones"):
        load_config(path, env={})
