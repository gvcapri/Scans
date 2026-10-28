import { useState } from "react";
import Layout, { type Route } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Tool from "./pages/Tool";

/**
 * Roteamento simples em estado (sem dependência de router):
 * painel → ferramenta → histórico.
 */
export default function App() {
  const [route, setRoute] = useState<Route>("dashboard");

  return (
    <Layout route={route} onNavigate={setRoute}>
      {route === "dashboard" && <Dashboard onNavigate={setRoute} />}
      {route === "history" && <History onOpenTool={(id) => setRoute({ tool: id })} />}
      {typeof route === "object" && (
        <Tool toolId={route.tool} onBack={() => setRoute("dashboard")} />
      )}
    </Layout>
  );
}
