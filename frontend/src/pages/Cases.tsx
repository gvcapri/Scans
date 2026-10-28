import { useCallback, useEffect, useState } from "react";
import {
  api,
  formatDate,
  formatSize,
  type CaseDetail,
  type CaseFolder,
  type StoredFile,
} from "../api/client";

/** Rótulos em pt-BR dos kinds de job (histórico das pastas). */
const KIND_LABELS: Record<string, string> = {
  ocr: "OCR",
  blind: "PDF Blindado",
  merge: "Mesclar",
  split: "Dividir",
  convert: "Converter",
  compress: "Comprimir",
  redact: "Redigir dados",
  number: "Numeração / Fls.",
  outline: "Sumário / índice",
  metadata: "Metadados da peça",
  integrity: "Certificado de integridade",
  batch: "Processamento em lote",
};

/** Pastas de processo/cliente com arquivos e histórico de operações. */
export default function Cases() {
  const [folders, setFolders] = useState<CaseFolder[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [acervo, setAcervo] = useState<StoredFile[]>([]);
  const [name, setName] = useState("");
  const [cnj, setCnj] = useState("");
  const [moveId, setMoveId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    api
      .listCases()
      .then(setFolders)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const loadDetail = useCallback((id: string) => {
    api
      .getCase(id)
      .then(setDetail)
      .catch((e) => setError((e as Error).message));
    api
      .listFiles()
      .then(setAcervo)
      .catch(() => undefined);
  }, []);

  useEffect(refresh, [refresh]);

  const open = (id: string) => {
    setOpenId(id);
    setError(null);
    loadDetail(id);
  };

  const create = async () => {
    if (!name.trim()) return;
    setError(null);
    try {
      const created = await api.createCase(name.trim(), cnj.trim());
      setName("");
      setCnj("");
      refresh();
      open(created.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const removeFolder = async (id: string) => {
    await api.deleteCase(id).catch(() => undefined);
    setOpenId(null);
    setDetail(null);
    refresh();
  };

  const attach = async () => {
    if (!openId || !moveId) return;
    await api.addCaseFiles(openId, [moveId]).catch((e) => setError((e.message as string) ?? "Erro"));
    setMoveId("");
    loadDetail(openId);
    refresh();
  };

  const detach = async (fileId: string) => {
    if (!openId) return;
    await api.removeCaseFile(openId, fileId).catch(() => undefined);
    loadDetail(openId);
    refresh();
  };

  // ------------------------------------------------------------ detalhe
  if (openId && detail) {
    const disponiveis = acervo.filter(
      (f) => !detail.files.some((mine) => mine.id === f.id)
    );
    return (
      <section className="space-y-6">
        <header className="flex flex-wrap items-start gap-3">
          <button
            type="button"
            onClick={() => {
              setOpenId(null);
              setDetail(null);
              refresh();
            }}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-gold-400 dark:border-slate-700"
          >
            ← Pastas
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-2xl font-semibold text-ink-800 dark:text-slate-100">
              {detail.name}
            </h1>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {detail.process_number && (
                <span className="mr-2 rounded bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-700 dark:bg-slate-800 dark:text-slate-300">
                  CNJ {detail.process_number}
                </span>
              )}
              {detail.file_count} arquivo(s) · criada em {formatDate(detail.created_at)}
            </p>
          </div>
          <button
            type="button"
            onClick={() => removeFolder(detail.id)}
            className="rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400"
          >
            Apagar pasta
          </button>
        </header>

        {/* mover arquivo para dentro */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Mover arquivo para esta pasta
          </h2>
          {disponiveis.length === 0 ? (
            <p className="text-sm text-slate-500">
              Todos os arquivos do acervo já estão aqui.
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-56 flex-1">
                <label
                  htmlFor="case-move"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Arquivo
                </label>
                <select
                  id="case-move"
                  value={moveId}
                  onChange={(e) => setMoveId(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                >
                  <option value="">Escolher arquivo...</option>
                  {disponiveis.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                onClick={attach}
                disabled={!moveId}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:border-gold-400 disabled:opacity-50 dark:border-slate-700"
              >
                Mover
              </button>
            </div>
          )}
        </div>

        {/* arquivos da pasta */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Arquivos
          </h2>
          {detail.files.length === 0 ? (
            <p className="text-sm text-slate-500">Pasta vazia.</p>
          ) : (
            <ul className="space-y-2">
              {detail.files.map((file) => (
                <li
                  key={file.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700"
                >
                  <span className="min-w-0 truncate text-sm font-medium text-ink-800 dark:text-slate-100">
                    {file.name}
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      {formatSize(file.size)} · {formatDate(file.created_at)}
                    </span>
                  </span>
                  <span className="flex gap-3 text-xs">
                    <a
                      href={api.downloadUrl(file.id)}
                      className="font-medium text-ink-600 hover:underline dark:text-gold-400"
                      download
                    >
                      ⬇ Baixar
                    </a>
                    <button
                      type="button"
                      onClick={() => detach(file.id)}
                      className="font-medium text-red-600 hover:underline dark:text-red-400"
                    >
                      Retirar
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* histórico de operações */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Histórico de operações
          </h2>
          {detail.operations.length === 0 ? (
            <p className="text-sm text-slate-500">
              Nenhuma operação registrada nestes arquivos ainda.
            </p>
          ) : (
            <ul className="space-y-2">
              {detail.operations.map((op) => (
                <li
                  key={op.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700"
                >
                  <span className="font-medium text-ink-800 dark:text-slate-100">
                    {KIND_LABELS[op.kind] ?? op.kind}
                    <span className="ml-2 font-normal text-slate-500">
                      {op.message}
                    </span>
                  </span>
                  <span className="flex items-center gap-3 text-xs">
                    <span
                      className={`rounded-full px-2 py-0.5 font-medium ${
                        op.status === "done"
                          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                          : op.status === "error"
                            ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
                            : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                      }`}
                    >
                      {op.status === "done"
                        ? "Concluído"
                        : op.status === "error"
                          ? "Erro"
                          : "Em andamento"}
                    </span>
                    <span className="text-slate-500">{formatDate(op.created_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    );
  }

  // -------------------------------------------------------------- lista
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-ink-800 dark:text-slate-100">
          Pastas de processo
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Organize os arquivos por processo ou cliente e acompanhe o histórico
          de cada um. Apagar a pasta não apaga os arquivos.
        </p>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Nova pasta
        </h2>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label
              htmlFor="case-name"
              className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
            >
              Nome (ex.: cliente ou processo)
            </label>
            <input
              id="case-name"
              type="text"
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Silva x Transportes"
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
          <div className="min-w-56 flex-1">
            <label
              htmlFor="case-cnj"
              className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
            >
              Número CNJ (opcional)
            </label>
            <input
              id="case-cnj"
              type="text"
              value={cnj}
              maxLength={32}
              onChange={(e) => setCnj(e.target.value)}
              placeholder="0000001-10.2026.8.01.0001"
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
          <button
            type="button"
            onClick={create}
            disabled={!name.trim()}
            className="rounded-md bg-ink-800 px-5 py-2 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gold-500 dark:text-slate-950"
          >
            Criar pasta
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Carregando...</p>
      ) : folders.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
          Nenhuma pasta ainda. Crie a primeira acima.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {folders.map((folder) => (
            <button
              key={folder.id}
              type="button"
              onClick={() => open(folder.id)}
              className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-gold-400 hover:shadow-md dark:border-slate-800 dark:bg-slate-900"
            >
              <p className="truncate font-semibold text-ink-800 dark:text-slate-100">
                {folder.name}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {folder.process_number ? `CNJ ${folder.process_number} · ` : ""}
                {folder.file_count} arquivo(s)
              </p>
              <p className="mt-0.5 text-xs text-slate-400">
                {formatDate(folder.created_at)}
              </p>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
