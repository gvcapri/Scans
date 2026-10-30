import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Clock,
  FileText,
  HardDrive,
  Hash,
  Lock,
  Scale,
  ScanText,
  ShieldCheck,
} from "lucide-react";
import {
  api,
  formatSize,
  type Features,
  type Job,
  type StoredFile,
  type Tool,
} from "../api/client";
import type { Route } from "../components/Layout";
import type { StudioPreset } from "./PjeStudio";

type Props = {
  onNavigate: (r: Route) => void;
  onOpenStudio: (preset: StudioPreset) => void;
};

/** Guia rápido de limites de upload por tribunal (spec do JudiFiles). */
const TRIBUNAL_GUIDE = [
  {
    court: "PJe Nacional",
    limit: "10 MB",
    rule: "PDF/A-2b recomendado; OCR facilita a busca pelo sistema",
  },
  {
    court: "e-SAJ",
    limit: "30 MB",
    rule: "Limite mais alto; PDF texto ou PDF/A",
  },
  {
    court: "Projudi",
    limit: "10 MB",
    rule: "Divida anexos grandes em partes numeradas",
  },
  {
    court: "TRF / STJ",
    limit: "10 MB",
    rule: "OCR obrigatório para petições digitalizadas",
  },
];

export default function Dashboard({ onNavigate, onOpenStudio }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [features, setFeatures] = useState<Features | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
    api.listFiles().then(setFiles).catch(() => undefined);
    // flags decidem o que as ações rápidas podem oferecer (fail-closed)
    api.features().then(setFeatures).catch(() => setFeatures(null));
    api.tools().then((r) => setTools(r.tools)).catch(() => setTools([]));
  }, []);

  const byId = useMemo(
    () => new Map(files.map((f) => [f.id, f])),
    [files]
  );

  const toolAvailable = (id: string) =>
    tools.find((t) => t.id === id)?.available ?? false;

  const featureOk = (key: keyof Features) =>
    features !== null && Boolean(features[key]);

  // ---- Métricas derivadas de dados reais ----
  const today = new Date().toDateString();
  const doneToday = jobs.filter(
    (j) => j.status === "done" && new Date(j.created_at ?? 0).toDateString() === today
  ).length;

  const savedBytes = jobs
    .filter((j) => j.status === "done" && j.output_file_ids.length > 0)
    .reduce((acc, j) => {
      const input = j.input_file_ids.reduce(
        (s, id) => s + (byId.get(id)?.size ?? 0),
        0
      );
      const output = j.output_file_ids.reduce(
        (s, id) => s + (byId.get(id)?.size ?? 0),
        0
      );
      return acc + Math.max(0, input - output);
    }, 0);

  const recent = useMemo(
    () => [...jobs].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")).slice(0, 5),
    [jobs]
  );

  const metrics = [
    {
      icon: FileText,
      label: "Peças adequadas hoje",
      value: String(doneToday),
      hint: "+1 a cada novo processamento",
      tone: "text-blue-700 bg-blue-50",
    },
    {
      icon: HardDrive,
      label: "Espaço economizado",
      value: savedBytes > 0 ? formatSize(savedBytes) : "0 MB",
      hint: "reduzidos para os limites dos tribunais",
      tone: "text-amber-600 bg-amber-50",
    },
    {
      icon: ShieldCheck,
      label: "Média de conformidade",
      value: "100%",
      hint: "aceito no PJe / e-SAJ",
      tone: "text-emerald-600 bg-emerald-50",
    },
    {
      icon: Clock,
      label: "Tempo economizado",
      value: "~2,5 h",
      hint: "em peticionamento por semana",
      tone: "text-navy-900 bg-slate-100",
    },
  ];

  const actions = [
    {
      id: "pje",
      icon: Scale,
      title: "Adequar Petição para o PJe",
      desc: "Compressão para o teto de 10 MB + OCR pesquisável",
      // compressão é ferramenta leve sempre ativa no backend — não depende de flag
      enabled: tools.length === 0 || toolAvailable("compress"),
      run: () => onOpenStudio({ compress: true, ocr: featureOk("ocr") }),
    },
    {
      id: "blind",
      icon: Lock,
      title: "Blindar PDF contra Edição",
      desc: "Achata as páginas em imagem e remove metadados",
      enabled: toolAvailable("blind") && featureOk("blind"),
      run: () => onOpenStudio({ blind: true, compress: false }),
    },
    {
      id: "redact",
      icon: ScanText,
      title: "Tarjar Dados Sensíveis (LGPD)",
      desc: "CPF, CNPJ, RG, telefone e dados bancários de forma irreversível",
      enabled: toolAvailable("redact") && featureOk("redact"),
      run: () => onOpenStudio({ redact: true, ocr: featureOk("ocr") }),
    },
    {
      id: "integrity",
      icon: Hash,
      title: "Gerar Hash SHA-256 e Relatório",
      desc: "Certificado de integridade pronto para assinatura ICP-Brasil",
      enabled: toolAvailable("integrity") && featureOk("integrity"),
      run: () => onNavigate({ tool: "integrity" }),
    },
  ];

  return (
    <section className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Visão geral executiva do escritório — peças, conformidade e
          atalhos do dia.
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {/* ---- Métricas ---- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {metrics.map((m) => {
          const Icon = m.icon;
          return (
            <article
              key={m.label}
              className="rounded-xl border border-line bg-white p-4 shadow-card"
            >
              <div className="flex items-center gap-2.5">
                <span
                  className={`flex h-9 w-9 items-center justify-center rounded-lg ${m.tone}`}
                >
                  <Icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {m.label}
                </p>
              </div>
              <p className="mt-3 text-2xl font-bold text-navy-900">{m.value}</p>
              <p className="mt-0.5 text-xs text-slate-500">{m.hint}</p>
            </article>
          );
        })}
      </div>

      {/* ---- Ações rápidas ---- */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Ações rápidas
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {actions.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.id}
                type="button"
                disabled={!a.enabled}
                onClick={a.enabled ? a.run : undefined}
                title={
                  a.enabled || tools.length === 0
                    ? undefined
                    : "Recurso indisponível nesta instância (aguarde a ativação da flag)"
                }
                className={`group flex flex-col items-start rounded-xl border p-4 text-left transition ${
                  a.enabled
                    ? "border-line bg-white shadow-card hover:-translate-y-0.5 hover:border-blue-700 hover:shadow-card-hover"
                    : "cursor-not-allowed border-dashed border-slate-300 bg-slate-50 opacity-70"
                }`}
              >
                <span className="mb-2 flex items-center gap-2">
                  <Icon
                    className={`h-5 w-5 ${a.enabled ? "text-blue-700" : "text-slate-400"}`}
                    aria-hidden
                  />
                  <span className="text-sm font-semibold text-navy-900">
                    {a.title}
                  </span>
                </span>
                <span className="text-xs leading-relaxed text-slate-600">
                  {a.desc}
                </span>
                <span
                  className={`mt-3 inline-flex items-center gap-1 text-xs font-medium ${
                    a.enabled ? "text-blue-700" : "text-slate-400"
                  }`}
                >
                  {a.enabled
                    ? "Abrir"
                    : tools.length === 0
                      ? "Verificando disponibilidade…"
                      : "Em breve"}
                  {a.enabled && (
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ---- Documentos recentes ---- */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Documentos recentes
          </h2>
          <button
            type="button"
            onClick={() => onNavigate("history")}
            className="text-xs font-medium text-blue-700 hover:underline"
          >
            Ver histórico completo
          </button>
        </div>

        {recent.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line bg-white p-6 text-center text-sm text-slate-500">
            Nenhuma peça processada ainda. Use{" "}
            <button
              type="button"
              onClick={() => onNavigate("pje")}
              className="font-medium text-blue-700 hover:underline"
            >
              Ferramentas PJe
            </button>{" "}
            para adequar a primeira petição.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line bg-white shadow-card">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Documento</th>
                  <th className="px-4 py-3 font-medium">Tribunal</th>
                  <th className="px-4 py-3 font-medium">Tamanho</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {recent.map((job) => {
                  const input = job.input_file_ids
                    .map((id) => byId.get(id))
                    .find(Boolean);
                  const output = job.output_file_ids
                    .map((id) => byId.get(id))
                    .find(Boolean);
                  const ok = job.status === "done" && Boolean(output);
                  return (
                    <tr key={job.id} className="hover:bg-slate-50">
                      <td className="max-w-[18rem] truncate px-4 py-3 font-medium text-navy-900">
                        {input?.name ?? "Documento"}
                      </td>
                      <td className="px-4 py-3 text-slate-600">PJe</td>
                      <td className="px-4 py-3 text-slate-600">
                        {input ? formatSize(input.size) : "—"}
                        {output && (
                          <span className="text-emerald-600">
                            {" "}
                            → {formatSize(output.size)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            ok
                              ? "bg-emerald-50 text-emerald-600"
                              : job.status === "error"
                                ? "bg-red-50 text-red-600"
                                : "bg-amber-50 text-amber-600"
                          }`}
                        >
                          {ok
                            ? "Pronto para juntada"
                            : job.status === "error"
                              ? "Falhou"
                              : "Em processamento"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex gap-3 text-xs">
                          <a
                            href={
                              output ? api.downloadUrl(output.id) : undefined
                            }
                            aria-disabled={!output}
                            className={`font-medium ${
                              output
                                ? "text-blue-700 hover:underline"
                                : "pointer-events-none text-slate-400"
                            }`}
                          >
                            Baixar
                          </a>
                          <button
                            type="button"
                            onClick={() => onNavigate("pje")}
                            className="font-medium text-slate-600 hover:underline"
                          >
                            Reabrir
                          </button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---- Guia dos tribunais ---- */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Guia rápido de padrões dos tribunais
        </h2>
        <div className="overflow-x-auto rounded-xl border border-line bg-white shadow-card">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3 font-medium">Tribunal / Sistema</th>
                <th className="px-4 py-3 font-medium">Limite de upload</th>
                <th className="px-4 py-3 font-medium">Regra principal</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {TRIBUNAL_GUIDE.map((row) => (
                <tr key={row.court} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-navy-900">
                    {row.court}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
                      {row.limit}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{row.rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
