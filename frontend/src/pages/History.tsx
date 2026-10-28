import { useEffect, useState } from "react";
import { api, formatDate, formatSize, type Job, type StoredFile } from "../api/client";
import ProgressBar from "../components/ProgressBar";

/** Histórico: jobs (com saídas) e arquivos enviados. */
export default function History({ onOpenTool }: { onOpenTool: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
    api.listFiles().then(setFiles).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const removeFile = async (id: string) => {
    await api.deleteFile(id);
    load();
  };

  const removeJob = async (id: string) => {
    try {
      await api.deleteJob(id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink-800 dark:text-slate-100">Histórico</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Operações recentes e arquivos armazenados (cifrados, expurgo em 24 h).
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Processamentos
        </h2>
        {jobs.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            Nenhum processamento ainda.
          </p>
        ) : (
          <ul className="space-y-3">
            {jobs.map((job) => (
              <li
                key={job.id}
                className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink-800 dark:text-slate-100">
                      {job.kind === "ocr" ? "OCR" : "PDF Blindado"}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        job.status === "done"
                          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                          : job.status === "error"
                            ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
                            : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                      }`}
                    >
                      {job.status === "done"
                        ? "Concluído"
                        : job.status === "error"
                          ? "Falhou"
                          : "Em andamento"}
                    </span>
                    <span className="text-xs text-slate-500">{formatDate(job.created_at)}</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => onOpenTool(job.kind)}
                      className="text-xs font-medium text-ink-600 hover:underline dark:text-gold-400"
                    >
                      Repetir
                    </button>
                    <button
                      type="button"
                      onClick={() => removeJob(job.id)}
                      className="text-xs font-medium text-red-600 hover:underline dark:text-red-400"
                    >
                      Remover
                    </button>
                  </div>
                </div>

                <div className="mt-3">
                  <ProgressBar
                    progress={job.progress}
                    message={job.message}
                    pageCurrent={job.page_current}
                    pageTotal={job.page_total}
                    status={job.status}
                  />
                </div>

                {job.output_file_ids.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {job.output_file_ids.map((id) => (
                      <a
                        key={id}
                        href={api.downloadUrl(id)}
                        className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-ink-700 hover:border-gold-400 dark:border-slate-700 dark:text-slate-200"
                      >
                        ⬇ Baixar resultado
                      </a>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Arquivos
        </h2>
        {files.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            Nenhum arquivo armazenado.
          </p>
        ) : (
          <ul className="divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
            {files.map((file) => (
              <li key={file.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="truncate text-sm font-medium text-ink-800 dark:text-slate-100">
                  {file.name}
                </span>
                <span className="text-xs text-slate-500">
                  {formatSize(file.size)} · {file.role === "output" ? "gerado" : "enviado"} ·{" "}
                  {formatDate(file.created_at)}
                </span>
                <span className="ml-auto flex gap-3 text-xs">
                  <a
                    href={api.downloadUrl(file.id)}
                    className="font-medium text-ink-600 hover:underline dark:text-gold-400"
                  >
                    Baixar
                  </a>
                  <button
                    type="button"
                    onClick={() => removeFile(file.id)}
                    className="font-medium text-red-600 hover:underline dark:text-red-400"
                    aria-label={`Apagar agora ${file.name}`}
                  >
                    Apagar agora
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
