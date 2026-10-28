"""Configuração central do LexScan.

Todos os valores vêm de variáveis de ambiente (arquivo .env opcional),
para que dev local e Docker Compose rodem o mesmo código.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Caminhos conhecidos do Tesseract no Windows (instalador UB-Mannheim).
_WINDOWS_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

# LibreOffice (instalador oficial) e Ghostscript (instalador Artifex).
_WINDOWS_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
_WINDOWS_GS_PATTERNS = (
    r"gs\gs*",
    r"Ghostscript\gs*",
    r"ghostscript*",
)


class Settings(BaseSettings):
    """Configuração lida do ambiente (.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicação ---
    app_name: str = "LexScan"
    environment: str = "dev"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    # --- Banco ---
    database_url: str = "sqlite:///./lexscan.db"

    # --- Armazenamento ---
    storage_root: Path = Path("./storage")
    storage_secret: str = "dev-only-secret-key-troque-em-producao"
    storage_backend: str = "disk"  # disk | s3 (futuro)

    # --- Fila de tarefas ---
    task_backend: str = "local"  # local | celery
    celery_broker_url: str = "redis://localhost:6379/0"
    worker_concurrency: int = 2

    # --- LGPD ---
    retention_hours: int = 24
    max_upload_mb: int = 100

    # --- OCR ---
    tesseract_cmd: str = ""
    tesseract_langs: str = "por+eng"
    tessdata_prefix: str = ""
    ocr_dpi: int = 300

    # --- Conversão Word (Fase 2) ---
    soffice_cmd: str = ""

    # --- Compressão / PDF-A (Fase 2, Ghostscript) ---
    ghostscript_cmd: str = ""

    # --- Segurança ---
    secret_key: str = "dev-only-jwt-secret-troque-em-producao"
    rate_limit_per_min: int = 60
    clamav_enabled: bool = False
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310

    # --- Autenticação (Fase 5) ---
    # limite de tentativas de login/registro por minuto (0 = desligado)
    auth_rate_limit_per_min: int = 10
    # senha do usuário local de DESENVOLVIMENTO (nunca usada em ENVIRONMENT=prod)
    local_dev_password: str = "lexscan-dev"
    # frequência do expurgo LGPD em segundo plano
    purge_interval_minutes: int = 30

    # --- Corte de upload ---
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolve_tesseract(self) -> str:
        """Caminho do binário do Tesseract (env > autodetecta)."""
        if self.tesseract_cmd:
            return self.tesseract_cmd
        import shutil

        found = shutil.which("tesseract")
        if found:
            return found
        for candidate in _WINDOWS_TESSERACT_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return "tesseract"  # deixe o erro claro se não existir

    def resolve_soffice(self) -> str | None:
        """Binário do LibreOffice (env > autodetecta). None = não instalado."""
        if self.soffice_cmd:
            return self.soffice_cmd
        import shutil

        found = shutil.which("soffice") or shutil.which("libreoffice")
        if found:
            return found
        for candidate in _WINDOWS_SOFFICE_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return None

    def resolve_ghostscript(self) -> str | None:
        """Binário do Ghostscript (env > autodetecta). None = não instalado."""
        if self.ghostscript_cmd:
            return self.ghostscript_cmd
        import shutil

        for name in ("gswin64c", "gswin32c", "gs"):
            found = shutil.which(name)
            if found:
                return found
        for pattern in _WINDOWS_GS_PATTERNS:
            matches = sorted(Path(r"C:\Program Files").glob(pattern), reverse=True)
            for match in matches:
                exe = match / "bin" / "gswin64c.exe"
                if exe.exists():
                    return str(exe)
                exe = match / "bin" / "gs.exe"
                if exe.exists():
                    return str(exe)
        return None

    def resolve_tessdata(self) -> Path | None:
        """Pasta dos *.traineddata (env > ./tessdata > instalação padrão)."""
        if self.tessdata_prefix:
            return Path(self.tessdata_prefix).expanduser().resolve()
        local = Path(__file__).resolve().parents[3] / "tessdata"
        if (local / "por.traineddata").exists() or (local / "eng.traineddata").exists():
            return local
        return None


@lru_cache
def get_settings() -> Settings:
    """Singleton das configurações (cacheado por processo)."""
    return Settings()


settings = get_settings()
