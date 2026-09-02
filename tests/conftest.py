from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from learningloop.config import Settings
from learningloop.db import Database


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        enable_real_models=False,
        vibe_flash_key=SecretStr("vibe-flash-test-key"),
        vibe_pro_key=SecretStr("vibe-pro-test-key"),
        kcne_flash_key=SecretStr("kcne-flash-test-key"),
        kcne_pro_key=SecretStr("kcne-pro-test-key"),
    )


@pytest.fixture()
def db(settings: Settings) -> Database:
    settings.prepare_directories()
    return Database(settings.database_path)
