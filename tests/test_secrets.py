from pathlib import Path

from learningloop.config import Settings


def test_env_secrets_do_not_appear_in_project_files() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings(_env_file=root / ".env")
    secrets = [
        secret.get_secret_value()
        for provider in settings.providers.values()
        for secret in (provider.flash_key, provider.pro_key)
        if secret is not None
    ]
    for path in root.rglob("*"):
        if not path.is_file() or path.name == ".env" or ".git" in path.parts:
            continue
        if any(part in {"data", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for secret in secrets:
            assert secret not in text, f"secret leaked into {path}"
