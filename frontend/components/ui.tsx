import React from "react";

// ── Buttons ──────────────────────────────────────────────────────────────────

export function Btn({
  children,
  disabled,
  type = "button",
  variant = "primary",
  size = "md",
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  type?: "button" | "submit";
  variant?: "primary" | "ghost" | "danger";
  size?: "md" | "sm";
  onClick?: () => void;
}) {
  const base =
    "rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const sizing = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm";
  const styles =
    variant === "primary"
      ? "bg-accent text-white hover:bg-accentDark"
      : variant === "danger"
        ? "border border-red-200 bg-white text-red-700 hover:bg-red-50"
        : "border border-line bg-white text-ink hover:bg-panel";
  return (
    <button className={`${base} ${sizing} ${styles}`} disabled={disabled} type={type} onClick={onClick}>
      {children}
    </button>
  );
}

// ── Feedback ─────────────────────────────────────────────────────────────────

export function ErrorBanner({ message }: { message: string }) {
  return (
    <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{message}</p>
  );
}

export function Spinner({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin text-accent`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

// ── Action row (used by multi-step wizards) ─────────────────────────────────

export function ActionRow({
  label,
  description,
  status,
  error,
  onClick,
}: {
  label: string;
  description: string;
  status: "idle" | "running" | "done" | "error";
  error: string | null;
  onClick: () => void;
}) {
  const indicator =
    status === "done" ? (
      <span className="rounded px-2 py-0.5 text-xs font-medium text-green-700 bg-green-50 border border-green-200">
        Done
      </span>
    ) : status === "running" ? (
      <span className="flex items-center gap-1.5 text-xs text-slate-500">
        <Spinner className="h-3.5 w-3.5" />
        Running…
      </span>
    ) : null;

  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <p className="text-sm font-medium text-ink">{label}</p>
          <p className="text-xs text-slate-500">{description}</p>
          {status === "error" && error && <p className="mt-1 text-xs text-red-600">{error}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {indicator}
          <Btn variant={status === "done" ? "ghost" : "primary"} disabled={status === "running"} onClick={onClick}>
            {status === "done" ? "Re-run" : label}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Status badge ─────────────────────────────────────────────────────────────

type StatusTone = "neutral" | "active" | "warning" | "danger" | "success";

const STATUS_TONE: Record<string, StatusTone> = {
  draft: "neutral",
  pending: "neutral",
  planning: "active",
  running: "active",
  validating: "active",
  waiting_for_approval: "warning",
  failed: "danger",
  completed: "success",
  passed: "success",
};

const TONE_STYLES: Record<StatusTone, string> = {
  neutral: "bg-panel text-slate-600 ring-1 ring-line",
  active: "bg-accent/10 text-accent ring-1 ring-accent/30",
  warning: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-1 ring-red-200",
  success: "bg-green-50 text-green-700 ring-1 ring-green-200",
};

export function StatusBadge({ value }: { value: string }) {
  const tone = STATUS_TONE[value] ?? "neutral";
  const label = value.replace(/_/g, " ");
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium capitalize ${TONE_STYLES[tone]}`}
    >
      {tone === "active" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
      {label}
    </span>
  );
}
