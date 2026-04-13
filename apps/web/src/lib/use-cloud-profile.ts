"use client";

import { useCallback, useEffect, useState } from "react";

export interface ServiceEntry {
  name: string;
  provider: "aws" | "gcp" | "azure";
  monthlyCost: number;
}

export interface CloudProfile {
  companyName: string;
  providers: Array<"aws" | "gcp" | "azure">;
  monthlySpend: { aws: number; gcp: number; azure: number };
  topServices: ServiceEntry[];
  resourceCount: number;
  painPoints: string;
  goals: string[];
  setupComplete: boolean;
  createdAt: string;
}

export const DEFAULT_GOALS = [
  "Reduce overall cloud spend",
  "Rightsize overprovisioned resources",
  "Eliminate idle & unused resources",
  "Optimize reserved instance coverage",
  "Improve cost visibility & tagging",
  "Set up budget alerts",
];

const STORAGE_KEY = "atlas_cloud_profile";

export function emptyProfile(): CloudProfile {
  return {
    companyName: "",
    providers: [],
    monthlySpend: { aws: 0, gcp: 0, azure: 0 },
    topServices: [],
    resourceCount: 0,
    painPoints: "",
    goals: [],
    setupComplete: false,
    createdAt: new Date().toISOString(),
  };
}

export function useCloudProfile() {
  const [profile, setProfileState] = useState<CloudProfile>(emptyProfile());
  const [loaded, setLoaded] = useState(false);

  // Load from localStorage on mount (client only)
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as CloudProfile;
        setProfileState(parsed);
      }
    } catch {
      // ignore parse errors
    }
    setLoaded(true);
  }, []);

  const saveProfile = useCallback((updates: Partial<CloudProfile>) => {
    setProfileState((prev) => {
      const next = { ...prev, ...updates };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore storage errors
      }
      return next;
    });
  }, []);

  const resetProfile = useCallback(() => {
    const fresh = emptyProfile();
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    setProfileState(fresh);
  }, []);

  // Derived values
  const totalMonthlySpend =
    profile.monthlySpend.aws + profile.monthlySpend.gcp + profile.monthlySpend.azure;

  // Industry-benchmark estimates (conservative):
  // rightsizing ~15%, reserved instances ~20%, idle ~8%, storage ~5% → ~20-25% target
  const estimatedSavings = Math.round(totalMonthlySpend * 0.22);
  const projectedMonthly = Math.round(totalMonthlySpend * 1.05); // trend +5% without action

  return {
    profile,
    loaded,
    saveProfile,
    resetProfile,
    totalMonthlySpend,
    estimatedSavings,
    projectedMonthly,
  };
}
