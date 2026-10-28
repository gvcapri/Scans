import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job } from "./api/client";

/** Tema claro/escuro persistido no navegador. */
export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", next);
      localStorage.setItem("lexscan-theme", next ? "dark" : "light");
      return next;
    });
  }, []);

  return { dark, toggle };
}

/** Polling do job enquanto ele estiver em andamento. */
export function useJobPolling(
  jobId: string | null,
  isActive: boolean,
  onTick?: (job: Job) => void
) {
  const tickRef = useRef(onTick);
  tickRef.current = onTick;

  useEffect(() => {
    if (!jobId || !isActive) return;
    let cancelled = false;

    const read = async () => {
      try {
        const job = await api.getJob(jobId);
        if (!cancelled) tickRef.current?.(job);
      } catch {
        /* falha transitória de rede: tenta de novo no próximo ciclo */
      }
    };

    read();
    const timer = window.setInterval(read, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, isActive]);
}
