import TemplateDetailClient from "./TemplateDetailClient";

/**
 * Server shell for `/portal/templates/[id]` under `output: "export"`.
 * See `app/sessions/[id]/page.tsx` for the full rationale — same
 * `generateStaticParams` + Amplify SPA fallback pattern. The client
 * component already reads the ID via `useParams()`, so no prop
 * forwarding is needed.
 */

export const dynamicParams = false;

export async function generateStaticParams(): Promise<{ id: string }[]> {
  return [{ id: "_" }];
}

export default function PortalTemplateDetailPage() {
  return <TemplateDetailClient />;
}
