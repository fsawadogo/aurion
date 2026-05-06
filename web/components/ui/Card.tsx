import { ReactNode } from "react";

interface CardProps {
  title?: string;
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
  hoverable?: boolean;
}

export default function Card({
  title,
  children,
  className = "",
  noPadding = false,
  hoverable = false,
}: CardProps) {
  return (
    <div
      className={`
        rounded-xl border border-gray-100 bg-white shadow-card
        ${hoverable ? "transition-shadow duration-200 hover:shadow-card-hover" : ""}
        ${className}
      `}
    >
      {title && (
        <div className="border-b border-gray-100 px-6 py-4">
          <h3 className="text-sm font-semibold text-navy-700">{title}</h3>
        </div>
      )}
      {noPadding ? children : <div className="p-6">{children}</div>}
    </div>
  );
}
