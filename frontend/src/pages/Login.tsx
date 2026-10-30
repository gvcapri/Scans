import { useState, type FormEvent } from "react";
import { Scale } from "lucide-react";
import { auth, ApiError, type AuthUser } from "../api/client";

type Props = {
  onAuthenticated: (user: AuthUser) => void;
  initialError?: string | null;
  /** Volta à apresentação pública (quando o login foi pedido por um cadeado). */
  onBack?: () => void;
  /** Aba inicial: a landing pode abrir direto em "Criar conta". */
  initialMode?: "login" | "register";
};

/**
 * Tela de acesso (Fase 5): entrar, criar conta e concluir com 2FA TOTP.
 * O token volta em cookie httpOnly — nada sensível fica no JavaScript.
 */
export default function Login({ onAuthenticated, initialError, onBack, initialMode }: Props) {
  const [mode, setMode] = useState<"login" | "register">(initialMode ?? "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [busy, setBusy] = useState(false);

  const fail = (e: unknown) =>
    setError(e instanceof ApiError || e instanceof Error ? e.message : "Falha inesperada.");

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (challenge) {
        // segundo passo do login: código do app autenticador
        const result = await auth.login2fa(challenge, code.trim());
        onAuthenticated(result.user);
        return;
      }
      if (mode === "register") {
        const created = await auth.register(email.trim(), password);
        onAuthenticated(created.user);
        return;
      }
      const result = await auth.login(email.trim(), password);
      if ("two_factor_required" in result && result.two_factor_required) {
        setChallenge(result.challenge);
        setBusy(false);
        return;
      }
      onAuthenticated((result as { token: string; user: AuthUser }).user);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const input =
    "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-navy-900 " +
    "placeholder:text-slate-400 focus:border-blue-700 focus:outline-none focus:ring-2 " +
    "focus:ring-blue-700/25 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10 dark:bg-slate-950">
      <div className="w-full max-w-md">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-ink-800 dark:text-slate-400 dark:hover:text-slate-100"
          >
            ← Voltar
          </button>
        )}
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-navy-900 text-amber-600">
            <Scale className="h-6 w-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-navy-900">
            Judi<span className="text-amber-600">Files</span>
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Pronto para organizar e proteger seus documentos jurídicos?
          </p>
        </div>

        <div className="rounded-xl border border-line bg-white p-6 shadow-card dark:border-slate-800 dark:bg-slate-900">
          {error && (
            <p
              role="alert"
              className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
            >
              {error}
            </p>
          )}

          {challenge ? (
            <form onSubmit={submit} className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-ink-800 dark:text-slate-100">
                  Verificação em duas etapas
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  Para maior segurança, confirme o código de 6 dígitos gerado pelo seu
                  app autenticador.
                </p>
              </div>
              <div>
                <label htmlFor="otp" className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                  Código
                </label>
                <input
                  id="otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className={input}
                  placeholder="000000"
                />
              </div>
              <button
                type="submit"
                disabled={busy || code.length < 6}
                className="w-full rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-60 dark:bg-gold-500 dark:text-slate-900 dark:hover:bg-gold-400"
              >
                {busy ? "Verificando…" : "Confirmar e entrar"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setChallenge(null);
                  setCode("");
                  setError(null);
                }}
                className="w-full text-center text-sm text-slate-500 hover:underline dark:text-slate-400"
              >
                Voltar
              </button>
            </form>
          ) : (
            <>
              <h2 className="mb-4 text-lg font-semibold text-ink-800 dark:text-slate-100">
                {mode === "login" ? "Entrar na sua conta" : "Criar sua conta"}
              </h2>
              <div
                className="mb-5 flex rounded-md bg-slate-100 p-1 dark:bg-slate-800"
                role="tablist"
                aria-label="Acesso"
              >
                {(["login", "register"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="tab"
                    aria-selected={mode === m}
                    onClick={() => {
                      setMode(m);
                      setError(null);
                    }}
                    className={`flex-1 rounded px-3 py-1.5 text-sm font-medium transition ${
                      mode === m
                        ? "bg-white text-navy-900 shadow dark:bg-slate-900 dark:text-slate-100"
                        : "text-slate-600 dark:text-slate-400"
                    }`}
                  >
                    {m === "login" ? "Entrar" : "Criar conta"}
                  </button>
                ))}
              </div>

              <form onSubmit={submit} className="space-y-4">
                <div>
                  <label htmlFor="email" className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                    E-mail
                  </label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={input}
                    placeholder="voce@escritorio.adv.br"
                  />
                </div>
                <div>
                  <label htmlFor="password" className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                    Senha
                  </label>
                  <input
                    id="password"
                    type="password"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    required
                    minLength={mode === "register" ? 8 : 1}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={input}
                    placeholder={mode === "register" ? "mínimo de 8 caracteres" : "sua senha"}
                  />
                </div>
                <button
                  type="submit"
                  disabled={busy}
                className="w-full rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-60 dark:bg-gold-500 dark:text-slate-900 dark:hover:bg-gold-400"
              >
                {busy ? "Aguarde…" : mode === "login" ? "Entrar" : "Criar conta"}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-slate-500 dark:text-slate-400">
          Suas informações ficam protegidas com criptografia de ponta a ponta e são
          apagadas automaticamente após 24 horas.
        </p>
      </div>
    </div>
  );
}
