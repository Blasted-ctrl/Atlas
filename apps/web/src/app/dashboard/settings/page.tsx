"use client";

import { Bell, Building2, CheckCircle, Eye, EyeOff, Key, Mail, Save, Shield, X, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";
import { useCloudProfile } from "@/lib/use-cloud-profile";

const SETTINGS_KEY = "atlas_settings";

interface AtlasSettings {
  billingEmail: string;
  currency: string;
  timezone: string;
  fiscalYearStart: string;
  notifications: {
    email: boolean;
    slack: boolean;
    weeklyReport: boolean;
    anomalyAlerts: boolean;
    savingsDigest: boolean;
    recommendationUpdates: boolean;
    budgetAlerts: boolean;
  };
  thresholds: {
    anomalyPercent: string;
    budgetLimit: string;
    savingsTarget: string;
  };
  security: {
    twoFactor: boolean;
    sso: boolean;
    sessionTimeout: boolean;
  };
  ipAllowlist: string[];
}

function loadSettings(fallbackEmail: string): AtlasSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return JSON.parse(raw) as AtlasSettings;
  } catch {
    // ignore
  }
  return {
    billingEmail: fallbackEmail,
    currency: "USD",
    timezone: "America/New_York",
    fiscalYearStart: "January",
    notifications: {
      email: true,
      slack: false,
      weeklyReport: true,
      anomalyAlerts: true,
      savingsDigest: true,
      recommendationUpdates: false,
      budgetAlerts: true,
    },
    thresholds: {
      anomalyPercent: "20",
      budgetLimit: "35000",
      savingsTarget: "20",
    },
    security: {
      twoFactor: false,
      sso: false,
      sessionTimeout: true,
    },
    ipAllowlist: [],
  };
}

const tabs = [
  { id: "org", label: "Organization", icon: Building2 },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "api", label: "API Keys", icon: Key },
  { id: "security", label: "Security", icon: Shield },
] as const;

type TabId = (typeof tabs)[number]["id"];

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none",
        checked ? "bg-brand-600" : "bg-slate-200",
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow ring-0 transition-transform",
          checked ? "translate-x-4" : "translate-x-0",
        )}
      />
    </button>
  );
}

export default function SettingsPage() {
  const { profile, saveProfile } = useCloudProfile();
  const [activeTab, setActiveTab] = useState<TabId>("org");
  const [saved, setSaved] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [ipInput, setIpInput] = useState("");

  const [orgName, setOrgName] = useState("");
  const [settings, setSettings] = useState<AtlasSettings | null>(null);

  // Load settings after mount (client only)
  useEffect(() => {
    const loaded = loadSettings("");
    setSettings(loaded);
  }, []);

  // Once profile is loaded, set org name and fill billing email if settings has no email
  useEffect(() => {
    if (profile.companyName) {
      setOrgName(profile.companyName);
    }
    if (settings && !settings.billingEmail && profile.companyName) {
      setSettings((s) => s ? { ...s, billingEmail: s.billingEmail || "" } : s);
    }
  }, [profile.companyName, settings]);

  if (!settings) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  function persistSettings(next: AtlasSettings) {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  }

  function updateSettings(patch: Partial<AtlasSettings>) {
    setSettings((prev) => {
      if (!prev) return prev;
      return { ...prev, ...patch };
    });
  }

  function handleSave() {
    // Persist org name to cloud profile
    if (orgName && orgName !== profile.companyName) {
      saveProfile({ companyName: orgName });
    }
    // Persist all other settings to their own key
    if (settings) persistSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  function addIp() {
    if (!settings) return;
    const ip = ipInput.trim();
    if (!ip) return;
    const next = { ...settings, ipAllowlist: [...settings.ipAllowlist, ip] };
    setSettings(next);
    setIpInput("");
  }

  function removeIp(ip: string) {
    if (!settings) return;
    updateSettings({ ipAllowlist: settings.ipAllowlist.filter((i) => i !== ip) });
  }

  const slug = orgName.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Manage your organization, notifications, and integrations
          </p>
        </div>
        <button
          onClick={handleSave}
          className={cn("btn-primary gap-1.5 text-xs transition-all", saved && "bg-success-500 hover:bg-success-500")}
        >
          {saved ? (
            <><CheckCircle className="h-3.5 w-3.5" /> Saved</>
          ) : (
            <><Save className="h-3.5 w-3.5" /> Save Changes</>
          )}
        </button>
      </div>

      <div className="flex gap-6">
        <div className="w-52 shrink-0">
          <nav className="space-y-0.5">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-all",
                  activeTab === tab.id
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                )}
              >
                <tab.icon className={cn("h-4 w-4 shrink-0", activeTab === tab.id ? "text-brand-600" : "text-slate-400")} />
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 space-y-6">
          {activeTab === "org" && (
            <>
              <div className="card space-y-5 p-6">
                <h2 className="text-base font-semibold text-slate-900">Organization Details</h2>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Organization Name</label>
                    <input
                      type="text"
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Slug</label>
                    <input
                      type="text"
                      readOnly
                      value={slug}
                      className="w-full rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-400 outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Billing Email</label>
                    <input
                      type="email"
                      value={settings.billingEmail}
                      onChange={(e) => updateSettings({ billingEmail: e.target.value })}
                      placeholder="billing@yourcompany.com"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Currency</label>
                    <select
                      value={settings.currency}
                      onChange={(e) => updateSettings({ currency: e.target.value })}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
                    >
                      <option>USD</option><option>EUR</option><option>GBP</option><option>JPY</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Timezone</label>
                    <select
                      value={settings.timezone}
                      onChange={(e) => updateSettings({ timezone: e.target.value })}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
                    >
                      <option>America/New_York</option>
                      <option>America/Los_Angeles</option>
                      <option>Europe/London</option>
                      <option>Europe/Berlin</option>
                      <option>Asia/Tokyo</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-slate-600">Fiscal Year Start</label>
                    <select
                      value={settings.fiscalYearStart}
                      onChange={(e) => updateSettings({ fiscalYearStart: e.target.value })}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
                    >
                      {["January","February","March","April","July","October"].map((m) => <option key={m}>{m}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              <div className="card space-y-4 p-6">
                <h2 className="text-base font-semibold text-slate-900">Budget & Threshold Alerts</h2>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {(
                    [
                      { label: "Anomaly Alert Threshold", key: "anomalyPercent", suffix: "% spike", prefix: undefined },
                      { label: "Monthly Budget Limit", key: "budgetLimit", suffix: undefined, prefix: "$" },
                      { label: "Savings Target", key: "savingsTarget", suffix: "%", prefix: undefined },
                    ] as const
                  ).map((field) => (
                    <div key={field.key}>
                      <label className="mb-1.5 block text-xs font-semibold text-slate-600">{field.label}</label>
                      <div className="relative">
                        {field.prefix && (
                          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">{field.prefix}</span>
                        )}
                        <input
                          type="number"
                          value={settings.thresholds[field.key]}
                          onChange={(e) =>
                            updateSettings({ thresholds: { ...settings.thresholds, [field.key]: e.target.value } })
                          }
                          className={cn("w-full rounded-lg border border-slate-200 py-2 pr-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100", field.prefix ? "pl-7" : "pl-3")}
                        />
                        {field.suffix && (
                          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">{field.suffix}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {activeTab === "notifications" && (
            <div className="card space-y-6 p-6">
              <h2 className="text-base font-semibold text-slate-900">Notification Preferences</h2>
              <div>
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Delivery Channels</h3>
                <div className="space-y-3">
                  {(
                    [
                      {
                        key: "email" as const,
                        label: "Email Notifications",
                        icon: Mail,
                        desc: settings.billingEmail || "Set a billing email in Organization settings",
                      },
                      { key: "slack" as const, label: "Slack Integration", icon: Zap, desc: "Connect #cloud-costs channel" },
                    ]
                  ).map((channel) => (
                    <div key={channel.key} className="flex items-center justify-between rounded-xl border border-slate-200 p-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100">
                          <channel.icon className="h-4 w-4 text-slate-600" />
                        </div>
                        <div>
                          <p className="text-sm font-medium text-slate-900">{channel.label}</p>
                          <p className="text-xs text-slate-400">{channel.desc}</p>
                        </div>
                      </div>
                      <Toggle
                        checked={settings.notifications[channel.key]}
                        onChange={(v) => updateSettings({ notifications: { ...settings.notifications, [channel.key]: v } })}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Alert Types</h3>
                <div className="space-y-2.5">
                  {(
                    [
                      { key: "weeklyReport" as const, label: "Weekly Cost Report", desc: "Sent every Monday morning" },
                      { key: "anomalyAlerts" as const, label: "Spend Anomaly Alerts", desc: "Triggered when spend spikes above threshold" },
                      { key: "savingsDigest" as const, label: "Savings Digest", desc: "Monthly summary of savings achieved" },
                      { key: "recommendationUpdates" as const, label: "New Recommendations", desc: "When Atlas AI generates new optimization opportunities" },
                      { key: "budgetAlerts" as const, label: "Budget Alerts", desc: "When spend approaches monthly limit" },
                    ]
                  ).map((item) => (
                    <div key={item.key} className="flex items-center justify-between py-2.5">
                      <div>
                        <p className="text-sm font-medium text-slate-900">{item.label}</p>
                        <p className="text-xs text-slate-400">{item.desc}</p>
                      </div>
                      <Toggle
                        checked={settings.notifications[item.key]}
                        onChange={(v) => updateSettings({ notifications: { ...settings.notifications, [item.key]: v } })}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === "api" && (
            <div className="card space-y-5 p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-slate-900">API Keys</h2>
                <button className="btn-primary gap-1.5 text-xs">
                  <Key className="h-3.5 w-3.5" /> Generate Key
                </button>
              </div>
              <div className="rounded-xl border border-slate-200 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Atlas API Key</p>
                    <p className="text-xs text-slate-400">Used to authenticate requests to the Atlas REST API</p>
                  </div>
                  <span className="badge bg-slate-100 text-slate-500">Demo</span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <input
                    type={showKey ? "text" : "password"}
                    readOnly
                    value="atl_demo_sk_generate_a_real_key_in_production"
                    className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600 outline-none"
                  />
                  <button
                    onClick={() => setShowKey(!showKey)}
                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                  >
                    {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <p className="mb-1 text-xs font-semibold text-slate-600">Usage example</p>
                <pre className="overflow-x-auto font-mono text-xs text-slate-500">
                  {`curl -H "Authorization: Bearer atl_..." \\\n  https://api.atlas.io/v1/costs`}
                </pre>
              </div>
              <div className="rounded-xl border border-amber-100 bg-amber-50 p-4">
                <p className="text-xs font-semibold text-amber-800">Anthropic AI integration</p>
                <p className="mt-0.5 text-xs text-amber-700">
                  Your Anthropic API key is configured server-side via the <code className="font-mono">ANTHROPIC_API_KEY</code> environment variable and is never exposed in the browser.
                </p>
              </div>
            </div>
          )}

          {activeTab === "security" && (
            <div className="space-y-4">
              <div className="card space-y-4 p-6">
                <h2 className="text-base font-semibold text-slate-900">Authentication</h2>
                {(
                  [
                    { key: "twoFactor" as const, label: "Two-Factor Authentication", desc: "Require 2FA for all members" },
                    { key: "sso" as const, label: "SSO / SAML", desc: "Single Sign-On via identity provider" },
                    { key: "sessionTimeout" as const, label: "Session Timeout", desc: "Auto-logout after 8 hours of inactivity" },
                  ]
                ).map((item) => (
                  <div key={item.key} className="flex items-center justify-between py-2">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{item.label}</p>
                      <p className="text-xs text-slate-400">{item.desc}</p>
                    </div>
                    <Toggle
                      checked={settings.security[item.key]}
                      onChange={(v) => updateSettings({ security: { ...settings.security, [item.key]: v } })}
                    />
                  </div>
                ))}
              </div>
              <div className="card space-y-3 p-6">
                <h2 className="text-base font-semibold text-slate-900">IP Allowlist</h2>
                <p className="text-sm text-slate-500">Restrict API and dashboard access to specific IP ranges.</p>
                <div className="flex gap-2">
                  <input
                    value={ipInput}
                    onChange={(e) => setIpInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addIp()}
                    placeholder="e.g. 192.168.1.0/24"
                    className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
                  />
                  <button onClick={addIp} className="btn-secondary px-4 text-xs">Add</button>
                </div>
                {settings.ipAllowlist.length > 0 ? (
                  <div className="space-y-1.5">
                    {settings.ipAllowlist.map((ip) => (
                      <div key={ip} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
                        {ip}
                        <button onClick={() => removeIp(ip)} className="text-slate-400 hover:text-red-500">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
                    No IP restrictions configured. All IPs are allowed.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
