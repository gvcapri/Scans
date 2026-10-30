import {
  EyeOff,
  FileCheck2,
  Fingerprint,
  History,
  Lock,
  ScrollText,
  ServerCog,
  ShieldCheck,
} from "lucide-react";
import type { AuthUser } from "../api/client";

type Props = {
  user: AuthUser | null;
  onOpenAccount: () => void;
};

/**
 * Aba "Segurança & LGPD": garantias de criptografia, expurgo em 24 h e
 * conformidade legal — tudo baseado no que o backend realmente faz
 * (fail-closed de produção, cookies httpOnly, retenção e auditoria).
 */
const GUARANTEES = [
  {
    icon: Lock,
    title: "Criptografia ponta a ponta",
    body: "Tráfego protegido por TLS 1.3 e arquivos cifrados em repouso no volume do servidor. Nenhum documento é servido diretamente pelo Nginx: o download sempre passa pela API, com sessão autenticada.",
    tag: "TLS 1.3 · AES-256",
  },
  {
    icon: History,
    title: "Expurgo automático em 24 horas",
    body: "Todo arquivo enviado é marcado para exclusão automática em 24 h, incluindo entradas de banco, índices de busca, miniaturas e pré-visualizações geradas durante o processamento.",
    tag: "Retenção de 24 h",
  },
  {
    icon: Fingerprint,
    title: "Autenticação forte",
    body: "Senhas com Argon2id, verificação opcional em duas etapas (2FA TOTP), cookie de sessão httpOnly + SameSite, controle de tentativas de login e rate limiting nos endpoints de acesso.",
    tag: "Argon2id · 2FA",
  },
  {
    icon: EyeOff,
    title: "Privacidade por design (LGPD)",
    body: "Tarjamento irreversível de dados sensíveis, minimização de dados coletidos e processo decisório baseado em legítimo interesse para a finalidade única de adequação de peças aos sistemas judiciais.",
    tag: "LGPD · Art. 6º",
  },
  {
    icon: ScrollText,
    title: "Auditoria de acessos",
    body: "Autenticações, falhas de acesso e operações sensíveis são registradas em log estruturado, com rotação e proteção contra leitura indevida. Senhas e tokens nunca aparecem nos logs.",
    tag: "Logs imutáveis",
  },
  {
    icon: ServerCog,
    title: "Processamento isolado",
    body: "Cada job roda em ambiente isolado, sem privilégios de root e sem exposição de portas internas. Apenas as portas 80/443 ficam abertas publicamente na infraestrutura.",
    tag: "Isolamento por job",
  },
];

export default function SecurityPage({ user, onOpenAccount }: Props) {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-navy-900">
            <ShieldCheck className="h-6 w-6 text-emerald-600" aria-hidden />
            Segurança &amp; LGPD
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Garantias de criptografia, expurgo em 24 h e conformidade legal
            do JudiFiles.
          </p>
        </div>
        <button
          type="button"
          onClick={onOpenAccount}
          className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          Gerenciar segurança da conta
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {GUARANTEES.map((g) => {
          const Icon = g.icon;
          return (
            <article
              key={g.title}
              className="flex flex-col rounded-xl border border-line bg-white p-5 shadow-card"
            >
              <span className="mb-3 flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                  <Icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  {g.tag}
                </span>
              </span>
              <h2 className="text-sm font-semibold text-navy-900">{g.title}</h2>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                {g.body}
              </p>
            </article>
          );
        })}
      </div>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          <FileCheck2 className="h-4 w-4 text-emerald-600" aria-hidden />
          Seus dados sob a LGPD
        </h2>
        <div className="mt-3 grid gap-4 text-xs leading-relaxed text-slate-600 sm:grid-cols-2">
          <p>
            <strong className="text-navy-900">Finalidade:</strong> os
            documentos são processados exclusivamente para adequação a
            formatos dos sistemas judiciais (PJe, e-SAJ, Projudi, TRF/STJ) e
            descartados automaticamente em 24 h — não há retenção para outras
            finalidades.
          </p>
          <p>
            <strong className="text-navy-900">Direitos do titular:</strong>{" "}
            você pode apagar individualmente qualquer arquivo a qualquer
            momento pelo Histórico, além de encerrar a conta e revogar o 2FA
            pelo painel da conta.
          </p>
          <p>
            <strong className="text-navy-900">Controlador:</strong> o acesso é
            individual e nominal; cada operação usa o proprietário do recurso
            como base de autorização (não existem atalhos por identificador
            previsível na API).
          </p>
          <p>
            <strong className="text-navy-900">Incidentes:</strong> falhas de
            acesso são registradas em log e a instância opera em modo
            fail-closed: sem sessão válida ou flag ativa, a resposta é 401/503
            — nunca dado aberto.
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4 text-xs">
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-600">
            Conta: {user?.email ?? "—"}
          </span>
          <span
            className={`rounded-full px-2.5 py-1 font-medium ${
              user?.two_factor_enabled
                ? "bg-emerald-50 text-emerald-600"
                : "bg-amber-50 text-amber-600"
            }`}
          >
            {user?.two_factor_enabled
              ? "2FA ativado"
              : "2FA recomendado — ative no painel da conta"}
          </span>
        </div>
      </div>
    </section>
  );
}
