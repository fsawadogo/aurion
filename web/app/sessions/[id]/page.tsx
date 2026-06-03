import SessionDetailClient from "./SessionDetailClient";

/**
 * Server shell for `/sessions/[id]` under `output: "export"`.
 *
 * Next.js static export requires every dynamic route to declare
 * which params to pre-render via `generateStaticParams`. We don't
 * know session IDs at build time — they're issued at runtime when
 * a physician finishes a recording — so we return `[]` here and
 * rely on the Amplify SPA-fallback rewrite (configured in
 * `infrastructure/amplify.tf`'s `custom_rules`) to serve
 * `index.html` for any unknown path. The client component then
 * reads the ID from `useParams()` and fetches normally.
 *
 * `dynamicParams = false` belts-and-braces — keeps the build from
 * ever attempting to render an unknown ID server-side, which would
 * fail under static export.
 */

// `_` is a placeholder ID — Next.js requires `generateStaticParams`
// to return at least one entry under `output: "export"`. The
// generated `/sessions/_/index.html` is never linked from anywhere;
// Amplify's SPA-fallback rewrite catches real visits to
// `/sessions/<real-id>` and serves that same shell, the client
// component then reads the real ID from `useParams()` and fetches
// normally.
export const dynamicParams = false;

export async function generateStaticParams(): Promise<{ id: string }[]> {
  return [{ id: "_" }];
}

export default function SessionDetailPage({
  params,
}: {
  params: { id: string };
}) {
  return <SessionDetailClient params={params} />;
}
