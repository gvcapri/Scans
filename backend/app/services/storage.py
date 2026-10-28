"""Armazenamento cifrado em repouso, com isolamento por usuário.

Decisões de segurança:
* Cada arquivo é gravado em `STORAGE_ROOT/<user_id>/<file_id><ext>` — o nome
  original nunca vira caminho de disco (evita path traversal).
* Conteúdo cifrado com Fernet (AES-128-CBC + HMAC), em blocos de 1 MiB,
  por usuário. Padrão de arquivo: uma linha por bloco criptografado.
* SHA-256 calculado sobre o conteúdo **original** (é o hash que alimenta o
  Certificado de Integridade da Fase 3).
* Downloads são descriptografados em streaming: o texto claro não fica em disco.
"""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_CHUNK = 1024 * 1024
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


class StorageError(RuntimeError):
    """Falha de leitura/gravação no armazenamento."""


@dataclass
class StoredMeta:
    """Metadados do arquivo recém-gravado."""

    file_id: str
    size: int
    sha256: str
    ext: str


class EncryptedStorage:
    """Responsável por cifrar, ler e apagar arquivos em disco."""

    def __init__(self, root: Path, secret: str):
        self.root = Path(root).expanduser().resolve()
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    # ------------------------------------------------------------------ paths
    def _user_dir(self, user_id: str) -> Path:
        if not _SAFE_ID.match(user_id):
            raise StorageError("Identificador de usuário inválido.")
        path = (self.root / user_id).resolve()
        if not path.is_relative_to(self.root):  # defesa extra
            raise StorageError("Caminho fora da raiz de armazenamento.")
        return path

    def _path_for(self, user_id: str, file_id: str, ext: str) -> Path:
        if not _SAFE_ID.match(file_id):
            raise StorageError("Identificador de arquivo inválido.")
        path = (self._user_dir(user_id) / f"{file_id}{ext}").resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Caminho fora da raiz de armazenamento.")
        return path

    def _locate(self, user_id: str, file_id: str) -> Path:
        """Encontra o arquivo de um usuário (só entre os dele)."""
        user_dir = self._user_dir(user_id)
        matches = list(user_dir.glob(f"{file_id}.*")) if user_dir.exists() else []
        if not matches:
            raise FileNotFoundError("Arquivo não encontrado.")
        return matches[0]

    # ------------------------------------------------------------------ write
    def save_stream(
        self,
        user_id: str,
        source: BinaryIO,
        file_id: str,
        ext: str,
    ) -> StoredMeta:
        """Cifra um fluxo (upload) diretamente no disco."""
        dest = self._path_for(user_id, file_id, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size, digest = self._encrypt_into(source, dest)
        return StoredMeta(file_id=file_id, size=size, sha256=digest, ext=ext)

    def save_path(self, user_id: str, src: Path, file_id: str, ext: str | None = None) -> StoredMeta:
        """Cifra um arquivo já existente no disco (saída de um job)."""
        ext = ext if ext is not None else src.suffix
        with open(src, "rb") as fh:
            return self.save_stream(user_id, fh, file_id, ext)

    def _encrypt_into(self, source: BinaryIO, dest: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with open(tmp, "wb") as out:
                while True:
                    block = source.read(_CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    size += len(block)
                    out.write(self._fernet.encrypt(block))
                    out.write(b"\n")
            tmp.replace(dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return size, digest.hexdigest()

    # ------------------------------------------------------------------- read
    def decrypt_iter(self, user_id: str, file_id: str) -> Iterator[bytes]:
        """Itera o conteúdo claro (usado no download em streaming)."""
        path = self._locate(user_id, file_id)
        try:
            with open(path, "rb") as fh:
                for line in fh:
                    token = line.strip()
                    if not token:
                        continue
                    yield self._fernet.decrypt(token)
        except InvalidToken as exc:  # arquivo corrompido ou chave trocada
            raise StorageError("Falha ao descriptografar o arquivo.") from exc

    def decrypt_to(self, user_id: str, file_id: str, dest: Path) -> Path:
        """Descriptografa para um arquivo temporário (materialização p/ jobs)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            for chunk in self.decrypt_iter(user_id, file_id):
                out.write(chunk)
        return dest

    def materialize(
        self, user_id: str, file_id: str, workdir: Path, display_name: str | None = None
    ) -> Path:
        """Cópia clara do arquivo para processamento.

        Usa o nome original (quando informado) para que as saídas geradas
        herdem um nome compreensível — ex.: `peticao_ocr.pdf`.
        """
        path = self._locate(user_id, file_id)
        ext = path.suffix
        if display_name:
            base = Path(display_name.replace("\\", "/")).name.strip()
            if not base or base in (".", ".."):
                base = file_id
            if not base.lower().endswith(ext.lower()):
                base = f"{Path(base).stem or file_id}{ext}"
            dest = workdir / base
        else:
            dest = workdir / f"{file_id}{ext}"
        return self.decrypt_to(user_id, file_id, dest)

    def size_on_disk(self, user_id: str, file_id: str) -> int:
        return self._locate(user_id, file_id).stat().st_size

    # ----------------------------------------------------------------- delete
    def delete(self, user_id: str, file_id: str) -> None:
        """Apagamento seguro ("Apagar agora" / expurgo LGPD)."""
        try:
            self._locate(user_id, file_id).unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    def purge_user(self, user_id: str) -> None:
        """Remove todos os arquivos de um usuário."""
        user_dir = self._user_dir(user_id)
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)

    # ------------------------------------------------------------- utilitários
    @staticmethod
    def workdir(prefix: str = "lexscan-") -> tempfile.TemporaryDirectory:
        """Pasta temporária de trabalho (fora do projeto/OneDrive)."""
        return tempfile.mkdtemp(prefix=prefix)


_storage: EncryptedStorage | None = None


def get_storage() -> EncryptedStorage:
    """Singleton do armazenamento."""
    global _storage
    if _storage is None:
        _storage = EncryptedStorage(settings.storage_root, settings.storage_secret)
    return _storage
