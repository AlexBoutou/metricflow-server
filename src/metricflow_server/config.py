from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_key: str
    admin_key: str
    # File-based profiles dir (local dev / Docker mount)
    dbt_profiles_dir: Path = Path("/app/.dbt")
    # Base64-encoded profiles.yml content (CI/CD)
    profiles_b64: Optional[str] = None
    # Profile name to use from profiles.yml
    dbt_profile_name: str = "metricflow_server"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"

    model_config = {
        "env_prefix": "MF_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def resolve_profiles_dir(self) -> Path:
        """Return the profiles directory to use.

        If MF_PROFILES_B64 is set, decode it and write profiles.yml to a
        temporary directory tracked by this instance (cleaned up via
        cleanup_profiles_dir). Otherwise fall back to MF_DBT_PROFILES_DIR.
        """
        if not self.profiles_b64:
            return self.dbt_profiles_dir

        content = base64.b64decode(self.profiles_b64).decode()
        # Keep a reference so the directory persists until cleanup is called.
        self._profiles_tmpdir: tempfile.TemporaryDirectory = (
            tempfile.TemporaryDirectory(prefix="mfserver_profiles_")
        )
        tmpdir = Path(self._profiles_tmpdir.name)
        (tmpdir / "profiles.yml").write_text(content)
        return tmpdir

    def cleanup_profiles_dir(self) -> None:
        """Delete the temporary profiles directory created by resolve_profiles_dir, if any."""
        tmpdir = getattr(self, "_profiles_tmpdir", None)
        if tmpdir is not None:
            tmpdir.cleanup()
            del self._profiles_tmpdir


settings = Settings()
