import { ReactNode } from "react";

/**
 * Aurion card primitive.
 *
 * 16pt radius, 2-layer card shadow, optional hairline border for
 * surfaces that need a sharper edge against the canvas. Title slot
 * becomes a top-padded header with a hairline divider; pass JSX
 * (icon + text) for richer headings.
 */
interface CardProps {
  title?: ReactNode;
  /** Right-aligned slot in the card header, e.g. action button. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
  hoverable?: boolean;
}

export default function Card({
  title,
  action,
  children,
  className = "",
  noPadding = false,
  hoverable = false,
}: CardProps) {
  return (
    <div
      className={
        "aurion-card " +
        (hoverable ? "aurion-card-hoverable " : "") +
        className
      }
    >
      {title && (
        <div className="flex items-center gap-3 border-b border-hairline px-6 py-4">
          <div className="flex-1 text-aurion-headline">{title}</div>
          {action}
        </div>
      )}
      {noPadding ? children : <div className="p-6">{children}</div>}
    </div>
  );
}
