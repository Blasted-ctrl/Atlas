import {
  BarChart3,
  Cloud,
  Server,
  Sparkles,
  TrendingDown,
  Zap,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { HeroSection } from "@/components/ui/hero-section";
import { getHealthStatus } from "@/lib/api/health";

export const metadata: Metadata = {
  title: "Atlas — Cloud Cost Intelligence",
};

export const revalidate = 60;

export default async function HomePage() {
  const health = await getHealthStatus().catch(() => null);

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      {/* ── Nav ─────────────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-white/[0.07] bg-slate-950/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-600">
              <TrendingDown className="h-4 w-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-base font-bold tracking-tight text-white">Atlas</span>
          </Link>

          <div className="hidden items-center gap-3 sm:flex">
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-slate-400 transition-colors hover:text-white"
            >
              API docs
            </a>
            <Link
              href="/dashboard"
              className="rounded-full border border-white/15 px-4 py-2 text-sm font-medium text-slate-300 transition-all hover:border-white/25 hover:text-white"
            >
              Dashboard
            </Link>
            <Link
              href="/onboarding"
              className="rounded-full bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-brand-500"
            >
              Get started
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Animated hero ────────────────────────────────────────────────── */}
      <HeroSection />

      {/* ── Features ────────────────────────────────────────────────────── */}
      <section className="border-t border-white/[0.07] px-4 py-20 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-brand-400">
              Platform capabilities
            </p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Everything you need to own your cloud costs
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-slate-400">
              From raw spend visibility to AI-powered optimization, Atlas covers the full workflow in one place.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group rounded-2xl border border-white/[0.07] bg-white/[0.03] p-6 transition-colors hover:border-white/15 hover:bg-white/[0.06]"
              >
                <div
                  className={`mb-4 flex h-10 w-10 items-center justify-center rounded-xl ${feature.iconBg}`}
                >
                  <feature.icon className={`h-5 w-5 ${feature.iconColor}`} />
                </div>
                <h3 className="font-semibold text-white">{feature.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-400">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ────────────────────────────────────────────────── */}
      <section className="border-t border-white/[0.07] px-4 py-20 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="mb-12 text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-brand-400">
              How it works
            </p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white">
              From setup to savings in minutes
            </h2>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {steps.map((step, i) => (
              <div
                key={step.title}
                className="rounded-2xl border border-white/[0.07] bg-white/[0.03] p-6"
              >
                <div className="mb-4 flex items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
                    {i + 1}
                  </span>
                </div>
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-900/60">
                  <step.icon className="h-5 w-5 text-brand-400" />
                </div>
                <h3 className="font-semibold text-white">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-400">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ─────────────────────────────────────────────────────────── */}
      <section className="border-t border-white/[0.07] px-4 py-20 text-center sm:px-6">
        <div className="mx-auto max-w-2xl">
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Ready to cut your cloud bill?
          </h2>
          <p className="mx-auto mt-4 max-w-md text-slate-400">
            Setup takes two minutes. Atlas will show you exactly where you are overspending and what to do about it.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/onboarding"
              className="rounded-full bg-brand-600 px-8 py-3 text-sm font-semibold text-white transition-all hover:bg-brand-500"
            >
              Get started free
            </Link>
            <Link
              href="/dashboard"
              className="rounded-full border border-white/15 px-8 py-3 text-sm font-medium text-slate-300 transition-all hover:border-white/25 hover:text-white"
            >
              Explore the dashboard
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="border-t border-white/[0.07] px-4 py-6 sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center justify-between text-xs text-slate-600">
          <span>Atlas Cloud Cost Platform</span>
          <span className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health?.status === "ok" ? "bg-emerald-500" : "bg-slate-600"
              }`}
            />
            API {health ? `${health.status} · v${health.version}` : "not running, start with pnpm dev"}
          </span>
        </div>
      </footer>
    </main>
  );
}

// ── Data ─────────────────────────────────────────────────────────────────────

const features = [
  {
    icon: BarChart3,
    iconBg: "bg-brand-900/60",
    iconColor: "text-brand-400",
    title: "Multi-cloud cost visibility",
    description:
      "Unified spend tracking across AWS, GCP, and Azure with daily breakdowns by service, team, and environment.",
  },
  {
    icon: Sparkles,
    iconBg: "bg-violet-900/60",
    iconColor: "text-violet-400",
    title: "AI-powered recommendations",
    description:
      "Atlas AI analyzes your specific environment and returns prioritized, actionable savings opportunities with confidence scores.",
  },
  {
    icon: Server,
    iconBg: "bg-slate-800",
    iconColor: "text-slate-400",
    title: "Resource inventory",
    description:
      "Track every VM, database, and serverless function with CPU and memory utilization to spot over-provisioning instantly.",
  },
  {
    icon: TrendingDown,
    iconBg: "bg-emerald-900/60",
    iconColor: "text-emerald-400",
    title: "Cost forecasting",
    description:
      "Project your 30-day cost trajectory based on current trends. Catch spend drift before it becomes a budget conversation.",
  },
  {
    icon: Zap,
    iconBg: "bg-amber-900/60",
    iconColor: "text-amber-400",
    title: "Rightsizing engine",
    description:
      "Identify compute instances running at low capacity. Rightsize with confidence using real utilization data, not guesses.",
  },
  {
    icon: Cloud,
    iconBg: "bg-sky-900/60",
    iconColor: "text-sky-400",
    title: "Cloud account management",
    description:
      "Connect and monitor multiple AWS accounts, GCP projects, and Azure subscriptions from a single control plane.",
  },
];

const steps = [
  {
    icon: Cloud,
    title: "Tell Atlas about your environment",
    description:
      "Enter your cloud providers and monthly spend. No API credentials required to get started, just your infrastructure details.",
  },
  {
    icon: BarChart3,
    title: "Atlas maps your cost profile",
    description:
      "See spend broken down by provider, service, and resource type. Identify trends, anomalies, and where budget is being wasted.",
  },
  {
    icon: Sparkles,
    title: "Get targeted recommendations",
    description:
      "Atlas AI generates prioritized savings opportunities specific to your environment, with estimated impact and steps to action.",
  },
];


