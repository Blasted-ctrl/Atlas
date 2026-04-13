"use client";

import {
  ArrowRight,
  BarChart3,
  Cloud,
  DollarSign,
  Lightbulb,
  Plus,
  Server,
  Settings,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

interface TooltipPayload {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}

const CustomTooltip = ({ active, payload, label }: CustomTooltipProps) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-lg">
      <p className="mb-2 text-xs font-semibold text-slate-500">{label}</p>
      {payload.map((point) => (
        <div key={point.name} className="flex items-center gap-2 text-sm">
          <span className="h-2 w-2 rounded-full" style={{ background: point.color }} />
          <span className="font-medium text-slate-700">{point.name}</span>
          <span className="ml-auto font-semibold text-slate-900">
            ${point.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
};

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50">
        <Cloud className="h-8 w-8 text-brand-400" />
      </div>
      <h2 className="text-xl font-semibold text-slate-900">No cloud data yet</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
        Complete the setup wizard so Atlas can analyze your infrastructure and generate
        AI-powered recommendations tailored to your environment.
      </p>
      <Link href="/onboarding" className="btn-primary mt-6 gap-2 rounded-xl px-6 py-2.5 text-sm">
        <Plus className="h-4 w-4" />
        Set up my cloud profile
      </Link>
      <Link
        href="/dashboard/recommendations"
        className="mt-3 text-xs text-slate-400 underline underline-offset-2 hover:text-slate-600"
      >
        Or explore with demo data &rarr;
      </Link>
    </div>
  );
}

export default function DashboardPage() {
  const { profile, loaded, totalMonthlySpend, estimatedSavings, projectedMonthly } =
    useCloudProfile();

  if (!loaded) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  if (!profile.setupComplete) {
    return (
      <div className="p-2 sm:p-4">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Overview</h1>
          <p className="mt-1 text-sm text-slate-500">Cloud cost snapshot</p>
        </div>
        <EmptyState />
      </div>
    );
  }

  const spendByProvider = [
    { provider: "AWS", value: profile.monthlySpend.aws, color: "#4c6ef5" },
    { provider: "GCP", value: profile.monthlySpend.gcp, color: "#22c55e" },
    { provider: "Azure", value: profile.monthlySpend.azure, color: "#f59e0b" },
  ].filter((provider) => provider.value > 0);

  const trendData = Array.from({ length: 6 }, (_, index) => {
    const label = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"][index];
    const factor = [0.72, 0.78, 0.85, 0.9, 0.97, 1][index] ?? 1;
    return {
      month: label,
      aws: Math.round(profile.monthlySpend.aws * factor),
      gcp: Math.round(profile.monthlySpend.gcp * factor),
      azure: Math.round(profile.monthlySpend.azure * factor),
    };
  });

  const topServices = [...profile.topServices]
    .sort((left, right) => right.monthlyCost - left.monthlyCost)
    .slice(0, 5);

  const kpis = [
    {
      label: "Total Spend (MTD)",
      value: `$${totalMonthlySpend.toLocaleString()}`,
      sub: `Across ${profile.providers.length} provider${profile.providers.length !== 1 ? "s" : ""}`,
      icon: DollarSign,
      color: "text-brand-600",
      bg: "bg-brand-50",
      delta: null as number | null,
    },
    {
      label: "Projected Monthly",
      value: `$${projectedMonthly.toLocaleString()}`,
      sub: "Without optimization",
      icon: TrendingUp,
      color: "text-warning-700",
      bg: "bg-warning-50",
      delta: 5,
    },
    {
      label: "Estimated Savings",
      value: `$${estimatedSavings.toLocaleString()}`,
      sub: "~22% of current spend",
      icon: TrendingDown,
      color: "text-success-700",
      bg: "bg-success-50",
      delta: null,
      highlight: true,
    },
    {
      label: "Resources Tracked",
      value: profile.resourceCount > 0 ? profile.resourceCount.toLocaleString() : "-",
      sub: profile.resourceCount > 0 ? "Across all providers" : "Add in settings",
      icon: Server,
      color: "text-slate-600",
      bg: "bg-slate-100",
      delta: null,
    },
  ];

  return (
    <div className="space-y-6 p-2 sm:p-4">
      <section className="card overflow-hidden">
        <div className="grid gap-6 px-6 py-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-end">
          <div className="animate-fade-up">
            <span className="section-kicker">Executive overview</span>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
              {profile.companyName} cloud operating picture
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
              Atlas gives you a single review surface for spend, optimization
              opportunity, and resource pressure so the next action is easier to
              defend.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 animate-fade-up [animation-delay:100ms]">
            <div className="rounded-[1.6rem] border border-white/80 bg-white/88 p-4 shadow-sm">
              <div className="text-xs uppercase tracking-[0.16em] text-slate-500">
                Active providers
              </div>
              <div className="mt-3 text-2xl font-semibold text-slate-950">
                {profile.providers.map((provider) => provider.toUpperCase()).join(" / ")}
              </div>
              <div className="mt-1 text-sm text-slate-500">
                {new Date().toLocaleDateString("en-US", { month: "long", year: "numeric" })}
              </div>
            </div>
            <div className="rounded-[1.6rem] border border-slate-800/70 bg-slate-950 p-4 text-white shadow-lg shadow-slate-900/10">
              <div className="text-xs uppercase tracking-[0.16em] text-slate-400">
                Expected savings
              </div>
              <div className="mt-3 text-3xl font-semibold tracking-tight">
                ${estimatedSavings.toLocaleString()}
              </div>
              <div className="mt-1 text-sm text-slate-300">About 22% of current monthly spend.</div>
            </div>
          </div>
        </div>
      </section>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-950">Dashboard highlights</h2>
          <p className="mt-1 text-sm text-slate-500">
            Spend, trends, optimization headroom, and the actions worth reviewing first.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/onboarding" className="btn-secondary gap-1.5 text-xs">
            <Settings className="h-3.5 w-3.5" /> Edit profile
          </Link>
          <Link href="/dashboard/recommendations" className="btn-primary gap-1.5 text-xs">
            <Zap className="h-3.5 w-3.5" /> Get AI recommendations
          </Link>
        </div>
      </div>

      {profile.goals.length > 0 && (
        <div className="card flex items-start gap-3 p-4">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
          <div>
            <p className="text-sm font-semibold text-brand-800">Your optimization goals</p>
            <p className="mt-0.5 text-xs text-brand-600">{profile.goals.join(" / ")}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi, index) => (
          <div
            key={kpi.label}
            className={cn("metric-card animate-fade-up", kpi.highlight && "ring-1 ring-success-500/20")}
            style={{ animationDelay: `${index * 70}ms` }}
          >
            <div className="flex items-start justify-between">
              <p className="text-sm font-medium text-slate-500">{kpi.label}</p>
              <div className={cn("flex h-9 w-9 items-center justify-center rounded-xl", kpi.bg)}>
                <kpi.icon className={cn("h-4 w-4", kpi.color)} />
              </div>
            </div>
            <p className="mt-4 text-3xl font-semibold tracking-tight text-slate-900">{kpi.value}</p>
            <p className="mt-1 text-xs text-slate-500">{kpi.sub}</p>
            {kpi.delta !== null && kpi.delta > 0 && (
              <p className="mt-0.5 text-xs font-semibold text-warning-700">+{kpi.delta}% without action</p>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="card col-span-2 p-6">
          <div className="mb-5 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Projected spend trend</h2>
              <p className="text-xs text-slate-500">Last 6 months, estimated from your current inputs</p>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              {spendByProvider.map((provider) => (
                <span key={provider.provider} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: provider.color }} />
                  {provider.provider}
                </span>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={trendData} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
              <defs>
                {spendByProvider.map((provider) => (
                  <linearGradient key={provider.provider} id={`grad-${provider.provider}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={provider.color} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={provider.color} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#edf2f7" />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} tickFormatter={(value: number) => `$${(value / 1000).toFixed(0)}k`} />
              <Tooltip content={<CustomTooltip />} />
              {profile.monthlySpend.aws > 0 && (
                <Area type="monotone" dataKey="aws" name="AWS" stroke="#4c6ef5" strokeWidth={2} fill="url(#grad-AWS)" dot={false} />
              )}
              {profile.monthlySpend.gcp > 0 && (
                <Area type="monotone" dataKey="gcp" name="GCP" stroke="#22c55e" strokeWidth={2} fill="url(#grad-GCP)" dot={false} />
              )}
              {profile.monthlySpend.azure > 0 && (
                <Area type="monotone" dataKey="azure" name="Azure" stroke="#f59e0b" strokeWidth={2} fill="url(#grad-Azure)" dot={false} />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-6">
          <div className="mb-4">
            <h2 className="text-base font-semibold text-slate-900">Spend by provider</h2>
            <p className="text-xs text-slate-500">Current monthly mix</p>
          </div>
          {spendByProvider.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie
                    data={spendByProvider}
                    cx="50%"
                    cy="50%"
                    innerRadius={42}
                    outerRadius={70}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {spendByProvider.map((entry) => (
                      <Cell key={entry.provider} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: number) => [`$${value.toLocaleString()}/mo`, ""]}
                    contentStyle={{ borderRadius: "12px", border: "1px solid #e2e8f0", fontSize: "12px" }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-4 space-y-2">
                {spendByProvider.map((provider) => (
                  <div key={provider.provider} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: provider.color }} />
                      <span className="font-medium text-slate-700">{provider.provider}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-semibold text-slate-900">${provider.value.toLocaleString()}</span>
                      <span className="ml-1 text-xs text-slate-400">
                        ({((provider.value / totalMonthlySpend) * 100).toFixed(0)}%)
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-slate-400">
              No spend data entered
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Top cost drivers</h2>
            <Link href="/dashboard/costs" className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700">
              Explore <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          {topServices.length > 0 ? (
            <div className="space-y-3">
              {topServices.map((service) => {
                const percent = totalMonthlySpend > 0 ? (service.monthlyCost / totalMonthlySpend) * 100 : 0;
                const providerColor =
                  service.provider === "aws"
                    ? "bg-orange-100 text-orange-700"
                    : service.provider === "gcp"
                      ? "bg-green-100 text-green-700"
                      : "bg-blue-100 text-blue-700";

                return (
                  <div key={`${service.name}-${service.provider}`} className="flex items-center gap-3">
                    <span className={cn("shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold", providerColor)}>
                      {service.provider.toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="truncate font-medium text-slate-700">{service.name}</span>
                        <span className="ml-2 shrink-0 font-semibold text-slate-900">
                          {service.monthlyCost > 0 ? `$${service.monthlyCost.toLocaleString()}` : "-"}
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-400" style={{ width: `${Math.min(percent, 100)}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center py-8 text-center text-slate-400">
              <BarChart3 className="mb-2 h-8 w-8" />
              <p className="text-sm font-medium">No services configured</p>
              <Link href="/onboarding" className="mt-2 text-xs text-brand-500 hover:underline">
                Add services in setup &rarr;
              </Link>
            </div>
          )}
        </div>

        <div className="card p-6">
          <h2 className="mb-4 text-base font-semibold text-slate-900">Quick actions</h2>
          <div className="space-y-2">
            {quickActions.map((action) => (
              <Link
                key={action.label}
                href={action.href}
                className="flex items-center gap-3 rounded-[1.2rem] border border-slate-100 p-3.5 transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-200 hover:bg-brand-50"
              >
                <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", action.iconBg)}>
                  <action.icon className={cn("h-4.5 w-4.5", action.iconColor)} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-900">{action.label}</p>
                  <p className="text-xs text-slate-500">{action.description}</p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-slate-300" />
              </Link>
            ))}
          </div>
        </div>
      </div>

      {profile.painPoints && (
        <div className="card p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-50">
              <Lightbulb className="h-4 w-4 text-warning-700" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">Your described challenge</p>
              <p className="mt-1 text-sm italic leading-relaxed text-slate-500">
                "{profile.painPoints}"
              </p>
              <Link href="/dashboard/recommendations" className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700">
                Generate AI recommendations targeting this <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const quickActions = [
  {
    label: "Generate AI insights",
    description: "Let Claude analyze your environment",
    href: "/dashboard/recommendations",
    icon: Lightbulb,
    iconBg: "bg-brand-50",
    iconColor: "text-brand-600",
  },
  {
    label: "Explore cost breakdown",
    description: "Drill into spend by service and date",
    href: "/dashboard/costs",
    icon: BarChart3,
    iconBg: "bg-success-50",
    iconColor: "text-success-700",
  },
  {
    label: "View resource inventory",
    description: "Check utilization and idle resources",
    href: "/dashboard/resources",
    icon: Server,
    iconBg: "bg-warning-50",
    iconColor: "text-warning-700",
  },
  {
    label: "Update cloud profile",
    description: "Edit providers, spend, and goals",
    href: "/onboarding",
    icon: Settings,
    iconBg: "bg-slate-100",
    iconColor: "text-slate-600",
  },
];
