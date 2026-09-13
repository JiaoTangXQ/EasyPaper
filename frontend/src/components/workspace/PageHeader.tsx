import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
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
}: {
  title: string;
  description?: string;
  children?: ReactNode;
  error?: boolean;
}) {
  return (
    <div className="workspace-empty" role={error ? "alert" : undefined}>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {children && <div className="empty-actions">{children}</div>}
    </div>
  );
}
