"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  Mission,
  RepositoryCloneResponse,
  attachOrCloneRepository,
  createMission,
  generatePlan,
  generateValidationContract,
} from "../../../lib/api";

// ── Step indicator ────────────────────────────────────────────────────────────

const STEP_LABELS = ["Mission details", "Repository", "Clone", "Next steps"];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEP_LABELS.map((label, idx) => (
        <div key={idx} className="flex flex-1 items-center">
          <div className="flex flex-col items-center gap-1">
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-colors ${
                idx < current
                  ? "bg-accent text-white"
                  : idx === current
                    ? "bg-accent/15 text-accent ring-1 ring-accent"
                    : "bg-panel text-slate-400 ring-1 ring-line"
              }`}
            >
              {idx < current ? "✓" : idx + 1}
            </span>
            <span
              className={`hidden text-xs sm:block ${
                idx === current ? "font-medium text-ink" : "text-slate-400"
              }`}
            >
              {label}
            </span>
          </div>
          {idx < STEP_LABELS.length - 1 && (
            <div
              className={`mx-2 mb-4 h-px flex-1 transition-colors ${idx < current ? "bg-accent" : "bg-line"}`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function ErrorBanner({ message }: { message: string }) {
  return (
    <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {message}
    </p>
  );
}

function Btn({
  children,
  disabled,
  type = "button",
  variant = "primary",
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  type?: "button" | "submit";
  variant?: "primary" | "ghost";
  onClick?: () => void;
}) {
  const base = "rounded-md px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50";
  const styles =
    variant === "primary"
      ? `${base} bg-accent text-white`
      : `${base} border border-line bg-white text-ink hover:bg-panel`;
  return (
    <button className={styles} disabled={disabled} type={type} onClick={onClick}>
      {children}
    </button>
  );
}

// ── Step 1: Mission details ───────────────────────────────────────────────────

function MissionDetailsStep({
  onCreated,
}: {
  onCreated: (mission: Mission) => void;
}) {
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const mission = await createMission({ title, goal });
      onCreated(mission);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create mission");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <label className="block">
        <span className="text-sm font-medium">Title</span>
        <input
          className="mt-1 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={255}
          placeholder="e.g. Add OAuth login"
        />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Goal</span>
        <textarea
          className="mt-1 min-h-32 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          required
          placeholder="Describe what the orchestrator should build or change…"
        />
      </label>
      {error && <ErrorBanner message={error} />}
      <div className="flex justify-end">
        <Btn type="submit" disabled={saving}>
          {saving ? "Creating…" : "Create mission →"}
        </Btn>
      </div>
    </form>
  );
}

// ── Step 2: Repository setup ──────────────────────────────────────────────────

function RepositorySetupStep({
  onNext,
}: {
  onNext: (repoUrl: string, defaultBranch: string) => void;
}) {
  const [repoUrl, setRepoUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!repoUrl.startsWith("https://") && !repoUrl.startsWith("git@")) {
      setError("Repo URL must start with https:// or git@");
      return;
    }
    onNext(repoUrl, defaultBranch);
  }

  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <p className="text-sm text-slate-600">
        Connect a GitHub repository so the orchestrator can read and modify code in a dedicated
        mission branch.
      </p>
      <label className="block">
        <span className="text-sm font-medium">Repository URL</span>
        <input
          className="mt-1 w-full rounded-md border border-line px-3 py-2 font-mono text-sm outline-none focus:border-accent"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          required
          placeholder="https://github.com/org/repo"
        />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Default branch</span>
        <input
          className="mt-1 w-full rounded-md border border-line px-3 py-2 font-mono text-sm outline-none focus:border-accent"
          value={defaultBranch}
          onChange={(e) => setDefaultBranch(e.target.value)}
          required
          placeholder="main"
        />
      </label>
      {error && <ErrorBanner message={error} />}
      <div className="flex justify-end">
        <Btn type="submit">Clone repository →</Btn>
      </div>
    </form>
  );
}

// ── Step 3: Clone status ──────────────────────────────────────────────────────

function CloneStatusStep({
  missionId,
  repoUrl,
  defaultBranch,
  onSuccess,
}: {
  missionId: string;
  repoUrl: string;
  defaultBranch: string;
  onSuccess: (result: RepositoryCloneResponse) => void;
}) {
  const [status, setStatus] = useState<"cloning" | "success" | "error">("cloning");
  const [result, setResult] = useState<RepositoryCloneResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runClone() {
    setStatus("cloning");
    setError(null);
    try {
      const res = await attachOrCloneRepository(missionId, { repo_url: repoUrl, default_branch: defaultBranch });
      setResult(res);
      setStatus("success");
      onSuccess(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Clone failed");
      setStatus("error");
    }
  }

  useEffect(() => {
    runClone();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "cloning") {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-slate-500">
        <Spinner />
        <p className="text-sm">Cloning repository…</p>
        <p className="max-w-xs text-center text-xs text-slate-400 font-mono">{repoUrl}</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="space-y-4">
        <ErrorBanner message={error ?? "Clone failed"} />
        <div className="flex justify-end">
          <Btn onClick={runClone}>Retry clone</Btn>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-3">
        <span className="text-green-600">✓</span>
        <span className="text-sm font-medium text-green-800">Repository cloned successfully</span>
      </div>
      <dl className="space-y-2 rounded-md border border-line bg-panel p-4 text-sm">
        <Row label="Repo URL" value={result!.repo_url} mono />
        <Row label="Default branch" value={result!.default_branch} mono />
        <Row label="Mission branch" value={result!.current_branch} mono />
        <Row label="Local path" value={result!.local_path ?? "—"} mono />
      </dl>
      <div className="flex justify-end">
        <Btn onClick={() => onSuccess(result!)}>Continue →</Btn>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3">
      <dt className="w-32 shrink-0 text-slate-500">{label}</dt>
      <dd className={`break-all text-ink ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-8 w-8 animate-spin text-accent"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

// ── Step 4: Next steps ────────────────────────────────────────────────────────

function NextStepsStep({
  mission,
  cloneResult,
}: {
  mission: Mission;
  cloneResult: RepositoryCloneResponse;
}) {
  const router = useRouter();
  const [planStatus, setPlanStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [contractStatus, setContractStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [planError, setPlanError] = useState<string | null>(null);
  const [contractError, setContractError] = useState<string | null>(null);

  async function onGeneratePlan() {
    setPlanStatus("running");
    setPlanError(null);
    try {
      await generatePlan(mission.id);
      setPlanStatus("done");
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "Plan generation failed");
      setPlanStatus("error");
    }
  }

  async function onGenerateContract() {
    setContractStatus("running");
    setContractError(null);
    try {
      await generateValidationContract(mission.id);
      setContractStatus("done");
    } catch (err) {
      setContractError(err instanceof Error ? err.message : "Contract generation failed");
      setContractStatus("error");
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-md border border-line bg-panel p-4 text-sm">
        <p className="font-medium text-ink">{mission.title}</p>
        <p className="mt-0.5 text-xs text-slate-500">
          Branch{" "}
          <span className="font-mono">{cloneResult.current_branch}</span>
          {" "}·{" "}
          <span className="font-mono">{cloneResult.repo_url}</span>
        </p>
      </div>

      <p className="text-sm text-slate-600">
        Your mission is set up. Start the orchestration process or go straight to the mission view.
      </p>

      <div className="space-y-3">
        <ActionRow
          label="Generate plan"
          description="Run the planner agent to break the goal into milestones and tasks."
          status={planStatus}
          error={planError}
          onClick={onGeneratePlan}
        />
        <ActionRow
          label="Generate validation contract"
          description="Define the assertions and tests the code must satisfy."
          status={contractStatus}
          error={contractError}
          onClick={onGenerateContract}
        />
      </div>

      <div className="flex justify-end border-t border-line pt-4">
        <Btn onClick={() => router.push(`/missions/${mission.id}`)}>
          Go to mission →
        </Btn>
      </div>
    </div>
  );
}

function ActionRow({
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
      <span className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5">Done</span>
    ) : status === "running" ? (
      <span className="text-xs text-slate-500">Running…</span>
    ) : null;

  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <p className="text-sm font-medium text-ink">{label}</p>
          <p className="text-xs text-slate-500">{description}</p>
          {status === "error" && error && <p className="text-xs text-red-600 mt-1">{error}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {indicator}
          <Btn
            variant={status === "done" ? "ghost" : "primary"}
            disabled={status === "running"}
            onClick={onClick}
          >
            {status === "done" ? "Re-run" : label}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ── Main wizard page ──────────────────────────────────────────────────────────

export default function NewMissionPage() {
  const [step, setStep] = useState(0);
  const [mission, setMission] = useState<Mission | null>(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [cloneResult, setCloneResult] = useState<RepositoryCloneResponse | null>(null);

  const stepTitles = [
    "Create your mission",
    "Attach a repository",
    "Cloning repository",
    "Start orchestration",
  ];
  const stepSubtitles = [
    "Define the goal the orchestrator will plan around.",
    "Connect a GitHub repo for the agents to work in.",
    "The backend is setting up the workspace.",
    "Kick off the agents or head to the mission view.",
  ];

  return (
    <section className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">New mission</h1>
        <p className="mt-1 text-sm text-slate-500">{stepSubtitles[step]}</p>
      </div>

      <StepIndicator current={step} />

      <div className="rounded-md border border-line bg-white p-5 shadow-sm">
        <h2 className="mb-4 text-base font-medium text-ink">{stepTitles[step]}</h2>

        {step === 0 && (
          <MissionDetailsStep
            onCreated={(m) => {
              setMission(m);
              setStep(1);
            }}
          />
        )}

        {step === 1 && (
          <RepositorySetupStep
            onNext={(url, branch) => {
              setRepoUrl(url);
              setDefaultBranch(branch);
              setStep(2);
            }}
          />
        )}

        {step === 2 && mission && (
          <CloneStatusStep
            missionId={mission.id}
            repoUrl={repoUrl}
            defaultBranch={defaultBranch}
            onSuccess={(res) => {
              setCloneResult(res);
              setStep(3);
            }}
          />
        )}

        {step === 3 && mission && cloneResult && (
          <NextStepsStep mission={mission} cloneResult={cloneResult} />
        )}
      </div>
    </section>
  );
}
