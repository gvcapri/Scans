import { useEffect, useState } from "react";
import { auth, type AuthUser } from "./api/client";
import Layout, { type Route } from "./components/Layout";
import SecurityModal from "./components/SecurityModal";
import Batch from "./pages/Batch";
import Cases from "./pages/Cases";
import Compare from "./pages/Compare";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import PjeStudio, { type StudioPreset } from "./pages/PjeStudio";
import Search from "./pages/Search";
import SecurityPage from "./pages/Security";
import Tool from "./pages/Tool";

/** Ferramentas com página própria (Fase 4) em vez do gerador genérico. */
const CUSTOM_PAGES = ["search", "compare", "batch"];

type Session = {
  status: "loading" | "anon" | "dev" | "authed";
  user: AuthUser | null;
};

/**
 * Roteamento simples em estado (sem dependência de router) + guarda de
 * sessão (Fase 5): sem sessão (ou após "Sair") mostra a tela de acesso.
 * `dev` = backend atendeu sem sessão (fallback de desenvolvimento).
 */
export default function App() {
  const [route, setRoute] = useState<Route>("dashboard");
  const [session, setSession] = useState<Session>({ status: "loading", user: null });
  const [securityOpen, setSecurityOpen] = useState(false);
  // Visitante sem sessão vê a landing pública; `pendingRoute` guarda a
  // rota que ele tentou abrir (cadeado) para voltar a ela após o login.
  const [view, setView] = useState<"landing" | "login">("landing");
  const [loginMode, setLoginMode] = useState<"login" | "register">("login");
  const [pendingRoute, setPendingRoute] = useState<Route | null>(null);
  // presets do Dashboard que abrem o Estúdio PJe já configurado
  const [studioPreset, setStudioPreset] = useState<StudioPreset | null>(null);
  const back = () => setRoute("dashboard");

  const openStudio = (preset: StudioPreset) => {
    setStudioPreset(preset);
    setRoute("pje");
  };

  useEffect(() => {
    auth
      .me()
      .then((user) =>
        setSession({ status: user.authenticated ? "authed" : "dev", user })
      )
      .catch(() => setSession({ status: "anon", user: null }));
  }, []);

  const logout = async () => {
    try {
      await auth.logout();
    } catch {
      /* cookie já ausente — segue para a tela de acesso */
    }
    setSecurityOpen(false);
    setRoute("dashboard");
    setPendingRoute(null);
    setView("landing");
    setSession({ status: "anon", user: null });
  };

  if (session.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 text-sm text-slate-500 dark:bg-slate-950">
        Carregando…
      </div>
    );
  }

  if (session.status === "anon") {
    // Sem sessão: landing pública; a partir dela, o cadeado leva ao login
    // e o login devolve o usuário à rota que ele tentou abrir (return-to).
    if (view === "login") {
      return (
        <Login
          initialMode={loginMode}
          onBack={() => setView("landing")}
          onAuthenticated={(user) => {
            setSession({ status: "authed", user });
            if (pendingRoute) {
              setRoute(pendingRoute);
              setPendingRoute(null);
            }
            setView("landing");
          }}
        />
      );
    }
    return (
      <Landing
        onEnter={(target, mode) => {
          setPendingRoute(target);
          setLoginMode(mode ?? "login");
          setView("login");
        }}
      />
    );
  }

  return (
    <Layout
      route={route}
      onNavigate={setRoute}
      user={session.user}
      onLogout={logout}
      onSecurity={() => setSecurityOpen(true)}
    >
      {route === "dashboard" && (
        <Dashboard onNavigate={setRoute} onOpenStudio={openStudio} />
      )}
      {route === "pje" && (
        <PjeStudio
          preset={studioPreset}
          onNavigate={setRoute}
          onPresetApplied={() => setStudioPreset(null)}
        />
      )}
      {route === "security" && (
        <SecurityPage
          user={session.user}
          onOpenAccount={() => setSecurityOpen(true)}
        />
      )}
      {route === "history" && <History onOpenTool={(id) => setRoute({ tool: id })} />}
      {route === "cases" && <Cases />}
      {typeof route === "object" && route.tool === "search" && <Search onBack={back} />}
      {typeof route === "object" && route.tool === "compare" && <Compare onBack={back} />}
      {typeof route === "object" && route.tool === "batch" && <Batch onBack={back} />}
      {typeof route === "object" &&
        !CUSTOM_PAGES.includes(route.tool) && (
          <Tool toolId={route.tool} onBack={back} />
        )}

      {securityOpen && session.user && (
        <SecurityModal
          user={session.user}
          onClose={() => setSecurityOpen(false)}
          onUserChange={(user) => setSession((s) => ({ ...s, user }))}
        />
      )}
    </Layout>
  );
}
