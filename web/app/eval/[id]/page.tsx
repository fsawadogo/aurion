import EvalDetailClient from "./EvalDetailClient";

/**
 * Server shell for `/eval/[id]` under `output: "export"`.
 * See `app/sessions/[id]/page.tsx` for the rationale — same
 * `generateStaticParams` + Amplify SPA fallback pattern.
 */

// `_` is a placeholder ID — Next.js requires `generateStaticParams`
// to return at least one entry under `output: "export"`. The
// generated `/eval/_/index.html` is never linked from anywhere;
// Amplify's SPA-fallback rewrite catches real visits to
// `/eval/<real-id>` and serves that same shell, the client component
// then reads the real ID from `useParams()` and fetches normally.
export const dynamicParams = false;

export async function generateStaticParams(): Promise<{ id: string }[]> {
  return [{ id: "_" }];
}

export default function EvalDetailPage({
  params,
}: {
  params: { id: string };
}) {
  return <EvalDetailClient params={params} />;
}
