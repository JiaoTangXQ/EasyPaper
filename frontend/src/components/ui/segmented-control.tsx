import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  hint?: ReactNode;
  ariaLabel?: string;
  title?: string;
  disabled?: boolean;
};

/**
 * iOS-style segmented control. A single thumb slides under the selected option;
 * options stay ordinary toggle buttons so keyboard and screen-reader behaviour is native.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = "md",
  className,
}: {
  options: SegmentedOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  ariaLabel: string;
  size?: "md" | "lg";
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; width: number } | null>(null);
  const [animate, setAnimate] = useState(false);

  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => {
      const active = element.querySelector<HTMLElement>(`[data-value="${CSS.escape(String(value))}"]`);
      setThumb(active ? { x: active.offsetLeft, width: active.offsetWidth } : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    // Enable the slide only after the first paint so the thumb does not fly in on mount.
    const frame = requestAnimationFrame(() => setAnimate(true));
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [value, options.length]);

  return (
    <div
      ref={root}
      role="group"
      aria-label={ariaLabel}
      className={cn("segmented", size === "lg" && "segmented--lg", className)}
    >
      <span
        aria-hidden="true"
        className="segmented-thumb"
        style={{
          width: thumb?.width ?? 0,
          transform: `translateX(${thumb?.x ?? 0}px)`,
          opacity: thumb ? 1 : 0,
          transition: animate ? undefined : "none",
        }}
      />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          data-value={option.value}
          className="segmented-option"
          aria-pressed={value === option.value}
          aria-label={option.ariaLabel}
          title={option.title}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
          {option.hint ? <span className="segmented-hint">{option.hint}</span> : null}
        </button>
      ))}
    </div>
  );
}
