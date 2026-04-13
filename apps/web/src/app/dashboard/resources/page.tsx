"use client";

import { AlertTriangle, ExternalLink, Plus, Server } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

const providerConfig = {
  aws: { bg: "bg-orange-50", text: "text-orange-700", label: "AWS" },
  gcp: { bg: "bg-green-50", text: "text-green-700", label: "GCP" },
  azure: { bg: "bg-blue-50", text: "text-blue-700", label: "Azure" },
} as const;

export default function ResourcesPage() {
  const { profile, loaded } = useCloudProfile();

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
        <h1 className="text-2xl font-bold text-slate-900">Resources</h1>
        <p className="mt-0.5 text-sm text-slate-500">Infrastructure inventory and utilization</p>
        <div className="mt-12 flex flex-col items-center py-10 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
            <Server className="h-7 w-7 text-brand-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900">No resources configured</h2>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
            Set up your cloud profile to see your resource inventory, utilization data, and rightsizing opportunities.
          </p>
          <Link href="/onboarding" className="btn-primary mt-6 gap-2 rounded-xl px-6 py-2.5 text-sm">
            <Plus className="h-4 w-4" />
            Set up my profile
          </Link>
        </div>
      </div>
    );
  }

  const totalResources = profile.resourceCount;
  const resourcesPerProvider =
    totalResources > 0
      ? Math.round(totalResources / profile.providers.length)
      : 0;

  return (
    <div className="space-y-6 p-6">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Resources</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          {totalResources > 0
            ? `~${totalResources.toLocaleString()} resources across ${profile.providers.length} provider${profile.providers.length !== 1 ? "s" : ""}`
            : "No resource count configured"}
        </p>
      </div>

      {/* ── Provider summary cards ───────────────────────────────────────── */}
      <div className={cn("grid gap-4", profile.providers.length === 1 ? "grid-cols-1 max-w-xs" : profile.providers.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
        {profile.providers.map((provider) => {
          const cfg = providerConfig[provider as keyof typeof providerConfig];
          const spend = profile.monthlySpend[provider as keyof typeof profile.monthlySpend] ?? 0;
          return (
            <div key={provider} className="card p-5">
              <span className={cn("badge mb-3", cfg.bg, cfg.text)}>{cfg.label}</span>
              <p className="text-2xl font-bold text-slate-900">
                {totalResources > 0 ? resourcesPerProvider.toLocaleString() : "—"}
              </p>
              <p className="text-xs text-slate-500">estimated resources</p>
              <p className="mt-2 text-sm font-semibold text-slate-700">
                ${spend.toLocaleString()}<span className="text-xs font-normal text-slate-400">/mo</span>
              </p>
            </div>
          );
        })}
      </div>

      {/* ── Top services breakdown ───────────────────────────────────────── */}
      {profile.topServices.length > 0 && (
        <div className="card overflow-hidden">
          <div className="border-b border-slate-100 px-6 py-4">
            <h2 className="text-base font-semibold text-slate-900">Top services by cost</h2>
            <p className="mt-0.5 text-xs text-slate-500">From your profile configuration</p>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Service</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Provider</th>
                <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">Monthly Cost</th>
                <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">% of Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {[...profile.topServices]
                .sort((a, b) => b.monthlyCost - a.monthlyCost)
                .map((svc) => {
                  const totalSpend = profile.topServices.reduce((s, i) => s + i.monthlyCost, 0);
                  const pct = totalSpend > 0 ? ((svc.monthlyCost / totalSpend) * 100).toFixed(1) : "0.0";
                  const cfg = providerConfig[svc.provider as keyof typeof providerConfig];
                  return (
                    <tr key={`${svc.provider}-${svc.name}`} className="hover:bg-slate-50/60">
                      <td className="px-5 py-3.5 font-medium text-slate-900">{svc.name}</td>
                      <td className="px-5 py-3.5">
                        {cfg && (
                          <span className={cn("badge", cfg.bg, cfg.text)}>{cfg.label}</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right font-semibold text-slate-900">
                        ${svc.monthlyCost.toLocaleString()}
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
          </table>
        </div>
      )}

      {/* ── Connect live data callout ────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="flex items-start gap-4 p-6">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50">
            <Server className="h-5 w-5 text-brand-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Individual resource inventory</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-500">
              See every VM, database, and serverless function with CPU and memory utilization, rightsizing flags, and per-resource cost. Requires live cloud credentials.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                { label: "Compute instances", example: "EC2, GCE, Azure VMs" },
                { label: "Managed databases", example: "RDS, Cloud SQL, Cosmos DB" },
                { label: "Serverless functions", example: "Lambda, Cloud Functions" },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                  <p className="text-xs font-semibold text-slate-700">{item.label}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{item.example}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 border-t border-slate-100 bg-slate-50/60 px-6 py-3">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <p className="flex-1 text-xs text-slate-500">
            Live inventory requires AWS IAM, GCP service account, or Azure service principal credentials.
          </p>
          <Link
            href="/dashboard/settings"
            className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:underline"
          >
            Configure credentials <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}
