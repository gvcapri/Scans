import type { ReactNode } from "react";
import type { AuthUser } from "../api/client";
import Header from "./Header";

export type Route =
  | "dashboard"
  | "pje"
  | "history"
  | "security"
  | "cases"
  | { tool: string };

type Props = {
  route: Route;
  onNavigate: (route: Route) => void;
  children: ReactNode;
  user: AuthUser | null;
  onLogout: () => void;
  onSecurity: () => void;
};

/**
 * Estrutura da aplicação: barra superior (Header) + conteúdo em canvas
 * claro (#F8FAFC) + rodapé institucional discreto.
 *
 * O botão `onSecurity` continua existindo na interface de props (usado
 * pela página Segurança & LGPD para abrir o modal da conta), mas a
 * navegação principal vive nas abas do Header.
 */
export default function Layout({ route, onNavigate, children, user, onLogout }: Props) {
  return (
    <div className="flex min-h-screen flex-col bg-canvas text-navy-900">
      <Header route={route} onNavigate={onNavigate} user={user} onLogout={onLogout} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>

      <footer className="border-t border-line bg-white py-5">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 text-center text-xs text-slate-500 sm:flex-row sm:text-left">
          <span>
            JudiFiles — Direito mais digital. Justiça mais acessível. v1.0.0
          </span>
          <span>
            Documentos cifrados em repouso e expurgados automaticamente em 24 h ·
            conformidade LGPD
          </span>
        </div>
      </footer>
    </div>
  );
}
