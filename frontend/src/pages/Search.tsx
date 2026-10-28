import { useState } from "react";
import { api, formatDate, formatSize, type SearchHit } from "../api/client";

/** Pesquisa no acervo: varre o texto dos documentos e destaqueia o trecho. */
export default function Search({ onBack }: { onBack: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    const term = q.trim();
    if (!term) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.search(term);
      setHits(response.results);
      setTotal(response.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-gold-400 dark:border-slate-700"
        >
          ← Painel
        </button>
        <div>
          <h1 className="text-2xl font-semibold text-ink-800 dark:text-slate-100">
            Pesquisa em acervo
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Busca textual em todos os seus documentos, com o trecho encontrado
            destacado. Acentos e maiúsculas são ignorados.
          </p>
        </div>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
        className="flex flex-wrap gap-2"
      >
        <label htmlFor="busca-q" className="sr-only">
          Termo da busca
        </label>
        <input
          id="busca-q"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ex.: honorário, cláusula 7, CPF 529.982..."
          className="min-w-60 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
        <button
          type="submit"
          disabled={loading || !q.trim()}
          className="rounded-md bg-ink-800 px-5 py-2 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gold-500 dark:text-slate-950"
        >
          {loading ? "Buscando..." : "Buscar"}
        </button>
      </form>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      {hits && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
            {total === 0
              ? "Nenhum documento encontrado."
              : `${total} documento(s) encontrado(s) para “${q}”.`}
          </p>

          <ul className="space-y-3">
            {hits.map((hit) => (
              <li
                key={hit.file_id}
                className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-ink-800 dark:text-slate-100">
                    {hit.name}
                  </span>
                  <span className="text-xs text-slate-500">
                    {hit.size ? formatSize(hit.size) : ""}
                    {hit.created_at ? ` · ${formatDate(hit.created_at)}` : ""}
                  </span>
                </div>
                {/* snippet: HTML gerado pelo backend com apenas <mark> */}
                <p
                  className="mt-1.5 text-sm leading-relaxed text-slate-700 dark:text-slate-300"
                  dangerouslySetInnerHTML={{ __html: hit.snippet }}
                />
                <a
                  href={api.downloadUrl(hit.file_id)}
                  className="mt-1 inline-block text-xs font-medium text-ink-600 hover:underline dark:text-gold-400"
                  download
                >
                  ⬇ Baixar
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-slate-500">
        A busca varre PDFs com camada de texto, TXT e Word. PDFs escaneados
        entram no índice depois que você roda o OCR — e todo processamento
        gera um novo arquivo já indexado.
      </p>
    </section>
  );
}
