import { useEffect, useLayoutEffect, useState } from "react";

function storageKey(scope: string) {
  return `easypaper:workspace:${localStorage.getItem("email") || "user"}:${scope}`;
}

export function useWorkspaceValue(scope: string, initial = "") {
  const key = storageKey(scope);
  const [value, setValue] = useState(() => {
    try {
      return sessionStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, value);
    } catch {
      /* Optional view memory. */
    }
  }, [key, value]);
  return [value, setValue] as const;
}

export function useWorkspaceScroll(scope: string, ready: boolean) {
  const key = storageKey(`${scope}:scroll`);
  useLayoutEffect(() => {
    if (!ready) return;
    let saved = 0;
    try {
      saved = Number(sessionStorage.getItem(key)) || 0;
    } catch {
      /* Optional view memory. */
    }
    const frame = requestAnimationFrame(() => window.scrollTo(0, saved));
    const remember = () => {
      try {
        sessionStorage.setItem(key, String(window.scrollY));
      } catch {
        /* Optional view memory. */
      }
    };
    window.addEventListener("scroll", remember, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      remember();
      window.removeEventListener("scroll", remember);
    };
  }, [key, ready]);
}
