import { useRef, useState, type DragEvent } from "react";

type Props = {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  hint?: string;
};

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.doc,.docx";

/** Área de envio com arrastar e soltar + clique (acessível por teclado). */
export default function Dropzone({ onFiles, disabled, hint }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Enviar arquivos: arraste e solte ou pressione Enter"
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={handleDrop}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
        over
          ? "border-gold-400 bg-gold-400/10"
          : "border-slate-300 bg-white hover:border-ink-600 hover:bg-ink-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-500"
      } ${disabled ? "pointer-events-none opacity-60" : ""}`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
      <svg viewBox="0 0 24 24" aria-hidden="true" className="mb-3 h-9 w-9 text-ink-600 dark:text-slate-400">
        <path
          d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <p className="text-sm font-medium text-ink-800 dark:text-slate-100">
        Arraste os arquivos aqui ou clique para escolher
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        {hint ?? "PDF, JPG, PNG, TIFF ou Word — até 100 MB por arquivo"}
      </p>
    </div>
  );
}
