import { useEffect, useState } from "react";
import { api, type Tool } from "../api/client";
import type { Route } from "../components/Layout";

type Props = {
  /** Clique numa ferramenta (cadeado) ou no "Entrar": pede login e volta pra cá. */
  onEnter: (route: Route | null) => void;
};

const DESTAQUES = [
  {
    icon: "🔒",
    title: "Cifrado em repouso",
    text: "Cada arquivo é gravado com criptografia por usuário — nem o disco expõe o documento.",
  },
  {
    icon: "⏱️",
    title: "Expurgo automático",
    text: "Tudo é apagado em 24 horas, sem ação manual — regra de retenção alinhada à LGPD.",
  },
  {
    icon: "🛡️",
    title: "Acesso com 2FA",
    text: "Conta protegida por senha e verificação em duas etapas pelo app autenticador.",
  },
];

/**
 * Apresentação pública (Fase de produção): quem chega sem sessão vê esta
 * página em vez de uma tela de login crua. As ferramentas ficam atrás do
 * cadeado — clicar pede login e, depois da autenticação, o usuário cai
 * exatamente na ferramenta que tentou abrir (return-to).
 */
export default function Landing({ onEnter }: Props) {
  const [tools, setTools] = useState<Tool[]>([]);

  useEffect(() => {
    api
      .tools()
      .then((r) => setTools(r.tools))
      .catch(() => setTools([])); // catálogo indisponível: landing continua no ar
  }, []);

  return (
    <div className="min-h-screen bg-ink-50 text-ink-900 dark:bg-slate-950 dark:text-slate-100">
      {/* Cabeçalho */}
      <header className="bg-ink-800 text-white dark:bg-ink-900/70">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
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
          </div>
          <button
            type="button"
            onClick={() => onEnter(null)}
            className="rounded-md bg-white/12 px-4 py-1.5 text-sm font-medium text-white hover:bg-white/20"
          >
            Entrar
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 py-14 text-center">
        <p className="mb-3 text-sm font-medium uppercase tracking-widest text-gold-600 dark:text-gold-400">
          Documentos jurídicos com sigilo
        </p>
        <h1 className="mx-auto max-w-3xl text-3xl font-semibold leading-tight text-ink-800 sm:text-4xl dark:text-slate-100">
          Converta, redija, compare e organize PDFs sem tirar o arquivo do
          seu controle
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base dark:text-slate-400">
          Tudo processado com armazenamento cifrado, isolamento por usuário e
          expurgo automático em 24 horas. Crie sua conta e comece em segundos.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => onEnter(null)}
            className="rounded-md bg-ink-800 px-6 py-2.5 text-sm font-medium text-white transition hover:bg-ink-700 dark:bg-gold-500 dark:text-slate-900 dark:hover:bg-gold-400"
          >
            Entrar na conta
          </button>
          <button
            type="button"
            onClick={() => onEnter(null)}
            className="rounded-md border border-slate-300 px-6 py-2.5 text-sm font-medium text-ink-800 transition hover:border-gold-400 dark:border-slate-700 dark:text-slate-200"
          >
            Criar conta
          </button>
        </div>
      </section>

      {/* Selos de segurança */}
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-12 sm:grid-cols-3">
        {DESTAQUES.map((d) => (
          <div
            key={d.title}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="mb-2 text-xl">{d.icon}</div>
            <h2 className="text-sm font-semibold text-ink-800 dark:text-slate-100">
              {d.title}
            </h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {d.text}
            </p>
          </div>
        ))}
      </section>

      {/* Catálogo de ferramentas (atrás do cadeado) */}
      <section className="mx-auto max-w-6xl px-4 pb-16">
        <h2 className="text-xl font-semibold text-ink-800 dark:text-slate-100">
          Ferramentas
        </h2>
        <p className="mb-5 mt-1 text-sm text-slate-600 dark:text-slate-400">
          Clique para entrar. Recursos ainda não liberados aparecem como{" "}
          <strong>Em breve</strong>.
        </p>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tools.map((tool) => {
            const disabled = !tool.available;
            return (
              <button
                key={tool.id}
                type="button"
                disabled={disabled}
                onClick={() => onEnter({ tool: tool.id })}
                aria-describedby={`landing-${tool.id}-desc`}
                className={`group flex flex-col rounded-xl border p-4 text-left transition ${
                  disabled
                    ? "cursor-not-allowed border-dashed border-slate-300 bg-slate-100/60 dark:border-slate-700 dark:bg-slate-900/40"
                    : "border-slate-200 bg-white shadow-sm hover:-translate-y-0.5 hover:border-gold-400 hover:shadow-md dark:border-slate-800 dark:bg-slate-900"
                }`}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <span
                    className={`text-base font-semibold ${
                      disabled
                        ? "text-slate-500 dark:text-slate-500"
                        : "text-ink-800 dark:text-slate-100"
                    }`}
                  >
                    {tool.name}
                  </span>
                  <span
                    title={
                      disabled && tool.phase
                        ? `Recurso previsto para a Fase ${tool.phase}`
                        : undefined
                    }
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      disabled
                        ? "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                    }`}
                  >
                    {disabled ? "Em breve" : "Disponível"}
                  </span>
                </div>
                <p
                  id={`landing-${tool.id}-desc`}
                  className="text-sm text-slate-600 dark:text-slate-400"
                >
                  {tool.description}
                </p>
                {!disabled && (
                  <span className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-gold-600 dark:text-gold-400">
                    🔒 Entrar para usar
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <footer className="border-t border-slate-200 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        JudiFiles — documentos jurídicos tratados com sigilo. Arquivos cifrados e
        expurgados automaticamente em 24 h.
      </footer>
    </div>
  );
}
