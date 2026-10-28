import { useEffect, useState } from "react";
import {
  api,
  formatSize,
  type Job,
  type Preset,
  type StoredFile,
} from "../api/client";
import Dropzone from "../components/Dropzone";
import ProgressBar from "../components/ProgressBar";
import { useJobPolling } from "../hooks";

type Step = { kind: string; options: Record<string, unknown> };

const STEP_LABELS: Record<string, string> = {
  ocr: "OCR (→ PDF pesquisável)",
  blind: "PDF Blindado",
  compress: "Compressor",
  convert: "Converter",
  redact: "Redigir dados",
  number: "Numerar / Fls.",
};

/** Opções iniciais de cada passo ao ser adicionado ao fluxo. */
const STEP_DEFAULTS: Record<string, Record<string, unknown>> = {
  ocr: { output: "pdf", dpi: 300 },
  blind: { dpi: 300, jpeg_quality: 75 },
  compress: { limit_mb: 10, quality: "ebook", split: true, pdfa: false },
  convert: { target: "", dpi: 200 },
  redact: { mode: "black" },
  number: { style: "fls", start: 1, pad: 3, prefix: "", watermark: "" },
};

/** Lote: sobe vários arquivos (ou ZIP), monta um fluxo e baixa um ZIP. */
export default function Batch({ onBack }: { onBack: () => void }) {
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [steps, setSteps] = useState<Step[]>([
    { kind: "ocr", options: { ...STEP_DEFAULTS.ocr } },
  ]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [outputs, setOutputs] = useState<StoredFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = job?.status === "queued" || job?.status === "running";

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

  const refreshPresets = () => {
    api
      .presets("batch")
      .then((r) => setPresets(r.presets))
      .catch(() => undefined);
  };
  useEffect(refreshPresets, []);

  const setStep = (index: number, patch: Partial<Step>) =>
    setSteps((prev) =>
      prev.map((step, i) => (i === index ? { ...step, ...patch } : step))
    );

  const setStepOption = (index: number, key: string, value: unknown) =>
    setSteps((prev) =>
      prev.map((step, i) =>
        i === index
          ? { ...step, options: { ...step.options, [key]: value } }
          : step
      )
    );

  const handleFiles = async (selected: File[]) => {
    setError(null);
    setUploading(true);
    try {
      const uploaded = await api.upload(selected);
      setFiles((prev) => [...prev, ...uploaded]);
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

  const applyPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    const raw = (preset.options.steps as Step[] | undefined) ?? [];
    setSteps(
      raw.length
        ? raw.map((s) => ({
            kind: s.kind,
            options: { ...STEP_DEFAULTS[s.kind], ...(s.options ?? {}) },
          }))
        : steps
    );
    setNote(null);
  };

  const savePreset = async () => {
    setNote(null);
    try {
      const created = await api.savePreset("batch", presetName.trim(), { steps });
      setPresetName("");
      refreshPresets();
      setNote(`Fluxo "${created.name}" salvo.`);
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  const deletePreset = async (id: string) => {
    await api.deletePreset(id).catch(() => undefined);
    refreshPresets();
  };

  const run = async () => {
    if (!files.length || !steps.length) return;
    setError(null);
    setOutputs([]);
    try {
      const created = await api.createJob(
        "batch",
        files.map((f) => f.id),
        { steps }
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
            Processamento em lote
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Vários arquivos (ou um ZIP) passam pelo mesmo fluxo de operações e
            voltam reunidos em um único ZIP.
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
      <div className="space-y-3">
        {files.map((file, index) => (
          <div
            key={file.id}
            className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900"
          >
            <span className="w-6 text-center text-sm font-semibold text-slate-400">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-ink-800 dark:text-slate-100">
                {file.name}
              </p>
              <p className="text-xs text-slate-500">
                {formatSize(file.size)} · SHA-256 {file.sha256.slice(0, 16)}…
              </p>
            </div>
            <button
              type="button"
              onClick={() => removeFile(file.id)}
              disabled={active}
              className="text-xs font-medium text-red-600 hover:underline dark:text-red-400"
            >
              Remover
            </button>
          </div>
        ))}
        {files.length < 50 && (
          <Dropzone
            onFiles={handleFiles}
            disabled={uploading || active}
            accept=".zip,.pdf,.png,.jpg,.jpeg,.tif,.tiff,.doc,.docx"
            hint="Envie um ZIP com a pasta inteira, ou os arquivos — até 50 por lote"
          />
        )}
      </div>

      {/* ---------------- 2. Fluxo ---------------- */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Fluxo (sequência de operações)
        </h2>

        {/* presets de fluxo */}
        <div className="mb-4 space-y-2 sm:col-span-2">
          <label
            htmlFor="batch-preset"
            className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
          >
            Fluxo pronto
          </label>
          <select
            id="batch-preset"
            defaultValue=""
            onChange={(e) => applyPreset(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          >
            <option value="">Escolher fluxo...</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.builtin ? p.name : `★ ${p.name}`}
              </option>
            ))}
          </select>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-44 flex-1">
              <label
                htmlFor="batch-preset-name"
                className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
              >
                Salvar fluxo atual
              </label>
              <input
                id="batch-preset-name"
                type="text"
                value={presetName}
                maxLength={60}
                placeholder="Ex.: Digitalizar e comprimir"
                onChange={(e) => setPresetName(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </div>
            <button
              type="button"
              onClick={savePreset}
              disabled={!presetName.trim()}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:border-gold-400 disabled:opacity-50 dark:border-slate-700"
            >
              Salvar fluxo
            </button>
          </div>
          {note && <p className="text-xs text-slate-500">{note}</p>}
          {presets.some((p) => !p.builtin) && (
            <div className="mt-1">
              <p className="mb-1 text-xs font-medium text-slate-500">
                Meus fluxos salvos:
              </p>
              <ul className="flex flex-wrap gap-2">
                {presets
                  .filter((p) => !p.builtin)
                  .map((p) => (
                    <li
                      key={p.id}
                      className="flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1 text-xs dark:border-slate-700"
                    >
                      <span className="text-ink-800 dark:text-slate-200">★ {p.name}</span>
                      <button
                        type="button"
                        onClick={() => deletePreset(p.id)}
                        aria-label={`Apagar fluxo ${p.name}`}
                        className="text-red-600 hover:underline dark:text-red-400"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>

        <ul className="space-y-4">
          {steps.map((step, index) => (
            <li
              key={index}
              className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"
            >
              <div className="flex flex-wrap items-end gap-3">
                <div className="min-w-52 flex-1">
                  <label
                    htmlFor={`step-kind-${index}`}
                    className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
                  >
                    Passo {index + 1}
                  </label>
                  <select
                    id={`step-kind-${index}`}
                    value={step.kind}
                    onChange={(e) =>
                      setStep(index, {
                        kind: e.target.value,
                        options: { ...STEP_DEFAULTS[e.target.value] },
                      })
                    }
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                  >
                    {Object.entries(STEP_LABELS).map(([kind, label]) => (
                      <option key={kind} value={kind}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setSteps((prev) => prev.filter((_, i) => i !== index))
                  }
                  disabled={steps.length === 1}
                  className="rounded-md border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40 dark:border-red-900 dark:text-red-400"
                >
                  Remover passo
                </button>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {step.kind === "ocr" && (
                  <>
                    <SelectField
                      id={`ocr-out-${index}`}
                      label="Saída"
                      value={String(step.options.output)}
                      onChange={(v) => setStepOption(index, "output", v)}
                      options={[
                        { value: "pdf", label: "PDF pesquisável" },
                        { value: "txt", label: "Texto (.txt)" },
                        { value: "docx", label: "Word (.docx)" },
                      ]}
                    />
                    <SelectField
                      id={`ocr-dpi-${index}`}
                      label="Resolução"
                      value={String(step.options.dpi)}
                      onChange={(v) => setStepOption(index, "dpi", Number(v))}
                      options={[
                        { value: "200", label: "200 DPI" },
                        { value: "300", label: "300 DPI" },
                        { value: "600", label: "600 DPI" },
                      ]}
                    />
                  </>
                )}
                {step.kind === "blind" && (
                  <SelectField
                    id={`blind-dpi-${index}`}
                    label="Resolução"
                    value={String(step.options.dpi)}
                    onChange={(v) => setStepOption(index, "dpi", Number(v))}
                    options={[
                      { value: "150", label: "150 DPI — menor" },
                      { value: "200", label: "200 DPI" },
                      { value: "300", label: "300 DPI — alta" },
                    ]}
                  />
                )}
                {step.kind === "compress" && (
                  <>
                    <NumberField
                      id={`compress-limit-${index}`}
                      label="Limite por arquivo (MB, 0 = sem limite)"
                      value={Number(step.options.limit_mb ?? 10)}
                      onChange={(v) => setStepOption(index, "limit_mb", v)}
                    />
                    <SelectField
                      id={`compress-q-${index}`}
                      label="Qualidade"
                      value={String(step.options.quality)}
                      onChange={(v) => setStepOption(index, "quality", v)}
                      options={[
                        { value: "screen", label: "Tela (110 DPI)" },
                        { value: "ebook", label: "E-book (150 DPI)" },
                        { value: "printer", label: "Impressão (300 DPI)" },
                      ]}
                    />
                  </>
                )}
                {step.kind === "convert" && (
                  <SelectField
                    id={`convert-target-${index}`}
                    label="Formato de saída"
                    value={String(step.options.target ?? "")}
                    onChange={(v) => setStepOption(index, "target", v)}
                    options={[
                      { value: "", label: "Automático (recomendado)" },
                      { value: "pdf", label: "PDF" },
                      { value: "png", label: "PNG" },
                      { value: "jpg", label: "JPG" },
                      { value: "txt", label: "Texto (.txt)" },
                      { value: "docx", label: "Word (.docx)" },
                    ]}
                  />
                )}
                {step.kind === "redact" && (
                  <SelectField
                    id={`redact-mode-${index}`}
                    label="Modo da tarja"
                    value={String(step.options.mode)}
                    onChange={(v) => setStepOption(index, "mode", v)}
                    options={[
                      { value: "black", label: "Tarja preta" },
                      { value: "white", label: "Apagar (fundo branco)" },
                    ]}
                  />
                )}
                {step.kind === "number" && (
                  <>
                    <SelectField
                      id={`number-style-${index}`}
                      label="Estilo"
                      value={String(step.options.style)}
                      onChange={(v) => setStepOption(index, "style", v)}
                      options={[
                        { value: "fls", label: "Carimbo Fls." },
                        { value: "bates", label: "Bates" },
                        { value: "plain", label: "Numeração simples" },
                      ]}
                    />
                    <TextField
                      id={`number-wm-${index}`}
                      label="Marca d'água (opcional)"
                      value={String(step.options.watermark ?? "")}
                      placeholder="Ex.: USO JUDICIAL"
                      onChange={(v) => setStepOption(index, "watermark", v)}
                    />
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={() =>
            setSteps((prev) =>
              prev.length >= 6
                ? prev
                : [...prev, { kind: "convert", options: { ...STEP_DEFAULTS.convert } }]
            )
          }
          disabled={steps.length >= 6}
          className="mt-4 rounded-md border border-slate-300 px-3 py-2 text-sm hover:border-gold-400 disabled:opacity-50 dark:border-slate-700"
        >
          + Adicionar passo
        </button>
      </div>

      {/* ---------------- 3. Execução ---------------- */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={run}
          disabled={!files.length || !steps.length || active || uploading}
          className="rounded-md bg-ink-800 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gold-500 dark:text-slate-950"
        >
          Processar lote
        </button>
        {!files.length && (
          <span className="text-xs text-slate-500">Envie ao menos um arquivo.</span>
        )}
        {job && !active && (
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-slate-300 px-4 py-2.5 text-sm hover:border-gold-400 dark:border-slate-700"
          >
            Novo lote
          </button>
        )}
        <span className="text-xs text-slate-500">
          Passos incompatíveis com um arquivo são ignorados com aviso.
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
              <div className="mt-4 space-y-3">
                {outputs.map((out) => (
                  <div
                    key={out.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink-800 dark:text-slate-100">
                        {out.name}
                      </p>
                      <p className="text-xs text-slate-500">{formatSize(out.size)}</p>
                    </div>
                    <div className="flex gap-3 text-xs">
                      <a
                        href={api.downloadUrl(out.id)}
                        className="font-medium text-ink-600 hover:underline dark:text-gold-400"
                        download
                      >
                        ⬇ Baixar ZIP
                      </a>
                      <button
                        type="button"
                        onClick={() =>
                          api
                            .deleteFile(out.id)
                            .then(() =>
                              setOutputs((p) => p.filter((f) => f.id !== out.id))
                            )
                            .catch(() => undefined)
                        }
                        className="font-medium text-red-600 hover:underline dark:text-red-400"
                      >
                        Apagar agora
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              {job.preview && (
                <div className="mt-4">
                  <h3 className="mb-2 text-sm font-semibold text-ink-800 dark:text-slate-200">
                    Resumo
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

function SelectField({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
      >
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

function NumberField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
      >
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={0}
        max={500}
        step={0.5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
      />
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  placeholder,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200"
      >
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
      />
    </div>
  );
}
