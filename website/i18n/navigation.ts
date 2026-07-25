import { createNavigation } from "next-intl/navigation"

import { routing } from "./routing"

/** Use these instead of `next/link` for locale-aware internal navigation. */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing)
