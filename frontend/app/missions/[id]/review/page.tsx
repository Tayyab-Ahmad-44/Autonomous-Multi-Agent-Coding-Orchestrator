"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FeatureTask,
  Milestone,
  MissionDetail,
  RepoProfile,
  Repository,
  analyzeRepo,
  approvePlan,
  generatePlan,
  generateValidationContract,
  getMission,
  getRepository,
  rejectPlan,
} from "../../../../lib/api";

// ── Shared primitives ─────────────────────────────────────────────────────────

function statusStyle(s: string): string {
  switch (s) {
    case "completed":           return "bg-green-50 text-green-700 ring-green-200";
    case "running":             return "bg-blue-50 text-blue-700 ring-blue-200";
    case "failed":              return "bg-red-50 text-red-700 ring-red-200";
    case "validating":          return "bg-purple-50 text-purple-700 ring-purple-200";
    case "waiting_for_approval":return "bg-amber-50 text-amber-700 ring-amber-200";
    case "planning":            return "bg-indigo-50 text-indigo-700 ring-indigo-200";
    default:                    return "bg-slate-50 text-slate-600 ring-slate-200";
  }
}

function Badge({ value }: { value: string }) {
  return (
    <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ring-1 ${statusStyle(value)}`}>
      {value.replace(/_/g, " ")}
    </span>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-md border border-line bg-white ${className}`}>{children}</div>
  );
}

function CardHeader({ children }: { children: React.ReactNode }) {
  return <div className="border-b border-line px-4 py-3">{children}</div>;
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

// ── Action button ─────────────────────────────────────────────────────────────

type BtnVariant = "primary" | "secondary" | "ghost";

function Btn({
  children,
  onClick,
  disabled,
  variant = "secondary",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: BtnVariant;
}) {
  const base = "rounded-md px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50";
  const styles: Record<BtnVariant, string> = {
    primary:   `${base} bg-accent text-white`,
    secondary: `${base} border border-line bg-white text-ink hover:bg-panel`,
    ghost:     `${base} text-slate-600 hover:text-ink`,
  };
  return (
    <button className={styles[variant]} disabled={disabled} type="button" onClick={onClick}>
      {children}
    </button>
  );
}

// ── Repository card ───────────────────────────────────────────────────────────

function RepoCard({ repo }: { repo: Repository | null }) {
  if (!repo) {
    return (
      <Card>
        <CardHeader><SectionTitle>Repository</SectionTitle></CardHeader>
        <EmptyHint text="No repository attached. Clone a repo from the wizard before running the mission." />
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader><SectionTitle>Repository</SectionTitle></CardHeader>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 px-4 py-3 text-sm">
        <dt className="text-slate-500">URL</dt>
        <dd className="break-all font-mono text-xs text-ink">{repo.repo_url}</dd>
        <dt className="text-slate-500">Default branch</dt>
        <dd className="font-mono text-xs text-ink">{repo.default_branch}</dd>
        {repo.local_path && (
          <>
            <dt className="text-slate-500">Local path</dt>
            <dd className="break-all font-mono text-xs text-ink">{repo.local_path}</dd>
          </>
        )}
      </dl>
    </Card>
  );
}

// ── Repo profile ──────────────────────────────────────────────────────────────

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <dt className="w-36 shrink-0 text-slate-500">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}

function RepoProfileCard({ profile }: { profile: RepoProfile | null }) {
  if (!profile) return null;
  return (
    <Card>
      <CardHeader><SectionTitle>Repository profile</SectionTitle></CardHeader>
      <dl className="space-y-1.5 px-4 py-3">
        {profile.language && <ProfileRow label="Language" value={profile.language} />}
        {profile.frontend_framework && <ProfileRow label="Frontend" value={profile.frontend_framework} />}
        {profile.backend_framework && <ProfileRow label="Backend" value={profile.backend_framework} />}
        {profile.package_manager && <ProfileRow label="Package manager" value={profile.package_manager} />}
        {profile.test_commands.length > 0 && (
          <ProfileRow label="Test commands" value={profile.test_commands.join(", ")} />
        )}
        {profile.build_commands.length > 0 && (
          <ProfileRow label="Build commands" value={profile.build_commands.join(", ")} />
        )}
        {profile.important_dirs.length > 0 && (
          <ProfileRow label="Key directories" value={profile.important_dirs.join(", ")} />
        )}
        <ProfileRow label="Docker" value={profile.has_docker ? "Yes" : "No"} />
        <ProfileRow label="CI" value={profile.has_ci ? "Yes" : "No"} />
        {profile.readme_summary && (
          <div className="pt-2">
            <p className="text-xs font-medium text-slate-500 mb-1">README excerpt</p>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-panel p-2 text-xs text-slate-700">
              {profile.readme_summary}
            </pre>
          </div>
        )}
      </dl>
    </Card>
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

  if (milestones.length === 0) {
    return (
      <Card>
        <CardHeader><SectionTitle>Plan</SectionTitle></CardHeader>
        <EmptyHint text="No plan generated yet." />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {milestones.map((ms) => (
        <Card key={ms.id}>
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium text-ink">
                  {ms.order_index}. {ms.name}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">{ms.description}</p>
              </div>
              <Badge value={ms.status} />
            </div>
          </CardHeader>
          <div className="divide-y divide-line">
            {(byMilestone.get(ms.id) ?? []).length === 0 ? (
              <EmptyHint text="No tasks." />
            ) : (
              (byMilestone.get(ms.id) ?? []).map((task) => (
                <div className="px-4 py-3" key={task.id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{task.title}</span>
                        <span className="rounded bg-panel px-1.5 py-0.5 text-xs text-slate-500">
                          {task.task_type}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">{task.description}</p>
                    </div>
                    <Badge value={task.status} />
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}

// ── Validation contract ───────────────────────────────────────────────────────

function ContractSection({ mission }: { mission: MissionDetail }) {
  const contract = mission.validation_contract;
  if (!contract) {
    return (
      <Card>
        <CardHeader><SectionTitle>Validation contract</SectionTitle></CardHeader>
        <EmptyHint text="No validation contract yet." />
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader><SectionTitle>Validation contract</SectionTitle></CardHeader>
      <div className="space-y-3 p-4">
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-panel p-3 text-xs leading-5 text-slate-700">
          {contract.content}
        </pre>
        {contract.assertions.length > 0 && (
          <details className="rounded-md border border-line">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Assertions ({contract.assertions.length})
            </summary>
            <pre className="max-h-56 overflow-auto px-3 pb-3 text-xs leading-5 text-slate-700">
              {JSON.stringify(contract.assertions, null, 2)}
            </pre>
          </details>
        )}
        {contract.required_tests.length > 0 && (
          <details className="rounded-md border border-line">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">
              Required tests ({contract.required_tests.length})
            </summary>
            <pre className="max-h-56 overflow-auto px-3 pb-3 text-xs leading-5 text-slate-700">
              {JSON.stringify(contract.required_tests, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </Card>
  );
}

// ── Action bar ────────────────────────────────────────────────────────────────

function ActionBar({
  mission,
  repository,
  busy,
  onAnalyzeRepo,
  onGeneratePlan,
  onGenerateContract,
  onApprovePlan,
  onRegeneratePlan,
  onRegenerateContract,
}: {
  mission: MissionDetail;
  repository: Repository | null;
  busy: string | null;
  onAnalyzeRepo: () => void;
  onGeneratePlan: () => void;
  onGenerateContract: () => void;
  onApprovePlan: () => void;
  onRegeneratePlan: () => void;
  onRegenerateContract: () => void;
}) {
  const hasRepo     = repository !== null && repository.local_path !== null;
  const hasProfile  = mission.repo_profile !== null;
  const hasPlan     = mission.milestones.length > 0;
  const hasContract = mission.validation_contract !== null;
  const canApprove  = hasPlan && hasContract;
  const isBusy      = busy !== null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-wrap gap-2">
        {hasRepo && (
          <Btn onClick={onAnalyzeRepo} disabled={isBusy} variant="ghost">
            {busy === "analyze" ? "Analyzing…" : hasProfile ? "Re-analyze repo" : "Analyze repo"}
          </Btn>
        )}
        {hasPlan && (
          <Btn onClick={onRegeneratePlan} disabled={isBusy} variant="ghost">
            {busy === "regenerate-plan" ? "Regenerating…" : "Regenerate plan"}
          </Btn>
        )}
        {hasContract && (
          <Btn onClick={onRegenerateContract} disabled={isBusy} variant="ghost">
            {busy === "regenerate-contract" ? "Regenerating…" : "Regenerate contract"}
          </Btn>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {!hasPlan && (
          <Btn onClick={onGeneratePlan} disabled={isBusy} variant="primary">
            {busy === "plan" ? "Generating plan…" : "Generate plan"}
          </Btn>
        )}
        {hasPlan && !hasContract && (
          <Btn onClick={onGenerateContract} disabled={isBusy} variant="primary">
            {busy === "contract" ? "Generating…" : "Generate validation contract"}
          </Btn>
        )}
        {canApprove && (
          <Btn onClick={onApprovePlan} disabled={isBusy} variant="primary">
            {busy === "approve" ? "Approving…" : "Approve plan"}
          </Btn>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router  = useRouter();

  const [mission,    setMission]    = useState<MissionDetail | null>(null);
  const [repository, setRepository] = useState<Repository | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [busy,       setBusy]       = useState<string | null>(null);

  const reload = useCallback(async () => {
    const updated = await getMission(id);
    setMission(updated);
  }, [id]);

  useEffect(() => {
    Promise.all([
      getMission(id),
      getRepository(id).catch(() => null),   // 404 is fine — no repo yet
    ])
      .then(([m, r]) => { setMission(m); setRepository(r); })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      if (key === "approve") {
        router.push(`/missions/${id}/run`);
        return;
      }
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${key} failed`);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!mission) return <p className="text-sm text-red-600">{error ?? "Mission not found."}</p>;

  return (
    <section className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <Link
              href="/missions"
              className="text-sm text-slate-500 hover:text-ink"
            >
              ← Missions
            </Link>
            <span className="text-slate-300">/</span>
            <span className="text-sm text-slate-500">Review</span>
          </div>
          <h1 className="text-2xl font-semibold text-ink">{mission.title}</h1>
          <div className="flex items-center gap-2">
            <Badge value={mission.status} />
          </div>
        </div>
        <Link
          href={`/missions/new`}
          className="text-sm text-slate-500 hover:text-ink"
        >
          ← Back to new mission
        </Link>
      </div>

      {/* Goal */}
      <Card>
        <CardHeader><SectionTitle>Goal</SectionTitle></CardHeader>
        <p className="px-4 py-3 text-sm leading-6 text-slate-700 whitespace-pre-wrap">{mission.goal}</p>
      </Card>

      {/* Action bar (top) */}
      {error && <ErrorBanner message={error} />}
      <ActionBar
        mission={mission}
        repository={repository}
        busy={busy}
        onAnalyzeRepo={()         => run("analyze",            () => analyzeRepo(id))}
        onGeneratePlan={()        => run("plan",               () => generatePlan(id))}
        onGenerateContract={()    => run("contract",           () => generateValidationContract(id))}
        onApprovePlan={()         => run("approve",            () => approvePlan(id))}
        onRegeneratePlan={()      => run("regenerate-plan",    async () => {
          await rejectPlan(id, "Regenerating plan", true);
          await generatePlan(id);
        })}
        onRegenerateContract={()  => run("regenerate-contract",() => generateValidationContract(id))}
      />

      {/* Repository */}
      <RepoCard repo={repository} />
      <RepoProfileCard profile={mission.repo_profile} />

      {/* Plan + contract side by side */}
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-3 min-w-0">
          <SectionTitle>Plan</SectionTitle>
          <MilestoneList
            milestones={[...mission.milestones].sort((a, b) => a.order_index - b.order_index)}
            tasks={mission.feature_tasks}
          />
        </div>
        <div className="space-y-3 min-w-0">
          <SectionTitle>Validation</SectionTitle>
          <ContractSection mission={mission} />
        </div>
      </div>

      {/* Action bar (bottom) */}
      <ActionBar
        mission={mission}
        repository={repository}
        busy={busy}
        onAnalyzeRepo={()         => run("analyze",            () => analyzeRepo(id))}
        onGeneratePlan={()        => run("plan",               () => generatePlan(id))}
        onGenerateContract={()    => run("contract",           () => generateValidationContract(id))}
        onApprovePlan={()         => run("approve",            () => approvePlan(id))}
        onRegeneratePlan={()      => run("regenerate-plan",    async () => {
          await rejectPlan(id, "Regenerating plan", true);
          await generatePlan(id);
        })}
        onRegenerateContract={()  => run("regenerate-contract",() => generateValidationContract(id))}
      />
    </section>
  );
}
