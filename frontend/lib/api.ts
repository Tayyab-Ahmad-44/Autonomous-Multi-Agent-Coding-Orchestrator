export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Mission = {
  id: string;
  title: string;
  goal: string;
  status: string;
  current_milestone_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Milestone = {
  id: string;
  mission_id: string;
  name: string;
  description: string;
  order_index: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type FeatureTask = {
  id: string;
  mission_id: string;
  milestone_id: string | null;
  title: string;
  description: string;
  task_type: string;
  status: string;
  assigned_agent_type: string | null;
  depends_on: string[] | null;
  created_at: string;
  updated_at: string;
};

export type ValidationContract = {
  id: string;
  mission_id: string;
  content: string;
  assertions: Record<string, unknown>[];
  required_tests: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
};

export type ValidationReport = {
  id: string;
  mission_id: string;
  milestone_id: string | null;
  validator_type: string;
  passed: boolean;
  summary: string;
  issues: Record<string, unknown>[];
  raw_output: Record<string, unknown> | null;
  created_at: string;
};

export type MissionEvent = {
  id: string;
  mission_id: string;
  event_type: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type MissionDetail = Mission & {
  milestones: Milestone[];
  feature_tasks: FeatureTask[];
  validation_contract: ValidationContract | null;
  validation_reports: ValidationReport[];
  events: MissionEvent[];
};

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listMissions() {
  return apiFetch<Mission[]>("/missions");
}

export function createMission(payload: { title: string; goal: string }) {
  return apiFetch<Mission>("/missions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getMission(id: string) {
  return apiFetch<MissionDetail>(`/missions/${id}`);
}

export function postMissionAction<T>(id: string, action: string) {
  return apiFetch<T>(`/missions/${id}/${action}`, {
    method: "POST",
  });
}
