"use client";

import { ArrowLeft, ArrowRight, BarChart3, Check, CheckCircle, ChevronRight, Cloud, Database, Globe, HardDrive, LayoutDashboard, Lightbulb, Plus, Server, Target, TrendingDown, Trash2, Zap } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { cn } from "@/lib/cn";
import { DEFAULT_GOALS, useCloudProfile } from "@/lib/use-cloud-profile";
import type { ServiceEntry } from "@/lib/use-cloud-profile";

// ─── Step config ───────────────────────────────────────────────────────────────
const STEPS = [
  { id: 1, label: "Providers", icon: Cloud },
  { id: 2, label: "Spend", icon: BarChart3 },
  { id: 3, label: "Services", icon: Server },
  { id: 4, label: "Goals", icon: Target },
];

const PROVIDER_OPTIONS = [
  {
    id: "aws" as const,
    name: "Amazon Web Services",
    short: "AWS",
    color: "border-orange-300 bg-orange-50",
    activeColor: "border-orange-500 bg-orange-100 ring-2 ring-orange-400",
    textColor: "text-orange-700",
    icon: Cloud,
  },
  {
    id: "gcp" as const,
    name: "Google Cloud Platform",
    short: "GCP",
    color: "border-green-300 bg-green-50",
    activeColor: "border-green-500 bg-green-100 ring-2 ring-green-400",
    textColor: "text-green-700",
    icon: Globe,
  },
  {
    id: "azure" as const,
    name: "Microsoft Azure",
    short: "Azure",
    color: "border-blue-300 bg-blue-50",
    activeColor: "border-blue-500 bg-blue-100 ring-2 ring-blue-400",
    textColor: "text-blue-700",
    icon: Cloud,
  },
];

const SERVICE_SUGGESTIONS: Record<string, { name: string; icon: typeof Server }[]> = {
  aws: [
    { name: "EC2 (Virtual Machines)", icon: Server },
    { name: "RDS (Databases)", icon: Database },
    { name: "S3 (Storage)", icon: HardDrive },
    { name: "Lambda (Serverless)", icon: Zap },
    { name: "EKS (Kubernetes)", icon: LayoutDashboard },
  ],
  gcp: [
    { name: "Compute Engine (VMs)", icon: Server },
    { name: "Cloud SQL (Databases)", icon: Database },
    { name: "Cloud Storage", icon: HardDrive },
    { name: "GKE (Kubernetes)", icon: LayoutDashboard },
    { name: "BigQuery (Analytics)", icon: BarChart3 },
  ],
  azure: [
    { name: "Virtual Machines", icon: Server },
    { name: "Azure SQL", icon: Database },
    { name: "Blob Storage", icon: HardDrive },
    { name: "AKS (Kubernetes)", icon: LayoutDashboard },
    { name: "Azure Functions", icon: Zap },
  ],
};

// ─── Component ─────────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const router = useRouter();
  const { saveProfile } = useCloudProfile();

  const [step, setStep] = useState(1);
  const [companyName, setCompanyName] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<Array<"aws" | "gcp" | "azure">>([]);
  const [spend, setSpend] = useState({ aws: "", gcp: "", azure: "" });
  const [services, setServices] = useState<ServiceEntry[]>([]);
  const [resourceCount, setResourceCount] = useState("");
  const [painPoints, setPainPoints] = useState("");
  const [selectedGoals, setSelectedGoals] = useState<string[]>([]);

  // ─── Helpers ─────────────────────────────────────────────────────────────────

  function toggleProvider(id: "aws" | "gcp" | "azure") {
    setSelectedProviders((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  }

  function addService(name: string, provider: "aws" | "gcp" | "azure") {
    if (services.some((s) => s.name === name && s.provider === provider)) return;
    setServices((prev) => [...prev, { name, provider, monthlyCost: 0 }]);
  }

  function updateServiceCost(index: number, cost: string) {
    setServices((prev) =>
      prev.map((s, i) => (i === index ? { ...s, monthlyCost: parseFloat(cost) || 0 } : s)),
    );
  }

  function removeService(index: number) {
    setServices((prev) => prev.filter((_, i) => i !== index));
  }

  function toggleGoal(goal: string) {
    setSelectedGoals((prev) =>
      prev.includes(goal) ? prev.filter((g) => g !== goal) : [...prev, goal],
    );
  }

  function canAdvance() {
    if (step === 1) return companyName.trim().length > 0 && selectedProviders.length > 0;
    if (step === 2) return selectedProviders.some((p) => parseFloat(spend[p]) > 0);
    if (step === 3) return services.length > 0;
    return true;
  }

  function handleFinish() {
    saveProfile({
      companyName: companyName.trim() || "My Company",
      providers: selectedProviders,
      monthlySpend: {
        aws: parseFloat(spend.aws) || 0,
        gcp: parseFloat(spend.gcp) || 0,
        azure: parseFloat(spend.azure) || 0,
      },
      topServices: services,
      resourceCount: parseInt(resourceCount) || 0,
      painPoints,
      goals: selectedGoals,
      setupComplete: true,
      createdAt: new Date().toISOString(),
    });
    router.push("/dashboard");
  }

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      {/* Top bar */}
      <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600">
            <TrendingDown className="h-4 w-4 text-white" strokeWidth={2.5} />
          </div>
          <span className="font-bold text-slate-900">Atlas</span>
        </div>
        <button
          onClick={() => router.push("/dashboard")}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          Skip setup →
        </button>
      </header>

      {/* Progress */}
      <div className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-center justify-between">
            {STEPS.map((s, idx) => (
              <div key={s.id} className="flex flex-1 items-center">
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={cn(
                      "flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-all",
                      step > s.id
                        ? "bg-brand-600 text-white"
                        : step === s.id
                          ? "bg-brand-100 text-brand-700 ring-2 ring-brand-400"
                          : "bg-slate-100 text-slate-400",
                    )}
                  >
                    {step > s.id ? <Check className="h-4 w-4" /> : s.id}
                  </div>
                  <span
                    className={cn(
                      "text-[10px] font-medium",
                      step >= s.id ? "text-brand-700" : "text-slate-400",
                    )}
                  >
                    {s.label}
                  </span>
                </div>
                {idx < STEPS.length - 1 && (
                  <div
                    className={cn(
                      "mx-2 mb-4 h-0.5 flex-1 transition-all",
                      step > s.id ? "bg-brand-400" : "bg-slate-200",
                    )}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <main className="flex flex-1 items-start justify-center px-4 py-10">
        <div className="w-full max-w-2xl">
          {/* ── Step 1: Providers ── */}
          {step === 1 && (
            <div className="animate-fade-in space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">
                  Welcome to Atlas
                </h1>
                <p className="mt-1 text-slate-500">
                  Tell us about your cloud setup. This powers your AI recommendations — no generic
                  advice, just analysis of your actual environment.
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-semibold text-slate-700">
                  Company or project name
                </label>
                <input
                  autoFocus
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Acme Corp, My Startup"
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                />
              </div>

              <div>
                <label className="mb-3 block text-sm font-semibold text-slate-700">
                  Which cloud providers do you use?
                  <span className="ml-1 font-normal text-slate-400">(select all that apply)</span>
                </label>
                <div className="grid grid-cols-3 gap-3">
                  {PROVIDER_OPTIONS.map((p) => {
                    const active = selectedProviders.includes(p.id);
                    return (
                      <button
                        key={p.id}
                        onClick={() => toggleProvider(p.id)}
                        className={cn(
                          "flex flex-col items-center gap-3 rounded-2xl border-2 p-5 transition-all",
                          active ? p.activeColor : p.color,
                        )}
                      >
                        <p.icon className={cn("h-8 w-8", p.textColor)} />
                        <div className="text-center">
                          <p className={cn("text-base font-bold", p.textColor)}>{p.short}</p>
                          <p className="mt-0.5 text-[10px] text-slate-500">{p.name}</p>
                        </div>
                        {active && (
                          <span className={cn("flex h-5 w-5 items-center justify-center rounded-full", p.textColor.replace("text-", "bg-").replace("700", "200"))}>
                            <Check className={cn("h-3 w-3", p.textColor)} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ── Step 2: Spend ── */}
          {step === 2 && (
            <div className="animate-fade-in space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">Monthly Cloud Spend</h1>
                <p className="mt-1 text-slate-500">
                  Enter your approximate monthly spend per provider. Rough estimates are fine — Atlas
                  uses these to calibrate savings projections.
                </p>
              </div>

              <div className="space-y-4">
                {selectedProviders.map((pId) => {
                  const p = PROVIDER_OPTIONS.find((o) => o.id === pId);
                  if (!p) return null;
                  return (
                    <div key={pId} className={cn("rounded-2xl border-2 p-5", p.color)}>
                      <div className="flex items-center gap-3">
                        <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl text-sm font-bold", p.textColor.replace("text-", "bg-").replace("700", "100"), p.textColor)}>
                          {p.short}
                        </div>
                        <div className="flex-1">
                          <p className={cn("text-sm font-semibold", p.textColor)}>{p.name}</p>
                          <p className="text-xs text-slate-500">Average monthly spend (USD)</p>
                        </div>
                        <div className="relative">
                          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-medium text-slate-500">$</span>
                          <input
                            type="number"
                            min="0"
                            value={spend[pId]}
                            onChange={(e) => setSpend((s) => ({ ...s, [pId]: e.target.value }))}
                            placeholder="0"
                            className="w-36 rounded-xl border border-slate-200 bg-white py-2.5 pl-7 pr-3 text-sm font-semibold outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-semibold text-slate-700">
                  Approximate number of cloud resources
                  <span className="ml-1 font-normal text-slate-400">(VMs, databases, functions…)</span>
                </label>
                <input
                  type="number"
                  min="0"
                  value={resourceCount}
                  onChange={(e) => setResourceCount(e.target.value)}
                  placeholder="e.g. 50"
                  className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                />
              </div>
            </div>
          )}

          {/* ── Step 3: Services ── */}
          {step === 3 && (
            <div className="animate-fade-in space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">Top Cost Drivers</h1>
                <p className="mt-1 text-slate-500">
                  Select your biggest services and enter their monthly cost. The more accurate you
                  are, the better Atlas can target savings.
                </p>
              </div>

              {/* Added services */}
              {services.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Added services
                  </p>
                  {services.map((svc, i) => {
                    const pCfg = PROVIDER_OPTIONS.find((p) => p.id === svc.provider);
                    if (!pCfg) return null;
                    return (
                      <div key={i} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3">
                        <span className={cn("rounded-lg px-2 py-0.5 text-xs font-bold", pCfg.color, pCfg.textColor)}>
                          {pCfg.short}
                        </span>
                        <span className="flex-1 text-sm font-medium text-slate-700">{svc.name}</span>
                        <div className="relative">
                          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-slate-400">$</span>
                          <input
                            type="number"
                            min="0"
                            value={svc.monthlyCost || ""}
                            onChange={(e) => updateServiceCost(i, e.target.value)}
                            placeholder="0/mo"
                            className="w-28 rounded-lg border border-slate-200 py-1.5 pl-5 pr-2 text-sm outline-none focus:border-brand-400"
                          />
                        </div>
                        <button
                          onClick={() => removeService(i)}
                          className="text-slate-300 hover:text-danger-500"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Suggestions per provider */}
              {selectedProviders.map((pId) => {
                const pCfg = PROVIDER_OPTIONS.find((p) => p.id === pId);
                const suggestions = SERVICE_SUGGESTIONS[pId] ?? [];
                const available = suggestions.filter(
                  (s) => !services.some((svc) => svc.name === s.name && svc.provider === pId),
                );
                if (!available.length || !pCfg) return null;
                return (
                  <div key={pId}>
                    <p className={cn("mb-2 text-xs font-semibold uppercase tracking-wide", pCfg.textColor)}>
                      {pCfg.name} services
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {available.map((s) => (
                        <button
                          key={s.name}
                          onClick={() => addService(s.name, pId)}
                          className={cn(
                            "flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-sm font-medium transition-all hover:shadow-sm",
                            pCfg.color,
                            pCfg.textColor,
                          )}
                        >
                          <s.icon className="h-3.5 w-3.5" />
                          {s.name}
                          <Plus className="h-3 w-3 opacity-60" />
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── Step 4: Goals ── */}
          {step === 4 && (
            <div className="animate-fade-in space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-slate-900">Your Optimization Goals</h1>
                <p className="mt-1 text-slate-500">
                  Tell Atlas what matters most. Claude uses this to prioritize its recommendations
                  specifically for your situation.
                </p>
              </div>

              <div>
                <label className="mb-3 block text-sm font-semibold text-slate-700">
                  What are you trying to achieve?
                  <span className="ml-1 font-normal text-slate-400">(pick all that apply)</span>
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {DEFAULT_GOALS.map((goal) => {
                    const active = selectedGoals.includes(goal);
                    return (
                      <button
                        key={goal}
                        onClick={() => toggleGoal(goal)}
                        className={cn(
                          "flex items-center gap-3 rounded-xl border-2 p-3.5 text-left text-sm font-medium transition-all",
                          active
                            ? "border-brand-400 bg-brand-50 text-brand-800 ring-1 ring-brand-300"
                            : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
                        )}
                      >
                        <span
                          className={cn(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                            active ? "bg-brand-600" : "bg-slate-200",
                          )}
                        >
                          {active && <Check className="h-3 w-3 text-white" />}
                        </span>
                        {goal}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-semibold text-slate-700">
                  Describe your biggest cloud cost challenge
                  <span className="ml-1 font-normal text-slate-400">(optional, but helps Atlas give better advice)</span>
                </label>
                <textarea
                  value={painPoints}
                  onChange={(e) => setPainPoints(e.target.value)}
                  placeholder="e.g. Our dev/staging environments run 24/7 and we suspect they're heavily over-provisioned. Our RDS costs jumped 40% last month and we're not sure why..."
                  rows={4}
                  className="w-full resize-none rounded-xl border border-slate-200 px-4 py-3 text-sm leading-relaxed outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                />
              </div>

              {/* Summary preview */}
              {(selectedProviders.length > 0) && (
                <div className="rounded-2xl border border-brand-200 bg-brand-50 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Lightbulb className="h-4 w-4 text-brand-600" />
                    <p className="text-sm font-semibold text-brand-800">What Atlas will analyze</p>
                  </div>
                  <ul className="space-y-1.5 text-xs text-brand-700">
                    <li className="flex items-center gap-2">
                      <ChevronRight className="h-3 w-3" />
                      Providers: {selectedProviders.map((p) => p.toUpperCase()).join(", ")}
                    </li>
                    <li className="flex items-center gap-2">
                      <ChevronRight className="h-3 w-3" />
                      Total monthly spend: ${Object.values(spend).reduce((s, v) => s + (parseFloat(v) || 0), 0).toLocaleString()}
                    </li>
                    {services.length > 0 && (
                      <li className="flex items-center gap-2">
                        <ChevronRight className="h-3 w-3" />
                        Top services: {services.map((s) => s.name.split(" ")[0]).join(", ")}
                      </li>
                    )}
                    {selectedGoals.length > 0 && (
                      <li className="flex items-center gap-2">
                        <ChevronRight className="h-3 w-3" />
                        {selectedGoals.length} optimization goals selected
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Navigation buttons */}
          <div className="mt-8 flex items-center justify-between">
            <button
              onClick={() => (step > 1 ? setStep((s) => s - 1) : router.push("/"))}
              className="flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-700"
            >
              <ArrowLeft className="h-4 w-4" />
              {step === 1 ? "Back to home" : "Back"}
            </button>

            {step < 4 ? (
              <button
                onClick={() => setStep((s) => s + 1)}
                disabled={!canAdvance()}
                className={cn(
                  "flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-semibold transition-all",
                  canAdvance()
                    ? "bg-brand-600 text-white hover:bg-brand-700 shadow-sm"
                    : "cursor-not-allowed bg-slate-100 text-slate-400",
                )}
              >
                Continue
                <ArrowRight className="h-4 w-4" />
              </button>
            ) : (
              <button
                onClick={handleFinish}
                className="flex items-center gap-2 rounded-xl bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
              >
                <CheckCircle className="h-4 w-4" />
                Launch Dashboard
              </button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
