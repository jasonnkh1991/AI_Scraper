import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type DispatchPayload = {
  ref: string;
  inputs?: {
    self_test?: string;
  };
};

function getRequiredEnv(name: string) {
  const value = process.env[name]?.trim();

  if (!value) {
    throw new Error(`Missing ${name}`);
  }

  return value;
}

function getBearerToken(request: NextRequest) {
  const authHeader = request.headers.get("authorization") ?? "";
  const [scheme, token] = authHeader.split(" ");

  if (scheme.toLowerCase() !== "bearer" || !token) {
    return null;
  }

  return token.trim();
}

async function dispatchWorkflow() {
  const githubToken = getRequiredEnv("GITHUB_DISPATCH_TOKEN");
  const owner = process.env.GITHUB_REPO_OWNER?.trim() || "jasonnkh1991";
  const repo = process.env.GITHUB_REPO_NAME?.trim() || "AI_Scraper";
  const workflowId = process.env.GITHUB_WORKFLOW_ID?.trim() || "monitor.yml";
  const ref = process.env.GITHUB_WORKFLOW_REF?.trim() || "main";

  const payload: DispatchPayload = {
    ref,
    inputs: {
      self_test: "false",
    },
  };

  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${githubToken}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GitHub dispatch failed: ${response.status} ${detail}`);
  }
}

export async function GET(request: NextRequest) {
  const cronSecret = getRequiredEnv("CRON_SECRET");
  const token = getBearerToken(request) || request.nextUrl.searchParams.get("token")?.trim();

  if (token !== cronSecret) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    await dispatchWorkflow();

    return NextResponse.json({
      ok: true,
      dispatched: true,
      workflow: process.env.GITHUB_WORKFLOW_ID?.trim() || "monitor.yml",
      ref: process.env.GITHUB_WORKFLOW_REF?.trim() || "main",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";

    return NextResponse.json({ error: message }, { status: 500 });
  }
}
