"""Configuração central do JudiFiles.

Todos os valores vêm de variáveis de ambiente (arquivo .env opcional),
para que dev local e Docker Compose rodem o mesmo código.

Regras de produção (falhar de forma fechada):
  * ENVIRONMENT não definido  -> assume prod (nunca suba sem exlaughter).
  * STORAGE_SECRET deve ter >= 32 chars — senão recuse subir.
  * Em prod NÃO cria o usuário local e NÃO aceita LOCAL_DEV_PASSWORD.
"""


from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Binários/rastreadores que só existem fora do Docker.
_WINDOWS_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
_WINDOWS_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
_WINDOWS_GS_PATTERNS = (
    r"gs\gs*",
    r"Ghostscript\gs*",
    r"ghostscript*",
)

# ---------------------------------------------------------------- flags ----


class FeatureFlags:
    """Flags de produção (custos em memória/CPU).

    Toda funcionalidade pesada deve ter uma flag; o padrão neste deploy de
    1 GB de RAM é desligada. Ative somente mudando o .env e reiniciando.

    O instanciador (`Settings.features`) deve passar `settings`, que este
    objeto mantém como referência para avaliar `ENVIRONMENT` e os caminhos
    de dependência. Em `Settings.features` não é necessário repassar o
    dicionário de campo; o `Settings` base já disponibiliza cada flag.
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    @property
    def _is_prod(self) -> bool:
        return self._settings.environment.lower() == "prod"

    def _flag(self, name: str, prod_default: bool = False) -> bool:
        """Resolve `FEATURE_<NAME>` do ambiente.

        * variável definida (true/false) -> ela manda, em qualquer ambiente;
        * ausente -> em **prod** vale `prod_default` (fail-closed para
          funcionalidades pesadas), em dev liga tudo para não atrapalhar os
          testes e o desenvolvimento local.
        """
        value = getattr(self._settings, f"feature_{name}", None)
        if value is not None:
            return bool(value)
        return prod_default if self._is_prod else True

    # ── Pesadas (desligadas por padrão na VM de 1 GB) ───────────────────
    ocr = property(lambda self: self._flag("ocr", prod_default=False))
    compare = property(lambda self: self._flag("compare", prod_default=False))
    redact = property(lambda self: self._flag("redact", prod_default=False))
    convert = property(lambda self: self._flag("convert", prod_default=False))
    batch = property(lambda self: self._flag("batch", prod_default=False))

    # ── Leves (ligadas por padrão, inclusive em prod) ────────────────────
    search = property(lambda self: self._flag("search", prod_default=True))
    cases = property(lambda self: self._flag("cases", prod_default=True))
    jobs = property(lambda self: self._flag("jobs", prod_default=True))
    numbering = property(lambda self: self._flag("numbering", prod_default=True))
    outline = property(lambda self: self._flag("outline", prod_default=True))
    integrity = property(lambda self: self._flag("integrity", prod_default=True))

    # Blindado depende do mesmo binário do OCR (tesseract).
    blind = property(lambda self: self.ocr)

    # CLI do tesseract existe (para relatórios, não decide a flag acima)
    ocr_cli = property(lambda self: bool(self._settings.tesseract_cmd))

    # ── Aceita cadastro ----
    def _registration_open(self) -> bool:
        return self._settings.registration_open

    registration_open = property(_registration_open)

    # ── Acesso público de ferramentas leves (PUBLIC_TOOLS=a,b,c) ─────────
    def _public_tools(self) -> list[str]:
        raw = getattr(self._settings, "public_tools", "") or ""
        return [t.strip() for t in raw.split(",") if t.strip()]

    public_tools = property(_public_tools)

    # ── Regime de produção ───────────────────────────────────────────────
    def _fail_close(self) -> bool:
        return self._settings.environment.lower() == "prod"

    fail_close = property(_fail_close)


class Settings(BaseSettings):
    """Configuração lida do ambiente (.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicação ---
    # Falha fechada: se ENVIRONMENT não estiver definido, assume prod
    # (dev define ENVIRONMENT=dev explicitamente — ver conftest/README).
    app_name: str = "JudiFiles"
    environment: str = "prod"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    # --- Banco ---
    database_url: str = "sqlite:///./lexscan.db"
    # Pool por processo — numa VM de 1 GB o Postgres não aguenta muitas
    # conexões simultâneas (API + worker disputam a mesma RAM).
    db_pool_size: int = 3
    db_max_overflow: int = 2

    # --- Armazenamento ---
    storage_root: Path = Path("./storage")
    storage_secret: str = "dev-only-secret-key-troque-em-producao"
    storage_backend: str = "disk"

    # --- Fila de tarefas ---
    task_backend: str = "local"
    celery_broker_url: str = "redis://localhost:6379/0"
    worker_concurrency: int = 2
    # Jobs pesados simultâneos por processo (semáforo): cada job carrega
    # PDF/OCR na memória, então em 1 GB o padrão é 1 por vez.
    max_concurrent_jobs: int = 1

    # --- LGPD ---
    retention_hours: int = 24
    max_upload_mb: int = 100

    # --- OCR ---
    tesseract_cmd: str = ""
    tesseract_langs: str = "por+eng"
    tessdata_prefix: str = ""
    ocr_dpi: int = 300

    # --- Conversão Word ---
    soffice_cmd: str = ""

    # --- Compressão / PDF-A (Ghostscript) ---
    ghostscript_cmd: str = ""

    # --- Segurança ---
    secret_key: str = "dev-only-jwt-secret-troque-em-producao"
    rate_limit_per_min: int = 1000000
    clamav_enabled: bool = False
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310

    # --- Autenticação (Fase 5) ---
    auth_rate_limit_per_min: int = 10
    local_dev_password: str = "lexscan-dev"
    purge_interval_minutes: int = 30

    # --- Feature flags (FEATURE_* no ambiente; ver FeatureFlags) ---------
    # Pesadas: None = "decidir pelo ambiente" (ligada em dev, desligada em
    # prod). Defina true/false para forçar.
    feature_ocr: bool | None = None
    feature_compare: bool | None = None
    feature_redact: bool | None = None
    feature_convert: bool | None = None
    feature_batch: bool | None = None
    # Leves: None = ligada em qualquer ambiente.
    feature_search: bool | None = None
    feature_cases: bool | None = None
    feature_jobs: bool | None = None
    feature_numbering: bool | None = None
    feature_outline: bool | None = None
    feature_integrity: bool | None = None
    registration_open: bool = True
    allowed_email_domains: str = ""  # vírgula-separados, vazio = aberto
    public_tools: str = ""  # nomes de ferramentas públicas, vazio = nenhuma

    # --- Corte de upload ---
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolve_tesseract(self) -> str:
        if self.tesseract_cmd:
            return self.tesseract_cmd
        import shutil

        found = shutil.which("tesseract")
        if found:
            return found
        for candidate in _WINDOWS_TESSERACT_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return "tesseract"

    def resolve_soffice(self) -> str | None:
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
        if self.tessdata_prefix:
            return Path(self.tessdata_prefix).expanduser().resolve()
        local = Path(__file__).resolve().parents[3] / "tessdata"
        if (local / "por.traineddata").exists() or (local / "eng.traineddata").exists():
            return local
        return None

    @property
    def features(self) -> FeatureFlags:
        return FeatureFlags(self)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # falha fechada: em prod, STORAGE_SECRET obrigatório, 32+ chars e
    # nunca o valor de exemplo (mesmo que tenha o comprimento mínimo)
    if settings.environment.lower() == "prod":
        _example = {
            "",
            "dev-only-secret-key-troque-em-producao",
            "troque-este-segredo",
        }
        if settings.storage_secret in _example or len(settings.storage_secret) < 32:
            raise RuntimeError(
                "ENVIRONMENT=prod exige STORAGE_SECRET real de 32+ caracteres "
                "(não pode ser o valor de exemplo). "
                "Gerar com: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
    return settings


settings = get_settings()
