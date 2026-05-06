import { ReactNode } from "react";

const variantStyles = {
  success: "bg-emerald-50 text-emerald-700 ring-emerald-600/10",
  warning: "bg-amber-50 text-amber-700 ring-amber-600/10",
  error: "bg-red-50 text-red-700 ring-red-600/10",
  info: "bg-navy-50 text-navy-600 ring-navy-500/10",
  neutral: "bg-gray-50 text-gray-600 ring-gray-500/10",
};

interface BadgeProps {
  variant?: "success" | "warning" | "error" | "info" | "neutral";
  children: ReactNode;
  className?: string;
  dot?: boolean;
}

export default function Badge({
  variant = "neutral",
  children,
  className = "",
  dot = false,
}: BadgeProps) {
  const dotColors: Record<string, string> = {
    success: "bg-emerald-500",
    warning: "bg-amber-500",
    error: "bg-red-500",
    info: "bg-navy-400",
    neutral: "bg-gray-400",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${variantStyles[variant]} ${className}`}
    >
      {dot && (
        <span className={`h-1.5 w-1.5 rounded-full ${dotColors[variant]}`} />
      )}
      {children}
    </span>
  );
}
