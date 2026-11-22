import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import { cn } from "@/lib/utils";

/** A thin progress bar. Omit `value` for an indeterminate sweep. */
const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => {
  const indeterminate = value === undefined || value === null;
  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={indeterminate ? null : value}
      className={cn("ui-progress", indeterminate && "is-indeterminate", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        style={indeterminate ? undefined : { transform: `scaleX(${Math.max(0, Math.min(100, value)) / 100})` }}
      />
    </ProgressPrimitive.Root>
  );
});
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };
