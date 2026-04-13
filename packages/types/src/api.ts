// ─── API Request/Response Types ──────────────────────────────────────────────
// Mirrors FastAPI response schemas. Regenerate from /openapi.json when the
// API schema changes: `npx openapi-typescript http://localhost:8000/openapi.json -o src/api.ts`

import type {
  CloudAccount,
  CostRecord,
  CostSummary,
  Organization,
  Recommendation,
  Resource,
} from "./models";

// ─── Generic wrappers ────────────────────────────────────────────────────────

export interface ApiResponse<T> {
  data: T;
  meta?: {
    page?: number;
    perPage?: number;
    total?: number;
    totalPages?: number;
  };
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

// ─── Health ──────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok" | "degraded" | "down";
  version: string;
  timestamp: string;
  checks: {
    database: "ok" | "error";
    redis: "ok" | "error";
    storage: "ok" | "error";
  };
}

// ─── Organizations ───────────────────────────────────────────────────────────

export type GetOrganizationResponse = ApiResponse<Organization>;

// ─── Cloud Accounts ──────────────────────────────────────────────────────────

export interface CreateCloudAccountRequest {
  provider: CloudAccount["provider"];
  accountId: string;
  displayName: string;
  credentials: Record<string, string>;
}

export type ListCloudAccountsResponse = ApiResponse<PaginatedResponse<CloudAccount>>;
export type GetCloudAccountResponse = ApiResponse<CloudAccount>;

// ─── Costs ──────────────────────────────────────────────────────────────────

export interface GetCostSummaryRequest {
  cloudAccountId?: string;
  period?: string;
}

export type GetCostSummaryResponse = ApiResponse<CostSummary>;
export type ListCostRecordsResponse = ApiResponse<PaginatedResponse<CostRecord>>;

// ─── Resources ───────────────────────────────────────────────────────────────

export type ListResourcesResponse = ApiResponse<PaginatedResponse<Resource>>;
export type GetResourceResponse = ApiResponse<Resource>;

// ─── Recommendations ─────────────────────────────────────────────────────────

export type ListRecommendationsResponse = ApiResponse<PaginatedResponse<Recommendation>>;

export interface ApplyRecommendationResponse {
  success: boolean;
  message: string;
  jobId: string | null;
}
