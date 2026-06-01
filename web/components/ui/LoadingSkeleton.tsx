/**
 * Aurion loading skeleton — shimmering bars with descending width
 * so the placeholder reads as a settled-into-place column rather
 * than a uniform block. Backed by the global `.aurion-shimmer`
 * keyframe utility for animation consistency.
 */
interface LoadingSkeletonProps {
  lines?: number;
  className?: string;
}

export default function LoadingSkeleton({
  lines = 3,
  className = "",
}: LoadingSkeletonProps) {
  return (
    <div className={"space-y-3 " + className}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-3.5 rounded-aurion-xs aurion-shimmer"
          style={{ width: `${92 - i * 9}%` }}
        />
      ))}
    </div>
  );
}
