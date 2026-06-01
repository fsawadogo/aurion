import { redirect } from "next/navigation";

/**
 * Bare `/portal` lands on the dashboard. Bookmarks to `/portal` stay
 * inside the portal surface; the dashboard is the natural home page.
 */
export default function PortalIndex() {
  redirect("/portal/dashboard");
}
