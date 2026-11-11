import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type TextBlock = { type: "text"; text: string };

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "write_candidate",
    label: "Write candidate file",
    description:
      "Save the complete improved file for this task. Call once with the full file content.",
    promptSnippet: "Save the improved file with write_candidate",
    promptGuidelines: [
      "Use write_candidate to save the improved file. Never write any other path.",
    ],
    parameters: Type.Object({
      content: Type.String({ description: "Content to write to the file" }),
    }),
    reachesTools: () => "all",
    prepareLoadout: () => ({ hiddenDeclarations: ["write"] }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const fixed = process.env.AUTORESEARCH_CANDIDATE ?? "";
      const nested = (await ctx.executeTool(
        "write",
        { path: fixed, content: String(params.content ?? "") },
        { signal },
      )) as unknown as { result?: { content?: TextBlock[] }; content?: TextBlock[] };
      return { content: nested.result?.content ?? nested.content ?? [], details: {} };
    },
  });
}
