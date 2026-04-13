/**
 * Atlas Cloud Cost Optimizer — TypeScript Client
 *
 * Generated from openapi.yaml v1.0.0
 * Runtime: native fetch (Node 18+ / browser)
 * No external dependencies beyond the standard library.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Enumerations
// ─────────────────────────────────────────────────────────────────────────────

export type CloudProvider = "aws" | "gcp" | "azure";

export type ResourceType =
  | "ec2_instance"
  | "rds_instance"
  | "rds_cluster"
  | "elasticache_cluster"
  | "lambda_function"
  | "s3_bucket"
  | "eks_node_group"
  | "elb"
  | "ebs_volume"
  | "cloudfront_distribution"
  | "nat_gateway";

export type ResourceStatus =
  | "running"
  | "stopped"
  | "terminated"
  | "pending"
  | "unknown";

export type MetricName =
  | "cpu_utilization"
  | "memory_utilization"
  | "network_in_bytes"
  | "network_out_bytes"
  | "disk_read_ops"
  | "disk_write_ops"
  | "connections"
  | "request_count"
  | "error_rate";

export type Granularity = "1m" | "5m" | "15m" | "1h" | "6h" | "1d";

export type RecommendationType =
  | "resize_down"
  | "resize_up"
  | "terminate"
  | "schedule"
  | "reserved_instance"
  | "savings_plan"
  | "graviton_migration";

export type RecommendationStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "applied"
  | "dismissed"
  | "expired";

export type RecommendationAction = "accept" | "reject" | "dismiss";

export type ForecastGranularity = "daily" | "weekly" | "monthly";

export type OptimizationJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed";

export type ErrorCode =
  | "invalid_request"
  | "authentication_required"
  | "forbidden"
  | "resource_not_found"
  | "conflict"
  | "rate_limit_exceeded"
  | "internal_error"
  | "service_unavailable";

// ─────────────────────────────────────────────────────────────────────────────
// Core Domain Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ResourceNetwork {
  vpcId: string | null;
  subnetId: string | null;
  securityGroups: string[];
  publicIp: string | null;
  privateIp: string | null;
}

export interface Resource {
  id: string;
  externalId: string;
  name: string | null;
  type: ResourceType;
  provider: CloudProvider;
  accountId: string;
  region: string;
  availabilityZone: string | null;
  status: ResourceStatus;
  instanceType: string | null;
  tags: Record<string, string>;
  monthlyCostUsd: number;
  createdAt: string;
  lastSeenAt: string;
}

export interface ResourceDetail extends Resource {
  specs: Record<string, unknown> | null;
  network: ResourceNetwork | null;
}

export interface MetricDatapoint {
  timestamp: string;
  value: number;
  unit: string;
}

export interface MetricStatistics {
  min: number;
  max: number;
  avg: number;
  p50: number;
  p90: number;
  p99: number;
}

export interface UsageMetric {
  resourceId: string;
  metric: MetricName;
  granularity: Granularity;
  periodStart: string;
  periodEnd: string;
  datapoints: MetricDatapoint[];
  statistics: MetricStatistics | null;
}

export interface ScheduleSuggestion {
  startCron: string;
  stopCron: string;
  timezone: string;
}

export interface RecommendationDetails {
  currentInstanceType: string | null;
  recommendedInstanceType: string | null;
  currentMonthlyCostUsd: number | null;
  projectedMonthlyCostUsd: number | null;
  avgCpuUtilizationPercent: number | null;
  avgMemoryUtilizationPercent: number | null;
  observationPeriodDays: number | null;
  scheduleSuggestion: ScheduleSuggestion | null;
}

export interface Recommendation {
  id: string;
  resourceId: string;
  type: RecommendationType;
  status: RecommendationStatus;
  title: string;
  description: string;
  savingsUsdMonthly: number;
  savingsUsdAnnual: number;
  confidence: number;
  details: RecommendationDetails | null;
  createdAt: string;
  expiresAt: string;
  appliedAt: string | null;
  dismissedAt: string | null;
  rejectionReason: string | null;
}

export interface ForecastScope {
  accountId: string | null;
  region: string | null;
  resourceType: ResourceType | null;
  resourceId: string | null;
}

export interface ForecastDatapoint {
  date: string;
  costUsd: number;
  lowerBoundUsd: number | null;
  upperBoundUsd: number | null;
}

export interface Forecast {
  id: string;
  scope: ForecastScope;
  granularity: ForecastGranularity;
  model: string;
  confidenceLevel: number;
  generatedAt: string;
  periodStart: string;
  periodEnd: string;
  datapoints: ForecastDatapoint[];
  totalCostUsd: number;
  savingsOpportunityUsd: number | null;
}

export interface AsyncJob {
  jobId: string;
  status: OptimizationJobStatus;
  createdAt: string;
  estimatedCompletion: string | null;
  completedAt: string | null;
  errorMessage: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Pagination
// ─────────────────────────────────────────────────────────────────────────────

export interface PageInfo {
  totalCount: number;
  hasNextPage: boolean;
  hasPreviousPage: boolean;
  nextCursor: string | null;
  previousCursor: string | null;
}

export interface PagedResponse<T> {
  data: T[];
  pagination: PageInfo;
}

// ─────────────────────────────────────────────────────────────────────────────
// Rate Limiting
// ─────────────────────────────────────────────────────────────────────────────

export interface RateLimitInfo {
  /** Maximum requests allowed per window. */
  limit: number;
  /** Requests remaining in the current window. */
  remaining: number;
  /** Unix timestamp (seconds) when the window resets. */
  reset: number;
  /** Window size in seconds. */
  window: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Errors
// ─────────────────────────────────────────────────────────────────────────────

export interface FieldError {
  field: string;
  message: string;
}

export interface AtlasErrorBody {
  code: ErrorCode;
  message: string;
  fieldErrors: FieldError[] | null;
  requestId: string;
  documentationUrl: string | null;
}

export class AtlasApiError extends Error {
  readonly statusCode: number;
  readonly code: ErrorCode;
  readonly requestId: string;
  readonly fieldErrors: FieldError[];
  readonly documentationUrl: string | null;
  readonly rateLimit: RateLimitInfo | null;

  constructor(
    statusCode: number,
    body: AtlasErrorBody,
    rateLimit: RateLimitInfo | null = null
  ) {
    super(`[${body.code}] ${body.message} (requestId: ${body.requestId})`);
    this.name = "AtlasApiError";
    this.statusCode = statusCode;
    this.code = body.code;
    this.requestId = body.requestId;
    this.fieldErrors = body.fieldErrors ?? [];
    this.documentationUrl = body.documentationUrl;
    this.rateLimit = rateLimit;
  }

  get isRateLimited(): boolean {
    return this.statusCode === 429;
  }

  get isNotFound(): boolean {
    return this.statusCode === 404;
  }

  get isAuthError(): boolean {
    return this.statusCode === 401 || this.statusCode === 403;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Query Parameter Types
// ─────────────────────────────────────────────────────────────────────────────

export interface PaginationParams {
  cursor?: string;
  limit?: number;
}

export interface TimeRangeParams {
  startTime?: string;
  endTime?: string;
}

export type ResourceSortField =
  | "monthly_cost_desc"
  | "monthly_cost_asc"
  | "created_at_desc"
  | "created_at_asc"
  | "name_asc"
  | "name_desc";

export interface ListResourcesParams extends PaginationParams {
  resourceType?: ResourceType;
  provider?: CloudProvider;
  accountId?: string;
  region?: string;
  status?: ResourceStatus;
  /** Tag filters in "key:value" format — multiple values are ANDed. */
  tag?: string | string[];
  minMonthlyCost?: number;
  maxMonthlyCost?: number;
  sort?: ResourceSortField;
}

export interface ListUsageParams extends PaginationParams, TimeRangeParams {
  resourceType?: ResourceType;
  /** Comma-separated Atlas resource IDs, or an array. */
  resourceId?: string | string[];
  metric?: MetricName;
  granularity?: Granularity;
  accountId?: string;
  region?: string;
}

export interface GetResourceUsageParams extends TimeRangeParams {
  /** Comma-separated metric names, or an array. */
  metric?: MetricName | MetricName[];
  granularity?: Granularity;
}

export type RecommendationSortField =
  | "savings_desc"
  | "savings_asc"
  | "confidence_desc"
  | "confidence_asc"
  | "created_at_desc"
  | "created_at_asc";

export interface ListRecommendationsParams extends PaginationParams {
  resourceType?: ResourceType;
  resourceId?: string;
  type?: RecommendationType;
  status?: RecommendationStatus;
  minSavings?: number;
  minConfidence?: number;
  accountId?: string;
  region?: string;
  sort?: RecommendationSortField;
}

export interface ListForecastsParams extends PaginationParams, TimeRangeParams {
  resourceType?: ResourceType;
  accountId?: string;
  region?: string;
  resourceId?: string;
  granularity?: ForecastGranularity;
}

export interface ActOnRecommendationBody {
  action: RecommendationAction;
  reason?: string;
}

export interface ForecastScope {
  accountId?: string | null;
  region?: string | null;
  resourceType?: ResourceType | null;
  resourceId?: string | null;
}

export interface GenerateForecastBody {
  periodStart: string;
  periodEnd: string;
  granularity: ForecastGranularity;
  scope?: ForecastScope;
}

export interface OptimizationScope {
  accountId?: string | null;
  region?: string | null;
  resourceType?: ResourceType | null;
  resourceIds?: string[] | null;
}

export interface OptimizationOptions {
  observationPeriodDays?: number;
  includeReservedInstances?: boolean;
  includeSavingsPlans?: boolean;
  minConfidenceThreshold?: number;
}

export interface TriggerOptimizationBody {
  scope?: OptimizationScope;
  options?: OptimizationOptions;
}

// ─────────────────────────────────────────────────────────────────────────────
// Client Configuration
// ─────────────────────────────────────────────────────────────────────────────

export interface AtlasClientConfig {
  /** Base URL of the Atlas API (without trailing slash). */
  baseUrl?: string;
  /**
   * Authentication: provide either an API key or a token factory.
   * The token factory is called before each request and supports
   * dynamic JWT rotation.
   */
  apiKey?: string;
  /** Async function that returns the current Bearer token. */
  getToken?: () => Promise<string>;
  /** Default request timeout in milliseconds (default: 30 000). */
  timeoutMs?: number;
  /** Custom fetch implementation (useful for testing). */
  fetch?: typeof fetch;
  /**
   * Optional hook called after every response.
   * Use this to observe rate-limit headers or log requests.
   */
  onRateLimit?: (info: RateLimitInfo) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal Helpers
// ─────────────────────────────────────────────────────────────────────────────

function parseRateLimit(headers: Headers): RateLimitInfo | null {
  const limit = headers.get("x-ratelimit-limit");
  const remaining = headers.get("x-ratelimit-remaining");
  const reset = headers.get("x-ratelimit-reset");
  const window = headers.get("x-ratelimit-window");

  if (!limit || !remaining || !reset) return null;

  return {
    limit: parseInt(limit, 10),
    remaining: parseInt(remaining, 10),
    reset: parseInt(reset, 10),
    window: window ? parseInt(window, 10) : 60,
  };
}

function toQueryString(params: Record<string, unknown>): string {
  const pairs: string[] = [];

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;

    if (Array.isArray(value)) {
      for (const item of value) {
        pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(item))}`);
      }
    } else {
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }

  return pairs.length > 0 ? `?${pairs.join("&")}` : "";
}

// Camel-to-snake conversion for query param keys
function toSnakeCase(str: string): string {
  return str.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

function normalizeParams(params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    out[toSnakeCase(key)] = value;
  }
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// Domain Sub-Clients
// ─────────────────────────────────────────────────────────────────────────────

class BaseClient {
  protected readonly config: Required<
    Pick<AtlasClientConfig, "baseUrl" | "timeoutMs">
  > &
    AtlasClientConfig;

  constructor(config: AtlasClientConfig) {
    this.config = {
      baseUrl: "https://api.atlas.example.com/v1",
      timeoutMs: 30_000,
      ...config,
    };
  }

  protected async request<T>(
    method: string,
    path: string,
    options: {
      query?: Record<string, unknown>;
      body?: unknown;
    } = {}
  ): Promise<T> {
    const f = this.config.fetch ?? fetch;

    const qs = options.query
      ? toQueryString(normalizeParams(options.query))
      : "";
    const url = `${this.config.baseUrl}${path}${qs}`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };

    if (this.config.apiKey) {
      headers["X-API-Key"] = this.config.apiKey;
    } else if (this.config.getToken) {
      const token = await this.config.getToken();
      headers["Authorization"] = `Bearer ${token}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      this.config.timeoutMs
    );

    let response: Response;
    try {
      response = await f(url, {
        method,
        headers,
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    const rateLimit = parseRateLimit(response.headers);
    if (rateLimit && this.config.onRateLimit) {
      this.config.onRateLimit(rateLimit);
    }

    if (!response.ok) {
      let errorBody: AtlasErrorBody;
      try {
        errorBody = await response.json();
      } catch {
        errorBody = {
          code: "internal_error",
          message: `HTTP ${response.status} ${response.statusText}`,
          fieldErrors: null,
          requestId: response.headers.get("x-request-id") ?? "unknown",
          documentationUrl: null,
        };
      }
      throw new AtlasApiError(response.status, errorBody, rateLimit);
    }

    if (response.status === 204) {
      return undefined as unknown as T;
    }

    return response.json() as Promise<T>;
  }

  protected get<T>(
    path: string,
    query?: Record<string, unknown>
  ): Promise<T> {
    return this.request<T>("GET", path, { query });
  }

  protected post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, { body });
  }
}

// ── Resources ────────────────────────────────────────────────────────────────

export class ResourcesClient extends BaseClient {
  /**
   * Paginated list of discovered cloud resources.
   *
   * @example
   * const page = await client.resources.list({ resourceType: "ec2_instance", limit: 50 });
   * for (const r of page.data) console.log(r.id, r.monthlyCostUsd);
   */
  list(params: ListResourcesParams = {}): Promise<PagedResponse<Resource>> {
    return this.get<PagedResponse<Resource>>("/resources", params);
  }

  /**
   * Full resource details including specs and network configuration.
   *
   * @throws {AtlasApiError} with statusCode 404 if the resource does not exist.
   */
  get(resourceId: string): Promise<ResourceDetail> {
    return this.get<ResourceDetail>(`/resources/${encodeURIComponent(resourceId)}`);
  }

  /**
   * Async iterator over all resources matching the filter.
   * Automatically fetches subsequent pages.
   *
   * @example
   * for await (const resource of client.resources.iterate({ status: "running" })) {
   *   console.log(resource.id);
   * }
   */
  async *iterate(
    params: Omit<ListResourcesParams, "cursor"> = {}
  ): AsyncGenerator<Resource> {
    let cursor: string | null | undefined = undefined;

    do {
      const page: PagedResponse<Resource> = await this.list({
        ...params,
        cursor: cursor ?? undefined,
        limit: params.limit ?? 100,
      });

      for (const resource of page.data) {
        yield resource;
      }

      cursor = page.pagination.nextCursor;
    } while (cursor);
  }
}

// ── Usage ─────────────────────────────────────────────────────────────────────

export class UsageClient extends BaseClient {
  /**
   * Paginated usage metrics across multiple resources.
   */
  list(params: ListUsageParams = {}): Promise<PagedResponse<UsageMetric>> {
    const normalized = {
      ...params,
      resourceId: Array.isArray(params.resourceId)
        ? params.resourceId.join(",")
        : params.resourceId,
    };
    return this.get<PagedResponse<UsageMetric>>("/usage", normalized);
  }

  /**
   * All usage metrics for a specific resource.
   * Returns one time-series per metric.
   */
  getForResource(
    resourceId: string,
    params: GetResourceUsageParams = {}
  ): Promise<UsageMetric[]> {
    const normalized = {
      ...params,
      metric: Array.isArray(params.metric)
        ? params.metric.join(",")
        : params.metric,
    };
    return this.get<UsageMetric[]>(
      `/usage/${encodeURIComponent(resourceId)}`,
      normalized
    );
  }
}

// ── Recommendations ───────────────────────────────────────────────────────────

export class RecommendationsClient extends BaseClient {
  /**
   * Paginated list of cost optimization recommendations.
   * Sorted by monthly savings (descending) by default.
   */
  list(
    params: ListRecommendationsParams = {}
  ): Promise<PagedResponse<Recommendation>> {
    return this.get<PagedResponse<Recommendation>>("/recommendations", params);
  }

  /**
   * Fetch a single recommendation by ID.
   */
  get(recommendationId: string): Promise<Recommendation> {
    return this.get<Recommendation>(
      `/recommendations/${encodeURIComponent(recommendationId)}`
    );
  }

  /**
   * Accept a recommendation (queues automated application).
   */
  accept(recommendationId: string): Promise<Recommendation> {
    return this.act(recommendationId, { action: "accept" });
  }

  /**
   * Reject a recommendation with an optional reason.
   */
  reject(recommendationId: string, reason?: string): Promise<Recommendation> {
    return this.act(recommendationId, { action: "reject", reason });
  }

  /**
   * Dismiss a recommendation (suppresses future re-generation).
   */
  dismiss(recommendationId: string, reason?: string): Promise<Recommendation> {
    return this.act(recommendationId, { action: "dismiss", reason });
  }

  /**
   * Low-level action method. Prefer `accept`, `reject`, or `dismiss`.
   */
  act(
    recommendationId: string,
    body: ActOnRecommendationBody
  ): Promise<Recommendation> {
    return this.post<Recommendation>(
      `/recommendations/${encodeURIComponent(recommendationId)}/actions`,
      body
    );
  }

  /**
   * Async iterator over all recommendations matching the filter.
   */
  async *iterate(
    params: Omit<ListRecommendationsParams, "cursor"> = {}
  ): AsyncGenerator<Recommendation> {
    let cursor: string | null | undefined = undefined;

    do {
      const page: PagedResponse<Recommendation> = await this.list({
        ...params,
        cursor: cursor ?? undefined,
        limit: params.limit ?? 100,
      });

      for (const rec of page.data) {
        yield rec;
      }

      cursor = page.pagination.nextCursor;
    } while (cursor);
  }
}

// ── Forecasts ─────────────────────────────────────────────────────────────────

export class ForecastsClient extends BaseClient {
  /**
   * Paginated list of cost forecasts.
   */
  list(params: ListForecastsParams = {}): Promise<PagedResponse<Forecast>> {
    return this.get<PagedResponse<Forecast>>("/forecasts", params);
  }

  /**
   * Fetch a single forecast by ID.
   */
  get(forecastId: string): Promise<Forecast> {
    return this.get<Forecast>(`/forecasts/${encodeURIComponent(forecastId)}`);
  }

  /**
   * Request asynchronous generation of a new forecast.
   * Poll `optimize.getJob(job.jobId)` or use `waitForJob` to wait for completion.
   */
  generate(body: GenerateForecastBody): Promise<AsyncJob> {
    return this.post<AsyncJob>("/forecasts/generate", body);
  }
}

// ── Optimization ──────────────────────────────────────────────────────────────

export class OptimizationClient extends BaseClient {
  /**
   * Trigger an asynchronous optimization analysis run.
   * Returns a job handle — recommendations appear in `/recommendations` on completion.
   */
  trigger(body: TriggerOptimizationBody = {}): Promise<AsyncJob> {
    return this.post<AsyncJob>("/optimize", body);
  }

  /**
   * Poll an optimization job for its current status.
   */
  getJob(jobId: string): Promise<AsyncJob> {
    return this.get<AsyncJob>(`/optimize/${encodeURIComponent(jobId)}`);
  }

  /**
   * Poll until the job reaches a terminal state (completed / failed).
   *
   * @param jobId - Job ID returned by `trigger` or `forecasts.generate`.
   * @param options.pollIntervalMs - How often to poll (default: 5 000 ms).
   * @param options.timeoutMs - Maximum wait time (default: 10 minutes).
   * @throws {Error} if the timeout is exceeded.
   * @throws {AtlasApiError} if the API returns an error.
   * @returns The terminal job state.
   *
   * @example
   * const job = await client.optimize.trigger({ scope: { region: "us-east-1" } });
   * const done = await client.optimize.waitForJob(job.jobId);
   * console.log(done.status); // "completed"
   */
  async waitForJob(
    jobId: string,
    options: { pollIntervalMs?: number; timeoutMs?: number } = {}
  ): Promise<AsyncJob> {
    const { pollIntervalMs = 5_000, timeoutMs = 10 * 60 * 1_000 } = options;
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      const job = await this.getJob(jobId);

      if (job.status === "completed" || job.status === "failed") {
        return job;
      }

      const remaining = deadline - Date.now();
      if (remaining <= 0) break;

      await new Promise<void>((resolve) =>
        setTimeout(resolve, Math.min(pollIntervalMs, remaining))
      );
    }

    throw new Error(
      `Timed out waiting for optimization job ${jobId} after ${timeoutMs}ms`
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Root Client
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Atlas Cloud Cost Optimizer API client.
 *
 * @example — API key authentication
 * ```ts
 * import { AtlasClient } from "./atlas-client";
 *
 * const atlas = new AtlasClient({ apiKey: process.env.ATLAS_API_KEY! });
 *
 * // List expensive running EC2 instances
 * const page = await atlas.resources.list({
 *   resourceType: "ec2_instance",
 *   status: "running",
 *   sort: "monthly_cost_desc",
 *   limit: 20,
 * });
 *
 * // Accept all high-confidence resize recommendations
 * for await (const rec of atlas.recommendations.iterate({
 *   type: "resize_down",
 *   minConfidence: 0.9,
 *   status: "pending",
 * })) {
 *   await atlas.recommendations.accept(rec.id);
 * }
 *
 * // Trigger a full optimization run and wait for completion
 * const job = await atlas.optimize.trigger();
 * const done = await atlas.optimize.waitForJob(job.jobId);
 * console.log("Optimization complete:", done.status);
 * ```
 *
 * @example — JWT / token rotation
 * ```ts
 * const atlas = new AtlasClient({
 *   getToken: async () => authService.getCurrentToken(),
 *   onRateLimit: (info) => console.warn("Rate limit:", info),
 * });
 * ```
 */
export class AtlasClient {
  readonly resources: ResourcesClient;
  readonly usage: UsageClient;
  readonly recommendations: RecommendationsClient;
  readonly forecasts: ForecastsClient;
  readonly optimize: OptimizationClient;

  constructor(config: AtlasClientConfig) {
    if (!config.apiKey && !config.getToken) {
      throw new Error(
        "AtlasClient requires either `apiKey` or `getToken` in config."
      );
    }

    this.resources = new ResourcesClient(config);
    this.usage = new UsageClient(config);
    this.recommendations = new RecommendationsClient(config);
    this.forecasts = new ForecastsClient(config);
    this.optimize = new OptimizationClient(config);
  }
}

export default AtlasClient;
