// ─── Core Domain Models ──────────────────────────────────────────────────────
// These mirror the Pydantic models in apps/api and are the source of truth
// for TypeScript consumers. When regenerating from OpenAPI, replace this file.

export type CloudProvider = "aws" | "gcp" | "azure";
export type ResourceStatus = "active" | "idle" | "terminated" | "unknown";
export type SavingsCategory =
  | "rightsizing"
  | "reserved_instances"
  | "spot_instances"
  | "unused_resources"
  | "storage_optimization"
  | "network_optimization";

// ─── Organization ────────────────────────────────────────────────────────────

export interface Organization {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  updatedAt: string;
}

// ─── Cloud Account ────────────────────────────────────────────────────────────

export interface CloudAccount {
  id: string;
  organizationId: string;
  provider: CloudProvider;
  accountId: string;
  displayName: string;
  isActive: boolean;
  lastSyncedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

// ─── Cost Record ─────────────────────────────────────────────────────────────

export interface CostRecord {
  id: string;
  cloudAccountId: string;
  service: string;
  resource: string | null;
  region: string | null;
  amount: number;
  currency: string;
  period: string; // YYYY-MM
  tags: Record<string, string>;
  createdAt: string;
}

// ─── Resource ────────────────────────────────────────────────────────────────

export interface Resource {
  id: string;
  cloudAccountId: string;
  provider: CloudProvider;
  resourceId: string;
  resourceType: string;
  region: string;
  status: ResourceStatus;
  monthlyCost: number | null;
  metadata: Record<string, unknown>;
  tags: Record<string, string>;
  lastSeenAt: string;
  createdAt: string;
}

// ─── Savings Recommendation ──────────────────────────────────────────────────

export interface Recommendation {
  id: string;
  cloudAccountId: string;
  resourceId: string | null;
  category: SavingsCategory;
  title: string;
  description: string;
  estimatedMonthlySavings: number;
  currency: string;
  confidence: number; // 0.0 – 1.0
  isApplied: boolean;
  isDismissed: boolean;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

// ─── Cost Summary ────────────────────────────────────────────────────────────

export interface CostSummary {
  period: string;
  totalCost: number;
  currency: string;
  breakdown: Array<{
    service: string;
    amount: number;
    percentage: number;
  }>;
  trend: number; // percentage change vs previous period
}
