"""Connection settings for a local SynapCores instance.

Credentials and options are read from the environment, never hard-coded, so
nothing sensitive lands in version control:

    SYNAPCORES_URL         base URL (default http://localhost:8090)
    SYNAPCORES_TOKEN       a pre-minted API key or JWT (wins if present)
    SYNAPCORES_USERNAME    admin username (default "admin")
    SYNAPCORES_PASSWORD    admin password
    SYNAPCORES_EMBED_MODEL pin the embedding model (optional, for reproducibility)
    SYNAPCORES_LLM_MODEL   pin the entity/LLM model (optional)

The SynapCores first-boot log prints an admin password and an API key once. Put
one of them in the environment (or a local .env you do not commit) before using
this package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_URL = "http://localhost:8090"


@dataclass
class Settings:
    """Resolved connection settings."""

    url: str = DEFAULT_URL
    token: str | None = None
    username: str = "admin"
    password: str | None = None
    embed_model: str | None = None
    llm_model: str | None = None

    @classmethod
    def from_env(cls, environ: dict | None = None) -> Settings:
        env = environ if environ is not None else os.environ
        return cls(
            url=env.get("SYNAPCORES_URL", DEFAULT_URL).rstrip("/"),
            token=env.get("SYNAPCORES_TOKEN") or None,
            username=env.get("SYNAPCORES_USERNAME", "admin"),
            password=env.get("SYNAPCORES_PASSWORD") or None,
            embed_model=env.get("SYNAPCORES_EMBED_MODEL") or None,
            llm_model=env.get("SYNAPCORES_LLM_MODEL") or None,
        )

    def has_credentials(self) -> bool:
        return bool(self.token or self.password)
