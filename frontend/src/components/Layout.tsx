import type { ReactNode } from "react";
import { useTheme } from "../hooks";

export type Route = "dashboard" | "history" | { tool: string };

type Props = {
  route: Route;
  onNavigate: (route: Route) => void;
  children: ReactNode;
};

/** Cabeçalho + navegação + rodapé, responsivos e acessíveis. */
export default function Layout({ route, onNavigate, children }: Props) {
  const { dark, toggle } = useTheme();

  const navItem = (id: "dashboard" | "history", label: string) => {
    const active = route === id;
    return (
      <button
        type="button"
        onClick={() => onNavigate(id)}
        aria-current={active ? "page" : undefined}
        className={`rounded-md px-3 py-2 text-sm font-medium transition ${
          active
            ? "bg-white/15 text-white"
            : "text-ink-100 hover:bg-white/10 hover:text-white"
        }`}
      >
        {label}
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-ink-50 text-ink-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="bg-ink-800 text-white shadow-md dark:bg-ink-900">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <button
            type="button"
            onClick={() => onNavigate("dashboard")}
            className="flex items-center gap-2"
            aria-label="Ir para o painel"
          >
            {/* Marca: escudo discreto com filete dourado */}
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-7 w-7">
              <path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5l8-3z" fill="#16324f" stroke="#c9a227" strokeWidth="1.4" />
              <path d="M8.5 12l2.3 2.4 4.7-5" fill="none" stroke="#c9a227" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-lg font-semibold tracking-tight">
              Lex<span className="text-gold-400">Scan</span>
            </span>
          </button>

          <nav className="flex flex-1 items-center gap-1" aria-label="Principal">
            {navItem("dashboard", "Painel")}
            {navItem("history", "Histórico")}
          </nav>

          <button
            type="button"
            onClick={toggle}
            aria-pressed={dark}
            className="rounded-md border border-white/25 px-3 py-1.5 text-sm text-ink-100 hover:bg-white/10"
          >
            {dark ? "☀️ Claro" : "🌙 Escuro"}
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6">{children}</main>

      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        LexScan — documentos jurídicos tratados com sigilo. Arquivos cifrados e
        expurgados automaticamente em 24 h.
      </footer>
    </div>
  );
}
