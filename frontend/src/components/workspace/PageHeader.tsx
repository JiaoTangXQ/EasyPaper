import type { ReactNode } from "react";
import { AlertCircle, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="page-heading ep-enter">
      <div className="page-heading-copy">
        {eyebrow && <span className="page-heading-eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-heading-actions">{actions}</div>}
    </header>
  );
}

export function EmptyState({
  title,
  description,
  children,
  error = false,
  icon,
  className,
}: {
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  error?: boolean;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("empty-state ep-enter", error && "is-error", className)} role={error ? "alert" : undefined}>
      <div className="empty-state-icon" aria-hidden="true">
        {icon ?? (error ? <AlertCircle /> : <Inbox />)}
      </div>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {children && <div className="empty-actions">{children}</div>}
    </div>
  );
}

/** Placeholder rows shown while a list loads, sized like the real rows. */
export function ListSkeleton({ rows = 3, label = "正在加载…" }: { rows?: number; label?: string }) {
  return (
    <div className="paper-list" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => (
        <div className="paper-row" key={index} aria-hidden="true">
          <span className="skeleton" style={{ width: 40, height: 40, borderRadius: 11 }} />
          <div className="paper-row-text" style={{ gap: 8 }}>
            <span className="skeleton" style={{ width: `${70 - index * 12}%`, height: 14 }} />
            <span className="skeleton" style={{ width: `${44 - index * 6}%`, height: 11 }} />
          </div>
        </div>
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}
