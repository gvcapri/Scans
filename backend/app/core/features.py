"""Habilitação de funcionalidades (feature flags).

Regra central da deploy de 1 GB:
  - Se `ENVIRONMENT=prod`, NENHUMA flag pesada está ligada por padrão.
  - Quatro camadas de proteção: (1) configuração, (2) código que impede
    conexão/copy de mídia, (3) endpoint /api/meta/features,
    (4) API (módulo modsecurity) concede 503 em quem não atende.

Implementação: `get_settings()` define as flags de acordo com o ambiente e as
variáveis de configuração. A frente só lê o método que a flag determina.
Toda string de ativação de funcionalidade (ex.: o frontend) é única no
código e proveniente exatamente desse módulo.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings

settings = get_settings()


def is_feature_enabled(name: str) -> bool:
    """Verifica se a funcionalidade `name` está ativa nesta instância."""
    if not isinstance(settings, Settings):
        return False
    return getattr(settings.features, name, False)


def get_flag(name: str, default: bool = False) -> bool:
    """Acesso de leitura para o código que avalia flags."""
    if not isinstance(settings, Settings):
        return default
    return getattr(settings.features, name, default)
