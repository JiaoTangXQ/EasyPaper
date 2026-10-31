import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type SwitchProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
};

export function Switch({ checked, onCheckedChange, className, ...props }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={cn("settings-switch", checked && "is-checked", className)}
      onClick={() => onCheckedChange(!checked)}
      {...props}
    >
      <span className="settings-switch-thumb" />
    </button>
  );
}
