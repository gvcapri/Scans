import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Aplica APENAS o tema escolhido manualmente antes da primeira renderização.
// O design system é executivo claro: o tema escuro do SO não é mais herdado
// automaticamente (deixava login/landing ilegíveis em maquina escura) — o
// botão de tema no menu do usuário continua alternando quando pedido.
const saved = localStorage.getItem("lexscan-theme");
if (saved === "dark") {
  document.documentElement.classList.add("dark");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
