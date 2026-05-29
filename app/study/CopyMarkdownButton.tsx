"use client";

import { useState } from "react";

type CopyMarkdownButtonProps = {
  value: string;
};

export function CopyMarkdownButton({ value }: CopyMarkdownButtonProps) {
  const [copied, setCopied] = useState(false);

  async function copyMarkdown() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <button
      className="h-9 border border-violet-500/50 bg-violet-950/40 px-3 font-mono text-xs text-violet-100 transition-colors hover:bg-violet-900/50"
      type="button"
      onClick={copyMarkdown}
    >
      {copied ? "Copied" : "Copy Markdown"}
    </button>
  );
}
