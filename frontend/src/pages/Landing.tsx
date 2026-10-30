import { useEffect, useState } from "react";
import { ArrowRight, Clock3, Lock, Scale, ShieldCheck } from "lucide-react";
import { api, type Tool } from "../api/client";
import type { Route } from "../components/Layout";

type Props = {
  /** Clique numa ferramenta (cadeado) ou no "Entrar": pede login e volta pra cá. */
  onEnter: (route: Route | null, mode?: "login" | "register") => void;
};

const DESTAQUES = [
  {
    icon: Lock,
    title: "Cifrado em repouso",
    text: "Cada arquivo é gravado com criptografia por usuário — nem o disco expõe o documento.",
    tag: "AES-256",
  },
  {
    icon: Clock3,
    title: "Expurgo automático",
    text: "Tudo é apagado em 24 horas, sem ação manual — regra de retenção alinhada à LGPD.",
    tag: "24 horas",
  },
  {
    icon: ShieldCheck,
    title: "Acesso com 2FA",
    text: "Conta protegida por senha e verificação em duas etapas pelo app autenticador.",
    tag: "2 etapas",
  },
];

/**
 * Apresentação pública: quem chega sem sessão vê esta página em vez de uma
 * tela de login crua. Visual executivo claro do JudiFiles (canvas slate,
 * cartões brancos, azul-marinho e âmbar). As ferramentas ficam atrás do
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
    <div className="min-h-screen bg-canvas text-navy-900">
      {/* Cabeçalho */}
      <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
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
          </div>
          <button
            type="button"
            onClick={() => onEnter(null, "login")}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-navy-900 transition hover:border-slate-300 hover:bg-slate-50"
          >
            Entrar
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 py-14 text-center">
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-amber-600">
          Documentos jurídicos com sigilo
        </p>
        <h1 className="mx-auto max-w-3xl text-3xl font-bold leading-tight tracking-tight text-navy-900 sm:text-4xl">
          Converta, redija, compare e organize PDFs sem tirar o arquivo do
          seu controle
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-sm text-slate-600 sm:text-base">
          Tudo processado com armazenamento cifrado, isolamento por usuário e
          expurgo automático em 24 horas. Crie sua conta e comece em segundos.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => onEnter(null, "login")}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
          >
            Entrar na conta
            <ArrowRight className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => onEnter(null, "register")}
            className="rounded-lg border border-line bg-white px-6 py-3 text-sm font-semibold text-navy-900 transition hover:border-slate-300 hover:bg-slate-50"
          >
            Criar conta
          </button>
        </div>
      </section>

      {/* Selos de segurança */}
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-12 sm:grid-cols-3">
        {DESTAQUES.map((d) => {
          const Icon = d.icon;
          return (
            <article
              key={d.title}
              className="rounded-xl border border-line bg-white p-5 shadow-card"
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                  <Icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  {d.tag}
                </span>
              </div>
              <h2 className="text-sm font-semibold text-navy-900">{d.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">
                {d.text}
              </p>
            </article>
          );
        })}
      </section>

      {/* Catálogo de ferramentas (atrás do cadeado) */}
      <section className="mx-auto max-w-6xl px-4 pb-16">
        <h2 className="text-xl font-bold tracking-tight text-navy-900">
          Ferramentas
        </h2>
        <p className="mb-5 mt-1 text-sm text-slate-600">
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
                    ? "cursor-not-allowed border-dashed border-slate-300 bg-slate-50 opacity-70"
                    : "border-line bg-white shadow-card hover:-translate-y-0.5 hover:border-blue-700 hover:shadow-card-hover"
                }`}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <span
                    className={`text-base font-semibold ${
                      disabled ? "text-slate-500" : "text-navy-900"
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
                        ? "bg-slate-200 text-slate-600"
                        : "bg-emerald-50 text-emerald-600"
                    }`}
                  >
                    {disabled ? "Em breve" : "Disponível"}
                  </span>
                </div>
                <p id={`landing-${tool.id}-desc`} className="text-sm text-slate-600">
                  {tool.description}
                </p>
                {!disabled && (
                  <span className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-600">
                    <Lock className="h-3.5 w-3.5" aria-hidden />
                    Entrar para usar
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <footer className="border-t border-line bg-white py-6 text-center text-xs text-slate-500">
        JudiFiles — Direito mais digital. Justiça mais acessível. v1.0.0 ·
        Arquivos cifrados e expurgados automaticamente em 24 h.
      </footer>
    </div>
  );
}
