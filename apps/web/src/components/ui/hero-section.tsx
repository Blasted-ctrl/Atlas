"use client";

import { motion, type Variants } from "framer-motion";
import { ArrowRight, BarChart3, DollarSign, Sparkles, Zap } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/cn";

const container: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.13, delayChildren: 0.05 },
  },
};

const item: Variants = {
  hidden: { opacity: 0, y: 22 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

const heroRecs = [
  {
    icon: BarChart3,
    iconBg: "bg-brand-900/70",
    iconColor: "text-brand-400",
    title: "Rightsize over-provisioned EC2 fleet",
    detail: "14 instances at 8% avg CPU, migrate to t3.medium",
    savings: "$9,200",
  },
  {
    icon: DollarSign,
    iconBg: "bg-emerald-900/60",
    iconColor: "text-emerald-400",
    title: "Convert on-demand to Reserved Instances",
    detail: "3-year RIs on core RDS and compute workloads",
    savings: "$12,800",
  },
  {
    icon: Zap,
    iconBg: "bg-amber-900/60",
    iconColor: "text-amber-400",
    title: "Terminate 7 idle resources",
    detail: "Unattached EBS volumes and stopped instances",
    savings: "$6,400",
  },
];

const stats = [
  { label: "Monthly spend", value: "$142k" },
  { label: "Savings found", value: "$28k" },
  { label: "Resources", value: "340" },
];

export function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-slate-950 px-4 py-20 sm:px-6 sm:py-28">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <div className="absolute left-1/4 top-0 h-[500px] w-[500px] -translate-x-1/2 rounded-full bg-brand-600/15 blur-[100px]" />
        <div className="absolute right-0 top-20 h-[400px] w-[400px] translate-x-1/3 rounded-full bg-violet-600/10 blur-[100px]" />
      </div>

      <motion.div
        variants={container}
        initial="hidden"
        animate="visible"
        className="relative mx-auto max-w-6xl"
      >
        <div className="grid gap-16 lg:grid-cols-2 lg:items-center">
          {/* ── Left copy ───────────────────────────────────────────────── */}
          <div>
            <motion.div variants={item} className="mb-6">
              <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium text-slate-300">
                <Sparkles className="h-3.5 w-3.5 text-brand-400" />
                AI-powered cloud cost intelligence
              </span>
            </motion.div>

            <motion.h1
              variants={item}
              className="text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-6xl"
            >
              Stop overpaying
              <br />
              <span className="bg-gradient-to-r from-brand-400 via-violet-400 to-brand-300 bg-clip-text text-transparent">
                for cloud infrastructure.
              </span>
            </motion.h1>

            <motion.p
              variants={item}
              className="mt-5 max-w-lg text-lg leading-relaxed text-slate-400"
            >
              Atlas maps your AWS, GCP, and Azure spend to individual services and resources, then tells you exactly what to optimize and how much you will save.
            </motion.p>

            <motion.div variants={item} className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link
                href="/onboarding"
                className={cn(
                  "inline-flex items-center justify-center gap-2 rounded-full px-7 py-3 text-sm font-semibold transition-all duration-150",
                  "bg-brand-600 text-white shadow-lg shadow-brand-600/25 hover:bg-brand-500 hover:-translate-y-px",
                )}
              >
                Get started free
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/dashboard"
                className={cn(
                  "inline-flex items-center justify-center gap-2 rounded-full px-7 py-3 text-sm font-semibold transition-all duration-150",
                  "border border-white/20 bg-white/5 text-white backdrop-blur-sm hover:bg-white/10 hover:border-white/30",
                )}
              >
                View demo dashboard
              </Link>
            </motion.div>

            <motion.div
              variants={item}
              className="mt-10 flex items-center gap-8 text-sm text-slate-500"
            >
              {[
                { value: "22%", label: "avg savings identified" },
                { value: "3", label: "cloud providers" },
                { value: "< 2 min", label: "to first insight" },
              ].map((stat, i) => (
                <div key={stat.label}>
                  {i > 0 && (
                    <span className="mr-8 inline-block h-6 w-px bg-white/10" />
                  )}
                  <div className="text-xl font-bold text-white">{stat.value}</div>
                  <div className="text-xs text-slate-500">{stat.label}</div>
                </div>
              ))}
            </motion.div>
          </div>

          {/* ── Right: product preview card ─────────────────────────────── */}
          <motion.div
            variants={item}
            className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur-sm"
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-brand-400" />
                <span className="text-sm font-semibold text-white">
                  Atlas AI recommendations
                </span>
              </div>
              <span className="rounded-full bg-emerald-400/15 px-2.5 py-1 text-xs font-semibold text-emerald-300">
                $28,400/mo identified
              </span>
            </div>

            <div className="space-y-2.5">
              {heroRecs.map((rec) => (
                <motion.div
                  key={rec.title}
                  variants={item}
                  className="flex items-start gap-3 rounded-xl border border-white/[0.07] bg-slate-900/70 p-3.5"
                >
                  <div
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${rec.iconBg}`}
                  >
                    <rec.icon className={`h-4 w-4 ${rec.iconColor}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-white">{rec.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-400">
                      {rec.detail}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-bold text-emerald-400">{rec.savings}</p>
                    <p className="text-[10px] text-slate-500">/month</p>
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/10 pt-4">
              {stats.map((stat) => (
                <div key={stat.label} className="text-center">
                  <p className="text-lg font-bold text-white">{stat.value}</p>
                  <p className="text-[10px] uppercase tracking-wide text-slate-500">
                    {stat.label}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </motion.div>
    </section>
  );
}
