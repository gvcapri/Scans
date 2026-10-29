import { useEffect, useState } from "react";
import { api, type Tool } from "../api/client";
import type { Route } from "../components/Layout";

/** Painel com os cards de ferramenta. */
export default function Dashboard({ onNavigate }: { onNavigate: (r: Route) => void }) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .tools()
      .then((r) => setTools(r.tools))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <section>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-ink-800 dark:text-slate-100">
          Ferramentas
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Escolha o que fazer com seus documentos. Tudo é processado com
          armazenamento cifrado e expurgo automático.
        </p>
      </div>

      {error && (
        <p className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tools.map((tool) => {
          const disabled = !tool.available;
          return (
            <button
              key={tool.id}
              type="button"
              disabled={disabled}
              onClick={() => onNavigate({ tool: tool.id })}
              aria-describedby={`${tool.id}-desc`}
              className={`group flex flex-col rounded-xl border p-4 text-left transition ${
                disabled
                  ? "cursor-not-allowed border-dashed border-slate-300 bg-slate-100/60 dark:border-slate-700 dark:bg-slate-900/40"
                  : "border-slate-200 bg-white shadow-sm hover:-translate-y-0.5 hover:border-gold-400 hover:shadow-md dark:border-slate-800 dark:bg-slate-900"
              }`}
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <span
                  className={`text-base font-semibold ${
                    disabled
                      ? "text-slate-500 dark:text-slate-500"
                      : "text-ink-800 dark:text-slate-100"
                  }`}
                >
                  {tool.name}
                </span>
                <span
                  title={
                    disabled && tool.phase
                      ? `Recurso previsto para a Fase ${tool.phase}`
                      : undefined
                  }
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    disabled
                      ? "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                      : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                  }`}
                >
                  {disabled ? "Em breve" : "Disponível"}
                </span>
              </div>
              <p
                id={`${tool.id}-desc`}
                className="text-sm text-slate-600 dark:text-slate-400"
              >
                {tool.description}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}
