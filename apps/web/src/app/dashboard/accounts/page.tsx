"use client";

import {
  AlertTriangle,
  CheckCircle,
  Cloud,
  ExternalLink,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

const providerConfig = {
  aws: {
    label: "Amazon Web Services",
    short: "AWS",
    color: "text-orange-600",
    bg: "bg-orange-50",
    border: "border-orange-200",
    dot: "bg-orange-500",
  },
  gcp: {
    label: "Google Cloud",
    short: "GCP",
    color: "text-green-600",
    bg: "bg-green-50",
    border: "border-green-200",
    dot: "bg-green-500",
  },
  azure: {
    label: "Microsoft Azure",
    short: "AZ",
    color: "text-blue-600",
    bg: "bg-blue-50",
    border: "border-blue-200",
    dot: "bg-blue-500",
  },
} as const;

type Provider = keyof typeof providerConfig;

export default function AccountsPage() {
  const { profile, loaded, totalMonthlySpend, saveProfile } = useCloudProfile();
  const [search, setSearch] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [accountName, setAccountName] = useState("");
  const [accountId, setAccountId] = useState("");
  const [monthlySpendInput, setMonthlySpendInput] = useState("");
  const [addError, setAddError] = useState("");

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
        <h1 className="text-2xl font-bold text-slate-900">Cloud Accounts</h1>
        <p className="mt-0.5 text-sm text-slate-500">Manage your connected cloud providers</p>
        <div className="mt-12 flex flex-col items-center py-10 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50">
            <Cloud className="h-7 w-7 text-brand-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900">No accounts configured</h2>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
            Complete your setup to see your cloud providers and their spend breakdown here.
          </p>
          <Link href="/onboarding" className="btn-primary mt-6 gap-2 rounded-xl px-6 py-2.5 text-sm">
            <Plus className="h-4 w-4" />
            Configure my cloud accounts
          </Link>
        </div>
      </div>
    );
  }

  // Build account rows from the user's real profile
  const accounts = profile.providers.map((provider, i) => {
    const spend = profile.monthlySpend[provider as keyof typeof profile.monthlySpend] ?? 0;
    const resourceShare =
      profile.resourceCount > 0
        ? Math.round(profile.resourceCount / profile.providers.length)
        : 0;
    return {
      id: `acc-${i + 1}`,
      provider: provider as Provider,
      name: `${providerConfig[provider as Provider].short} — ${profile.companyName}`,
      spendMTD: spend,
      resources: resourceShare,
      status: "active" as const,
    };
  });

  const filtered = accounts.filter((a) =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.provider.includes(search.toLowerCase()),
  );

  function openAddModal() {
    setSelectedProvider(null);
    setAccountName("");
    setAccountId("");
    setMonthlySpendInput("");
    setAddError("");
    setShowAddModal(true);
  }

  function handleSaveAccount() {
    if (!selectedProvider) {
      setAddError("Please select a cloud provider.");
      return;
    }
    if (profile.providers.includes(selectedProvider)) {
      setAddError(`${providerConfig[selectedProvider].label} is already connected. Edit the spend from Settings.`);
      return;
    }
    const spend = parseFloat(monthlySpendInput) || 0;
    saveProfile({
      providers: [...profile.providers, selectedProvider],
      monthlySpend: {
        ...profile.monthlySpend,
        [selectedProvider]: spend,
      },
    });
    setShowAddModal(false);
  }

  return (
    <div className="space-y-6 p-6">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Cloud Accounts</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {accounts.length} active {accounts.length === 1 ? "account" : "accounts"} ·{" "}
            ${totalMonthlySpend.toLocaleString()} MTD spend
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary gap-1.5 text-xs">
            <RefreshCw className="h-3.5 w-3.5" /> Sync All
          </button>
          <button onClick={openAddModal} className="btn-primary gap-1.5 text-xs">
            <Plus className="h-3.5 w-3.5" /> Add Account
          </button>
        </div>
      </div>

      {/* ── Provider summary cards ───────────────────────────────────────── */}
      <div className={cn("grid gap-4", profile.providers.length === 1 ? "grid-cols-1 max-w-xs" : profile.providers.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
        {profile.providers.map((provider) => {
          const cfg = providerConfig[provider as Provider];
          const spend = profile.monthlySpend[provider as keyof typeof profile.monthlySpend] ?? 0;
          return (
            <div key={provider} className={cn("card border p-5", cfg.border)}>
              <div className="flex items-center justify-between">
                <div className={cn("flex items-center gap-2 text-sm font-semibold", cfg.color)}>
                  <span className={cn("h-2 w-2 rounded-full", cfg.dot)} />
                  {cfg.short}
                </div>
                <span className="flex items-center gap-1 text-xs text-success-700">
                  <CheckCircle className="h-3 w-3" /> Active
                </span>
              </div>
              <p className="mt-3 text-2xl font-bold text-slate-900">${spend.toLocaleString()}</p>
              <p className="text-xs text-slate-500">monthly spend</p>
            </div>
          );
        })}
      </div>

      {/* ── Accounts table ──────────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="flex items-center gap-3 border-b border-slate-100 p-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter accounts..."
              className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-4 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            />
          </div>
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50/60">
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                Account
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                Provider
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                Resources
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                MTD Spend
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {filtered.map((account) => {
              const pCfg = providerConfig[account.provider];
              return (
                <tr key={account.id} className="transition-colors hover:bg-slate-50/80">
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <div
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold",
                          pCfg.bg,
                          pCfg.color,
                        )}
                      >
                        {pCfg.short}
                      </div>
                      <span className="font-medium text-slate-900">{account.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3.5">
                    <span className={cn("badge", pCfg.bg, pCfg.color)}>{pCfg.label}</span>
                  </td>
                  <td className="px-4 py-3.5 text-right font-medium text-slate-900">
                    {account.resources > 0 ? account.resources.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3.5 text-right">
                    <span className="font-semibold text-slate-900">
                      {account.spendMTD > 0 ? `$${account.spendMTD.toLocaleString()}` : "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="badge bg-success-50 text-success-700">
                      <CheckCircle className="h-3 w-3" />
                      Active
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="flex flex-col items-center py-12 text-slate-400">
            <Cloud className="mb-2 h-8 w-8" />
            <p className="text-sm font-medium">No accounts match your search</p>
          </div>
        )}
      </div>

      {/* ── Note about real integration ─────────────────────────────────── */}
      <div className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        <div>
          <p className="text-sm font-semibold text-slate-700">Spend data from your profile</p>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
            These figures come from the monthly spend you entered during setup. Connect live AWS, GCP, or Azure credentials to pull real billing data automatically.
          </p>
          <Link
            href="/onboarding"
            className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:underline"
          >
            Update my profile <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* ── Add Account modal ────────────────────────────────────────────── */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setShowAddModal(false)}
        >
          <div
            className="card w-full max-w-md p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-slate-900">Connect Cloud Account</h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Choose a provider and enter your account details.
            </p>

            <div className="mt-5 grid grid-cols-3 gap-3">
              {(["aws", "gcp", "azure"] as const).map((p) => {
                const cfg = providerConfig[p];
                const alreadyAdded = profile.providers.includes(p);
                return (
                  <button
                    key={p}
                    disabled={alreadyAdded}
                    onClick={() => { setSelectedProvider(p); setAddError(""); }}
                    className={cn(
                      "flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all",
                      alreadyAdded
                        ? "cursor-not-allowed border-slate-100 bg-slate-50 opacity-40"
                        : selectedProvider === p
                          ? cn("shadow-md", cfg.border, cfg.bg)
                          : "border-slate-200 bg-white hover:shadow-md",
                    )}
                  >
                    <span className={cn("text-lg font-black", alreadyAdded ? "text-slate-400" : cfg.color)}>{cfg.short}</span>
                    <span className={cn("text-xs font-medium", alreadyAdded ? "text-slate-400" : cfg.color)}>
                      {alreadyAdded ? "Added" : cfg.short}
                    </span>
                  </button>
                );
              })}
            </div>

            {selectedProvider && (
              <div className="mt-5 space-y-3">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-slate-600">
                    Account Name
                  </label>
                  <input
                    value={accountName}
                    onChange={(e) => setAccountName(e.target.value)}
                    placeholder={`e.g. Production ${providerConfig[selectedProvider].short}`}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-slate-600">
                    Account / Project ID
                  </label>
                  <input
                    value={accountId}
                    onChange={(e) => setAccountId(e.target.value)}
                    placeholder="e.g. 123456789012"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-slate-600">
                    Estimated Monthly Spend (USD)
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">$</span>
                    <input
                      type="number"
                      value={monthlySpendInput}
                      onChange={(e) => setMonthlySpendInput(e.target.value)}
                      placeholder="0"
                      min="0"
                      className="w-full rounded-lg border border-slate-200 py-2 pl-7 pr-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    />
                  </div>
                </div>
              </div>
            )}

            {addError && (
              <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{addError}</p>
            )}

            <div className="mt-6 flex gap-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="btn-secondary flex-1 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAccount}
                disabled={!selectedProvider}
                className={cn("btn-primary flex-1 gap-1.5 text-xs", !selectedProvider && "cursor-not-allowed opacity-50")}
              >
                <CheckCircle className="h-3.5 w-3.5" /> Save Account
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
