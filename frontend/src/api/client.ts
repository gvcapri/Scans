/* Cliente REST do LexScan — tudo em pt-BR, erros amigáveis. */

export type StoredFile = {
  id: string;
  name: string;
  mime: string;
  size: number;
  sha256: string;
  role: "input" | "output";
  job_id: string | null;
  created_at: string | null;
};

export type JobStatus = "queued" | "running" | "done" | "error";

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  page_current: number;
  page_total: number;
  message: string;
  error: string | null;
  options: Record<string, unknown>;
  input_file_ids: string[];
  output_file_ids: string[];
  preview: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type Tool = {
  id: string;
  name: string;
  description: string;
  phase: number;
  available: boolean;
  route: string;
};

export type OcrLanguages = { languages: string[]; default: string };

export type ScanGroup = {
  type: string;
  label: string;
  value: string;
  count: number;
  pages: number[];
};

export type ScanResult = {
  file_id: string;
  page_count: number;
  has_text_layer: boolean;
  total: number;
  groups: ScanGroup[];
  warning: string | null;
};

export type Preset = {
  id: string;
  name: string;
  tool: string;
  builtin: boolean;
  hint?: string;
  options: Record<string, unknown>;
  created_at?: string | null;
};

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail;
    } catch {
      /* corpo não é JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/meta/health"),
  tools: () => request<{ tools: Tool[] }>("/meta/tools"),
  languages: () => request<OcrLanguages>("/meta/languages"),

  upload: async (files: File[]): Promise<StoredFile[]> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return request<StoredFile[]>("/files", { method: "POST", body: form });
  },
  listFiles: () => request<StoredFile[]>("/files"),
  deleteFile: (id: string) => request<{ ok: boolean }>(`/files/${id}`, { method: "DELETE" }),
  downloadUrl: (id: string) => `${BASE}/files/${id}/download`,
  previewUrl: (id: string, page = 0, dpi = 90) =>
    `${BASE}/files/${id}/preview?page=${page}&dpi=${dpi}`,

  createJob: (kind: string, file_ids: string[], options: Record<string, unknown>) =>
    request<Job>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, file_ids, options }),
    }),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  listJobs: () => request<Job[]>("/jobs"),
  deleteJob: (id: string) => request<{ ok: boolean }>(`/jobs/${id}`, { method: "DELETE" }),

  scanRedact: (file_id: string, types?: string[]) =>
    request<ScanResult>("/redact/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id, types }),
    }),

  presets: (tool: string) =>
    request<{ tool: string; presets: Preset[] }>(`/presets?tool=${encodeURIComponent(tool)}`),
  savePreset: (tool: string, name: string, options: Record<string, unknown>) =>
    request<Preset>("/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, name, options }),
    }),
  deletePreset: (id: string) =>
    request<{ ok: boolean }>(`/presets/${id}`, { method: "DELETE" }),
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
