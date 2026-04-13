import Anthropic from "@anthropic-ai/sdk";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

interface ServiceEntry {
  name: string;
  provider: string;
  monthlyCost: number;
}

interface UserProfile {
  companyName: string;
  providers: string[];
  monthlySpend: { aws: number; gcp: number; azure: number };
  totalMonthlySpend: number;
  topServices: ServiceEntry[];
  resourceCount: number;
  painPoints: string;
  goals: string[];
}

interface RequestBody {
  userProfile: UserProfile;
}

const client = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as RequestBody;
    const { userProfile } = body;

    const serviceList = userProfile.topServices.length
      ? userProfile.topServices
          .map((s) => `- ${s.name} (${s.provider.toUpperCase()}): $${s.monthlyCost.toLocaleString()}/mo`)
          .join("\n")
      : "- No specific services provided";

    const providerBreakdown = userProfile.providers
      .map((p) => {
        const spend = userProfile.monthlySpend[p as keyof typeof userProfile.monthlySpend] ?? 0;
        return `- ${p.toUpperCase()}: $${spend.toLocaleString()}/mo`;
      })
      .join("\n");

    const goalsText = userProfile.goals.length ? userProfile.goals.join(", ") : "general cost optimization";

    const prompt = `You are an expert FinOps engineer and cloud cost optimization specialist. Analyze the following cloud infrastructure profile and provide specific, actionable cost optimization recommendations tailored to this company's situation.

## Company Profile
- Company: ${userProfile.companyName}
- Cloud Providers: ${userProfile.providers.map((p) => p.toUpperCase()).join(", ")}
- Total Monthly Cloud Spend: $${userProfile.totalMonthlySpend.toLocaleString()}
- Total Resources: ~${userProfile.resourceCount}

## Spend by Provider
${providerBreakdown}

## Top Services by Cost
${serviceList}

## Optimization Goals
${goalsText}

## Specific Pain Points / Context
${userProfile.painPoints || "Not specified — provide general best-practice recommendations for their provider mix and spend level."}

Based on this specific company profile, provide 5 tailored AI-powered cost optimization recommendations. Each recommendation must be:
1. Specific to their actual services, providers, and spend levels mentioned above
2. Actionable with clear next steps
3. Realistic in savings estimates (based on industry benchmarks: rightsizing 10-20%, Reserved Instances 30-40% on compute, idle cleanup 5-10%)
4. Directly addressing their stated goals and pain points where possible

Respond with a JSON array of recommendations. Each item must have these exact fields:
- title: string (concise action title, max 60 chars, start with a verb)
- description: string (2-3 sentences: what to do, why it matters for THIS company, how to start)
- estimatedSavings: number (monthly savings in USD — be realistic given their spend of $${userProfile.totalMonthlySpend.toLocaleString()}/mo)
- priority: "high" | "medium" | "low"
- category: "rightsizing" | "reserved-instances" | "idle-cleanup" | "architecture" | "commitment" | "scheduling" | "storage" | "network"
- confidence: number (0-100, your confidence in the savings estimate)

Return ONLY valid JSON array, no markdown, no explanation.`;

    const message = await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1500,
      messages: [{ role: "user", content: prompt }],
    });

    const firstBlock = message.content[0];
    if (!firstBlock || firstBlock.type !== "text") {
      throw new Error("Unexpected response type from Claude");
    }
    const rawText = firstBlock.text;

    let insights: unknown;
    try {
      insights = JSON.parse(rawText) as unknown;
    } catch {
      const match = rawText.match(/\[[\s\S]*\]/);
      if (match?.[0]) {
        insights = JSON.parse(match[0]) as unknown;
      } else {
        throw new Error("Could not parse Claude response as JSON");
      }
    }

    return NextResponse.json({
      insights,
      model: message.model,
      usage: message.usage,
    });
  } catch (error) {
    console.error("AI recommendations error:", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to generate insights" },
      { status: 500 },
    );
  }
}
