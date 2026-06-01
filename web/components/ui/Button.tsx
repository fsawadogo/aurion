import { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * Aurion button primitive.
 *
 * Four variants × three sizes. The primary variant carries the
 * canonical gold drop shadow + hover-lift that mirrors the iOS
 * primary CTA on Theme.swift — that combo is the visual anchor of
 * the brand on the web.
 *
 * Loading state masks the label with a spinner inline; disabled state
 * dampens contrast without dropping the entire affordance (so it's
 * still obvious WHAT the button would do). The focus-visible ring
 * matches the global `:focus-visible` token (gold w/ halo).
 */

const variantStyles = {
  primary:
    "bg-gold-500 text-navy-800 shadow-gold " +
    "hover:bg-gold-400 hover:shadow-gold-strong hover:-translate-y-px " +
    "active:bg-gold-600 active:translate-y-0 active:shadow-gold " +
    "disabled:bg-gold-200 disabled:text-navy-400 disabled:shadow-none disabled:transform-none",
  secondary:
    "border border-hairline bg-white text-navy-700 shadow-card " +
    "hover:bg-canvas hover:border-navy-200 hover:shadow-card-hover " +
    "active:bg-muted " +
    "disabled:bg-white disabled:text-navy-300 disabled:border-hairline disabled:shadow-none",
  destructive:
    "bg-accent-red text-white shadow-card " +
    "hover:bg-red-500 hover:shadow-card-hover " +
    "active:bg-red-700 " +
    "disabled:bg-red-200 disabled:shadow-none",
  ghost:
    "text-navy-600 " +
    "hover:bg-canvas hover:text-navy-800 " +
    "active:bg-muted " +
    "disabled:text-navy-300",
};

const sizeStyles = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-[14px]",
  lg: "h-12 px-6 text-[15px]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "destructive" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  fullWidth?: boolean;
  children: ReactNode;
}

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  fullWidth = false,
  disabled,
  children,
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={
        "inline-flex items-center justify-center gap-1.5 rounded-aurion-md font-semibold " +
        "tracking-tight transition-all duration-short ease-aurion " +
        "focus:outline-none disabled:cursor-not-allowed " +
        variantStyles[variant] + " " +
        sizeStyles[size] + " " +
        (fullWidth ? "w-full " : "") +
        className
      }
      {...props}
    >
      {loading && (
        <svg
          className="-ml-0.5 h-4 w-4 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="3"
          />
          <path
            className="opacity-90"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v3.5A4.5 4.5 0 007.5 12H4z"
          />
        </svg>
      )}
      {children}
    </button>
  );
}
