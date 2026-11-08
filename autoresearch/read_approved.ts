import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { realpath } from "node:fs/promises";
import { delimiter, sep } from "node:path";
import { Type } from "typebox";

type TextBlock = { type: "text"; text: string };

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "read_approved",
    label: "Read approved file",
    description:
      "Read a file approved for this task. Supports text and images with offset/limit paging. Reference only.",
    promptSnippet: "Read an approved reference file",
    promptGuidelines: [
      "Use read_approved to read reference files. Never read any other path.",
    ],
    parameters: Type.Object({
      path: Type.String(),
      offset: Type.Optional(Type.Number()),
      limit: Type.Optional(Type.Number()),
    }),
    reachesTools: () => "all",
    prepareLoadout: () => ({ hiddenDeclarations: ["read"] }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const arg = String(params.path ?? "").replace(/^@/, "");
      const roots = (process.env.AUTORESEARCH_READ_PATHS ?? "")
        .split(delimiter)
        .filter(Boolean);
      let real: string;
      try {
        real = await realpath(arg);
      } catch {
        return { content: [{ type: "text", text: `Not found: ${arg}` }], details: {} };
      }
      if (!roots.some((r) => real === r || real.startsWith(r + sep))) {
        return {
          content: [{ type: "text", text: `Not approved: ${arg}` }],
          details: {},
        };
      }
      const nested = (await ctx.executeTool(
        "read",
        { path: real, offset: params.offset, limit: params.limit },
        { signal },
      )) as unknown as { result?: { content?: TextBlock[] }; content?: TextBlock[] };
      const content = nested.result?.content ?? nested.content;
      if (!content) {
        return {
          content: [{ type: "text", text: `Read failed for approved file: ${arg}` }],
          details: {},
        };
      }
      return { content, details: {} };
    },
  });
}
