"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { createMission } from "../../../lib/api";

export default function NewMissionPage() {
  const router = useRouter();
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
      router.push(`/missions/${mission.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create mission");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">New mission</h1>
        <p className="mt-1 text-sm text-slate-600">Create the software goal the orchestrator will plan around.</p>
      </div>

      <form className="space-y-4 rounded-md border border-line bg-white p-5" onSubmit={onSubmit}>
        <label className="block">
          <span className="text-sm font-medium">Title</span>
          <input
            className="mt-1 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={255}
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Goal</span>
          <textarea
            className="mt-1 min-h-36 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            required
          />
        </label>
        {error ? <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
        <button
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          disabled={saving}
          type="submit"
        >
          {saving ? "Creating..." : "Create mission"}
        </button>
      </form>
    </section>
  );
}
