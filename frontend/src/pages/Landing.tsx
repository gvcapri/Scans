import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookMarked,
  Check,
  ChevronDown,
  CheckCircle2,
  EyeOff,
  FileCog,
  FileSearch,
  FileText,
  Fingerprint,
  GitCompare,
  Hash,
  Layers,
  ListChecks,
  Lock,
  Minimize2,
  Scale,
  ScanText,
  Scissors,
  ShieldCheck,
} from "lucide-react";
import { api, type Tool } from "../api/client";
import type { Route } from "../components/Layout";

type Props = {
  /** Clique numa ferramenta (cadeado) ou num CTA: pede login e volta pra cá. */
  onEnter: (route: Route | null, mode?: "login" | "register") => void;
};

/**
 * Catálogo de fallback (API offline): espelho do `/api/meta/tools` com as
 * flags de produção padrão — só as ferramentas leves (baseadas em PyMuPDF)
 * aparecem como disponíveis; tudo que depende de flag fica "Em breve".
 */
const DEFAULT_TOOLS: Tool[] = [
  { id: "split", name: "Dividir/Extrair", description: "Extrair páginas, por intervalos ou por metadado de um PDF.", available: true, phase: 2 },
  { id: "merge", name: "Mesclar PDFs", description: "Juntar vários PDFs na ordem escolhida, com sumário.", available: true, phase: 2 },
  { id: "compress", name: "Comprimir PDF", description: "Reduz o tamanho do PDF (Qualidade, PDF/A, divisão).", available: true, phase: 2 },
  { id: "number", name: "Numerar páginas", description: "Insere numeração automática (centro, canto, formato).", available: true, phase: 3 },
  { id: "numbering", name: "Numeração automática", description: "Aplica numeração automática (centro, canto, formato).", available: true, phase: 3 },
  { id: "outline", name: "Sumário (bookmarks)", description: "Gera ou reescreve o sumário do PDF a partir de uma tabela.", available: true, phase: 3 },
  { id: "metadata", name: "Metadados", description: "Ler/escrever título, autor, assunto, palavras-chave do PDF.", available: true, phase: 3 },
  { id: "convert", name: "Converter", description: "Imagem/PDF → PDF, Word → PDF, PDF → PNG/TXT/DOCX.", available: false, phase: 2 },
  { id: "redact", name: "Redigir PDF", description: "Tarja irreversível de dados sensíveis (CPF, CNPJ, cartões, e-mail...).", available: false, phase: 3 },
  { id: "blind", name: "PDF Blindado", description: "Achata o PDF em imagem (nada de edição, metadados zerados).", available: false, phase: 5 },
  { id: "integrity", name: "Certificado de integridade", description: "Gera SHA-256 e lê/escreve metadados de assinatura de documento.", available: false, phase: 5 },
  { id: "search", name: "Busca full-text", description: "Procura no texto extraído de todos os PDFs do usuário.", available: false, phase: 4 },
  { id: "compare", name: "Comparação lado a lado", description: "Diff de duas versões do mesmo documento por texto.", available: false, phase: 4 },
  { id: "batch", name: "Lote", description: "Aplica uma sequência de passos (PCA, OCR, compressão...) a vários PDFs.", available: false, phase: 4 },
];

/** Ícone representativo por ferramenta. */
const TOOL_ICONS: Record<string, typeof FileText> = {
  convert: FileText,
  split: Scissors,
  merge: Layers,
  compress: Minimize2,
  redact: EyeOff,
  number: Hash,
  numbering: Hash,
  outline: BookMarked,
  metadata: FileCog,
  search: FileSearch,
  compare: GitCompare,
  batch: ListChecks,
  blind: ShieldCheck,
  integrity: Fingerprint,
  ocr: ScanText,
};

const TRIBUNALS = [
  {
    name: "PJe Nacional",
    scope: "TRT, TJ e TRF",
    limit: "10 MB",
    rule: "Limite oficial de 10 MB por peça/anexo, com exigência de PDF/A e texto indexável (pesquisável).",
  },
  {
    name: "e-SAJ",
    scope: "TJSP e outros tribunais",
    limit: "30 MB",
    rule: "Limite de 30 MB por petição intermediária; resolução máxima recomendada de 200 DPI.",
  },
  {
    name: "Projudi",
    scope: "TJMG, TJRS e demais",
    limit: "10 MB",
    rule: "Limite de 10 MB por arquivo com fatiamento sequencial obrigatório dos anexos.",
  },
  {
    name: "TRF / STJ",
    scope: "Justiça Federal e Superior",
    limit: "10 MB",
    rule: "10 MB com OCR obrigatório, sob pena de devolução do processo para regularização.",
  },
];

const FAQ = [
  {
    q: "Os tribunais aceitam os documentos gerados pelo JudiFiles sem restrições?",
    a: "Sim. O formato gerado é o PDF/A recomendado pelo CNJ, aceito no PJe, e-SAJ, Projudi, TRF e STJ. A compressão respeita o teto de cada sistema e, quando a peça excede o limite, o arquivo é fatiado em partes numeradas.",
  },
  {
    q: "Meus documentos e dados de clientes ficam salvos na plataforma?",
    a: "Não. Todos os arquivos são expurgados automaticamente em 24 horas — incluindo índices, miniaturas e pré-visualizações — sem necessidade de ação manual. Não usamos seus documentos para treinar modelos nem os lemos para nenhum fim.",
  },
  {
    q: "Qual a diferença do JudiFiles para compressores comuns de PDF?",
    a: "Compressores comuns destroem a legibilidade e removem a camada de OCR. O JudiFiles preserva a nitidez de certidões, carimbos e assinaturas enquanto reduz o peso, mantendo o texto pesquisável e o padrão PDF/A.",
  },
  {
    q: "O OCR funciona em documentos escaneados e certidões antigas?",
    a: "Sim. Nosso motor de OCR reconhece caracteres em português (e inglês) mesmo em digitalizações antigas e adiciona uma camada invisível de texto pesquisável, sem alterar a aparência visual do documento.",
  },
];

const SECURITY = [
  {
    icon: ShieldCheck,
    title: "Criptografia Militar",
    text: "Arquivos cifrados em repouso com chave única por usuário (AES-256) e tráfego protegido por TLS — nem o disco do servidor expõe o documento.",
    tag: "AES-256",
  },
  {
    icon: Fingerprint,
    title: "Expurgo Automático em 24 Horas",
    text: "Destruição física em disco após o prazo da sessão: arquivos, índices, miniaturas e resultados intermediários somem sem ação manual.",
    tag: "24 horas",
  },
  {
    icon: Scale,
    title: "Sigilo Profissional da Advocacia",
    text: "Respeito absoluto ao art. 7º, II do Estatuto da OAB: nenhuma petição é lida por terceiros nem utilizada para treino de modelos.",
    tag: "Estatuto da OAB",
  },
];

const QUICK_PROOFS = [
  "Padrão PDF/A-1b e OCR",
  "Processamento Cifrado AES-256",
  "Expurgo em 24h sem rastro",
];

/**
 * Landing institucional e de conversão (Conceito Executivo Jurídico):
 * header fixo, hero de alta conversão com mockup antes/depois, painel de
 * limites dos tribunais, grade de ferramentas com status, segurança/LGPD,
 * FAQ e rodapé. Todos os CTAs passam por `onEnter` (return-to preservado).
 */
export default function Landing({ onEnter }: Props) {
  const [tools, setTools] = useState<Tool[]>(DEFAULT_TOOLS);
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  useEffect(() => {
    api
      .tools()
      .then((r) => setTools(r.tools))
      .catch(() => setTools(DEFAULT_TOOLS)); // API offline: catálogo padrão tipado
  }, []);

  const goToLimits = () =>
    document.getElementById("limites")?.scrollIntoView({ behavior: "smooth" });

  return (
    <div className="min-h-screen bg-canvas text-navy-900">
      {/* ============ A. Cabeçalho fixo ============ */}
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
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onEnter(null, "login")}
              className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-navy-900 transition hover:border-slate-300 hover:bg-slate-50"
            >
              Entrar
            </button>
            <button
              type="button"
              onClick={() => onEnter(null, "register")}
              className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600"
            >
              Criar conta
            </button>
          </div>
        </div>
      </header>

      {/* ============ B. Hero de alta conversão ============ */}
      <section className="mx-auto max-w-6xl px-4 pb-14 pt-12 sm:pt-16">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <div className="text-center lg:text-left">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-600/40 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-600">
              ⚖️ PADRÃO OFICIAL PARA TRIBUNAIS BRASILEIROS
            </span>

            <h1 className="mt-5 text-3xl font-bold leading-tight tracking-tight text-navy-900 sm:text-4xl xl:text-[2.75rem]">
              Nunca mais tenha uma petição rejeitada por tamanho ou falta de
              OCR.
            </h1>

            <p className="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
              Comprima, aplique OCR forense, junte, divida e blinde documentos
              jurídicos em conformidade estrita com o PJe, e-SAJ, Projudi, TRF
              e STJ, com total sigilo LGPD e respeito ao Estatuto da OAB.
            </p>

            <div className="mt-7 flex flex-wrap items-center justify-center gap-3 lg:justify-start">
              <button
                type="button"
                onClick={() => onEnter(null, "register")}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                Experimentar Agora
                <ArrowRight className="h-4 w-4" aria-hidden />
              </button>
              <button
                type="button"
                onClick={goToLimits}
                className="rounded-lg border border-line bg-white px-6 py-3 text-sm font-semibold text-navy-900 transition hover:border-slate-300 hover:bg-slate-50"
              >
                Ver Limites dos Tribunais
              </button>
            </div>

            <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs font-medium text-slate-600 lg:justify-start">
              {QUICK_PROOFS.map((proof) => (
                <li key={proof} className="inline-flex items-center gap-1.5">
                  <Check className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
                  {proof}
                </li>
              ))}
            </ul>
          </div>

          {/* ============ C. Mockup antes/depois ============ */}
          <div className="rounded-xl border border-line bg-white p-5 shadow-card">
            <div className="flex items-center gap-2 border-b border-line pb-3">
              <FileText className="h-4 w-4 text-blue-700" aria-hidden />
              <p className="truncate text-sm font-semibold text-navy-900">
                Apelação Cível com 14 Anexos e Certidões.pdf
              </p>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-line bg-slate-50 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  Antes
                </p>
                <p className="mt-1 text-2xl font-bold text-navy-900">28.4 MB</p>
                <span className="mt-2 inline-block rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-600">
                  Rejeitado no PJe — limite 10MB
                </span>
              </div>
              <div className="rounded-lg border border-emerald-600/30 bg-emerald-50 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-600">
                  Depois
                </p>
                <p className="mt-1 text-2xl font-bold text-navy-900">4.6 MB</p>
                <span className="mt-2 inline-block rounded-full bg-emerald-600 px-2 py-0.5 text-[11px] font-semibold text-white">
                  Aprovado no PJe, e-SAJ e TRF
                </span>
              </div>
            </div>

            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {[
                "OCR Pesquisável: Ativo",
                "Padrão: PDF/A-1b",
                "Tarjamento LGPD: Concluído",
                "Integridade: SHA-256",
              ].map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs font-medium text-navy-900"
                >
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ============ D. Padrões e limites dos tribunais ============ */}
      <section id="limites" className="border-t border-line bg-white py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">
            Padrões e limites dos tribunais
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Referência rápida das regras oficiais de upload do Judiciário
            brasileiro — o JudiFiles adequa cada peça ao teto do sistema
            escolhido.
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {TRIBUNALS.map((t) => (
              <article
                key={t.name}
                className="rounded-xl border border-line bg-white p-5 shadow-card"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-navy-900">{t.name}</h3>
                    <p className="text-xs text-slate-500">{t.scope}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-blue-700 px-2.5 py-1 text-xs font-semibold text-white">
                    {t.limit}
                  </span>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-slate-600">{t.rule}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ============ E. Grade de ferramentas ============ */}
      <section className="py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">
            Ferramentas
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Clique para entrar. Recursos ainda não liberados aparecem como{" "}
            <strong>Em breve</strong>.
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {tools.map((tool) => {
              const disabled = !tool.available;
              const Icon = TOOL_ICONS[tool.id] ?? FileText;
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
                    <span className="flex items-center gap-2">
                      <span
                        className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                          disabled
                            ? "bg-slate-200 text-slate-500"
                            : "bg-blue-700/10 text-blue-700"
                        }`}
                      >
                        <Icon className="h-4 w-4" aria-hidden />
                      </span>
                      <span
                        className={`text-base font-semibold ${
                          disabled ? "text-slate-500" : "text-navy-900"
                        }`}
                      >
                        {tool.name}
                      </span>
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
                  <p
                    id={`landing-${tool.id}-desc`}
                    className="text-sm text-slate-600"
                  >
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
        </div>
      </section>

      {/* ============ F. Segurança, sigilo e LGPD ============ */}
      <section className="border-t border-line bg-white py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">
            Segurança máxima, sigilo e LGPD
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Blindagem técnica pensada para o dever de sigilo do advogado.
          </p>

          <div className="mt-6 grid gap-4">
            {SECURITY.map((s) => {
              const Icon = s.icon;
              return (
                <article
                  key={s.title}
                  className="flex flex-col gap-3 rounded-xl border border-line bg-white p-5 shadow-card sm:flex-row sm:items-start"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-navy-900">{s.title}</h3>
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600">
                        {s.tag}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-relaxed text-slate-600">
                      {s.text}
                    </p>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============ G. FAQ jurídico ============ */}
      <section className="py-14">
        <div className="mx-auto max-w-3xl px-4">
          <h2 className="text-2xl font-bold tracking-tight text-navy-900">
            Perguntas frequentes
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Dúvidas essenciais do advogado antes de peticionar.
          </p>

          <div className="mt-6 space-y-3">
            {FAQ.map((item, i) => {
              const open = openFaq === i;
              return (
                <div
                  key={item.q}
                  className="rounded-xl border border-line bg-white shadow-card"
                >
                  <button
                    type="button"
                    onClick={() => setOpenFaq(open ? null : i)}
                    aria-expanded={open}
                    className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
                  >
                    <span className="text-sm font-semibold text-navy-900">
                      {item.q}
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${
                        open ? "rotate-180" : ""
                      }`}
                      aria-hidden
                    />
                  </button>
                  {open && (
                    <p className="border-t border-line px-5 py-4 text-sm leading-relaxed text-slate-600">
                      {item.a}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============ H. Rodapé institucional ============ */}
      <footer className="border-t border-line bg-white py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 text-center sm:flex-row sm:justify-between sm:text-left">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-navy-900 text-amber-600">
              <Scale className="h-4 w-4" aria-hidden />
            </span>
            <span className="text-sm font-semibold text-navy-900">
              Judi<span className="text-amber-600">Files</span> — Tecnologia a
              serviço da Justiça. v1.0.0
            </span>
          </div>
          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs">
            <a
              href="#termos"
              className="text-slate-600 transition hover:text-blue-700"
            >
              Termos de Uso
            </a>
            <a
              href="#privacidade"
              className="text-slate-600 transition hover:text-blue-700"
            >
              Política de Privacidade LGPD
            </a>
            <a
              href="mailto:suporte@judifiles.com.br"
              className="text-slate-600 transition hover:text-blue-700"
            >
              Contato / Suporte
            </a>
          </nav>
        </div>
        <p className="mt-4 text-center text-[11px] text-slate-500">
          Arquivos cifrados e expurgados automaticamente em 24 h ·
          conformidade LGPD
        </p>
      </footer>
    </div>
  );
}
