import { useEffect, useMemo, useState } from "react";
import {
  api,
  formatSize,
  type Job,
  type OcrLanguages,
  type Preset,
  type ScanResult,
  type StoredFile,
} from "../api/client";
import Dropzone from "../components/Dropzone";
import ProgressBar from "../components/ProgressBar";
import { useJobPolling } from "../hooks";

/** Configuração (título, opções padrão e formulário) de cada ferramenta. */
type ToolConfig = {
  title: string;
  subtitle: string;
  defaults: Record<string, unknown>;
  /** rótulo do botão de execução */
  action: string;
  /** aceita vários arquivos no mesmo job (mesclagem) */
  multiple?: boolean;
  /** mínimo de arquivos exigido pela API */
  minFiles?: number;
  /** dica exibida na área de envio */
  hint?: string;
};

const TOOLS: Record<string, ToolConfig> = {
  ocr: {
    title: "OCR de documentos",
    subtitle:
      "Transforma PDF escaneado ou imagem em PDF pesquisável, TXT ou DOCX.",
    action: "Executar OCR",
    defaults: {
      lang: "por+eng",
      output: "pdf",
      dpi: 300,
      deskew: true,
      denoise: true,
      auto_rotate: true,
      enhance_contrast: true,
      force_ocr: false,
    },
  },
  blind: {
    title: "PDF Blindado",
    subtitle:
      "Achata cada página em imagem de alta resolução: acaba com texto selecionável, formulários, scripts e metadados.",
    action: "Blindar documento",
    defaults: {
      dpi: 300,
      jpeg_quality: 75,
      keep_text_layer: false,
      owner_password: "",
    },
  },
  merge: {
    title: "Mesclar PDFs",
    subtitle:
      "Une vários arquivos em um único PDF na ordem que você escolher — arraste ou use as setas para reordenar.",
    action: "Mesclar arquivos",
    multiple: true,
    minFiles: 2,
    hint: "Arraste dois ou mais PDFs — a ordem aqui é a ordem do arquivo final",
    defaults: { bookmarks: true, title: "" },
  },
  split: {
    title: "Dividir PDF",
    subtitle:
      "Separa por intervalo de páginas, extrai páginas específicas ou corta em blocos fixos.",
    action: "Dividir documento",
    defaults: { mode: "ranges", ranges: "1-3", every: 5 },
  },
  convert: {
    title: "Converter documentos",
    subtitle:
      "Imagem → PDF, Word → PDF, PDF → PNG/JPG e PDF → TXT/DOCX. O formato é detectado pelo arquivo.",
    action: "Converter",
    defaults: { target: "", dpi: 200, jpeg_quality: 85 },
  },
  compress: {
    title: "Compressor de PDF",
    subtitle:
      "Reduz o tamanho para o limite do tribunal (PJe, e-SAJ, e-Proc), divide em partes se necessário e gera PDF/A.",
    action: "Comprimir",
    defaults: { limit_mb: 10, quality: "ebook", pdfa: false, split: true },
  },
  redact: {
    title: "Tarjar / Redigir dados",
    subtitle:
      "Remove dados sensíveis de forma irreversível: CPF, CNPJ, RG, telefone, e-mail, endereço e dados bancários. Você revisa antes de aplicar.",
    action: "Aplicar redação",
    hint: "PDF com camada de texto — se for imagem, rode o OCR primeiro",
    defaults: { mode: "black" },
  },
  metadata: {
    title: "Dados da peça",
    subtitle:
      "Grava metadados jurídicos (número CNJ, partes, datas e tipo de peça) no PDF e renomeia o arquivo.",
    action: "Gravar metadados",
    defaults: {
      cnj: "",
      tipo: "",
      autor: "",
      reu: "",
      data: "",
      template: "{tipo} - {cnj} - {autor} x {reu}",
      apply_metadata: true,
      rename: true,
    },
  },
  number: {
    title: "Numeração, Bates e marca d'água",
    subtitle:
      "Numera as páginas, aplica o carimbo \"Fls.\" ou o padrão Bates e coloca marca d'água (ex.: USO JUDICIAL).",
    action: "Numerar documento",
    defaults: {
      style: "fls",
      start: 1,
      pad: 3,
      prefix: "",
      show_total: false,
      position: "bottom-center",
      font_size: 10,
      pages: "",
      watermark: "",
      watermark_size: 42,
      watermark_opacity: 0.15,
    },
  },
  outline: {
    title: "Sumário e índice",
    subtitle:
      "Cria a página de índice com a nomeação dos anexos e o sumário navegável (bookmarks) da petição.",
    action: "Gerar sumário",
    defaults: {
      title: "ÍNDICE",
      insert_index: true,
      bookmarks: true,
      entries: [],
    },
  },
  integrity: {
    title: "Certificado de integridade",
    subtitle:
      "Gera o hash SHA-256 de cada arquivo em um relatório PDF, preparado para assinatura ICP-Brasil.",
    action: "Emitir certificado",
    multiple: true,
    hint: "Envie de 1 a 20 arquivos (PDF, imagem, Word ou texto)",
    defaults: { emitente: "", observacao: "" },
  },
};

type Props = { toolId: string; onBack: () => void };

export default function Tool({ toolId, onBack }: Props) {
  const config = TOOLS[toolId];
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [options, setOptions] = useState<Record<string, unknown>>(
    () => config?.defaults ?? {}
  );
  const [languages, setLanguages] = useState<OcrLanguages | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<StoredFile[]>([]);

  // revisão manual da redação (Fase 3)
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [customTerms, setCustomTerms] = useState("");

  const active = job?.status === "queued" || job?.status === "running";
  const minFiles = config?.minFiles ?? 1;
  const multiple = Boolean(config?.multiple);

  useJobPolling(job?.id ?? null, active, (updated) => {
    setJob(updated);
    if (updated.status === "done" && updated.output_file_ids.length) {
      api
        .listFiles()
        .then((all) =>
          setOutputs(all.filter((f) => updated.output_file_ids.includes(f.id)))
        )
        .catch(() => undefined);
    }
  });

  useEffect(() => {
    if (toolId === "ocr") {
      api.languages().then(setLanguages).catch(() => undefined);
    }
  }, [toolId]);

  // varre o PDF assim que ele é enviado (revisão antes de tarjar)
  useEffect(() => {
    if (toolId !== "redact" || files.length !== 1) {
      setScan(null);
      return;
    }
    let alive = true;
    setScanning(true);
    setScan(null);
    api
      .scanRedact(files[0].id)
      .then((r) => {
        if (!alive) return;
        setScan(r);
        setPicked(Object.fromEntries(r.groups.map((g) => [g.value, true])));
      })
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setScanning(false));
    return () => {
      alive = false;
    };
  }, [toolId, files]);

  const set = (key: string, value: unknown) =>
    setOptions((prev) => ({ ...prev, [key]: value }));

  // anexos do sumário (Fase 3)
  const entries = (options.entries as Array<{ label: string; page: number }>) ?? [];
  const addEntry = () =>
    set("entries", [...entries, { label: "", page: 1 }]);
  const updateEntry = (index: number, key: "label" | "page", value: string) =>
    set(
      "entries",
      entries.map((entry, i) =>
        i === index
          ? {
              ...entry,
              [key]: key === "page" ? Number(value) || 0 : value,
            }
          : entry
      )
    );
  const removeEntry = (index: number) =>
    set("entries", entries.filter((_, i) => i !== index));

  const handleFiles = async (selected: File[]) => {
    setError(null);
    setUploading(true);
    try {
      const uploaded = await api.upload(selected);
      if (multiple) {
        setFiles((prev) => [...prev, ...uploaded]);
      } else {
        // ferramenta de arquivo único: substitui o anterior
        const stale = files.map((f) => f.id);
        setFiles(uploaded);
        stale.forEach((id) => api.deleteFile(id).catch(() => undefined));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const removeFile = async (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
    await api.deleteFile(id).catch(() => undefined);
  };

  const move = (index: number, delta: number) => {
    setFiles((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const run = async () => {
    if (!files.length) return;
    if (files.length < minFiles) {
      setError(
        `Esta ferramenta precisa de pelo menos ${minFiles} arquivo(s).`
      );
      return;
    }
    setError(null);
    setOutputs([]);

    let payload = options as Record<string, unknown>;
    if (toolId === "redact") {
      const fromScan = Object.entries(picked)
        .filter(([, on]) => on)
        .map(([value]) => value);
      const manual = customTerms
        .split(/[\n,;]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      const terms = [...new Set([...fromScan, ...manual])];
      if (!terms.length) {
        setError(
          "Marque ao menos um dado na revisão ou informe um termo manual para redigir."
        );
        return;
      }
      payload = { ...payload, terms };
    }
    if (toolId === "outline") {
      const entries = ((payload.entries as Array<Record<string, unknown>>) ?? [])
        .filter((e) => String(e.label ?? "").trim() && Number(e.page) > 0)
        .map((e) => ({ label: String(e.label).trim(), page: Number(e.page) }));
      payload = { ...payload, entries };
    }

    try {
      const created = await api.createJob(
        toolId,
        files.map((f) => f.id),
        payload
      );
      setJob(created);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const reset = () => {
    setJob(null);
    setOutputs([]);
    setError(null);
  };

  const langOptions = useMemo(() => languages?.languages ?? ["por", "eng"], [languages]);

  if (!config) {
    return (
      <section>
        <p className="text-sm">Ferramenta não encontrada.</p>
        <button type="button" onClick={onBack} className="mt-3 text-sm underline">
          ← Voltar ao painel
        </button>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-gold-400 dark:border-slate-700"
        >
          ← Painel
        </button>
        <div>
          <h1 className="text-2xl font-semibold text-ink-800 dark:text-slate-100">
            {config.title}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            {config.subtitle}
          </p>
        </div>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      {/* ---------------- 1. Arquivos ---------------- */}
      {multiple ? (
        <div className="space-y-3">
          {files.map((file, index) => (
            <div
              key={file.id}
              className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
            >
              <span className="mt-1 w-6 text-center text-sm font-semibold text-slate-400">
                {index + 1}
              </span>
              <FileThumb file={file} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-ink-800 dark:text-slate-100">
                  {file.name}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {formatSize(file.size)} · SHA-256 {file.sha256.slice(0, 16)}…
                </p>
                <div className="mt-2 flex flex-wrap gap-3 text-xs">
                  <button
                    type="button"
                    onClick={() => move(index, -1)}
                    disabled={index === 0 || active}
                    className="font-medium text-slate-500 hover:underline disabled:opacity-40"
                  >
                    ↑ Subir
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, 1)}
                    disabled={index === files.length - 1 || active}
                    className="font-medium text-slate-500 hover:underline disabled:opacity-40"
                  >
                    ↓ Descer
                  </button>
                  <button
                    type="button"
                    onClick={() => removeFile(file.id)}
                    disabled={active}
                    className="font-medium text-red-600 hover:underline dark:text-red-400"
                  >
                    Remover
                  </button>
                </div>
              </div>
            </div>
          ))}
          {files.length < 50 && !active && (
            <Dropzone
              onFiles={handleFiles}
              disabled={uploading}
              hint={config.hint}
            />
          )}
        </div>
      ) : !files.length ? (
        <Dropzone onFiles={handleFiles} disabled={uploading} hint={config.hint} />
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-start gap-4">
            <FileThumb file={files[0]} />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-ink-800 dark:text-slate-100">
                {files[0].name}
              </p>
              <p className="mt-0.5 text-xs text-slate-500">
                {formatSize(files[0].size)} · SHA-256 {files[0].sha256.slice(0, 16)}…
              </p>
              <div className="mt-2 flex gap-3 text-xs">
                <button
                  type="button"
                  onClick={() => removeFile(files[0].id)}
                  className="font-medium text-red-600 hover:underline dark:text-red-400"
                >
                  Remover
                </button>
                {!active && (
                  <button
                    type="button"
                    onClick={() => setFiles([])}
                    className="font-medium text-slate-500 hover:underline"
                  >
                    Enviar outro
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ---------------- 2. Opções ---------------- */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Opções
        </h2>

        {toolId === "ocr" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Select
              label="Idioma do OCR"
              value={String(options.lang)}
              onChange={(v) => set("lang", v)}
              options={[
                { value: "por+eng", label: "Português + Inglês" },
                ...langOptions
                  .filter((l) => l !== "por" && l !== "eng")
                  .map((l) => ({ value: l, label: l })),
                ...(langOptions.includes("por") ? [] : [{ value: "por", label: "português" }]),
              ]}
            />
            <Select
              label="Formato de saída"
              value={String(options.output)}
              onChange={(v) => set("output", v)}
              options={[
                { value: "pdf", label: "PDF pesquisável" },
                { value: "txt", label: "Texto (.txt)" },
                { value: "docx", label: "Word (.docx)" },
              ]}
            />
            <Select
              label="Resolução"
              value={String(options.dpi)}
              onChange={(v) => set("dpi", Number(v))}
              options={[
                { value: "200", label: "200 DPI — rápido" },
                { value: "300", label: "300 DPI — recomendado" },
                { value: "600", label: "600 DPI — máxima (lento)" },
              ]}
            />
            <div className="space-y-2">
              <Switch
                label="Corrigir inclinação (deskew)"
                checked={Boolean(options.deskew)}
                onChange={(v) => set("deskew", v)}
              />
              <Switch
                label="Remover ruído"
                checked={Boolean(options.denoise)}
                onChange={(v) => set("denoise", v)}
              />
            </div>
            <div className="space-y-2">
              <Switch
                label="Rotação automática"
                checked={Boolean(options.auto_rotate)}
                onChange={(v) => set("auto_rotate", v)}
              />
              <Switch
                label="Melhorar contraste"
                checked={Boolean(options.enhance_contrast)}
                onChange={(v) => set("enhance_contrast", v)}
              />
            </div>
            <Switch
              label="Reconhecer mesmo com texto existente"
              checked={Boolean(options.force_ocr)}
              onChange={(v) => set("force_ocr", v)}
            />
          </div>
        )}

        {toolId === "blind" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Select
              label="Resolução da imagem"
              value={String(options.dpi)}
              onChange={(v) => set("dpi", Number(v))}
              options={[
                { value: "150", label: "150 DPI — menor tamanho" },
                { value: "200", label: "200 DPI — equilibrado" },
                { value: "300", label: "300 DPI — alta qualidade" },
              ]}
            />
            <div>
              <label className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                Qualidade JPEG: {String(options.jpeg_quality)}
              </label>
              <input
                type="range"
                min={20}
                max={95}
                step={5}
                value={Number(options.jpeg_quality)}
                onChange={(e) => set("jpeg_quality", Number(e.target.value))}
                aria-label="Qualidade JPEG"
                className="w-full accent-[#b8912f]"
              />
              <p className="mt-1 text-xs text-slate-500">
                Menor qualidade = arquivo menor para o tribunal.
              </p>
            </div>
            <Switch
              label="Manter camada de texto pesquisável"
              checked={Boolean(options.keep_text_layer)}
              onChange={(v) => set("keep_text_layer", v)}
              hint="OCR invisível por cima da imagem: dá para buscar, mas não para editar."
            />
            <div>
              <label
                htmlFor="owner-pass"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Senha de proprietário (opcional)
              </label>
              <input
                id="owner-pass"
                type="password"
                autoComplete="new-password"
                placeholder="Bloqueia edição, cópia e extração"
                value={String(options.owner_password ?? "")}
                onChange={(e) => set("owner_password", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              <p className="mt-1 text-xs text-slate-500">
                Guarde bem: sem ela não será possível reabrir para edição.
              </p>
            </div>
          </div>
        )}

        {toolId === "merge" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Switch
              label="Criar sumário por arquivo"
              checked={Boolean(options.bookmarks)}
              onChange={(v) => set("bookmarks", v)}
              hint="Cada arquivo de origem vira um item navegável no PDF final."
            />
            <div>
              <label
                htmlFor="merge-title"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Título do documento (opcional)
              </label>
              <input
                id="merge-title"
                type="text"
                placeholder="Ex.: Petição inicial com anexos"
                value={String(options.title ?? "")}
                onChange={(e) => set("title", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
          </div>
        )}

        {toolId === "split" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Select
              label="Modo de divisão"
              value={String(options.mode)}
              onChange={(v) => set("mode", v)}
              options={[
                { value: "ranges", label: "Intervalos → um PDF por intervalo" },
                { value: "extract", label: "Extrair páginas → um PDF só" },
                { value: "every", label: "Blocos fixos (N páginas cada)" },
              ]}
            />
            {String(options.mode) === "every" ? (
              <div>
                <label
                  htmlFor="split-every"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Páginas por bloco
                </label>
                <input
                  id="split-every"
                  type="number"
                  min={1}
                  max={500}
                  value={Number(options.every ?? 5)}
                  onChange={(e) => set("every", Number(e.target.value))}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
            ) : (
              <div>
                <label
                  htmlFor="split-ranges"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Páginas (1-based, ex.: 1-5, 8, 10-12)
                </label>
                <input
                  id="split-ranges"
                  type="text"
                  value={String(options.ranges ?? "")}
                  onChange={(e) => set("ranges", e.target.value)}
                  placeholder="1-5, 8, 10-12"
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
                <p className="mt-1 text-xs text-slate-500">
                  {String(options.mode) === "extract"
                    ? "As páginas saem num único PDF, na ordem digitada."
                    : "Cada intervalo vira um arquivo separado."}
                </p>
              </div>
            )}
          </div>
        )}

        {toolId === "convert" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Select
              label="Formato de saída"
              value={String(options.target ?? "")}
              onChange={(v) => set("target", v)}
              options={[
                { value: "", label: "Automático (recomendado)" },
                { value: "pdf", label: "PDF" },
                { value: "png", label: "PNG" },
                { value: "jpg", label: "JPG" },
                { value: "txt", label: "Texto (.txt)" },
                { value: "docx", label: "Word (.docx)" },
              ]}
            />
            <Select
              label="Resolução das imagens"
              value={String(options.dpi)}
              onChange={(v) => set("dpi", Number(v))}
              options={[
                { value: "150", label: "150 DPI — leve" },
                { value: "200", label: "200 DPI — recomendado" },
                { value: "300", label: "300 DPI — alta qualidade" },
              ]}
            />
            <div>
              <label className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                Qualidade JPEG: {String(options.jpeg_quality)}
              </label>
              <input
                type="range"
                min={20}
                max={95}
                step={5}
                value={Number(options.jpeg_quality)}
                onChange={(e) => set("jpeg_quality", Number(e.target.value))}
                aria-label="Qualidade JPEG"
                className="w-full accent-[#b8912f]"
              />
              <p className="mt-1 text-xs text-slate-500">
                Usada ao converter páginas em JPG.
              </p>
            </div>
          </div>
        )}

        {toolId === "compress" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Presets
              options={options}
              onApply={(patch) => setOptions((prev) => ({ ...prev, ...patch }))}
            />
            <div>
              <label
                htmlFor="limit-mb"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Limite por arquivo (MB)
              </label>
              <input
                id="limit-mb"
                type="number"
                min={0}
                max={500}
                step={0.5}
                value={Number(options.limit_mb ?? 10)}
                onChange={(e) => set("limit_mb", Number(e.target.value))}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              <p className="mt-1 text-xs text-slate-500">
                0 = sem limite. Confirme o limite do seu tribunal antes de protocolar.
              </p>
            </div>
            <Select
              label="Perfil de qualidade"
              value={String(options.quality)}
              onChange={(v) => set("quality", v)}
              options={[
                { value: "screen", label: "Tela (110 DPI) — menor arquivo" },
                { value: "ebook", label: "E-book (150 DPI) — recomendado" },
                { value: "printer", label: "Impressão (300 DPI)" },
                { value: "prepress", label: "Pré-impressão (300 DPI)" },
              ]}
            />
            <div className="space-y-2">
              <Switch
                label="Dividir automaticamente se passar do limite"
                checked={Boolean(options.split)}
                onChange={(v) => set("split", v)}
                hint="Gera parte_1, parte_2... cada uma dentro do limite."
              />
              <Switch
                label="Gerar PDF/A-2b"
                checked={Boolean(options.pdfa)}
                onChange={(v) => set("pdfa", v)}
                hint="Arquivo normalizado para guarda de longo prazo (Ghostscript)."
              />
            </div>
          </div>
        )}

        {toolId === "redact" && (
          <div className="space-y-5">
            <div className="sm:col-span-2">
              <h3 className="mb-2 text-sm font-semibold text-ink-800 dark:text-slate-200">
                Revisão antes de aplicar
              </h3>
              {scanning && (
                <p className="text-sm text-slate-500">
                  Analisando o documento...
                </p>
              )}
              {scan?.warning && (
                <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                  {scan.warning}
                </p>
              )}
              {scan && !scan.warning && scan.groups.length === 0 && (
                <p className="text-sm text-slate-500">
                  Nenhum dado sensível encontrado na camada de texto deste PDF.
                  Você ainda pode informar termos manuais abaixo.
                </p>
              )}
              {scan && scan.groups.length > 0 && (
                <>
                  <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
                    {scan.total} ocorrência(s) em {scan.groups.length} dado(s) —
                    desmarque o que <strong>não</strong> deve ser tarjado:
                  </p>
                  <ul className="max-h-64 space-y-1 overflow-auto rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                    {scan.groups.map((g) => (
                      <li key={`${g.type}:${g.value}`}>
                        <label className="flex cursor-pointer items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={Boolean(picked[g.value])}
                            onChange={(e) =>
                              setPicked((prev) => ({
                                ...prev,
                                [g.value]: e.target.checked,
                              }))
                            }
                            className="mt-0.5 h-4 w-4 accent-[#b8912f]"
                          />
                          <span className="min-w-0">
                            <span className="font-medium text-ink-800 dark:text-slate-200">
                              {g.label}
                            </span>{" "}
                            <code className="break-all text-ink-600 dark:text-gold-400">
                              {g.value}
                            </code>{" "}
                            <span className="text-xs text-slate-500">
                              {g.count}x · pág. {g.pages.join(", ")}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className="mt-3">
                <label
                  htmlFor="redact-custom"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Termos manuais (opcional)
                </label>
                <textarea
                  id="redact-custom"
                  rows={2}
                  value={customTerms}
                  onChange={(e) => setCustomTerms(e.target.value)}
                  placeholder={"Um por linha ou separados por vírgula\nEx.: sigiloso, nome da testemunha"}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
            </div>
            <Select
              label="Modo da tarja"
              value={String(options.mode)}
              onChange={(v) => set("mode", v)}
              options={[
                { value: "black", label: "Tarja preta (padrão)" },
                { value: "white", label: "Apagar (fundo branco)" },
              ]}
            />
          </div>
        )}

        {toolId === "metadata" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="meta-cnj"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Número CNJ (opcional)
              </label>
              <input
                id="meta-cnj"
                type="text"
                placeholder="0000001-10.2026.8.01.0001"
                value={String(options.cnj ?? "")}
                onChange={(e) => set("cnj", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              <p className="mt-1 text-xs text-slate-500">
                Formato NNNNNNN-DD.AAAA.J.TR.OOOO — validado antes de gravar.
              </p>
            </div>
            <div>
              <label
                htmlFor="meta-tipo"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Tipo de peça
              </label>
              <input
                id="meta-tipo"
                type="text"
                list="tipos-peca"
                placeholder="Ex.: Contestação"
                value={String(options.tipo ?? "")}
                onChange={(e) => set("tipo", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              <datalist id="tipos-peca">
                {[
                  "Petição inicial",
                  "Contestação",
                  "Réplica",
                  "Recurso",
                  "Manifestação",
                  "Sentença",
                  "Decisão",
                  "Procuração",
                  "Contrato",
                  "Declaração",
                ].map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </div>
            <div>
              <label
                htmlFor="meta-autor"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Autor (parte)
              </label>
              <input
                id="meta-autor"
                type="text"
                placeholder="Ex.: João da Silva"
                value={String(options.autor ?? "")}
                onChange={(e) => set("autor", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label
                htmlFor="meta-reu"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Réu (parte)
              </label>
              <input
                id="meta-reu"
                type="text"
                placeholder="Ex.: Transportes Ltda"
                value={String(options.reu ?? "")}
                onChange={(e) => set("reu", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label
                htmlFor="meta-data"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Data da peça
              </label>
              <input
                id="meta-data"
                type="date"
                value={String(options.data ?? "")}
                onChange={(e) => set("data", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Switch
                label="Gravar metadados no PDF"
                checked={Boolean(options.apply_metadata)}
                onChange={(v) => set("apply_metadata", v)}
                hint="Título, partes, assunto e palavras-chave com o CNJ."
              />
              <Switch
                label="Renomear o arquivo de saída"
                checked={Boolean(options.rename)}
                onChange={(v) => set("rename", v)}
                hint="Padrão: {tipo} - {cnj} - {autor} x {reu}."
              />
            </div>
          </div>
        )}

        {toolId === "number" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Select
              label="Estilo"
              value={String(options.style)}
              onChange={(v) => set("style", v)}
              options={[
                { value: "fls", label: "Carimbo Fls. (Fls. 001)" },
                { value: "bates", label: "Bates (prefixo + número)" },
                { value: "plain", label: "Numeração simples (1, 2, 3...)" },
              ]}
            />
            <Select
              label="Posição"
              value={String(options.position)}
              onChange={(v) => set("position", v)}
              options={[
                { value: "bottom-center", label: "Rodapé centralizado" },
                { value: "bottom-right", label: "Rodapé à direita" },
                { value: "bottom-left", label: "Rodapé à esquerda" },
                { value: "top-center", label: "Cabeçalho centralizado" },
                { value: "top-right", label: "Cabeçalho à direita" },
                { value: "top-left", label: "Cabeçalho à esquerda" },
              ]}
            />
            {String(options.style) === "bates" && (
              <div>
                <label
                  htmlFor="bates-prefix"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Prefixo do Bates
                </label>
                <input
                  id="bates-prefix"
                  type="text"
                  maxLength={20}
                  placeholder="Ex.: PROC"
                  value={String(options.prefix ?? "")}
                  onChange={(e) => set("prefix", e.target.value.toUpperCase())}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="number-start"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Primeira folha
                </label>
                <input
                  id="number-start"
                  type="number"
                  min={1}
                  value={Number(options.start ?? 1)}
                  onChange={(e) => set("start", Number(e.target.value))}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
              <div>
                <label
                  htmlFor="number-pad"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Dígitos
                </label>
                <input
                  id="number-pad"
                  type="number"
                  min={1}
                  max={12}
                  value={Number(options.pad ?? 3)}
                  onChange={(e) => set("pad", Number(e.target.value))}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
            </div>
            <div>
              <label
                htmlFor="number-pages"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Páginas (vazio = todas)
              </label>
              <input
                id="number-pages"
                type="text"
                placeholder="1-5, 8"
                value={String(options.pages ?? "")}
                onChange={(e) => set("pages", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            {String(options.style) === "plain" && (
              <Switch
                label="Mostrar total (ex.: 12/30)"
                checked={Boolean(options.show_total)}
                onChange={(v) => set("show_total", v)}
              />
            )}
            <div className="sm:col-span-2">
              <label
                htmlFor="wm-text"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Marca d'água (opcional)
              </label>
              <input
                id="wm-text"
                type="text"
                maxLength={80}
                placeholder="Ex.: USO JUDICIAL ou SIGILOSO"
                value={String(options.watermark ?? "")}
                onChange={(e) => set("watermark", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
              {String(options.watermark ?? "") && (
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                      Tamanho: {Number(options.watermark_size ?? 42)}
                    </label>
                    <input
                      type="range"
                      min={12}
                      max={120}
                      value={Number(options.watermark_size ?? 42)}
                      onChange={(e) =>
                        set("watermark_size", Number(e.target.value))
                      }
                      aria-label="Tamanho da marca d'água"
                      className="w-full accent-[#b8912f]"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                      Opacidade: {Math.round(Number(options.watermark_opacity ?? 0.15) * 100)}%
                    </label>
                    <input
                      type="range"
                      min={5}
                      max={60}
                      value={Math.round(Number(options.watermark_opacity ?? 0.15) * 100)}
                      onChange={(e) =>
                        set("watermark_opacity", Number(e.target.value) / 100)
                      }
                      aria-label="Opacidade da marca d'água"
                      className="w-full accent-[#b8912f]"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {toolId === "outline" && (
          <div className="space-y-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="idx-title"
                  className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                >
                  Título do índice
                </label>
                <input
                  id="idx-title"
                  type="text"
                  maxLength={80}
                  value={String(options.title ?? "")}
                  onChange={(e) => set("title", e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
              </div>
              <div className="space-y-2 sm:pt-7">
                <Switch
                  label="Inserir páginas de índice no início"
                  checked={Boolean(options.insert_index)}
                  onChange={(v) => set("insert_index", v)}
                  hint="A numeração dos anexos é deslocada automaticamente."
                />
                <Switch
                  label="Criar sumário navegável (bookmarks)"
                  checked={Boolean(options.bookmarks)}
                  onChange={(v) => set("bookmarks", v)}
                />
              </div>
            </div>
            <div>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-ink-800 dark:text-slate-200">
                  Anexos (nome e página inicial)
                </h3>
                <button
                  type="button"
                  onClick={addEntry}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-gold-400 dark:border-slate-700"
                >
                  + Adicionar anexo
                </button>
              </div>
              {entries.length === 0 && (
                <p className="mb-2 text-xs text-slate-500">
                  Sem anexos informados, o serviço usa os bookmarks já existentes
                  no PDF (se houver).
                </p>
              )}
              <ul className="space-y-2">
                {entries.map((entry, index) => (
                  <li key={index} className="flex gap-2">
                    <input
                      aria-label={`Nome do anexo ${index + 1}`}
                      type="text"
                      placeholder="Ex.: ANEXO I — Procuração"
                      value={entry.label}
                      onChange={(e) => updateEntry(index, "label", e.target.value)}
                      className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                    />
                    <input
                      aria-label={`Página do anexo ${index + 1}`}
                      type="number"
                      min={1}
                      value={entry.page || ""}
                      onChange={(e) => updateEntry(index, "page", e.target.value)}
                      className="w-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                    />
                    <button
                      type="button"
                      onClick={() => removeEntry(index)}
                      aria-label={`Remover anexo ${index + 1}`}
                      className="rounded-md border border-red-200 px-3 text-sm text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {toolId === "integrity" && (
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="cert-emitente"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Emitente (opcional)
              </label>
              <input
                id="cert-emitente"
                type="text"
                placeholder="Ex.: Escritório Silva Advogados"
                value={String(options.emitente ?? "")}
                onChange={(e) => set("emitente", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <div>
              <label
                htmlFor="cert-obs"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Observação (opcional)
              </label>
              <input
                id="cert-obs"
                type="text"
                placeholder="Ex.: Processo 123456-78.2026.8.26.0100"
                value={String(options.observacao ?? "")}
                onChange={(e) => set("observacao", e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <p className="text-xs text-slate-500 sm:col-span-2">
              O certificado lista nome, tamanho e SHA-256 de cada arquivo e deixa
              o hash pronto para assinatura digital ICP-Brasil.
            </p>
          </div>
        )}
      </div>

      {/* ---------------- 3. Execução ---------------- */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={run}
          disabled={!files.length || files.length < minFiles || active || uploading}
          className="rounded-md bg-ink-800 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gold-500 dark:text-slate-950"
        >
          {config.action}
        </button>
        {files.length < minFiles && (
          <span className="text-xs text-slate-500">
            Selecione ao menos {minFiles} arquivo(s).
          </span>
        )}
        {job && !active && (
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-slate-300 px-4 py-2.5 text-sm hover:border-gold-400 dark:border-slate-700"
          >
            Nova operação
          </button>
        )}
        <span className="text-xs text-slate-500">
          Os arquivos são cifrados e apagados automaticamente em 24 h.
        </span>
      </div>

      {job && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Progresso
          </h2>
          <ProgressBar
            progress={job.progress}
            message={job.message}
            pageCurrent={job.page_current}
            pageTotal={job.page_total}
            status={job.status}
          />

          {job.status === "error" && (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">{job.error}</p>
          )}

          {job.status === "done" && (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {outputs.map((out) => (
                  <div
                    key={out.id}
                    className="flex gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                  >
                    <FileThumb file={out} small />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink-800 dark:text-slate-100">
                        {out.name}
                      </p>
                      <p className="text-xs text-slate-500">{formatSize(out.size)}</p>
                      <div className="mt-2 flex gap-3 text-xs">
                        <a
                          href={api.downloadUrl(out.id)}
                          className="font-medium text-ink-600 hover:underline dark:text-gold-400"
                          download
                        >
                          ⬇ Baixar
                        </a>
                        <button
                          type="button"
                          onClick={() => api.deleteFile(out.id).then(() => setOutputs((p) => p.filter((f) => f.id !== out.id)))}
                          className="font-medium text-red-600 hover:underline dark:text-red-400"
                        >
                          Apagar agora
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {job.preview && (
                <div className="mt-4">
                  <h3 className="mb-2 text-sm font-semibold text-ink-800 dark:text-slate-200">
                    Prévia do conteúdo
                  </h3>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-950 dark:text-slate-300">
                    {job.preview.slice(0, 6000)}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ peças */

function FileThumb({ file, small }: { file: StoredFile; small?: boolean }) {
  const [broken, setBroken] = useState(false);
  const renderable = /\.(pdf|png|jpe?g|tiff?)$/i.test(file.name);
  const size = small ? "h-16 w-12" : "h-24 w-18";

  if (!renderable || broken) {
    return (
      <div
        className={`${size} flex items-center justify-center rounded-md bg-ink-100 text-[10px] font-semibold text-ink-600 dark:bg-slate-800 dark:text-slate-300`}
        aria-hidden="true"
      >
        {file.name.split(".").pop()?.toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={api.previewUrl(file.id, 0, 70)}
      alt={`Prévia de ${file.name}`}
      loading="lazy"
      onError={() => setBroken(true)}
      className={`${size} rounded-md border border-slate-200 object-cover dark:border-slate-700`}
    />
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const id = `sel-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Switch({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3 text-sm">
      <span className="text-ink-800 dark:text-slate-200">
        {label}
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 accent-[#b8912f]"
      />
    </label>
  );
}

/** Perfis de compressão: embutidos (PJe, e-SAJ...) + salvos pelo usuário. */
function Presets({
  options,
  onApply,
}: {
  options: Record<string, unknown>;
  onApply: (patch: Record<string, unknown>) => void;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const refresh = () => {
    api
      .presets("compress")
      .then((r) => setPresets(r.presets))
      .catch(() => undefined);
  };

  useEffect(refresh, []);

  const apply = (id: string) => {
    setSelected(id);
    const preset = presets.find((p) => p.id === id);
    if (preset) onApply(preset.options);
    setNote(null);
  };

  const save = async () => {
    setNote(null);
    try {
      const created = await api.savePreset("compress", name.trim(), {
        limit_mb: options.limit_mb,
        quality: options.quality,
        pdfa: options.pdfa,
        split: options.split,
      });
      setName("");
      refresh();
      setSelected(created.id);
      setNote(`Perfil "${created.name}" salvo.`);
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  const remove = async () => {
    if (!selected || selected.startsWith("builtin:")) return;
    await api.deletePreset(selected).catch(() => undefined);
    setSelected("");
    refresh();
  };

  const hasCustom = Boolean(selected && !selected.startsWith("builtin:"));

  return (
    <div className="space-y-2 sm:col-span-2">
      <Select
        label="Perfil de tribunal"
        value={selected}
        onChange={apply}
        options={[
          { value: "", label: "Escolher perfil..." },
          ...presets.map((p) => ({
            value: p.id,
            label: p.builtin ? `${p.name} — ${String(p.options.limit_mb)} MB` : `★ ${p.name}`,
          })),
        ]}
      />
      {presets.find((p) => p.id === selected)?.hint && (
        <p className="text-xs text-slate-500">
          {presets.find((p) => p.id === selected)?.hint}
        </p>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-40 flex-1">
          <label
            htmlFor="preset-name"
            className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
          >
            Salvar configuração atual
          </label>
          <input
            id="preset-name"
            type="text"
            value={name}
            maxLength={60}
            placeholder="Ex.: Tribunal Regional — 7 MB"
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
        </div>
        <button
          type="button"
          onClick={save}
          disabled={!name.trim()}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:border-gold-400 disabled:opacity-50 dark:border-slate-700"
        >
          Salvar perfil
        </button>
        {hasCustom && (
          <button
            type="button"
            onClick={remove}
            className="rounded-md border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400"
          >
            Apagar
          </button>
        )}
      </div>
      {note && <p className="text-xs text-slate-500">{note}</p>}
    </div>
  );
}
