import { redirect } from "next/navigation";

/**
 * Bare `/portal` lands on the profile page until PR-F ships the
 * proper dashboard. Keeping a redirect (not a 404) so anyone who
 * bookmarks `/portal` stays inside the portal surface.
 */
export default function PortalIndex() {
  redirect("/portal/profile");
}
