import type { HealthResponse } from "@atlas/types/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getHealthStatus(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`, {
    next: { revalidate: 60 },
    headers: { Accept: "application/json" },
  });

  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }

  return res.json() as Promise<HealthResponse>;
}
