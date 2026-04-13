// Realistic mock data for Atlas Cloud Cost Optimization Platform

export const mockOrg = {
  name: "Acme Corp",
  plan: "Enterprise",
  avatar: "AC",
};

export const mockKPIs = {
  totalSpendMTD: 24812,
  projectedMonthly: 31440,
  potentialSavings: 6340,
  openRecommendations: 14,
  savingsPercent: 20.2,
  spendDelta: 3.2, // % vs last month
  projectedDelta: -1.5,
};

export const mockSpendTrend = [
  { month: "Nov", aws: 18200, gcp: 4100, azure: 2900 },
  { month: "Dec", aws: 19800, gcp: 4300, azure: 3100 },
  { month: "Jan", aws: 21400, gcp: 4800, azure: 3300 },
  { month: "Feb", aws: 20100, gcp: 4600, azure: 3200 },
  { month: "Mar", aws: 22600, gcp: 5200, azure: 3500 },
  { month: "Apr", aws: 16100, gcp: 5400, azure: 3312 },
];

export const mockServiceBreakdown = [
  { name: "EC2", value: 9200, provider: "aws", color: "#4c6ef5" },
  { name: "RDS", value: 4800, provider: "aws", color: "#5c7cfa" },
  { name: "S3", value: 2100, provider: "aws", color: "#748ffc" },
  { name: "GKE", value: 3400, provider: "gcp", color: "#22c55e" },
  { name: "BigQuery", value: 2000, provider: "gcp", color: "#16a34a" },
  { name: "Azure VMs", value: 3312, provider: "azure", color: "#f59e0b" },
];

export const mockAccounts = [
  {
    id: "acc-001",
    name: "Production AWS",
    provider: "aws" as const,
    accountId: "123456789012",
    status: "active" as const,
    region: "us-east-1",
    spendMTD: 16100,
    lastSync: "2 mins ago",
    resources: 847,
  },
  {
    id: "acc-002",
    name: "Dev/Staging AWS",
    provider: "aws" as const,
    accountId: "987654321098",
    status: "active" as const,
    region: "us-west-2",
    spendMTD: 3240,
    lastSync: "5 mins ago",
    resources: 312,
  },
  {
    id: "acc-003",
    name: "GCP Production",
    provider: "gcp" as const,
    accountId: "proj-atlas-prod-4821",
    status: "active" as const,
    region: "us-central1",
    spendMTD: 5400,
    lastSync: "3 mins ago",
    resources: 203,
  },
  {
    id: "acc-004",
    name: "Azure Enterprise",
    provider: "azure" as const,
    accountId: "sub-f7a2-8b31-cc91",
    status: "degraded" as const,
    region: "East US",
    spendMTD: 3312,
    lastSync: "18 mins ago",
    resources: 156,
  },
  {
    id: "acc-005",
    name: "GCP Analytics",
    provider: "gcp" as const,
    accountId: "proj-atlas-analytics",
    status: "inactive" as const,
    region: "europe-west1",
    spendMTD: 0,
    lastSync: "3 days ago",
    resources: 0,
  },
];

export const mockDailySpend = Array.from({ length: 30 }, (_, i) => {
  const day = i + 1;
  const base = 820;
  const variance = Math.sin(i * 0.4) * 120 + Math.random() * 80;
  return {
    day: `Apr ${day}`,
    spend: Math.round(base + variance),
    forecast: day > 12 ? Math.round(base + variance * 0.9 + 20) : null,
  };
});

export const mockCostByService = [
  { service: "EC2 / Compute", aws: 9200, gcp: 3400, azure: 2100 },
  { service: "Database", aws: 4800, gcp: 1200, azure: 890 },
  { service: "Storage", aws: 2100, gcp: 800, azure: 612 },
  { service: "Networking", aws: 1400, gcp: 600, azure: 410 },
  { service: "ML / AI", aws: 800, gcp: 1800, azure: 300 },
  { service: "Containers", aws: 1200, gcp: 900, azure: 0 },
];

export const mockResources = [
  {
    id: "res-001",
    name: "prod-api-server-1",
    type: "EC2 t3.xlarge",
    provider: "aws" as const,
    region: "us-east-1",
    account: "Production AWS",
    status: "running" as const,
    costPerMonth: 145.6,
    cpuAvg: 12,
    memAvg: 34,
    tags: { env: "production", team: "platform" },
  },
  {
    id: "res-002",
    name: "prod-api-server-2",
    type: "EC2 t3.xlarge",
    provider: "aws" as const,
    region: "us-east-1",
    account: "Production AWS",
    status: "running" as const,
    costPerMonth: 145.6,
    cpuAvg: 8,
    memAvg: 28,
    tags: { env: "production", team: "platform" },
  },
  {
    id: "res-003",
    name: "prod-db-primary",
    type: "RDS db.r6g.2xlarge",
    provider: "aws" as const,
    region: "us-east-1",
    account: "Production AWS",
    status: "running" as const,
    costPerMonth: 892.4,
    cpuAvg: 45,
    memAvg: 67,
    tags: { env: "production", team: "data" },
  },
  {
    id: "res-004",
    name: "staging-worker-pool",
    type: "EC2 c5.large",
    provider: "aws" as const,
    region: "us-west-2",
    account: "Dev/Staging AWS",
    status: "idle" as const,
    costPerMonth: 68.2,
    cpuAvg: 2,
    memAvg: 11,
    tags: { env: "staging", team: "backend" },
  },
  {
    id: "res-005",
    name: "analytics-cluster",
    type: "GKE n2-standard-4",
    provider: "gcp" as const,
    region: "us-central1",
    account: "GCP Production",
    status: "running" as const,
    costPerMonth: 312.0,
    cpuAvg: 38,
    memAvg: 52,
    tags: { env: "production", team: "analytics" },
  },
  {
    id: "res-006",
    name: "old-batch-processor",
    type: "EC2 m5.2xlarge",
    provider: "aws" as const,
    region: "us-east-1",
    account: "Production AWS",
    status: "stopped" as const,
    costPerMonth: 0,
    cpuAvg: 0,
    memAvg: 0,
    tags: { env: "production", team: "legacy" },
  },
  {
    id: "res-007",
    name: "dev-test-instance",
    type: "EC2 t3.medium",
    provider: "aws" as const,
    region: "us-west-2",
    account: "Dev/Staging AWS",
    status: "idle" as const,
    costPerMonth: 28.8,
    cpuAvg: 1,
    memAvg: 8,
    tags: { env: "dev", team: "frontend" },
  },
  {
    id: "res-008",
    name: "azure-vm-prod-01",
    type: "Standard_D4s_v3",
    provider: "azure" as const,
    region: "East US",
    account: "Azure Enterprise",
    status: "running" as const,
    costPerMonth: 186.4,
    cpuAvg: 22,
    memAvg: 44,
    tags: { env: "production", team: "infra" },
  },
];

export const mockRecommendations = [
  {
    id: "rec-001",
    title: "Rightsize overprovisioned EC2 instances",
    description:
      "12 EC2 t3.xlarge instances show average CPU utilization below 15%. Downsizing to t3.large would maintain performance with 50% cost reduction.",
    provider: "aws" as const,
    priority: "high" as const,
    estimatedSavings: 1742,
    status: "open" as const,
    category: "rightsizing",
    resources: ["prod-api-server-1", "prod-api-server-2", "+10 more"],
    effort: "low" as const,
    createdAt: "2026-04-10",
  },
  {
    id: "rec-002",
    title: "Purchase Reserved Instances for stable workloads",
    description:
      "RDS and EC2 instances in production have been running continuously for 6+ months. 1-year reserved instances would yield 35–40% savings vs on-demand.",
    provider: "aws" as const,
    priority: "high" as const,
    estimatedSavings: 2140,
    status: "open" as const,
    category: "commitment",
    resources: ["prod-db-primary", "+8 EC2 instances"],
    effort: "medium" as const,
    createdAt: "2026-04-09",
  },
  {
    id: "rec-003",
    title: "Terminate idle dev/staging instances",
    description:
      "4 instances in dev/staging environment have CPU utilization < 2% for 7+ days. Schedule auto-stop during off-hours (6pm–8am) to reduce waste.",
    provider: "aws" as const,
    priority: "medium" as const,
    estimatedSavings: 486,
    status: "open" as const,
    category: "idle",
    resources: ["staging-worker-pool", "dev-test-instance", "+2 more"],
    effort: "low" as const,
    createdAt: "2026-04-11",
  },
  {
    id: "rec-004",
    title: "Migrate BigQuery to on-demand pricing",
    description:
      "Current flat-rate BigQuery slots are underutilized at 34% average. Switching to on-demand saves costs for bursty analytics workloads.",
    provider: "gcp" as const,
    priority: "medium" as const,
    estimatedSavings: 620,
    status: "open" as const,
    category: "pricing",
    resources: ["BigQuery flat-rate slots (us-central1)"],
    effort: "low" as const,
    createdAt: "2026-04-08",
  },
  {
    id: "rec-005",
    title: "Enable S3 Intelligent-Tiering",
    description:
      "Production S3 buckets store 4.2TB of infrequently-accessed data. Enabling Intelligent-Tiering automatically moves cold data to cheaper storage classes.",
    provider: "aws" as const,
    priority: "low" as const,
    estimatedSavings: 312,
    status: "open" as const,
    category: "storage",
    resources: ["atlas-prod-assets", "atlas-billing-exports"],
    effort: "low" as const,
    createdAt: "2026-04-07",
  },
  {
    id: "rec-006",
    title: "Delete unattached EBS volumes",
    description:
      "23 EBS volumes (1.8TB total) are unattached and have not been accessed in 30+ days. Snapshot and delete to stop incurring storage charges.",
    provider: "aws" as const,
    priority: "low" as const,
    estimatedSavings: 198,
    status: "in_progress" as const,
    category: "storage",
    resources: ["23 unattached volumes"],
    effort: "low" as const,
    createdAt: "2026-04-06",
  },
];

export const mockForecast = {
  currentMonth: 31440,
  nextMonth: 29800,
  twoMonths: 27200,
  savingsTrajectory: [
    { month: "Apr", actual: 24812, forecast: 31440 },
    { month: "May", actual: null, forecast: 29800 },
    { month: "Jun", actual: null, forecast: 27200 },
    { month: "Jul", actual: null, forecast: 25100 },
  ],
};
