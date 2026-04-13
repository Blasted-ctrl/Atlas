"use client";

import {
  Activity,
  AlertCircle,
  BarChart3,
  Bell,
  ChevronDown,
  Cloud,
  LayoutDashboard,
  Lightbulb,
  Search,
  Server,
  Settings,
  TrendingDown,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

const navigation = [
  {
    name: "Overview",
    href: "/dashboard",
    icon: LayoutDashboard,
    description: "Cost snapshot and KPIs",
  },
  {
    name: "Cloud Accounts",
    href: "/dashboard/accounts",
    icon: Cloud,
    description: "Manage AWS, GCP, Azure",
  },
  {
    name: "Cost Explorer",
    href: "/dashboard/costs",
    icon: BarChart3,
    description: "Drill into spend by service",
  },
  {
    name: "Resources",
    href: "/dashboard/resources",
    icon: Server,
    description: "Inventory and utilization",
  },
  {
    name: "Recommendations",
    href: "/dashboard/recommendations",
    icon: Lightbulb,
    description: "AI-powered savings",
    badge: true,
  },
  {
    name: "Settings",
    href: "/dashboard/settings",
    icon: Settings,
    description: "Alerts and API keys",
  },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { profile, loaded, totalMonthlySpend } = useCloudProfile();

  const setupComplete = loaded && profile.setupComplete;
  const companyInitials = profile.companyName ? profile.companyName.slice(0, 2).toUpperCase() : "AC";
  const currentPage =
    navigation.find((item) =>
      item.href === "/dashboard"
        ? pathname === "/dashboard"
        : pathname.startsWith(item.href),
    )?.name ?? "Dashboard";

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex min-h-screen">
        <aside className="hidden w-[288px] shrink-0 flex-col px-4 py-4 lg:flex">
          <div className="card flex h-full flex-col overflow-hidden">
            <div className="flex h-16 shrink-0 items-center px-5">
              <Link href="/" className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-950 text-white shadow-lg shadow-slate-900/10">
                  <TrendingDown className="h-4 w-4" strokeWidth={2.5} />
                </div>
                <div>
                  <span className="text-base font-semibold tracking-tight text-slate-950">Atlas</span>
                  <p className="text-[11px] leading-none text-slate-500">Cloud cost platform</p>
                </div>
              </Link>
            </div>

            <div className="px-4">
              {loaded && !setupComplete && (
                <Link
                  href="/onboarding"
                  className="mb-4 flex items-start gap-3 rounded-[1.4rem] border border-warning-200 bg-warning-50 p-4 text-left transition-colors hover:bg-warning-100"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning-600" />
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-warning-800">
                      Setup required
                    </p>
                    <p className="mt-1 text-[11px] leading-snug text-warning-700">
                      Add your cloud data to unlock recommendations.
                    </p>
                  </div>
                </Link>
              )}
            </div>

            <nav className="flex flex-1 flex-col gap-1 px-4 pb-4">
              <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Platform
              </p>
              {navigation.map((item) => {
                const active =
                  item.href === "/dashboard"
                    ? pathname === "/dashboard"
                    : pathname.startsWith(item.href);

                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    className={cn(
                      "group flex items-center gap-3 rounded-[1.2rem] px-3 py-3 transition-all duration-200",
                      active
                        ? "bg-slate-950 text-white shadow-lg shadow-slate-900/10"
                        : "text-slate-600 hover:-translate-y-0.5 hover:bg-slate-100 hover:text-slate-900",
                    )}
                  >
                    <item.icon
                      className={cn(
                        "h-4 w-4 shrink-0",
                        active ? "text-white" : "text-slate-400 group-hover:text-slate-600",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-none">{item.name}</p>
                      <p
                        className={cn(
                          "mt-1 text-[11px] leading-none",
                          active ? "text-slate-300" : "text-slate-400",
                        )}
                      >
                        {item.description}
                      </p>
                    </div>
                    {item.badge && (
                      <span
                        className={cn(
                          "flex h-5 min-w-8 shrink-0 items-center justify-center rounded-full px-2 text-[10px] font-bold",
                          active ? "bg-white/10 text-white" : "bg-brand-600 text-white",
                        )}
                      >
                        AI
                      </span>
                    )}
                  </Link>
                );
              })}
            </nav>

            <div className="soft-divider px-4 py-4">
              {setupComplete ? (
                <Link
                  href="/onboarding"
                  className="flex items-center gap-3 rounded-[1.2rem] p-2 transition-colors hover:bg-slate-50"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand-600 text-[11px] font-bold text-white">
                    {companyInitials}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-700">{profile.companyName}</p>
                    <p className="text-[11px] text-slate-500">
                      {profile.providers.map((provider) => provider.toUpperCase()).join(" / ")} · ${totalMonthlySpend.toLocaleString()}/mo
                    </p>
                  </div>
                </Link>
              ) : (
                <div className="flex items-center gap-2 rounded-full bg-success-50 px-3 py-2">
                  <Activity className="h-3.5 w-3.5 text-success-700" />
                  <span className="text-xs font-medium text-success-700">Systems operational</span>
                </div>
              )}
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 px-4 pb-2 pt-4 sm:px-6">
            <div className="card flex min-h-16 items-center justify-between px-5 py-4">
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Atlas workspace</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{currentPage}</div>
              </div>

              <div className="flex items-center gap-3">
                <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-sm text-slate-500 xl:flex">
                  <Search className="h-4 w-4" />
                  Search accounts, services, or recommendations
                </div>

                <button className="relative flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition-colors hover:bg-slate-50">
                  <Bell className="h-4 w-4" />
                  <span className="absolute right-3 top-3 h-1.5 w-1.5 rounded-full bg-brand-600" />
                </button>

                {setupComplete ? (
                  <Link
                    href="/onboarding"
                    className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 transition-all duration-200 hover:-translate-y-0.5 hover:bg-slate-50"
                  >
                    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-[10px] font-bold text-white">
                      {companyInitials}
                    </div>
                    <span className="hidden text-sm font-medium text-slate-700 sm:inline">{profile.companyName}</span>
                    <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                  </Link>
                ) : (
                  <Link href="/onboarding" className="btn-primary gap-1.5 text-xs">
                    <AlertCircle className="h-3.5 w-3.5" /> Complete setup
                  </Link>
                )}
              </div>
            </div>
          </header>

          <main className="flex-1 px-4 pb-8 sm:px-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
