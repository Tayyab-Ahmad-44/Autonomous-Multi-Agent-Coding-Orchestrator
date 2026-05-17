"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  API_BASE_URL,
  FeatureTask,
  getMission,
  Milestone,
  MissionDetail,
  MissionEvent,
  postMissionAction,
  ValidationReport,
} from "../../../lib/api";

const actions = [
  ["Generate plan", "plan"],
  ["Generate validation contract", "validation-contract"],
  ["Approve plan", "approve-plan"],
  ["Tick mission", "tick"],
  ["Validate mission", "validate"],
] as const;

export default function MissionDetailPage() {
  const params = useParams<{ id: string }>();
  const missionId = params.id;
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [liveState, setLiveState] = useState("connecting");

  const refresh = useCallback(async () => {
    const latest = await getMission(missionId);
    setMission(latest);
  }, [missionId]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    const source = new EventSource(`${API_BASE_URL}/missions/${missionId}/events`);
    source.addEventListener("open", () => setLiveState("live"));
    source.addEventListener("mission", (event) => {
      setLiveState("live");
      setMission(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("error", () => setLiveState("reconnecting"));
    return () => source.close();
  }, [missionId]);

  async function runAction(action: string) {
    setError(null);
    setBusyAction(action);
    try {
      await postMissionAction<unknown>(missionId, action);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Action failed: ${action}`);
    } finally {
      setBusyAction(null);
    }
  }

  const tasksByMilestone = useMemo(() => groupTasksByMilestone(mission?.feature_tasks ?? []), [mission]);

  if (!mission) {
    return <p className="text-sm text-slate-600">Loading mission...</p>;
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-normal">{mission.title}</h1>
            <span className="rounded-md bg-white px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-line">
              {mission.status}
            </span>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">{mission.goal}</p>
        </div>
        <span className="rounded-md bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-line">{liveState}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {actions.map(([label, action]) => (
          <button
            className="rounded-md border border-line bg-white px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-60"
            disabled={busyAction !== null}
            key={action}
            onClick={() => runAction(action)}
            type="button"
          >
            {busyAction === action ? "Working..." : label}
          </button>
        ))}
      </div>

      {error ? <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="space-y-3">
          <h2 className="text-lg font-semibold tracking-normal">Milestones</h2>
          {mission.milestones.length === 0 ? <EmptyState text="No milestones yet." /> : null}
          {mission.milestones.map((milestone) => (
            <MilestonePanel
              key={milestone.id}
              milestone={milestone}
              tasks={tasksByMilestone.get(milestone.id) ?? []}
            />
          ))}
        </section>

        <section className="space-y-5">
          <EventTimeline events={mission.events} />
          <ValidationContractPanel mission={mission} />
          <ValidationReportsPanel reports={mission.validation_reports} />
        </section>
      </div>
    </section>
  );
}

function MilestonePanel({ milestone, tasks }: { milestone: Milestone; tasks: FeatureTask[] }) {
  return (
    <div className="rounded-md border border-line bg-white">
      <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
        <div>
          <h3 className="font-medium">{milestone.order_index}. {milestone.name}</h3>
          <p className="mt-1 text-sm text-slate-600">{milestone.description}</p>
        </div>
        <StatusLabel value={milestone.status} />
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
              <StatusLabel value={task.status} />
            </div>
          </div>
        ))}
      </div>
    </div>
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
              <StatusLabel value={report.passed ? "passed" : "failed"} />
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

function StatusLabel({ value }: { value: string }) {
  return <span className="shrink-0 rounded-md bg-panel px-2 py-1 text-xs font-medium text-slate-700">{value}</span>;
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
