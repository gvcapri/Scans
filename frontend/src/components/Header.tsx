import { useEffect, useRef, useState } from "react";
import { ChevronDown, LayoutDashboard, LogOut, Moon, Scale, ShieldCheck, Sun, Wrench } from "lucide-react";
import type { AuthUser } from "../api/client";
import type { Route } from "./Layout";
import { useTheme } from "../hooks";

type Props = {
  route: Route;
  onNavigate: (route: Route) => void;
  user: AuthUser | null;
  onLogout: () => void;
};

/** Abas principais do aplicativo (spec: Dashboard, Ferramentas PJe,
 *  Histórico, Segurança & LGPD). */
const TABS: { id: Route; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "pje", label: "Ferramentas PJe", icon: Wrench },
  { id: "history", label: "Histórico", icon: Scale },
  { id: "security", label: "Segurança & LGPD", icon: ShieldCheck },
];

function isActive(route: Route, id: Route): boolean {
  if (typeof id === "string") return route === id;
  return typeof route === "object";
}

/**
 * Barra superior: marca + slogan à esquerda, abas de navegação no centro
 * e menu de usuário (avatar, nome, dropdown de conta) à direita.
 */
export default function Header({ route, onNavigate, user, onLogout }: Props) {
  const { dark, toggle } = useTheme();
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // fecha o dropdown ao clicar fora (ou Esc)
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const initials = (user?.email ?? "?")
    .split("@")[0]
    .split(/[._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4">
        {/* Marca */}
        <button
          type="button"
          onClick={() => onNavigate("dashboard")}
          className="flex items-center gap-2.5 text-left"
          aria-label="Ir para o Dashboard"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy-900 text-amber-600">
            <Scale className="h-5 w-5" aria-hidden />
          </span>
          <span className="leading-tight">
            <span className="block text-lg font-bold tracking-tight text-navy-900">
              Judi<span className="text-amber-600">Files</span>
            </span>
            <span className="hidden text-[11px] text-slate-500 sm:block">
              Tecnologia a serviço da Justiça
            </span>
          </span>
        </button>

        {/* Abas centrais */}
        <nav className="mx-auto flex items-center gap-1" aria-label="Navegação principal">
          {TABS.map((tab) => {
            const active = isActive(route, tab.id);
            const Icon = tab.icon;
            return (
              <button
                key={String(tab.id)}
                type="button"
                onClick={() => onNavigate(tab.id)}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  active
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-navy-900"
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden />
                <span className="hidden md:inline">{tab.label}</span>
                <span className="md:hidden">{tab.label.split(" ")[0]}</span>
              </button>
            );
          })}
        </nav>

        {/* Menu de usuário */}
        <div className="relative flex items-center gap-2" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenu((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menu}
            className="flex items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-left transition hover:border-slate-300 hover:bg-slate-50"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-navy-900 text-xs font-semibold text-white">
              {initials || "?"}
            </span>
            <span className="hidden leading-tight sm:block">
              <span className="block max-w-[12rem] truncate text-sm font-medium text-navy-900">
                {user?.email ?? "Visitante"}
              </span>
              <span className="block text-[11px] text-slate-500">
                {user?.two_factor_enabled ? "Conta com 2FA" : "Conta protegida"}
              </span>
            </span>
            <ChevronDown className="h-4 w-4 text-slate-400" aria-hidden />
          </button>

          {menu && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-2 w-60 overflow-hidden rounded-xl border border-line bg-white shadow-card-hover"
            >
              <div className="border-b border-line px-4 py-3">
                <p className="truncate text-sm font-medium text-navy-900">{user?.email}</p>
                <p className="text-xs text-slate-500">
                  {user?.two_factor_enabled ? "2FA ativo" : "2FA disponível"}
                </p>
              </div>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  onNavigate("security");
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                <ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden />
                Segurança &amp; LGPD
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  toggle();
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                {dark ? (
                  <Sun className="h-4 w-4 text-amber-600" aria-hidden />
                ) : (
                  <Moon className="h-4 w-4 text-slate-500" aria-hidden />
                )}
                {dark ? "Tema claro" : "Tema escuro"}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  onLogout();
                }}
                className="flex w-full items-center gap-2 border-t border-line px-4 py-2.5 text-sm text-red-600 hover:bg-red-50"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                Sair da conta
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
