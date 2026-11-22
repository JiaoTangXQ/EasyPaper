export type ConfirmRequest = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};
export type PendingConfirm = ConfirmRequest & { resolve: (ok: boolean) => void };

let show: ((request: PendingConfirm) => void) | null = null;

/** Called by the mounted ConfirmHost to receive requests. */
export function registerConfirmHost(handler: ((request: PendingConfirm) => void) | null) {
  show = handler;
}

/** Promise-based replacement for window.confirm that matches the app's dialogs. */
export function confirmAction(request: ConfirmRequest): Promise<boolean> {
  if (!show) return Promise.resolve(window.confirm(request.title));
  return new Promise((resolve) => show?.({ ...request, resolve }));
}
