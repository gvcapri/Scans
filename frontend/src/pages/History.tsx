import { useEffect, useState } from "react";
import { api, formatDate, formatSize, type Job, type StoredFile, type Tool } from "../api/client";
import ProgressBar from "../components/ProgressBar";

/** Rótulo amigável do tipo de operação, pelo catálogo da API. */
function kindLabel(kind: string, tools: Tool[]): string {
  return tools.find((t) => t.id === kind)?.name ?? kind;
}

/** Histórico: tabela de logs dos últimos processamentos + arquivos. */
export default function History({ onOpenTool }: { onOpenTool: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
    api.listFiles().then(setFiles).catch((e) => setError(e.message));
    api.tools().then((r) => setTools(r.tools)).catch(() => undefined);
  };

  useEffect(load, []);

  const byId = new Map(files.map((f) => [f.id, f]));

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
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">
          Histórico
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Log dos últimos processamentos e arquivos armazenados (cifrados,
          expurgo automático em 24 h).
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Processamentos
        </h2>
        {jobs.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line bg-white p-6 text-center text-sm text-slate-500">
            Nenhum processamento ainda.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line bg-white shadow-card">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Data</th>
                  <th className="px-4 py-3 font-medium">Operação</th>
                  <th className="px-4 py-3 font-medium">Documento</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Progresso</th>
                  <th className="px-4 py-3 text-right font-medium">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {jobs.map((job) => {
                  const input = job.input_file_ids.map((id) => byId.get(id)).find(Boolean);
                  const ok = job.status === "done";
                  return (
                    <tr key={job.id} className="align-top hover:bg-slate-50">
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                        {formatDate(job.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-navy-900">
                        {kindLabel(job.kind, tools)}
                      </td>
                      <td className="max-w-[14rem] truncate px-4 py-3 text-slate-600">
                        {input?.name ?? "—"}
                        {input && (
                          <span className="block text-xs text-slate-400">
                            {formatSize(input.size)}
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            ok
                              ? "bg-emerald-50 text-emerald-600"
                              : job.status === "error"
                                ? "bg-red-50 text-red-600"
                                : "bg-amber-50 text-amber-600"
                          }`}
                        >
                          {ok ? "Concluído" : job.status === "error" ? "Falhou" : "Em andamento"}
                        </span>
                      </td>
                      <td className="w-48 px-4 py-3">
                        <ProgressBar
                          progress={job.progress}
                          message={job.message}
                          pageCurrent={job.page_current}
                          pageTotal={job.page_total}
                          status={job.status}
                        />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right text-xs">
                        <span className="inline-flex gap-3">
                          {job.output_file_ids.map((id) => (
                            <a
                              key={id}
                              href={api.downloadUrl(id)}
                              className="font-medium text-blue-700 hover:underline"
                            >
                              Baixar
                            </a>
                          ))}
                          <button
                            type="button"
                            onClick={() => onOpenTool(job.kind)}
                            className="font-medium text-slate-600 hover:underline"
                          >
                            Repetir
                          </button>
                          <button
                            type="button"
                            onClick={() => removeJob(job.id)}
                            className="font-medium text-red-600 hover:underline"
                          >
                            Remover
                          </button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {jobs.some((j) => j.status === "error") && (
          <p className="mt-2 text-xs text-red-600">
            {jobs.find((j) => j.status === "error")?.error}
          </p>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Arquivos
        </h2>
        {files.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line bg-white p-6 text-center text-sm text-slate-500">
            Nenhum arquivo armazenado.
          </p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white shadow-card">
            {files.map((file) => (
              <li key={file.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="truncate text-sm font-medium text-navy-900">
                  {file.name}
                </span>
                <span className="text-xs text-slate-500">
                  {formatSize(file.size)} · {file.role === "output" ? "gerado" : "enviado"} ·{" "}
                  {formatDate(file.created_at)}
                </span>
                <span className="ml-auto flex gap-3 text-xs">
                  <a
                    href={api.downloadUrl(file.id)}
                    className="font-medium text-blue-700 hover:underline"
                  >
                    Baixar
                  </a>
                  <button
                    type="button"
                    onClick={() => removeFile(file.id)}
                    className="font-medium text-red-600 hover:underline"
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
