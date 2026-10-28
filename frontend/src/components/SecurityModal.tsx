import { useEffect, useState } from "react";
import { auth, ApiError, type AuthUser } from "../api/client";

type Props = {
  user: AuthUser;
  onClose: () => void;
  onUserChange: (user: AuthUser) => void;
};

/**
 * Painel "Segurança" (Fase 5): ativar/desativar o 2FA TOTP.
 * Ativação em dois passos — o segredo só é gravado no banco depois que o
 * usuário confirma com um código válido do app autenticador.
 */
export default function SecurityModal({ user, onClose, onUserChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ secret: string; uri: string; challenge: string } | null>(null);
  const [code, setCode] = useState("");
  const [disableMode, setDisableMode] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const fail = (e: unknown) =>
    setError(e instanceof ApiError || e instanceof Error ? e.message : "Falha inesperada.");

  const startEnable = async () => {
    setError(null);
    setBusy(true);
    try {
      setSecret(await auth.enable2fa());
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!secret) return;
    setError(null);
    setBusy(true);
    try {
      await auth.confirm2fa(secret.challenge, code.trim());
      onUserChange({ ...user, two_factor_enabled: true });
      onClose();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const disable = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await auth.disable2fa(code.trim());
      onUserChange({ ...user, two_factor_enabled: false });
      onClose();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const input =
    "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink-900 " +
    "focus:border-gold-400 focus:outline-none focus:ring-2 focus:ring-gold-400/40 " +
    "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Segurança da conta"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-ink-800 dark:text-slate-100">Segurança</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400">{user.email}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            ✕
          </button>
        </div>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
          >
            {error}
          </p>
        )}

        {user.two_factor_enabled && !disableMode && (
          <div className="space-y-4">
            <p className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              ✅ Verificação em duas etapas ativa. Ao entrar, será pedido o código do app
              autenticador.
            </p>
            <button
              type="button"
              onClick={() => {
                setCode("");
                setError(null);
                setDisableMode(true);
              }}
              className="rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
            >
              Desativar 2FA
            </button>
          </div>
        )}

        {user.two_factor_enabled && disableMode && (
          <form onSubmit={disable} className="space-y-4">
            <div>
              <label htmlFor="off-code" className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                Código atual do app autenticador
              </label>
              <input
                id="off-code"
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
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={busy || code.length < 6}
                className="rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-60"
              >
                {busy ? "Desativando…" : "Confirmar desativação"}
              </button>
              <button
                type="button"
                onClick={() => setDisableMode(false)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm text-ink-800 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Cancelar
              </button>
            </div>
          </form>
        )}

        {!user.two_factor_enabled && !secret && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              A segunda camada exige um código de 6 dígitos do app autenticador (Google
              Authenticator, Authy, 1Password…) sempre que você entrar.
            </p>
            <button
              type="button"
              onClick={startEnable}
              disabled={busy}
              className="rounded-md bg-ink-800 px-4 py-2 text-sm font-medium text-white hover:bg-ink-700 disabled:opacity-60 dark:bg-gold-500 dark:text-slate-900 dark:hover:bg-gold-400"
            >
              {busy ? "Gerando…" : "Ativar 2FA"}
            </button>
          </div>
        )}

        {!user.two_factor_enabled && secret && (
          <form onSubmit={confirm} className="space-y-4">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                1. No app autenticador, adicione uma conta manualmente com este segredo:
              </p>
              <p className="mt-2 break-all rounded-md bg-slate-100 px-3 py-2 font-mono text-sm text-ink-900 dark:bg-slate-800 dark:text-slate-100">
                {secret.secret}
              </p>
              <a
                href={secret.uri}
                className="mt-2 inline-block text-sm text-gold-600 hover:underline dark:text-gold-400"
              >
                Abrir no app autenticador (otpauth://)
              </a>
            </div>
            <div>
              <label htmlFor="on-code" className="mb-1 block text-sm font-medium text-ink-800 dark:text-slate-200">
                2. Digite o código gerado para confirmar
              </label>
              <input
                id="on-code"
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
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={busy || code.length < 6}
                className="rounded-md bg-ink-800 px-4 py-2 text-sm font-medium text-white hover:bg-ink-700 disabled:opacity-60 dark:bg-gold-500 dark:text-slate-900 dark:hover:bg-gold-400"
              >
                {busy ? "Confirmando…" : "Confirmar e ativar"}
              </button>
              <button
                type="button"
                onClick={() => setSecret(null)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm text-ink-800 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Cancelar
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
