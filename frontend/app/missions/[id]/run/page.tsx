"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  API_BASE_URL,
  FeatureTask,
  Milestone,
  MissionDetail,
  OpenPrResponse,
  Repository,
  ValidationReport,
  getMission,
  getRepository,
  openPr,
  tickMission,
  validateMission,
} from "../../../../lib/api";

// ── Status helpers ────────────────────────────────────────────────────────────

function statusStyle(s: string): string {
  switch (s) {
    case "completed":            return "bg-green-50 text-green-700 ring-green-200";
    case "running":              return "bg-blue-50 text-blue-700 ring-blue-200";
    case "failed":               return "bg-red-50 text-red-700 ring-red-200";
    case "validating":           return "bg-purple-50 text-purple-700 ring-purple-200";
    case "waiting_for_approval": return "bg-amber-50 text-amber-700 ring-amber-200";
    case "planning":             return "bg-indigo-50 text-indigo-700 ring-indigo-200";
    case "passed":               return "bg-green-50 text-green-700 ring-green-200";
    default:                     return "bg-slate-50 text-slate-600 ring-slate-200";
  }
}

function Badge({ value, large }: { value: string; large?: boolean }) {
  return (
    <span
      className={`shrink-0 rounded px-2 py-0.5 font-medium ring-1 ${statusStyle(value)} ${large ? "text-sm" : "text-xs"}`}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

function LiveDot({ state }: { state: string }) {
  const color = state === "live" ? "bg-green-500" : "bg-amber-400";
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500">
      <span className={`inline-block h-2 w-2 rounded-full ${color} ${state === "live" ? "animate-pulse" : ""}`} />
      {state}
    </span>
  );
}

// ── Primitives ────────────────────────────────────────────────────────────────

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-md border border-line bg-white ${className}`}>{children}</div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-base font-semibold text-ink">{children}</h2>;
}

function EmptyHint({ text }: { text: string }) {
  return <p className="px-4 py-4 text-sm text-slate-400">{text}</p>;
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {message}
    </div>
  );
}

type BtnVariant = "primary" | "secondary" | "danger" | "ghost";

function Btn({
  children,
  onClick,
  disabled,
  variant = "secondary",
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: BtnVariant;
  title?: string;
}) {
  const base = "rounded-md px-3 py-2 text-sm font-medium transition-opacity disabled:opacity-50";
  const styles: Record<BtnVariant, string> = {
    primary:   `${base} bg-accent text-white`,
    secondary: `${base} border border-line bg-white text-ink hover:bg-panel`,
    danger:    `${base} border border-red-200 bg-red-50 text-red-700 hover:bg-red-100`,
    ghost:     `${base} text-slate-500 hover:text-ink`,
  };
  return (
    <button
      className={styles[variant]}
      disabled={disabled}
      title={title}
      type="button"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

// ── Progress summary ──────────────────────────────────────────────────────────

function ProgressSummary({
  tasks,
  mission,
  repo,
}: {
  tasks: FeatureTask[];
  mission: MissionDetail;
  repo: Repository | null;
}) {
  const total     = tasks.length;
  const completed = tasks.filter((t) => t.status === "completed").length;
  const failed    = tasks.filter((t) => t.status === "failed").length;
  const running   = tasks.filter((t) => t.status === "running").length;
  const pct       = total === 0 ? 0 : Math.round((completed / total) * 100);

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        {/* Left: counts */}
        <div className="space-y-3">
          <div className="flex flex-wrap gap-4 text-sm">
            <Stat label="Tasks" value={`${completed} / ${total}`} />
            {running > 0  && <Stat label="Running" value={String(running)}  color="text-blue-600" />}
            {failed > 0   && <Stat label="Failed"  value={String(failed)}   color="text-red-600" />}
          </div>
          {repo && (
            <p className="text-xs text-slate-500">
              Branch{" "}
              <span className="font-mono text-ink">
                mission/{mission.id.slice(0, 8)}
              </span>
              {" "}· <span className="font-mono">{repo.repo_url}</span>
            </p>
          )}
        </div>
        {/* Right: progress bar */}
        <div className="flex min-w-[160px] flex-col items-end gap-1">
          <span className="text-xs text-slate-500">{pct}% complete</span>
          <div className="h-2 w-40 overflow-hidden rounded-full bg-panel ring-1 ring-line">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      </div>
    </Card>
  );
}

function Stat({
  label,
  value,
  color = "text-ink",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-lg font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ── Milestones + tasks ────────────────────────────────────────────────────────

function MilestoneList({
  milestones,
  tasks,
}: {
  milestones: Milestone[];
  tasks: FeatureTask[];
}) {
  const byMilestone = useMemo(() => {
    const map = new Map<string, FeatureTask[]>();
    for (const t of tasks) {
      if (!t.milestone_id) continue;
      const arr = map.get(t.milestone_id) ?? [];
      arr.push(t);
      map.set(t.milestone_id, arr);
    }
    return map;
  }, [tasks]);

  if (milestones.length === 0) return <EmptyHint text="No milestones." />;

  return (
    <div className="space-y-3">
      {milestones.map((ms) => {
        const msTasks   = byMilestone.get(ms.id) ?? [];
        const msTotal   = msTasks.length;
        const msDone    = msTasks.filter((t) => t.status === "completed").length;
        const hasFailed = msTasks.some((t) => t.status === "failed");
        return (
          <Card key={ms.id}>
            <div
              className={`flex items-start justify-between gap-3 border-b border-line px-4 py-3 ${hasFailed ? "bg-red-50/40" : ""}`}
            >
              <div>
                <p className="font-medium text-ink">
                  {ms.order_index}. {ms.name}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">{ms.description}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <Badge value={ms.status} />
                {msTotal > 0 && (
                  <span className="text-xs text-slate-400">
                    {msDone}/{msTotal} tasks
                  </span>
                )}
              </div>
            </div>
            <div className="divide-y divide-line">
              {msTasks.length === 0 ? (
                <EmptyHint text="No tasks." />
              ) : (
                msTasks.map((task) => (
                  <div
                    key={task.id}
                    className={`flex items-start justify-between gap-3 px-4 py-3 ${task.status === "failed" ? "bg-red-50/60" : ""}`}
                  >
                    <div className="space-y-0.5 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{task.title}</span>
                        <span className="rounded bg-panel px-1.5 py-0.5 text-xs text-slate-500">
                          {task.task_type}
                        </span>
                        {task.assigned_agent_type && (
                          <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-600 ring-1 ring-indigo-200">
                            {task.assigned_agent_type}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 line-clamp-2">{task.description}</p>
                    </div>
                    <Badge value={task.status} />
                  </div>
                ))
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ── Validation reports ────────────────────────────────────────────────────────

function ValidationPanel({ reports }: { reports: ValidationReport[] }) {
  const latest = reports[0];
  return (
    <Card>
      <div className="border-b border-line px-4 py-3">
        <SectionTitle>Latest validation</SectionTitle>
      </div>
      {!latest ? (
        <EmptyHint text="No validation reports yet." />
      ) : (
        <div className="p-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">{latest.summary}</p>
            <Badge value={latest.passed ? "passed" : "failed"} />
          </div>
          {latest.issues.length > 0 && (
            <details className="rounded-md border border-line">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-red-700">
                {latest.issues.length} issue{latest.issues.length > 1 ? "s" : ""}
              </summary>
              <pre className="max-h-48 overflow-auto px-3 pb-3 text-xs leading-5 text-slate-700">
                {JSON.stringify(latest.issues, null, 2)}
              </pre>
            </details>
          )}
          {reports.length > 1 && (
            <p className="text-xs text-slate-400">{reports.length - 1} earlier report{reports.length > 2 ? "s" : ""} not shown.</p>
          )}
        </div>
      )}
    </Card>
  );
}

// ── Events timeline ───────────────────────────────────────────────────────────

function Timeline({ events }: { events: MissionDetail["events"] }) {
  const recent = events.slice(0, 20);
  return (
    <Card>
      <div className="border-b border-line px-4 py-3">
        <SectionTitle>Timeline</SectionTitle>
      </div>
      {recent.length === 0 ? (
        <EmptyHint text="No events yet." />
      ) : (
        <div className="divide-y divide-line">
          {recent.map((ev) => (
            <div className="flex items-start gap-3 px-4 py-3" key={ev.id}>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-ink">{ev.message}</p>
                <p className="text-xs text-slate-400">{ev.event_type}</p>
              </div>
              <time className="shrink-0 text-xs text-slate-400">
                {new Date(ev.created_at).toLocaleTimeString()}
              </time>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── PR result banner ──────────────────────────────────────────────────────────

function PrBanner({ pr }: { pr: OpenPrResponse }) {
  return (
    <div className="rounded-md border border-green-200 bg-green-50 p-4">
      <p className="text-sm font-medium text-green-800">Pull request opened 🎉</p>
      <a
        href={pr.pr_url}
        target="_blank"
        rel="noreferrer"
        className="mt-1 block break-all text-sm text-green-700 underline"
      >
        {pr.pr_url}
      </a>
      <p className="mt-1 text-xs text-green-600">Branch: {pr.branch}</p>
    </div>
  );
}

// ── Action toolbar ────────────────────────────────────────────────────────────

function Toolbar({
  mission,
  busy,
  onTick,
  onValidate,
  onOpenPr,
  onRefresh,
}: {
  mission: MissionDetail;
  busy: string | null;
  onTick: () => void;
  onValidate: () => void;
  onOpenPr: () => void;
  onRefresh: () => void;
}) {
  const s = mission.status;
  const isRunning    = s === "running";
  const isValidating = s === "validating";
  const isDone       = s === "completed";
  const isBusy       = busy !== null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-white px-4 py-3 shadow-sm">
      <Btn
        variant="primary"
        onClick={onTick}
        disabled={isBusy || isDone}
        title="Advance the mission by one orchestration step"
      >
        {busy === "tick" ? "Ticking…" : "Tick mission"}
      </Btn>
      {(isRunning || isValidating) && (
        <Btn onClick={onValidate} disabled={isBusy}>
          {busy === "validate" ? "Validating…" : "Validate now"}
        </Btn>
      )}
      {isDone && (
        <Btn variant="primary" onClick={onOpenPr} disabled={isBusy}>
          {busy === "open-pr" ? "Opening PR…" : "Open pull request"}
        </Btn>
      )}
      <Btn
        variant="ghost"
        onClick={onRefresh}
        disabled={isBusy}
        title="Pause — not yet supported by the orchestrator"
      >
        Pause
      </Btn>
      <Btn
        variant="ghost"
        onClick={onRefresh}
        title="Resume — not yet supported by the orchestrator"
      >
        Resume
      </Btn>
      <span className="flex-1" />
      <Btn variant="ghost" onClick={onRefresh} disabled={isBusy}>
        Refresh
      </Btn>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RunPage() {
  const { id }  = useParams<{ id: string }>();

  const [mission,    setMission]    = useState<MissionDetail | null>(null);
  const [repo,       setRepo]       = useState<Repository | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [busy,       setBusy]       = useState<string | null>(null);
  const [liveState,  setLiveState]  = useState("connecting");
  const [pr,         setPr]         = useState<OpenPrResponse | null>(null);

  const refresh = useCallback(async () => {
    const m = await getMission(id);
    setMission(m);
  }, [id]);

  // Initial load
  useEffect(() => {
    Promise.all([getMission(id), getRepository(id).catch(() => null)])
      .then(([m, r]) => { setMission(m); setRepo(r); })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  // SSE stream
  useEffect(() => {
    const source = new EventSource(`${API_BASE_URL}/missions/${id}/events`);
    source.addEventListener("open",    ()    => setLiveState("live"));
    source.addEventListener("mission", (ev)  => {
      setLiveState("live");
      setMission(JSON.parse((ev as MessageEvent).data));
    });
    source.addEventListener("error",   ()    => setLiveState("reconnecting"));
    return () => source.close();
  }, [id]);

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      const result = await fn();
      if (key === "open-pr") {
        setPr(result as OpenPrResponse);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${key} failed`);
    } finally {
      setBusy(null);
    }
  }

  const sortedMilestones = useMemo(
    () => [...(mission?.milestones ?? [])].sort((a, b) => a.order_index - b.order_index),
    [mission],
  );

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!mission) return <p className="text-sm text-red-600">{error ?? "Mission not found."}</p>;

  return (
    <section className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <Link href={`/missions/${id}/review`} className="text-sm text-slate-500 hover:text-ink">
              ← Review
            </Link>
            <span className="text-slate-300">/</span>
            <Link href="/missions" className="text-sm text-slate-500 hover:text-ink">
              Missions
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold text-ink">{mission.title}</h1>
            <Badge value={mission.status} large />
          </div>
        </div>
        <LiveDot state={liveState} />
      </div>

      {pr && <PrBanner pr={pr} />}
      {error && <ErrorBanner message={error} />}

      {/* Toolbar */}
      <Toolbar
        mission={mission}
        busy={busy}
        onTick={()     => run("tick",      () => tickMission(id))}
        onValidate={() => run("validate",  () => validateMission(id))}
        onOpenPr={()   => run("open-pr",   () => openPr(id))}
        onRefresh={()  => refresh()}
      />

      {/* Progress */}
      <ProgressSummary tasks={mission.feature_tasks} mission={mission} repo={repo} />

      {/* Main content */}
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        {/* Left: milestones + tasks */}
        <section className="space-y-3">
          <SectionTitle>Milestones &amp; tasks</SectionTitle>
          <MilestoneList milestones={sortedMilestones} tasks={mission.feature_tasks} />
        </section>

        {/* Right: validation + timeline */}
        <section className="space-y-3">
          <SectionTitle>Execution log</SectionTitle>
          <ValidationPanel reports={mission.validation_reports} />
          <Timeline events={mission.events} />
        </section>
      </div>
    </section>
  );
}
