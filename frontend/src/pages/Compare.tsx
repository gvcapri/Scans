import { useEffect, useState } from "react";
import {
  api,
  formatDate,
  type CompareResponse,
  type DiffOp,
  type StoredFile,
} from "../api/client";
import Dropzone from "../components/Dropzone";

const MAX_PAGES_SHOWN = 60;

/** Comparador: duas versões de um documento, diff linha a linha. */
export default function Compare({ onBack }: { onBack: () => void }) {
  const [pdfs, setPdfs] = useState<StoredFile[]>([]);
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickDefaults = (list: StoredFile[]) => {
    if (list.length >= 2) {
      setLeft((current) => (current ? current : list[1].id));
      setRight((current) => (current && current !== left ? current : list[0].id));
    }
  };

  useEffect(() => {
    api
      .listFiles()
      .then((all) => {
        const only = all.filter((f) => /\.pdf$/i.test(f.name));
        setPdfs(only);
        pickDefaults(only);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const addFiles = async (selected: File[]) => {
    setUploading(true);
    setError(null);
    try {
      const uploaded = await api.upload(selected);
      const only = [...uploaded.filter((f) => /\.pdf$/i.test(f.name)), ...pdfs];
      setPdfs(only);
      pickDefaults(only);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const run = async () => {
    if (!left || !right) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.compare(left, right));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const swap = () => {
    setLeft(right);
    setRight(left);
  };

  const nameOf = (id: string) => pdfs.find((f) => f.id === id)?.name ?? "—";

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
            Comparador de versões
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Mostra as diferenças de texto entre duas versões lado a lado:
            remoções em vermelho, adições em verde.
          </p>
        </div>
      </header>

      {pdfs.length < 2 && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          O comparador precisa de pelo menos dois PDFs — envie as duas versões
          abaixo ou pelo painel.
        </p>
      )}

      <Dropzone
        onFiles={addFiles}
        disabled={uploading}
        accept=".pdf"
        hint="Envie as duas versões do documento (PDF)"
      />

      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="grid items-end gap-4 sm:grid-cols-[1fr_auto_1fr]">
          <div>
            <label
              htmlFor="cmp-left"
              className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
            >
              Versão original (esquerda)
            </label>
            <select
              id="cmp-left"
              value={left}
              onChange={(e) => setLeft(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            >
              <option value="">Escolher PDF...</option>
              {pdfs.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} — {formatDate(f.created_at)}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={swap}
            disabled={!left || !right}
            aria-label="Inverter lados"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:border-gold-400 disabled:opacity-50 dark:border-slate-700"
          >
            ⇄
          </button>
          <div>
            <label
              htmlFor="cmp-right"
              className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
            >
              Versão alterada (direita)
            </label>
            <select
              id="cmp-right"
              value={right}
              onChange={(e) => setRight(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            >
              <option value="">Escolher PDF...</option>
              {pdfs.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} — {formatDate(f.created_at)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={run}
            disabled={!left || !right || left === right || loading}
            className="rounded-md bg-ink-800 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gold-500 dark:text-slate-950"
          >
            {loading ? "Comparando..." : "Comparar versões"}
          </button>
          {left && right && left === right && (
            <span className="text-xs text-red-600">
              Escolha duas versões diferentes.
            </span>
          )}
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      {result && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Páginas" value={String(result.summary.pages_compared)} />
            <Stat
              label="Alteradas"
              value={String(result.summary.pages_changed)}
              highlight={result.summary.pages_changed > 0}
            />
            <Stat label="Linhas +" value={`+${result.summary.lines_added}`} tone="green" />
            <Stat label="Linhas −" value={`−${result.summary.lines_removed}`} tone="red" />
          </div>

          <p className="text-sm text-slate-600 dark:text-slate-400">
            <strong>{nameOf(left)}</strong> (esquerda) vs{" "}
            <strong>{nameOf(right)}</strong> (direita)
            {result.pages.length > MAX_PAGES_SHOWN &&
              ` — exibindo as primeiras ${MAX_PAGES_SHOWN} páginas alteradas`}
          </p>

          <div className="space-y-5">
            {result.pages.slice(0, MAX_PAGES_SHOWN).map((page) => (
              <div
                key={page.index}
                className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 text-sm font-semibold text-ink-800 dark:border-slate-700 dark:text-slate-100">
                  <span>Página {page.index}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      page.changed
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                        : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                    }`}
                  >
                    {page.changed ? "alterada" : "igual"}
                  </span>
                </div>
                <DiffPage ops={page.ops} />
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
  highlight,
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
  highlight?: boolean;
}) {
  const color =
    tone === "green"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "red"
        ? "text-red-700 dark:text-red-300"
        : highlight
          ? "text-amber-700 dark:text-amber-300"
          : "text-ink-800 dark:text-slate-100";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-center dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-lg font-semibold ${color}`}>{value}</p>
    </div>
  );
}

/** Duas colunas: esquerda = original, direita = alterada. */
function DiffPage({ ops }: { ops: DiffOp[] }) {
  return (
    <div className="divide-y divide-slate-100 text-[13px] leading-6 dark:divide-slate-800">
      {ops.map((op, i) => {
        const leftLines = op.type === "insert" ? [] : op.a;
        const rightLines = op.type === "delete" ? [] : op.b;
        const leftTone =
          op.type === "delete" || op.type === "replace"
            ? "bg-red-50 text-red-900 dark:bg-red-950/60 dark:text-red-100"
            : "text-slate-700 dark:text-slate-300";
        const rightTone =
          op.type === "insert" || op.type === "replace"
            ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-100"
            : "text-slate-700 dark:text-slate-300";

        const column = (lines: string[], tone: string, side: "L" | "R") => (
          <div className={`min-w-0 px-4 py-2 font-mono ${tone} ${side === "L" ? "border-r border-slate-200 dark:border-slate-700" : ""}`}>
            {lines.length === 0 ? (
              <span className="text-slate-400 dark:text-slate-600">·</span>
            ) : (
              lines.map((line, j) => (
                <div key={j} className="break-words whitespace-pre-wrap">
                  {line}
                </div>
              ))
            )}
          </div>
        );

        return (
          <div key={i} className="grid grid-cols-2">
            {column(leftLines, leftTone, "L")}
            {column(rightLines, rightTone, "R")}
          </div>
        );
      })}
    </div>
  );
}
