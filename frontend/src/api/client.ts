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
  available: boolean; // false = flag desligada ("Em breve")
  phase?: number;
  category?: string;
  requires?: string[];
};

export type OcrLanguages = { languages: string[]; default: string };

export type ScanGroup = {
  type: string;
  label: string;
  value: string;
  count: number;
  pages: number[];
};;

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

export type SearchHit = {
  file_id: string;
  name: string;
  snippet: string; // já vem com <mark>...
  score: number;
  size: number | null;
  mime: string | null;
  created_at: string | null;
};

export type SearchResponse = {
  query: string;
  total: number;
  results: SearchHit[];
};

export type DiffOp = {
  type: "equal" | "delete" | "insert" | "replace";
  a: string[];
  b: string[];
};

export type CompareResponse = {
  file_a: { id: string; name: string; pages: number };
  file_b: { id: string; name: string; pages: number };
  summary: {
    pages_compared: number;
    pages_changed: number;
    lines_added: number;
    lines_removed: number;
    only_a: number;
    only_b: number;
  };
  pages: { index: number; changed: boolean; ops: DiffOp[] }[];
};

export type CaseFolder = {
  id: string;
  name: string;
  process_number: string;
  file_count: number;
  created_at: string | null;
};

export type CaseDetail = CaseFolder & {
  files: StoredFile[];
  operations: {
    id: string;
    kind: string;
    status: JobStatus;
    message: string;
    created_at: string | null;
    finished_at: string | null;
    files: number;
  }[];
};

export type AuthUser = {
  id: string;
  email: string;
  two_factor_enabled: boolean;
  authenticated?: boolean; // false = fallback de desenvolvimento
};

export type LoginResult =
  | { token: string; user: AuthUser }
  | { two_factor_required: true; challenge: string; expires_in: number };

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "same-origin", // envia/recebe o cookie httpOnly de sessão
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
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const auth = {
  me: () => request<AuthUser>("/auth/me"),
  login: (email: string, password: string) =>
    request<LoginResult>("/auth/login", json({ email, password })),
  login2fa: (challenge: string, code: string) =>
    request<{ token: string; user: AuthUser }>("/auth/login/2fa", json({ challenge, code })),
  register: (email: string, password: string) =>
    request<{ token: string; user: AuthUser }>("/auth/register", json({ email, password })),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  enable2fa: () => request<{ secret: string; uri: string; challenge: string }>("/auth/2fa/enable", { method: "POST" }),
  confirm2fa: (challenge: string, code: string) =>
    request<{ ok: boolean; two_factor_enabled: boolean }>("/auth/2fa/confirm", json({ challenge, code })),
  disable2fa: (code: string) =>
    request<{ ok: boolean; two_factor_enabled: boolean }>("/auth/2fa", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }),
};

export const api = {
  health: () => request<{ status: string }>("/meta/health"),
  auth,
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

  // ---------------- Fase 4 ----------------
  search: (q: string, limit = 20) =>
    request<SearchResponse>(
      `/search?q=${encodeURIComponent(q)}&limit=${limit}`
    ),
  compare: (file_a: string, file_b: string) =>
    request<CompareResponse>("/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_a, file_b }),
    }),

  listCases: () => request<CaseFolder[]>("/cases"),
  createCase: (name: string, process_number = "") =>
    request<CaseFolder>("/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, process_number }),
    }),
  getCase: (id: string) => request<CaseDetail>(`/cases/${id}`),
  updateCase: (id: string, patch: { name?: string; process_number?: string }) =>
    request<CaseFolder>(`/cases/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  deleteCase: (id: string) =>
    request<{ ok: boolean }>(`/cases/${id}`, { method: "DELETE" }),
  addCaseFiles: (id: string, file_ids: string[]) =>
    request<{ ok: boolean; moved: number }>(`/cases/${id}/files`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids }),
    }),
  removeCaseFile: (id: string, file_id: string) =>
    request<{ ok: boolean }>(`/cases/${id}/files/${file_id}`, {
      method: "DELETE",
    }),
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
