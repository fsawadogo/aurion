import AuditDetailClient from "./AuditDetailClient";

/**
 * Server shell for `/audit/[sessionId]` under `output: "export"`.
 * See `app/sessions/[id]/page.tsx` for the rationale — same
 * `generateStaticParams` + Amplify SPA fallback pattern.
 */

// `_` is a placeholder ID — Next.js requires `generateStaticParams`
// to return at least one entry under `output: "export"`. The
// generated `/audit/_/index.html` is never linked from anywhere;
// Amplify's SPA-fallback rewrite catches real visits to
// `/audit/<real-session-id>` and serves that same shell, the client
// component then reads the real ID from `useParams()` and fetches
// normally.
export const dynamicParams = false;

export async function generateStaticParams(): Promise<
  { sessionId: string }[]
> {
  return [{ sessionId: "_" }];
}

export default function AuditDetailPage({
  params,
}: {
  params: { sessionId: string };
}) {
  return <AuditDetailClient params={params} />;
}
