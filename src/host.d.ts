/**
 * Minimal ambient shapes for the host packages that `src/index.ts` imports as
 * types only: `@deepseek-ai/cordis`, `@deepseek-ai/dsh-llm`, and
 * `@deepseek-ai/dsh-tools`.
 *
 * Every one of those imports is `import type`, so they are erased at compile
 * time and the emitted `lib/index.js` has no dependency on any of them — DSH
 * resolves the real modules at load time, and a filesystem-path install never
 * needs them on disk at all. These declarations exist so this package
 * typechecks standalone, without installing the host packages.
 *
 * They intentionally describe only what this plugin touches. If the real
 * packages are installed, an ambient declaration still wins resolution, so
 * keep these shapes structurally compatible with the upstream types
 * (`GenerateOptions` and `StreamChunk` mirror `@deepseek-ai/dsh-llm`'s
 * `lib/types/types.d.ts`).
 *
 * `@deepseek-ai/schemastery` is NOT declared here: it is a real runtime
 * dependency (package.json `dependencies`), imported by value for the `Config`
 * schema the DSH settings service renders its form from.
 */

declare module '@deepseek-ai/cordis' {
  export interface Context {
    logger: { warn(message: string): void }
    effect(dispose: () => Generator<unknown, void, unknown>, label?: string): void
    on(event: string, listener: (...args: never[]) => unknown): unknown
    /** LLM service; follows the provider/model the DSH profile configures. */
    llm: { stream(options: GenerateOptions): AsyncIterable<StreamChunk> }
  }
}

declare module '@deepseek-ai/dsh-tools' {
  export type PreToolDecision =
    | { kind: 'allow' }
    | { kind: 'ask'; reason?: string }
    | { kind: 'deny'; reason?: string }

  export interface ToolExecution {
    readonly name: string
    readonly arguments: unknown
    readonly agent?: {
      id?: unknown
      session?: {
        cwd?: unknown
        header?: { cwd?: unknown }
        /** Live provider/model route for the current request. */
        requestHeader?: () => { config?: { provider?: unknown; model?: unknown } } | undefined
      }
    }
  }
}

declare module '@deepseek-ai/dsh-llm' {
  export interface GenerateOptions {
    provider: string
    model: string
    system?: string
    messages: readonly {
      role: 'user'
      content: readonly { type: 'text'; text: string }[]
    }[]
    temperature?: number
    signal?: AbortSignal
  }

  /**
   * Mirrors `StreamChunk` in `@deepseek-ai/dsh-llm`'s `lib/types/types.d.ts`.
   * The exhaustive enumeration matters: a catch-all member would swallow the
   * `finish` narrowing in the judge loop.
   */
  export type StreamChunk =
    | { type: 'block-start'; index: number; blockType: string }
    | { type: 'text-delta'; index: number; text: string }
    | { type: 'reasoning-delta'; index: number; text: string }
    | { type: 'tool-call-delta'; index: number; id: string; name?: string; argumentsDelta: string }
    | { type: 'block-end'; index: number; block: unknown }
    | { type: 'usage'; usage: unknown }
    | {
      type: 'finish'
      reason:
        | { kind: 'stop' }
        | { kind: 'error'; failure: { code: string; message: string } }
        | { kind: 'aborted'; failure: { code: string; message: string } }
        | { kind: 'max-tokens' }
    }
}
