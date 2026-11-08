import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFile, realpath } from "node:fs/promises";
import { delimiter, sep } from "node:path";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "read_approved",
    label: "Read approved file",
    description: "Read a file approved for this task. Reference only.",
    promptSnippet: "Read an approved reference file",
    promptGuidelines: [
      "Use read_approved to read reference files. Never read any other path.",
    ],
    parameters: Type.Object({ path: Type.String() }),
    async execute(_toolCallId, params) {
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
      try {
        const text = await readFile(real, "utf8");
        return { content: [{ type: "text", text }], details: {} };
      } catch {
        return {
          content: [{ type: "text", text: `Cannot read: ${arg}` }],
          details: {},
        };
      }
    },
  });
}
