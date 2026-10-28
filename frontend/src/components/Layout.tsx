import type { ReactNode } from "react";
import type { AuthUser } from "../api/client";
import { useTheme } from "../hooks";

export type Route = "dashboard" | "history" | "cases" | { tool: string };

type Props = {
  route: Route;
  onNavigate: (route: Route) => void;
  children: ReactNode;
  user: AuthUser | null;
  onLogout: () => void;
  onSecurity: () => void;
};

/**
 * Cabeçalho, navegação e rodapé do JudiFiles.
 * Design neutro (jornalística + sócio), vazio de distrações, foco no que
 * o usuário está fazendo com o documento.
 */
export default function Layout({ route, onNavigate, children, user, onLogout, onSecurity }: Props) {
  const { dark, toggle } = useTheme();

  const navItem = (id: "dashboard" | "history" | "cases", label: string) => {
    const active = route === id;
    return (
      <button
        type="button"
        onClick={() => onNavigate(id)}
        aria-current={active ? "page" : undefined}
        className={`rounded-md px-3 py-2 text-sm font-medium transition ${
          active
            ? "bg-white/12 text-white"
            : "text-ink-100 hover:bg-white/8 hover:text-white"
        }`}
      >
        {label}
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-ink-50 text-ink-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="bg-ink-800 text-white shadow-sm dark:bg-ink-900/70">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          {/* Marca */}
          <button
            type="button"
            onClick={() => onNavigate("dashboard")}
            className="flex items-center gap-2 rounded-md hover:bg-white/10"
            aria-label="Ir para o painel principal"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-7 w-7">
              <path
                d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5l8-3z"
                fill="#16324f"
                stroke="#c9a227"
                strokeWidth="1.4"
              />
              <path
                d="M8.5 12l2.3 2.4 4.7-5"
                fill="none"
                stroke="#c9a227"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <span className="text-lg font-semibold tracking-tight">
              Judi<span className="text-gold-400">Files</span>
            </span>
          </button>

          {/* Navegação */}
          <nav className="flex flex-1 items-center gap-1" aria-label="Principal">
            {navItem("dashboard", "Painel")}
            {navItem("history", "Histórico")}
            {navItem("cases", "Pastas")}
          </nav>

          {/* Ações */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggle}
              aria-pressed={dark}
              className="rounded-md border border-white/25 px-3 py-1.5 text-sm text-ink-100 hover:bg-white/10"
            >
              {dark ? "☀️ Claro" : "🌙 Escuro"}
            </button>

            {user?.authenticated ? (
              <button
                type="button"
                onClick={onSecurity}
                title="Segurança da conta (2FA)"
                className="hidden rounded-md border border-white/25 px-3 py-1.5 text-sm text-ink-100 hover:bg-white/10 sm:block"
              >
                🛡 Segurança
              </button>
            ) : (
              <span
                title="Backend atendendo sem sessão — exclusivo de desenvolvimento"
                className="hidden rounded-full bg-amber-400/20 px-2 py-1 text-[11px] font-medium text-amber-200 sm:block"
              >
                modo desenvolvimento
              </span>
            )}

            <span className="hidden max-w-[14rem] truncate text-xs text-ink-100 md:block">
              {user?.email}
            </span>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md bg-white/12 px-3 py-1.5 text-sm font-medium text-white hover:bg-white/20"
            >
              Sair
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6">{children}</main>

      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        JudiFiles — documentos jurídicos tratados com sigilo. Arquivos cifrados e
        expurgados automaticamente em 24 h.
      </footer>
    </div>
  );
}
