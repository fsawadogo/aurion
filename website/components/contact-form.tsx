"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useTranslations } from "next-intl"
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SITE } from "@/lib/site"

const REASONS = ["demo", "pilot", "partnership", "general"] as const

type FormValues = z.infer<ReturnType<typeof buildSchema>>

function buildSchema(t: (key: string) => string) {
  return z.object({
    name: z.string().trim().min(1, { message: t("validation.required") }),
    email: z
      .string()
      .trim()
      .min(1, { message: t("validation.required") })
      .email({ message: t("validation.email") }),
    reason: z.enum(REASONS, { message: t("validation.reason") }),
    // Free-text specialty/organization is optional — a partner or general
    // enquiry won't have one.
    specialty: z.string().trim().optional(),
  })
}

export function ContactForm() {
  const t = useTranslations("contact")
  const schema = useMemo(() => buildSchema(t), [t])
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle")
  const [serverMsg, setServerMsg] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", reason: undefined, specialty: "" },
  })

  async function onSubmit(values: FormValues) {
    setStatus("idle")
    setServerMsg(null)

    try {
      // Static site — submissions go straight to the PeriTwin backend's
      // public waitlist endpoint (stored in Postgres, no PII logged).
      const res = await fetch(`${SITE.apiBaseUrl}/api/v1/public/waitlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: values.name,
          email: values.email,
          reason: values.reason,
          specialty: values.specialty || null,
        }),
      })
      if (res.status === 503) {
        setStatus("error")
        setServerMsg(t("errorNotConfigured"))
        return
      }
      if (!res.ok) {
        setStatus("error")
        setServerMsg(t("error"))
        return
      }
      setStatus("success")
      form.reset()
    } catch {
      setStatus("error")
      setServerMsg(t("error"))
    }
  }

  if (status === "success") {
    return (
      <div className="rounded-lg border border-outline-variant/60 bg-surface-container/40 p-6 text-center">
        <p className="text-sm text-on-surface">{t("success")}</p>
      </div>
    )
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5" noValidate>
      <div className="space-y-2">
        <Label htmlFor="contact-name">{t("fields.name")}</Label>
        <Input
          id="contact-name"
          autoComplete="name"
          placeholder={t("placeholders.name")}
          aria-invalid={!!form.formState.errors.name}
          {...form.register("name")}
        />
        {form.formState.errors.name ? (
          <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
        ) : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-email">{t("fields.email")}</Label>
        <Input
          id="contact-email"
          type="email"
          autoComplete="email"
          placeholder={t("placeholders.email")}
          aria-invalid={!!form.formState.errors.email}
          {...form.register("email")}
        />
        {form.formState.errors.email ? (
          <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
        ) : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-reason">{t("fields.reason")}</Label>
        <select
          id="contact-reason"
          defaultValue=""
          aria-invalid={!!form.formState.errors.reason}
          className="border-input focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:border-destructive flex h-10 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
          {...form.register("reason")}
        >
          <option value="" disabled>
            {t("reasonOptions.placeholder")}
          </option>
          {REASONS.map((r) => (
            <option key={r} value={r}>
              {t(`reasonOptions.${r}`)}
            </option>
          ))}
        </select>
        {form.formState.errors.reason ? (
          <p className="text-xs text-destructive">{form.formState.errors.reason.message}</p>
        ) : null}
      </div>

      <div className="space-y-2">
        <Label htmlFor="contact-specialty">{t("fields.specialty")}</Label>
        <Input
          id="contact-specialty"
          autoComplete="organization-title"
          placeholder={t("placeholders.specialty")}
          {...form.register("specialty")}
        />
      </div>

      {status === "error" && serverMsg ? (
        <p className="text-sm text-destructive" role="alert">
          {serverMsg}
        </p>
      ) : null}

      <Button
        type="submit"
        disabled={form.formState.isSubmitting}
        className="h-auto w-full rounded-xl bg-primary px-unit-8 py-unit-4 text-[15.5px] font-semibold text-on-primary shadow-sm transition-all hover:bg-primary-container active:scale-[0.98] sm:w-auto sm:min-w-[200px]"
      >
        {form.formState.isSubmitting ? t("submitting") : t("submit")}
      </Button>
    </form>
  )
}
