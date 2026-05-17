"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listMissions, Mission } from "../../lib/api";

export default function MissionsPage() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listMissions()
      .then(setMissions)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">Missions</h1>
          <p className="mt-1 text-sm text-slate-600">Newest missions first.</p>
        </div>
        <Link className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white" href="/missions/new">
          New mission
        </Link>
      </div>

      {loading ? <p className="text-sm text-slate-600">Loading missions...</p> : null}
      {error ? <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      <div className="overflow-hidden rounded-md border border-line bg-white">
        <table className="w-full border-collapse text-left text-sm">
          <thead className="bg-panel text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3 font-semibold">Title</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Created</th>
            </tr>
          </thead>
          <tbody>
            {missions.map((mission) => (
              <tr key={mission.id} className="border-t border-line">
                <td className="px-4 py-3">
                  <Link className="font-medium text-accent hover:underline" href={`/missions/${mission.id}`}>
                    {mission.title}
                  </Link>
                  <div className="mt-1 max-w-2xl truncate text-xs text-slate-500">{mission.goal}</div>
                </td>
                <td className="px-4 py-3">
                  <span className="rounded-md bg-panel px-2 py-1 text-xs font-medium">{mission.status}</span>
                </td>
                <td className="px-4 py-3 text-slate-600">{new Date(mission.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {!loading && missions.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-sm text-slate-500" colSpan={3}>
                  No missions yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
