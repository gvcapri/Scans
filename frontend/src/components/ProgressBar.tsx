type Props = {
  progress: number;
  message: string;
  pageCurrent?: number;
  pageTotal?: number;
  status: "queued" | "running" | "done" | "error";
};

/** Barra de progresso com página atual e mensagem em pt-BR. */
export default function ProgressBar({ progress, message, pageCurrent, pageTotal, status }: Props) {
  const pct = Math.max(0, Math.min(100, progress));
  const done = status === "done";
  const error = status === "error";
  const indeterminate = status === "queued" && pct === 0;

  return (
    <div>
      <div
        className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progresso do processamento"
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            error ? "bg-red-500" : done ? "bg-emerald-500" : "bg-gold-500"
          } ${indeterminate ? "w-1/3 animate-pulse" : ""}`}
          style={indeterminate ? undefined : { width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-600 dark:text-slate-400">
        <span aria-live="polite">{message}</span>
        <span className="tabular-nums">
          {pageTotal ? `pág. ${pageCurrent ?? 0}/${pageTotal} · ` : ""}
          {pct}%
        </span>
      </div>
    </div>
  );
}
