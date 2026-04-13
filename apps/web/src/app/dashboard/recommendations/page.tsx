"use client";

import {
  AlertCircle,
  BarChart3,
  CheckCircle,
  ChevronRight,
  Clock,
  DollarSign,
  HardDrive,
  Lightbulb,
  Loader2,
  Plus,
  Server,
  Sparkles,
  Tag,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { ComponentType } from "react";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

interface AIInsight {
  title: string;
  description: string;
  estimatedSavings: number;
  priority: "high" | "medium" | "low";
  category: string;
  confidence: number;
}

const priorityConfig = {
  high: { color: "text-danger-700", bg: "bg-danger-50", border: "border-danger-200", label: "High priority" },
  medium: { color: "text-warning-700", bg: "bg-warning-50", border: "border-warning-200", label: "Medium priority" },
  low: { color: "text-success-700", bg: "bg-success-50", border: "border-success-200", label: "Low priority" },
};

const categoryIcons: Record<string, ComponentType<{ className?: string }>> = {
  anomaly: AlertCircle,
  architecture: Zap,
  commitment: Tag,
  idle: Clock,
  pricing: DollarSign,
  rightsizing: BarChart3,
  scheduling: Clock,
  storage: HardDrive,
};

function NoProfileState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50">
        <Sparkles className="h-8 w-8 text-brand-400" />
      </div>
      <h2 className="text-xl font-semibold text-slate-900">Set up your profile first</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
        Claude needs context about your environment to produce recommendations that are worth taking seriously.
      </p>
      <Link href="/onboarding" className="btn-primary mt-6 gap-2 rounded-xl px-6 py-2.5 text-sm">
        <Plus className="h-4 w-4" />
        Add my cloud data
      </Link>
    </div>
  );
}

export default function RecommendationsPage() {
  const { profile, loaded, totalMonthlySpend } = useCloudProfile();

  const [aiInsights, setAiInsights] = useState<AIInsight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzed, setAnalyzed] = useState(false);

  async function generateAIInsights() {
    setLoading(true);
    setError(null);

    const payload = {
      companyName: profile.companyName,
      providers: profile.providers,
      monthlySpend: profile.monthlySpend,
      totalMonthlySpend,
      topServices: profile.topServices,
      resourceCount: profile.resourceCount,
      painPoints: profile.painPoints,
      goals: profile.goals,
    };

    try {
      const res = await fetch("/api/ai/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userProfile: payload }),
      });

      const data = (await res.json()) as { insights?: AIInsight[]; error?: string };

      if (!res.ok) throw new Error(data.error ?? "Failed to generate insights");
      if (data.insights) {
        setAiInsights(data.insights);
        setAnalyzed(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  if (!loaded) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-2 sm:p-4">
      <section className="card overflow-hidden">
        <div className="grid gap-5 px-6 py-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-end">
          <div>
            <span className="section-kicker">AI recommendations</span>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
              Review optimization ideas with enough context to trust them.
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-7 text-slate-600">
              Atlas AI analyzes your environment and returns concrete recommendations, confidence levels, and estimated savings.
            </p>
          </div>

          {profile.setupComplete && (
            <div className="flex justify-start lg:justify-end">
              <button
                onClick={() => void generateAIInsights()}
                disabled={loading}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full px-5 py-3 text-sm font-semibold transition-all duration-200",
                  loading
                    ? "cursor-not-allowed bg-slate-100 text-slate-400"
                    : "bg-slate-950 text-white hover:-translate-y-0.5 hover:bg-slate-800 hover:shadow-lg",
                )}
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {loading ? "Atlas is analyzing..." : analyzed ? "Re-analyze" : "Generate AI insights"}
              </button>
            </div>
          )}
        </div>
      </section>

      {!profile.setupComplete && <NoProfileState />}

      {profile.setupComplete && !analyzed && !loading && !error && (
        <div className="card p-10 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
            <Sparkles className="h-7 w-7 text-brand-500" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900">Ready to analyze your environment</h2>
          <div className="mx-auto mt-4 max-w-md space-y-1.5 text-left">
            <p className="text-sm font-semibold text-slate-600">Atlas AI will analyze:</p>
            <ul className="space-y-1 text-sm text-slate-500">
              <li className="flex items-center gap-2">
                <CheckCircle className="h-3.5 w-3.5 text-success-500" />
                Your {profile.providers.map((provider) => provider.toUpperCase()).join(", ")} spend (${totalMonthlySpend.toLocaleString()}/mo)
              </li>
              {profile.topServices.length > 0 && (
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-3.5 w-3.5 text-success-500" />
                  {profile.topServices.length} specific services you listed
                </li>
              )}
              {profile.goals.length > 0 && (
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-3.5 w-3.5 text-success-500" />
                  Your goals: {profile.goals.slice(0, 2).join(", ")}
                  {profile.goals.length > 2 ? ` +${profile.goals.length - 2} more` : ""}
                </li>
              )}
              {profile.painPoints && (
                <li className="flex items-start gap-2">
                  <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success-500" />
                  <span className="italic">"{profile.painPoints.slice(0, 80)}{profile.painPoints.length > 80 ? "..." : ""}"</span>
                </li>
              )}
              {profile.resourceCount > 0 && (
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-3.5 w-3.5 text-success-500" />
                  Around {profile.resourceCount} resources in your environment
                </li>
              )}
            </ul>
          </div>
          <button
            onClick={() => void generateAIInsights()}
            className="btn-primary mx-auto mt-6 gap-2 px-6 py-2.5"
          >
            <Sparkles className="h-4 w-4" />
            Run Atlas AI
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-danger-200 bg-danger-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-danger-700">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Analysis failed
          </div>
          <p className="mt-1 text-sm text-danger-600">{error}</p>
          <p className="mt-1 text-xs text-danger-500">
            Make sure ANTHROPIC_API_KEY is set in your environment and the dev server is running.
          </p>
        </div>
      )}

      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="card animate-pulse p-5">
              <div className="flex items-start gap-4">
                <div className="h-5 w-20 rounded-full bg-slate-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-3/4 rounded-lg bg-slate-100" />
                  <div className="h-3 w-full rounded-lg bg-slate-100" />
                  <div className="h-3 w-2/3 rounded-lg bg-slate-100" />
                </div>
                <div className="h-8 w-20 rounded-lg bg-slate-100" />
              </div>
            </div>
          ))}
          <p className="text-center text-xs text-slate-400">
            Atlas AI is analyzing your environment and formulating recommendations...
          </p>
        </div>
      )}

      {!loading && aiInsights.length > 0 && (
        <div className="space-y-4">
          <div className="panel-dark px-5 py-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-brand-300" />
                  <p className="text-sm font-semibold text-brand-100">
                    Atlas has analyzed {profile.companyName}&apos;s environment
                  </p>
                </div>
                <p className="mt-2 text-3xl font-semibold">
                  ${aiInsights.reduce((sum, insight) => sum + insight.estimatedSavings, 0).toLocaleString()}
                  <span className="ml-2 text-base font-medium text-slate-300">/month in identified savings</span>
                </p>
                <p className="mt-1 text-sm text-slate-300">
                  Based on your ${totalMonthlySpend.toLocaleString()}/mo spend across {profile.providers.map((provider) => provider.toUpperCase()).join(", ")}
                </p>
              </div>
              <div className="hidden text-right sm:block">
                <p className="text-3xl font-semibold">
                  {((aiInsights.reduce((sum, insight) => sum + insight.estimatedSavings, 0) / totalMonthlySpend) * 100).toFixed(0)}%
                </p>
                <p className="text-sm text-slate-300">savings rate</p>
              </div>
            </div>
          </div>

          {aiInsights.map((insight, index) => {
            const config = priorityConfig[insight.priority];
            const Icon = categoryIcons[insight.category] ?? Lightbulb;
            return (
              <div
                key={`${insight.title}-${index}`}
                className={cn("card border-l-4 p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-hover", config.border, "animate-fade-up")}
                style={{ animationDelay: `${index * 80}ms` }}
              >
                <div className="flex items-start gap-4">
                  <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl", config.bg)}>
                    <Icon className={cn("h-5 w-5", config.color)} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("badge", config.bg, config.color)}>{config.label}</span>
                      <span className="badge bg-slate-100 text-slate-600 capitalize">{insight.category}</span>
                      <span className="text-xs text-slate-400">{insight.confidence}% confidence</span>
                    </div>
                    <h3 className="mt-2 font-semibold text-slate-900">{insight.title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-slate-600">{insight.description}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-xl font-semibold text-success-700">${insight.estimatedSavings.toLocaleString()}</p>
                    <p className="text-xs text-slate-400">/month</p>
                    <button className="btn-primary mt-2 gap-1 px-2.5 py-1 text-xs">
                      Apply <ChevronRight className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {profile.setupComplete && totalMonthlySpend > 0 && (
        <div className="card p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-900">
            Industry benchmark estimates
            <span className="ml-2 text-xs font-normal text-slate-400">
              (for context only)
            </span>
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {benchmarks(totalMonthlySpend).map((benchmark) => (
              <div key={benchmark.label} className={cn("rounded-2xl border p-4", benchmark.border)}>
                <div className={cn("mb-2 flex h-8 w-8 items-center justify-center rounded-lg", benchmark.iconBg)}>
                  <benchmark.icon className={cn("h-4 w-4", benchmark.iconColor)} />
                </div>
                <p className="text-lg font-semibold text-slate-900">${benchmark.saving.toLocaleString()}</p>
                <p className="text-xs font-medium text-slate-600">{benchmark.label}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">{benchmark.description}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Benchmark estimates are directional. Generate AI insights for recommendations tailored to your setup.
          </p>
        </div>
      )}

      {profile.setupComplete && (profile.topServices.length === 0 || !profile.painPoints) && (
        <div className="card flex items-start gap-3 p-4">
          <Server className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
          <div>
            <p className="text-sm font-semibold text-slate-700">Improve recommendation quality</p>
            <p className="mt-0.5 text-xs text-slate-500">
              Add your top services and describe your pain points in the setup wizard so Atlas can produce more specific advice.
            </p>
            <Link href="/onboarding" className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-brand-600">
              Improve my profile <ChevronRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function benchmarks(monthly: number) {
  return [
    {
      label: "Rightsizing",
      saving: Math.round(monthly * 0.15),
      description: "~15% from overprovisioned VMs",
      icon: BarChart3,
      iconBg: "bg-brand-50",
      iconColor: "text-brand-600",
      border: "border-brand-100",
    },
    {
      label: "Reserved Instances",
      saving: Math.round(monthly * 0.2),
      description: "~20% switching on-demand to RI",
      icon: Tag,
      iconBg: "bg-success-50",
      iconColor: "text-success-700",
      border: "border-success-100",
    },
    {
      label: "Idle Resources",
      saving: Math.round(monthly * 0.08),
      description: "~8% from unused infrastructure",
      icon: Clock,
      iconBg: "bg-warning-50",
      iconColor: "text-warning-700",
      border: "border-warning-100",
    },
    {
      label: "Storage Tiering",
      saving: Math.round(monthly * 0.05),
      description: "~5% moving cold data to cheaper tiers",
      icon: HardDrive,
      iconBg: "bg-slate-100",
      iconColor: "text-slate-600",
      border: "border-slate-200",
    },
  ];
}
