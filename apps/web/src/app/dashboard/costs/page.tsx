"use client";

import { AlertTriangle, Download, ExternalLink, Filter } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

const ranges = ["Last 7 days", "Last 30 days", "Last 3 months", "Last 6 months"] as const;

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
  const total = payload.reduce((sum, p) => sum + (p.value ?? 0), 0);
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-lg">
      <p className="mb-2 text-xs font-semibold text-slate-500">{label}</p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-sm">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-600">{p.name}</span>
          <span className="ml-auto font-semibold text-slate-900">${p.value?.toLocaleString()}</span>
        </div>
      ))}
      {payload.length > 1 && (
        <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-sm">
          <span className="text-slate-500">Total</span>
          <span className="font-semibold text-slate-900">${total.toLocaleString()}</span>
        </div>
      )}
    </div>
  );
};

export default function CostExplorerPage() {
  const { profile, loaded, totalMonthlySpend } = useCloudProfile();
  const [range, setRange] = useState<string>("Last 30 days");
  const [groupBy, setGroupBy] = useState<string>("service");

  if (!loaded) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  if (!profile.setupComplete) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold text-slate-900">Cost Explorer</h1>
        <p className="mt-0.5 text-sm text-slate-500">Drill into spend by service and provider</p>
        <div className="mt-12 flex flex-col items-center py-10 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
            <AlertTriangle className="h-7 w-7 text-brand-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900">No spend data configured</h2>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
            Complete your cloud profile to see your spend breakdown, trends, and service-level analysis.
          </p>
          <Link href="/onboarding" className="btn-primary mt-6 gap-2 rounded-xl px-6 py-2.5 text-sm">
            Set up my profile
          </Link>
        </div>
      </div>
    );
  }

  // Build 6-month trend from the user's real monthly spend
  const months = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"];
  const factors = [0.72, 0.78, 0.85, 0.9, 0.97, 1];
  const trendData = months.map((month, i) => ({
    month,
    aws: Math.round(profile.monthlySpend.aws * (factors[i] ?? 1)),
    gcp: Math.round(profile.monthlySpend.gcp * (factors[i] ?? 1)),
    azure: Math.round(profile.monthlySpend.azure * (factors[i] ?? 1)),
  }));

  // Build daily spend for current month (30 days, based on monthly total)
  const dailyBase = Math.round(totalMonthlySpend / 30);
  const dailyData = Array.from({ length: 30 }, (_, i) => {
    const day = i + 1;
    const noise = 0.85 + Math.random() * 0.3;
    const actual = day <= 13 ? Math.round(dailyBase * noise) : null;
    const forecast = Math.round(dailyBase * (0.97 + (day / 30) * 0.06));
    return {
      day: `Apr ${day}`,
      spend: actual,
      forecast,
    };
  });

  const dailyAvg = dailyBase;
  const mtdTotal = totalMonthlySpend;

  // Build service breakdown from user's topServices
  const serviceRows =
    profile.topServices.length > 0
      ? profile.topServices.map((svc) => ({
          service: svc.name,
          aws: svc.provider === "aws" ? svc.monthlyCost : 0,
          gcp: svc.provider === "gcp" ? svc.monthlyCost : 0,
          azure: svc.provider === "azure" ? svc.monthlyCost : 0,
        }))
      : profile.providers.map((p) => ({
          service: p.toUpperCase(),
          aws: p === "aws" ? profile.monthlySpend.aws : 0,
          gcp: p === "gcp" ? profile.monthlySpend.gcp : 0,
          azure: p === "azure" ? profile.monthlySpend.azure : 0,
        }));

  const grandTotal = serviceRows.reduce((sum, r) => sum + r.aws + r.gcp + r.azure, 0);

  return (
    <div className="space-y-6 p-2 sm:p-4">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <section className="card overflow-hidden">
        <div className="grid gap-5 px-6 py-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-end">
          <div>
            <span className="section-kicker">Cost explorer</span>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
              Spend breakdown for {profile.companyName}
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
              Trend analysis and service-level breakdown based on the profile you configured. Connect live credentials for real-time billing data.
            </p>
          </div>
          <div className="flex justify-start lg:justify-end">
            <button className="btn-secondary gap-1.5 text-xs">
              <Download className="h-3.5 w-3.5" /> Export CSV
            </button>
          </div>
        </div>
      </section>

      {/* ── Controls ────────────────────────────────────────────────────── */}
      <div className="card flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-white p-1">
          {ranges.map((item) => (
            <button
              key={item}
              onClick={() => setRange(item)}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs font-medium transition-all",
                item === range
                  ? "bg-slate-950 text-white shadow-sm"
                  : "text-slate-600 hover:bg-slate-100",
              )}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">Group by</span>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 outline-none focus:border-brand-400"
          >
            <option value="service">Service</option>
            <option value="provider">Provider</option>
          </select>
        </div>

        <button className="btn-secondary gap-1.5 text-xs">
          <Filter className="h-3.5 w-3.5" /> Filters
        </button>

        <div className="ml-auto flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs text-slate-500">Monthly total</p>
            <p className="text-lg font-semibold text-slate-900">${mtdTotal.toLocaleString()}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-slate-500">Daily avg</p>
            <p className="text-lg font-semibold text-slate-900">${dailyAvg.toLocaleString()}</p>
          </div>
        </div>
      </div>

      {/* ── 6-month provider trend ───────────────────────────────────────── */}
      <div className="card p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">6-month spend trend</h2>
            <p className="text-xs text-slate-500">By provider, Nov 2025 to Apr 2026</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {profile.providers.includes("aws") && (
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-[#4c6ef5]" /> AWS
              </span>
            )}
            {profile.providers.includes("gcp") && (
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-[#22c55e]" /> GCP
              </span>
            )}
            {profile.providers.includes("azure") && (
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm bg-[#f59e0b]" /> Azure
              </span>
            )}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={trendData} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#edf2f7" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<CustomTooltip />} />
            {profile.providers.includes("aws") && (
              <Bar dataKey="aws" name="AWS" stackId="a" fill="#4c6ef5" />
            )}
            {profile.providers.includes("gcp") && (
              <Bar dataKey="gcp" name="GCP" stackId="a" fill="#22c55e" />
            )}
            {profile.providers.includes("azure") && (
              <Bar dataKey="azure" name="Azure" stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* ── Daily spend (current month) ──────────────────────────────────── */}
      <div className="card p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Daily spend</h2>
            <p className="text-xs text-slate-500">April 2026 · actual vs forecast</p>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-brand-600" /> Actual
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-[18px] border-t-2 border-dashed border-brand-400" /> Forecast
            </span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={dailyData} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#edf2f7" />
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} interval={4} />
            <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v}`} />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={dailyAvg} stroke="#e2e8f0" strokeDasharray="4 4" label={{ value: "avg", position: "right", fontSize: 10, fill: "#94a3b8" }} />
            <Line type="monotone" dataKey="spend" name="Actual" stroke="#4c6ef5" strokeWidth={2} dot={false} activeDot={{ r: 4 }} connectNulls={false} />
            <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#748ffc" strokeWidth={2} strokeDasharray="5 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── Service breakdown table ──────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="soft-divider px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">Cost breakdown by service</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50/60">
              <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Service</th>
              {profile.providers.includes("aws") && (
                <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">AWS</th>
              )}
              {profile.providers.includes("gcp") && (
                <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">GCP</th>
              )}
              {profile.providers.includes("azure") && (
                <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">Azure</th>
              )}
              <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">Total</th>
              <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">% of spend</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {serviceRows.map((row) => {
              const rowTotal = row.aws + row.gcp + row.azure;
              const pct = grandTotal > 0 ? ((rowTotal / grandTotal) * 100).toFixed(1) : "0.0";
              return (
                <tr key={row.service} className="hover:bg-slate-50/60">
                  <td className="px-5 py-3.5 font-medium text-slate-900">{row.service}</td>
                  {profile.providers.includes("aws") && (
                    <td className="px-5 py-3.5 text-right text-slate-600">
                      {row.aws > 0 ? `$${row.aws.toLocaleString()}` : "-"}
                    </td>
                  )}
                  {profile.providers.includes("gcp") && (
                    <td className="px-5 py-3.5 text-right text-slate-600">
                      {row.gcp > 0 ? `$${row.gcp.toLocaleString()}` : "-"}
                    </td>
                  )}
                  {profile.providers.includes("azure") && (
                    <td className="px-5 py-3.5 text-right text-slate-600">
                      {row.azure > 0 ? `$${row.azure.toLocaleString()}` : "-"}
                    </td>
                  )}
                  <td className="px-5 py-3.5 text-right font-semibold text-slate-900">
                    ${rowTotal.toLocaleString()}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-10 text-right text-xs font-medium text-slate-500">{pct}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-200 bg-slate-50">
              <td className="px-5 py-3.5 text-sm font-semibold text-slate-900">Total</td>
              {profile.providers.includes("aws") && (
                <td className="px-5 py-3.5 text-right text-sm font-semibold text-slate-900">
                  ${serviceRows.reduce((s, r) => s + r.aws, 0).toLocaleString()}
                </td>
              )}
              {profile.providers.includes("gcp") && (
                <td className="px-5 py-3.5 text-right text-sm font-semibold text-slate-900">
                  ${serviceRows.reduce((s, r) => s + r.gcp, 0).toLocaleString()}
                </td>
              )}
              {profile.providers.includes("azure") && (
                <td className="px-5 py-3.5 text-right text-sm font-semibold text-slate-900">
                  ${serviceRows.reduce((s, r) => s + r.azure, 0).toLocaleString()}
                </td>
              )}
              <td className="px-5 py-3.5 text-right text-sm font-semibold text-brand-700">
                ${grandTotal.toLocaleString()}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* ── Data source note ────────────────────────────────────────────── */}
      <div className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        <div>
          <p className="text-sm font-semibold text-slate-700">Charts built from your profile data</p>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
            Spend figures are based on the monthly totals and services you entered. Connect live AWS, GCP, or Azure credentials to pull actual billing records automatically.
          </p>
          <Link href="/onboarding" className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:underline">
            Update my profile <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}
