import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Download,
  FileText,
  Lock,
  RotateCw,
  ScanText,
  ShieldCheck,
  Trash2,
  UploadCloud,
  Wrench,
} from "lucide-react";
import {
  api,
  formatSize,
  type Features,
  type StoredFile,
  type Tool,
} from "../api/client";
import Dropzone from "../components/Dropzone";
import ProgressBar from "../components/ProgressBar";
import type { Route } from "../components/Layout";

/** Atalhos vindos do Dashboard (ex.: "Blindar PDF" já vem com a troca ligada). */
export type StudioPreset = {
  compress?: boolean;
  ocr?: boolean;
  blind?: boolean;
  redact?: boolean;
};

type Props = {
  preset?: StudioPreset | null;
  onNavigate: (r: Route) => void;
  /** avisa o App para limpar o preset depois de aplicado (evita reapplicar ao reabrir a aba). */
  onPresetApplied?: () => void;
};

type TribunalId = "pje" | "esaj" | "projudi" | "trf";

const TRIBUNALS: { id: TribunalId; label: string; short: string; limit: number }[] = [
  { id: "pje", label: "PJe", short: "PJe", limit: 10 },
  { id: "esaj", label: "e-SAJ", short: "e-SAJ", limit: 30 },
  { id: "projudi", label: "Projudi", short: "Projudi", limit: 10 },
  { id: "trf", label: "TRF / STJ", short: "TRF/STJ", limit: 10 },
];

const MAX_UPLOAD = 50 * 1024 * 1024; // 50 MB por arquivo (spec)

/** Petição de demonstração exibida antes do usuário enviar um arquivo. */
const DEMO_NAME = "Petição Inicial - Ação de Indenização.pdf";
const DEMO_PAGES: { heading: string; paragraphs: string[] }[] = [
  {
    heading: "EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA 3ª VARA CÍVEL DA COMARCA DE SÃO PAULO — ESTADO DE SÃO PAULO",
    paragraphs: [
      "JOÃO DA SILVA, brasileiro, portador do CPF nº 000.000.000-00, residente e domiciliado na Rua das Flores, nº 123, São Paulo/SP, por seu advogado que esta subscreve, com escritório profissional indicado no rodapé (OAB/SP 000.000), com fundamento nos artigos 319 e 320 do Código de Processo Civil, vem, respeitosamente, à presença de Vossa Excelência propor a presente",
      "AÇÃO DE INDENIZAÇÃO EM FACE DE EMPRESA LIMITADA, pessoa jurídica de direito privado, inscrita no CNPJ nº 00.000.000/0001-00, com sede na Av. Paulista, nº 1000, São Paulo/SP, pelos fatos e fundamentos a seguir expostos.",
    ],
  },
  {
    heading: "I — FATOS",
    paragraphs: [
      "1. Em 12/03/2024, a autora contratou da ré serviço descrito nos autos, nos termos da cópia contratual anexa (Doc. 01).",
      "2. A prestação do serviço apresentou vícios que impossibilitaram seu aproveitamento, conforme laudo técnico acostado (Doc. 02).",
      "3. Tentativas extrajudiciais de composição, registradas em notificação extrajudicial (Doc. 03), restaram sem êxito.",
      "4. Os prejuízos sofridos totalizam R$ 50.000,00 (cinquenta mil reais), valor que se requer a título de indenização.",
    ],
  },
  {
    heading: "II — DO DIREITO",
    paragraphs: [
      "1. A responsabilidade civil da ré decorre do art. 186 do Código Civil e da responsabilidade objetiva do art. 14 do Código de Defesa do Consumidor.",
      "2. O dano material e o dano moral são devidos conforme jurisprudência consolidada do Superior Tribunal de Justiça.",
      "3. Presentes os pressupostos legais para a procedência integral dos pedidos.",
    ],
  },
  {
    heading: "III — DOS PEDIDOS",
    paragraphs: [
      "Ante o exposto, requer-se: a) a citação da ré; b) a procedência integral do pedido; c) a condenação da ré ao pagamento de R$ 50.000,00, acrescidos de juros e correção; d) a condenação da ré nas custas e honorários advocatícios.",
      "Dá-se à causa o valor de R$ 50.000,00 (cinquenta mil reais).",
      "Nestes termos, pede deferimento. São Paulo, 12 de junho de 2024.",
      "Advogado(a) — OAB/SP 000.000",
    ],
  },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Step = { kind: string; label: string; options: Record<string, unknown> };

/**
 * Estúdio "Ferramentas PJe": coluna esquerda de envio/configuração e
 * coluna direita de pré-visualização interativa, com pipeline real
 * (OCR → tarja → compressão → blindagem) respeitando as flags da API —
 * ferramenta indisponível mantém o switch desligado e bloqueado.
 */
export default function PjeStudio({ preset, onNavigate, onPresetApplied }: Props) {
  // ---- flags e catálogo (fail-closed: sem resposta, sem recurso) ----
  const [features, setFeatures] = useState<Features | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [flagsReady, setFlagsReady] = useState(false);

  // ---- tribunal e opções ----
  const [tribunal, setTribunal] = useState<TribunalId>("pje");
  const [opts, setOpts] = useState({
    compress: true,
    ocr: false,
    blind: false,
    redact: false,
  });
  const [advanced, setAdvanced] = useState(false);
  const [dpi, setDpi] = useState(200);
  const [deskew, setDeskew] = useState(true);
  const [pdfa, setPdfa] = useState(false);

  // ---- arquivo ----
  const [file, setFile] = useState<StoredFile | null>(null);
  const [localUrl, setLocalUrl] = useState<string | null>(null);
  const [localKind, setLocalKind] = useState<"pdf" | "image" | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pageCount, setPageCount] = useState(1);
  const [page, setPage] = useState(0);
  const [rotation, setRotation] = useState(0);

  // ---- processamento ----
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ pct: number; label: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<StoredFile[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  /** teto de compressão escolhido (slider), sempre ≤ o teto do tribunal */
  const [targetMb, setTargetMb] = useState(10);

  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  useEffect(() => {
    Promise.allSettled([api.features(), api.tools()])
      .then(([f, t]) => {
        if (f.status === "fulfilled") setFeatures(f.value);
        if (t.status === "fulfilled") setTools(t.value.tools);
      })
      .finally(() => setFlagsReady(true));
  }, []);

  const toolAvailable = (id: string) =>
    tools.find((t) => t.id === id)?.available ?? false;

  const avail = {
    compress: toolAvailable("compress"),
    ocr: features?.ocr ?? false,
    blind: toolAvailable("blind"),
    redact: toolAvailable("redact"),
  };

  // switches de recurso indisponível permanecem desligados (fail-closed)
  useEffect(() => {
    setOpts((o) => ({
      compress: o.compress && avail.compress,
      ocr: o.ocr && avail.ocr,
      blind: o.blind && avail.blind,
      redact: o.redact && avail.redact,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avail.compress, avail.ocr, avail.blind, avail.redact]);

  // preset vindo do Dashboard (só liga o que a instância permite —
  // aguarda as flags chegarem para não aplicar no escuro)
  useEffect(() => {
    if (!preset || !flagsReady) return;
    setOpts((o) => ({
      compress: preset.compress !== undefined ? preset.compress : o.compress,
      ocr: preset.ocr !== undefined && avail.ocr ? preset.ocr : o.ocr,
      blind: preset.blind !== undefined && avail.blind ? preset.blind : o.blind,
      redact: preset.redact !== undefined && avail.redact ? preset.redact : o.redact,
    }));
    onPresetApplied?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, flagsReady]);

  const current = TRIBUNALS.find((t) => t.id === tribunal)!;
  const limitMb = current.limit;

  // ao trocar de tribunal, o teto do slider volta ao limite dele
  useEffect(() => setTargetMb(limitMb), [limitMb]);

  // ---- upload + preview local (FileReader) ----
  const handleFiles = async (selected: File[]) => {
    setError(null);
    const bad = selected.find((f) => f.size > MAX_UPLOAD);
    if (bad) {
      setError(`"${bad.name}" excede o limite de 50 MB por arquivo.`);
      return;
    }
    const chosen = selected[0];
    setUploading(true);
    try {
      const reader = new FileReader();
      reader.onload = () => {
        setLocalUrl(String(reader.result));
        setLocalKind(
          chosen.type === "application/pdf"
            ? "pdf"
            : chosen.type.startsWith("image/")
              ? "image"
              : null
        );
      };
      reader.readAsDataURL(chosen);

      const [uploaded] = await api.upload([chosen]);
      if (!alive.current) return;
      if (file) api.deleteFile(file.id).catch(() => undefined);
      setFile(uploaded);
      setOutputs([]);
      setTags([]);
      setPage(0);
      setRotation(0);
      setPageCount(1);
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) setUploading(false);
    }
  };

  const removeFile = () => {
    if (file) api.deleteFile(file.id).catch(() => undefined);
    setFile(null);
    setLocalUrl(null);
    setLocalKind(null);
    setOutputs([]);
    setTags([]);
    setError(null);
    setProgress(null);
    setPageCount(1);
    setPage(0);
  };

  // contagem real de páginas via endpoint de preview (fall-back: 1)
  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    let count = 1;
    const probe = (n: number) => {
      if (cancelled || n > 49) return;
      const img = new Image();
      img.onload = () => {
        if (cancelled) return;
        count = n + 1;
        setPageCount(count);
        probe(n + 1);
      };
      img.onerror = () => {
        if (!cancelled) setPageCount(Math.max(1, count));
      };
      img.src = api.previewUrl(file.id, n, 60);
    };
    probe(0);
    return () => {
      cancelled = true;
    };
  }, [file]);

  // ---- pipeline real: passos na ordem correta (OCR → tarja → compressão → blindagem) ----
  const steps: Step[] = [];
  if (opts.ocr && avail.ocr)
    steps.push({
      kind: "ocr",
      label: "OCR pesquisável",
      options: {
        lang: "por+eng",
        output: "pdf",
        dpi,
        deskew,
        denoise: true,
        auto_rotate: true,
        enhance_contrast: true,
        force_ocr: false,
      },
    });
  if (opts.redact && avail.redact)
    steps.push({
      kind: "redact",
      label: "Tarjamento LGPD",
      options: { mode: "black" },
    });
  if (opts.compress && avail.compress)
    steps.push({
      kind: "compress",
      label: `Compressão para ${targetMb} MB`,
      options: { limit_mb: targetMb, quality: "ebook", pdfa, split: true },
    });
  if (opts.blind && avail.blind)
    steps.push({
      kind: "blind",
      label: "PDF Blindado",
      options: { dpi, jpeg_quality: 75, keep_text_layer: false, owner_password: "" },
    });

  const process = async () => {
    if (!file || running) return;
    if (!steps.length) {
      setError("Ligue ao menos uma opção de processamento.");
      return;
    }
    setError(null);
    setRunning(true);
    setOutputs([]);
    setTags([]);
    const newTags: string[] = [];
    let currentIds = [file.id];
    try {
      for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        const base = Math.round((i / steps.length) * 100);
        setProgress({ pct: base, label: step.label });

        let options = step.options;
        if (step.kind === "redact") {
          // varre o documento e tarja automaticamente o que foi detectado
          const scan = await api.scanRedact(currentIds[0]);
          const terms = scan.groups.map((g) => g.value);
          if (!terms.length) {
            newTags.push("Tarja: nenhum dado sensível detectado automaticamente");
            continue;
          }
          options = { ...options, terms };
        }

        let job = await api.createJob(step.kind, currentIds, options);
        while (job.status === "queued" || job.status === "running") {
          await sleep(900);
          job = await api.getJob(job.id);
          if (!alive.current) return;
          const sub = Math.max(0, Math.min(100, job.progress));
          setProgress({
            pct: Math.min(99, base + Math.round(sub / steps.length)),
            label: `${step.label}${job.message ? ` — ${job.message}` : ""}`,
          });
        }
        if (job.status === "error") {
          throw new Error(job.error || `Falha no passo: ${step.label}`);
        }
        if (job.output_file_ids.length) currentIds = job.output_file_ids;

        if (step.kind === "ocr")
          newTags.push("OCR concluído — texto pesquisável detectado");
        if (step.kind === "compress")
          newTags.push(`Dentro do teto do ${current.short} (${targetMb} MB)`);
        if (step.kind === "blind")
          newTags.push("Blindado — páginas achatadas, metadados zerados");
        if (step.kind === "redact")
          newTags.push("Dados sensíveis tarjados (irreversível)");
      }

      const outs = await api.listFiles();
      if (!alive.current) return;
      setOutputs(outs.filter((f) => currentIds.includes(f.id) && f.id !== file.id));
      setTags(newTags);
      setProgress({ pct: 100, label: "Processamento concluído" });
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) setRunning(false);
    }
  };

  const resultFile = outputs[0] ?? null;
  const estimatedSize = useMemo(() => {
    if (!file) return 0;
    if (outputs.length) return outputs.reduce((s, f) => s + f.size, 0);
    if (opts.compress && avail.compress && file.size > targetMb * 1024 * 1024)
      return Math.round(targetMb * 1024 * 1024 * 0.92);
    return file.size;
  }, [file, outputs, opts.compress, avail.compress, targetMb]);

  const pages = Array.from({ length: pageCount }, (_, i) => i);
  const stepDone = [Boolean(file), running || outputs.length > 0, outputs.length > 0];

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-navy-900">
          Ferramentas PJe
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Estúdio de tratamento de petições: envie, configure o tribunal e
          pré-visualize antes de baixar para a juntada.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ================= Coluna esquerda: envio e configuração ================= */}
        <div className="space-y-5 rounded-xl border border-line bg-white p-5 shadow-card">
          {/* Tribunal */}
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Tribunal de destino
            </p>
            <div className="flex flex-wrap gap-2">
              {TRIBUNALS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTribunal(t.id)}
                  aria-pressed={tribunal === t.id}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
                    tribunal === t.id
                      ? "border-blue-700 bg-blue-700 text-white"
                      : "border-line bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  {t.label}
                  <span
                    className={`ml-2 text-xs ${tribunal === t.id ? "text-blue-100" : "text-slate-500"}`}
                  >
                    até {t.limit} MB
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Envio */}
          {file ? (
            <div className="flex items-center gap-3 rounded-xl border border-line bg-slate-50 px-4 py-3">
              <FileText className="h-5 w-5 shrink-0 text-blue-700" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-navy-900">
                  {file.name}
                </p>
                <p className="text-xs text-slate-500">
                  {formatSize(file.size)} · {pageCount}{" "}
                  {pageCount === 1 ? "página" : "páginas"} · enviado
                </p>
              </div>
              <button
                type="button"
                onClick={removeFile}
                className="rounded-md p-1.5 text-slate-500 transition hover:bg-red-50 hover:text-red-600"
                aria-label={`Remover ${file.name}`}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : (
            <Dropzone
              onFiles={handleFiles}
              disabled={uploading}
              hint="PDF, DOCX, JPG ou PNG — até 50 MB por arquivo (arraste ou clique)"
              accept=".pdf,.docx,.jpg,.jpeg,.png"
            />
          )}
          {uploading && (
            <p className="text-xs text-slate-500">Enviando e gerando o preview…</p>
          )}

          {/* Switches */}
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Opções de processamento
            </p>
            <Switch
              checked={opts.compress && avail.compress}
              disabled={!avail.compress}
              onChange={(v) => setOpts((o) => ({ ...o, compress: v }))}
              icon={<ShieldCheck className="h-4 w-4" aria-hidden />}
              label="Compressor de PDF"
              hint={
                avail.compress
                  ? `Reduz para o teto do ${current.short}: até ${limitMb} MB`
                  : "Indisponível nesta instância"
              }
            />
            {avail.compress && (
              <div className="pl-1">
                <input
                  type="range"
                  min={1}
                  max={limitMb}
                  step={1}
                  value={targetMb}
                  disabled={!opts.compress}
                  onChange={(e) => setTargetMb(Number(e.target.value))}
                  aria-label={`Teto de compressão em MB (máximo ${limitMb})`}
                  className="w-full accent-blue-700"
                />
                <p className="text-[11px] text-slate-500">
                  Teto aplicado: {targetMb} MB de um máximo de {limitMb} MB ({current.label})
                </p>
              </div>
            )}
            <Switch
              checked={opts.ocr && avail.ocr}
              disabled={!avail.ocr}
              onChange={(v) => setOpts((o) => ({ ...o, ocr: v }))}
              icon={<ScanText className="h-4 w-4" aria-hidden />}
              label="OCR pesquisável"
              hint={
                avail.ocr
                  ? "Reconhece texto de documentos digitalizados"
                  : "Indisponível nesta instância"
              }
            />
            <Switch
              checked={opts.blind && avail.blind}
              disabled={!avail.blind}
              onChange={(v) => setOpts((o) => ({ ...o, blind: v }))}
              icon={<Lock className="h-4 w-4" aria-hidden />}
              label="PDF Blindado"
              hint={
                avail.blind
                  ? "Achata em imagem de alta definição: remove scripts e metadados"
                  : "Indisponível nesta instância"
              }
            />
            <Switch
              checked={opts.redact && avail.redact}
              disabled={!avail.redact}
              onChange={(v) => setOpts((o) => ({ ...o, redact: v }))}
              icon={<ScanText className="h-4 w-4" aria-hidden />}
              label="Tarjamento LGPD"
              hint={
                avail.redact
                  ? "Tarja irreversível de CPF, RG, telefone e dados bancários"
                  : "Indisponível nesta instância"
              }
            />
          </div>

          {/* Configurações avançadas */}
          <div className="rounded-lg border border-line">
            <button
              type="button"
              onClick={() => setAdvanced((v) => !v)}
              aria-expanded={advanced}
              className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-navy-900 hover:bg-slate-50"
            >
              Configurações avançadas
              <span className="text-slate-400">{advanced ? "−" : "+"}</span>
            </button>
            {advanced && (
              <div className="space-y-4 border-t border-line px-4 py-4">
                <div>
                  <p className="mb-1.5 text-xs font-medium text-slate-600">
                    Resolução (DPI)
                  </p>
                  <div className="flex gap-2">
                    {[150, 200, 300].map((d) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() => setDpi(d)}
                        aria-pressed={dpi === d}
                        className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                          dpi === d
                            ? "border-blue-700 bg-blue-50 text-blue-700"
                            : "border-line text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {d} DPI
                      </button>
                    ))}
                  </div>
                </div>
                <Switch
                  checked={deskew}
                  onChange={setDeskew}
                  label="Deskew (endireitar páginas escaneadas)"
                  hint="Corrige inclinação da digitalização"
                />
                <Switch
                  checked={pdfa}
                  onChange={setPdfa}
                  label="Gerar PDF/A-2b"
                  hint="Norma de arquivo digital durável exigida por vários tribunais"
                />
              </div>
            )}
          </div>

          {/* Ação principal */}
          {error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={process}
            disabled={!file || running || uploading || steps.length === 0}
            className="w-full rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {running
              ? "Processando…"
              : file
                ? "Processar Documento para o Tribunal"
                : "Envie um documento para processar"}
          </button>

          {progress && (
            <ProgressBar
              progress={progress.pct}
              message={progress.label}
              status={running ? "running" : progress.pct >= 100 ? "done" : "queued"}
            />
          )}

          {/* Selos de segurança */}
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 border-t border-line pt-4 text-[11px] text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Lock className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
              Criptografia ponta a ponta
            </span>
            <span className="inline-flex items-center gap-1">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
              Processamento isolado por job
            </span>
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
              Conformidade LGPD
            </span>
          </div>
        </div>

        {/* ================= Coluna direita: pré-visualização ================= */}
        <div className="rounded-xl border border-line bg-white shadow-card">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <p className="text-sm font-semibold text-navy-900">
              Pré-visualização da petição
            </p>
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-600">
              {file ? "Arquivo enviado" : "Demonstração"}
            </span>
          </div>

          <div className="flex gap-4 p-4">
            {/* miniaturas */}
            <div className="flex w-16 shrink-0 flex-col gap-2">
              {(file ? pages : [0, 1, 2, 3]).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  aria-label={`Ir para a página ${p + 1}`}
                  aria-current={page === p ? "page" : undefined}
                  className={`relative h-20 w-14 overflow-hidden rounded border text-[10px] text-slate-500 transition ${
                    page === p
                      ? "border-blue-700 ring-2 ring-blue-100"
                      : "border-line hover:border-slate-300"
                  }`}
                >
                  {file && localUrl ? (
                    <img
                      src={api.previewUrl(file.id, p, 50)}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                      }}
                    />
                  ) : (
                    <span className="flex h-full items-center justify-center bg-slate-50">
                      {p + 1}
                    </span>
                  )}
                  <span className="absolute bottom-0.5 right-1 font-medium">
                    {p + 1}
                  </span>
                </button>
              ))}
            </div>

            {/* visualizador */}
            <div className="min-w-0 flex-1">
              <div
                className="flex min-h-[22rem] items-center justify-center overflow-auto rounded-lg border border-line bg-slate-100 p-3"
                style={{ transform: `rotate(${rotation}deg)` }}
              >
                {file && localKind !== "image" ? (
                  <img
                    src={api.previewUrl(file.id, page, 150)}
                    alt={`Pré-visualização da página ${page + 1}`}
                    className="max-h-[26rem] w-auto rounded bg-white shadow"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                ) : file && localKind === "image" && localUrl ? (
                  <img
                    src={localUrl}
                    alt="Pré-visualização da imagem enviada"
                    className="max-h-[26rem] w-auto rounded bg-white shadow"
                  />
                ) : (
                  <DemoPage index={Math.min(page, DEMO_PAGES.length - 1)} />
                )}
              </div>
              <p className="mt-2 text-center text-[11px] text-slate-500">
                Página {page + 1} de {file ? pageCount : DEMO_PAGES.length}
                {rotation > 0 && " · visualização rotacionada"}
              </p>
            </div>

            {/* informações do documento */}
            <aside className="hidden w-48 shrink-0 space-y-3 border-l border-line pl-4 xl:block">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Informações do documento
              </p>
              <div className="space-y-1.5 text-xs">
                <p className="text-slate-500">Nome</p>
                <p className="break-words font-medium text-navy-900">
                  {file?.name ?? DEMO_NAME}
                </p>
                <p className="pt-1 text-slate-500">Tamanho</p>
                <p className="font-medium text-navy-900">
                  {file ? formatSize(file.size) : "1,8 MB"}
                  {file && (
                    <span className="block font-normal text-slate-500">
                      estimado após: {formatSize(estimatedSize)}
                    </span>
                  )}
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                {tags.length > 0 ? (
                  tags.map((t) => (
                    <span
                      key={t}
                      className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] font-medium leading-snug text-emerald-600"
                    >
                      {t}
                    </span>
                  ))
                ) : (
                  <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-500">
                    Aguardando processamento
                  </span>
                )}
              </div>

              <div className="space-y-2 pt-1">
                <a
                  href={
                    (resultFile ?? file) ? api.downloadUrl((resultFile ?? file)!.id) : undefined
                  }
                  aria-disabled={!(resultFile ?? file)}
                  className={`flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold text-white transition ${
                    resultFile ?? file
                      ? "bg-blue-700 hover:bg-blue-600"
                      : "pointer-events-none bg-slate-300"
                  }`}
                >
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  {resultFile ? "Baixar PDF Otimizado" : "Baixar PDF"}
                </a>
                <button
                  type="button"
                  onClick={() => setRotation((r) => (r + 90) % 360)}
                  className="flex w-full items-center justify-center gap-1.5 rounded-md border border-line px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  <RotateCw className="h-3.5 w-3.5" aria-hidden />
                  Rotacionar visualização
                </button>
                <button
                  type="button"
                  onClick={removeFile}
                  disabled={!file}
                  className="flex w-full items-center justify-center gap-1.5 rounded-md border border-line px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  Remover
                </button>
              </div>
            </aside>
          </div>
        </div>
      </div>

      {/* ================= Barra de etapas ================= */}
      <ol className="grid gap-3 sm:grid-cols-3">
        {[
          { n: 1, title: "Enviar", hint: "Arraste a petição e escolha o tribunal" },
          { n: 2, title: "Processar", hint: "Conversão, OCR e compressão" },
          { n: 3, title: "Baixar e usar no PJe", hint: "Arquivo pronto para a juntada" },
        ].map((s, i) => (
          <li
            key={s.n}
            className={`flex items-start gap-3 rounded-xl border p-4 ${
              stepDone[i]
                ? "border-emerald-200 bg-emerald-50"
                : "border-line bg-white"
            }`}
          >
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                stepDone[i] ? "bg-emerald-600 text-white" : "bg-slate-200 text-slate-600"
              }`}
            >
              {s.n}
            </span>
            <span>
              <span className="block text-sm font-semibold text-navy-900">
                {s.title}
              </span>
              <span className="block text-xs text-slate-500">{s.hint}</span>
            </span>
          </li>
        ))}
      </ol>

      {/* ================= Catálogo completo (ferramentas fora do estúdio) ========= */}
      <div>
        <div className="mb-3 flex items-center gap-2">
          <Wrench className="h-4 w-4 text-slate-400" aria-hidden />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Todas as ferramentas
          </h2>
          <span className="text-xs text-slate-400">
            (as indisponíveis continuam bloqueadas nesta versão)
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tools.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={!t.available}
              onClick={() => onNavigate({ tool: t.id })}
              className={`rounded-lg border p-3 text-left text-sm transition ${
                t.available
                  ? "border-line bg-white shadow-card hover:-translate-y-0.5 hover:border-blue-700"
                  : "cursor-not-allowed border-dashed border-slate-300 bg-slate-50 opacity-70"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium text-navy-900">{t.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    t.available
                      ? "bg-emerald-50 text-emerald-600"
                      : "bg-slate-200 text-slate-600"
                  }`}
                >
                  {t.available ? "Disponível" : "Em breve"}
                </span>
              </span>
              <span className="mt-1 block text-xs leading-snug text-slate-500">
                {t.description}
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Switch acessível (role=switch) com ícone, rótulo e descrição. */
function Switch({
  checked,
  onChange,
  label,
  hint,
  icon,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  icon?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border border-line px-3 py-2.5 ${
        disabled ? "opacity-60" : "hover:bg-slate-50"
      }`}
    >
      {icon && <span className="text-blue-700">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-navy-900">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full transition ${
          checked ? "bg-blue-700" : "bg-slate-300"
        } ${disabled ? "cursor-not-allowed" : ""}`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
            checked ? "left-[1.125rem]" : "left-0.5"
          }`}
        />
      </button>
    </div>
  );
}

/** Página da petição de demonstração (visual). */
function DemoPage({ index }: { index: number }) {
  const page = DEMO_PAGES[index] ?? DEMO_PAGES[0];
  return (
    <article
      className="w-full max-w-[26rem] bg-white px-8 py-7 text-justify shadow-md"
      style={{ minHeight: "24rem", fontFamily: "'Times New Roman', Georgia, serif" }}
    >
      <header className="mb-5 text-center">
        <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center text-3xl text-slate-700">
          ⚖
        </div>
        <p className="text-[10px] uppercase tracking-wide text-slate-600">
          República Federativa do Brasil · Justiça Brasileira
        </p>
        <p className="mt-1 text-[11px] font-bold text-slate-800">
          CNJ nº 1001234-56.2024.8.26.0100
        </p>
      </header>
      <h3 className="mb-3 text-[11px] font-bold uppercase leading-snug text-slate-900">
        {page.heading}
      </h3>
      {page.paragraphs.map((p, i) => (
        <p key={i} className="mb-2.5 text-[11px] leading-relaxed text-slate-800">
          {p}
        </p>
      ))}
      <footer className="mt-6 text-center text-[10px] text-slate-500">
        Documento de demonstração — JudiFiles
      </footer>
    </article>
  );
}
