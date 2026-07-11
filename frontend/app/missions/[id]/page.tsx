"use client";

import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE_URL,
  FeatureTask,
  getMission,
  Milestone,
  MissionDetail,
  MissionEvent,
  approvePlan,
  postMissionAction,
  rejectPlan,
  ValidationReport,
} from "../../../lib/api";
import { RequireAuth } from "../../../components/RequireAuth";
import { getToken } from "../../../lib/token";
import { Btn, ErrorBanner, StatusBadge } from "../../../components/ui";

const ADVANCED_ACTIONS = [
  ["Re-run plan", "plan"],
  ["Regenerate validation contract", "validation-contract"],
  ["Validate now", "validate"],
] as const;

const FLASH_DURATION_MS = 1500;

function useStatusChangeFlash(items: { id: string; status: string }[]) {
  const prevStatuses = useRef<Map<string, string>>(new Map());
  const [flashing, setFlashing] = useState<Set<string>>(new Set());

  useEffect(() => {
    const prev = prevStatuses.current;
    const changed: string[] = [];
    for (const item of items) {
      const prevStatus = prev.get(item.id);
      if (prevStatus !== undefined && prevStatus !== item.status) {
        changed.push(item.id);
      }
      prev.set(item.id, item.status);
    }
    if (changed.length === 0) return;

    setFlashing((current) => new Set([...current, ...changed]));
    const timer = setTimeout(() => {
      setFlashing((current) => {
        const next = new Set(current);
        for (const id of changed) next.delete(id);
        return next;
      });
    }, FLASH_DURATION_MS);
    return () => clearTimeout(timer);
  }, [items]);

  return flashing;
}

export default function MissionDetailPage() {
  return (
    <RequireAuth>
      <MissionDetailPageContent />
    </RequireAuth>
  );
}

function MissionDetailPageContent() {
  const params = useParams<{ id: string }>();
  const missionId = params.id;
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [liveState, setLiveState] = useState("connecting");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState("");

  const refresh = useCallback(async () => {
    const latest = await getMission(missionId);
    setMission(latest);
  }, [missionId]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    // EventSource can't send an Authorization header, so the token travels
    // as a query param for this one streaming endpoint (see CurrentUserFromStream).
    const source = new EventSource(
      `${API_BASE_URL}/missions/${missionId}/events?token=${encodeURIComponent(token)}`,
    );
    source.addEventListener("open", () => setLiveState("live"));
    source.addEventListener("mission", (event) => {
      setLiveState("live");
      setMission(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("error", () => setLiveState("reconnecting"));
    return () => source.close();
  }, [missionId]);

  async function runAction(action: string, fn: () => Promise<unknown>) {
    setError(null);
    setBusyAction(action);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Action failed: ${action}`);
    } finally {
      setBusyAction(null);
    }
  }

  async function onReject(event: FormEvent) {
    event.preventDefault();
    await runAction("reject-plan", () => rejectPlan(missionId, rejectFeedback, true));
    setRejectOpen(false);
    setRejectFeedback("");
  }

  const tasksByMilestone = useMemo(() => groupTasksByMilestone(mission?.feature_tasks ?? []), [mission]);
  const flashingTaskIds = useStatusChangeFlash(mission?.feature_tasks ?? []);
  const flashingMilestoneIds = useStatusChangeFlash(mission?.milestones ?? []);

  if (!mission) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-600">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
        Loading mission…
      </div>
    );
  }

  const latestFailureEvent = mission.status === "failed"
    ? [...mission.events].reverse().find((e) => e.event_type.includes("failed") || e.event_type.includes("error"))
    : null;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-normal">{mission.title}</h1>
            <StatusBadge value={mission.status} />
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">{mission.goal}</p>
        </div>
        <span className="rounded-md bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-line">{liveState}</span>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {mission.status === "waiting_for_approval" && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-md border border-accent/30 bg-accent/5 p-4">
          <div>
            <p className="text-sm font-medium text-ink">Plan ready for review</p>
            <p className="mt-0.5 text-xs text-slate-600">
              Once approved, the orchestrator will work through every milestone autonomously — dispatching Codex,
              validating results, and retrying fixes — with no further clicks needed.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Btn variant="ghost" disabled={busyAction !== null} onClick={() => setRejectOpen((v) => !v)}>
              Reject
            </Btn>
            <Btn
              disabled={busyAction !== null}
              onClick={() => runAction("approve-plan", () => approvePlan(missionId))}
            >
              {busyAction === "approve-plan" ? "Starting…" : "Approve & Start"}
            </Btn>
          </div>
        </div>
      )}

      {rejectOpen && (
        <form onSubmit={onReject} className="space-y-3 rounded-md border border-line bg-white p-4">
          <label className="block">
            <span className="text-sm font-medium">What should change about the plan?</span>
            <textarea
              className="mt-1 min-h-20 w-full rounded-md border border-line px-3 py-2 text-sm outline-none focus:border-accent"
              value={rejectFeedback}
              onChange={(e) => setRejectFeedback(e.target.value)}
              placeholder="e.g. Split milestone 2 into smaller steps"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Btn variant="ghost" onClick={() => setRejectOpen(false)}>
              Cancel
            </Btn>
            <Btn type="submit" disabled={busyAction !== null}>
              Send back for re-planning
            </Btn>
          </div>
        </form>
      )}

      {mission.status === "failed" && (
        <div className="space-y-3 rounded-md border border-red-200 bg-red-50 p-4">
          <div>
            <p className="text-sm font-medium text-red-800">Mission paused — needs your input</p>
            <p className="mt-0.5 text-xs text-red-700">
              {latestFailureEvent?.message ?? "The orchestrator hit a limit it couldn't resolve on its own."}
            </p>
          </div>
          <Btn disabled={busyAction !== null} onClick={() => runAction("tick", () => postMissionAction(missionId, "tick"))}>
            {busyAction === "tick" ? "Resuming…" : "Resume"}
          </Btn>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold tracking-normal">Milestones</h2>
          {mission.milestones.length === 0 ? <EmptyState text="No milestones yet." /> : null}
          {mission.milestones.map((milestone) => (
            <MilestonePanel
              key={milestone.id}
              milestone={milestone}
              tasks={tasksByMilestone.get(milestone.id) ?? []}
              milestoneFlashing={flashingMilestoneIds.has(milestone.id)}
              flashingTaskIds={flashingTaskIds}
            />
          ))}
        </section>

        <section className="space-y-5">
          <EventTimeline events={mission.events} />
          <ValidationContractPanel mission={mission} />
          <ValidationReportsPanel reports={mission.validation_reports} />
        </section>
      </div>

      <AdvancedActions missionId={missionId} busyAction={busyAction} runAction={runAction} />
    </section>
  );
}

function AdvancedActions({
  missionId,
  busyAction,
  runAction,
}: {
  missionId: string;
  busyAction: string | null;
  runAction: (action: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <details className="rounded-md border border-line bg-white">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-600">
        Advanced
      </summary>
      <div className="flex flex-wrap gap-2 border-t border-line p-4">
        {ADVANCED_ACTIONS.map(([label, action]) => (
          <Btn
            key={action}
            variant="ghost"
            size="sm"
            disabled={busyAction !== null}
            onClick={() => runAction(action, () => postMissionAction(missionId, action))}
          >
            {busyAction === action ? "Working…" : label}
          </Btn>
        ))}
      </div>
    </details>
  );
}

function MilestonePanel({
  milestone,
  tasks,
  milestoneFlashing,
  flashingTaskIds,
}: {
  milestone: Milestone;
  tasks: FeatureTask[];
  milestoneFlashing: boolean;
  flashingTaskIds: Set<string>;
}) {
  return (
    <div className="rounded-md border border-line bg-white">
      <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
        <div>
          <h3 className="font-medium">{milestone.order_index}. {milestone.name}</h3>
          <p className="mt-1 text-sm text-slate-600">{milestone.description}</p>
        </div>
        <FlashRing active={milestoneFlashing}>
          <StatusBadge value={milestone.status} />
        </FlashRing>
      </div>
      <div className="divide-y divide-line">
        {tasks.length === 0 ? <EmptyState text="No tasks in this milestone." /> : null}
        {tasks.map((task) => (
          <div className="px-4 py-3" key={task.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-sm font-medium">{task.title}</h4>
                  <span className="rounded-md bg-panel px-2 py-0.5 text-xs text-slate-600">{task.task_type}</span>
                </div>
                <p className="mt-1 text-sm text-slate-600">{task.description}</p>
              </div>
              <FlashRing active={flashingTaskIds.has(task.id)}>
                <StatusBadge value={task.status} />
              </FlashRing>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FlashRing({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-md ring-2 ring-offset-1 transition-shadow duration-700 ${
        active ? "ring-accent/60" : "ring-transparent"
      }`}
    >
      {children}
    </span>
  );
}

function ValidationContractPanel({ mission }: { mission: MissionDetail }) {
  const contract = mission.validation_contract;
  return (
    <section className="rounded-md border border-line bg-white p-4">
      <h2 className="text-lg font-semibold tracking-normal">Validation contract</h2>
      {!contract ? <EmptyState text="No validation contract yet." /> : null}
      {contract ? (
        <div className="mt-3 space-y-3">
          <pre className="max-h-56 overflow-auto rounded-md bg-panel p-3 text-xs leading-5 text-slate-700">
            {contract.content}
          </pre>
          <JsonBlock title="Assertions" value={contract.assertions} />
          <JsonBlock title="Required tests" value={contract.required_tests} />
        </div>
      ) : null}
    </section>
  );
}

function EventTimeline({ events }: { events: MissionEvent[] }) {
  return (
    <section className="rounded-md border border-line bg-white p-4">
      <h2 className="text-lg font-semibold tracking-normal">Timeline</h2>
      {events.length === 0 ? <EmptyState text="No events yet." /> : null}
      <div className="mt-3 divide-y divide-line">
        {events.map((event) => (
          <div className="py-3" key={event.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium">{event.message}</p>
                <p className="mt-1 text-xs text-slate-500">{event.event_type}</p>
              </div>
              <time className="shrink-0 text-xs text-slate-500">{new Date(event.created_at).toLocaleTimeString()}</time>
            </div>
            {event.payload ? <JsonBlock title="Payload" value={event.payload} /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function ValidationReportsPanel({ reports }: { reports: ValidationReport[] }) {
  return (
    <section className="rounded-md border border-line bg-white p-4">
      <h2 className="text-lg font-semibold tracking-normal">Validation reports</h2>
      {reports.length === 0 ? <EmptyState text="No validation reports yet." /> : null}
      <div className="mt-3 space-y-3">
        {reports.map((report) => (
          <div className="rounded-md border border-line p-3" key={report.id}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{report.summary}</span>
              <StatusBadge value={report.passed ? "passed" : "failed"} />
            </div>
            {report.issues.length ? <JsonBlock title="Issues" value={report.issues} /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="rounded-md border border-line bg-white p-3">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <pre className="mt-2 max-h-56 overflow-auto text-xs leading-5 text-slate-700">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="px-4 py-3 text-sm text-slate-500">{text}</p>;
}

function groupTasksByMilestone(tasks: FeatureTask[]) {
  const grouped = new Map<string, FeatureTask[]>();
  for (const task of tasks) {
    if (!task.milestone_id) {
      continue;
    }
    const existing = grouped.get(task.milestone_id) ?? [];
    existing.push(task);
    grouped.set(task.milestone_id, existing);
  }
  return grouped;
}
