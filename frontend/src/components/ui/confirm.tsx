import { useEffect, useState } from "react";
import * as AlertDialog from "@radix-ui/react-dialog";
import { Button } from "./button";
import { registerConfirmHost, type PendingConfirm } from "@/lib/confirm";


/** Renders confirmation requests made through confirmAction(). Mount once near the root. */
export function ConfirmHost() {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  useEffect(() => {
    registerConfirmHost((request) =>
      setPending((current) => {
        current?.resolve(false);
        return request;
      }),
    );
    return () => registerConfirmHost(null);
  }, []);
  const close = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };
  return (
    <AlertDialog.Root open={Boolean(pending)} onOpenChange={(open) => !open && close(false)}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="ui-overlay" />
        <AlertDialog.Content className="ui-dialog confirm-dialog" role="alertdialog">
          <div className="ui-dialog-header">
            <AlertDialog.Title className="ui-dialog-title">{pending?.title}</AlertDialog.Title>
            {pending?.description ? (
              <AlertDialog.Description className="ui-dialog-description">{pending.description}</AlertDialog.Description>
            ) : (
              <AlertDialog.Description className="sr-only">请确认此操作</AlertDialog.Description>
            )}
          </div>
          <div className="ui-dialog-footer">
            <Button variant="secondary" onClick={() => close(false)}>
              {pending?.cancelLabel || "取消"}
            </Button>
            <Button variant={pending?.danger ? "destructive" : "default"} onClick={() => close(true)} autoFocus>
              {pending?.confirmLabel || "确定"}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
