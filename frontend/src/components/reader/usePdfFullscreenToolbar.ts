import { useEffect, useRef } from "react";

// The SDK renders its toolbars in a shadow root. Keep this small adapter at the
// viewer boundary; use its named UI items rather than its generated classes.
const toolbarStyle = `
:host([data-reader-fullscreen]) [data-reader-toolbar] {
  position: absolute; left: 0; right: 0;
  top: calc(var(--reader-chrome-height, 0px) + var(--reader-toolbar-offset, 0px));
  z-index: 40;
  transform: var(--reader-chrome-transform, translateY(0));
  transition: transform var(--reader-chrome-duration, 260ms) cubic-bezier(.16,1,.3,1);
  pointer-events: var(--reader-chrome-pointer-events, auto);
}
@media (prefers-reduced-motion: reduce) {
  :host([data-reader-fullscreen]) [data-reader-toolbar] { transition: none; }
}`;

export function usePdfFullscreenToolbar(
  container: HTMLElement | null,
  fullscreen: boolean,
  visible: boolean,
  onHeight?: (height: number) => void,
) {
  const state = useRef({ fullscreen, visible, onHeight });
  const update = useRef<() => void>();

  useEffect(() => {
    const shadow = container?.shadowRoot;
    if (!container || !shadow) return;
    const style = document.createElement("style");
    style.textContent = toolbarStyle;
    shadow.append(style);
    let bars: HTMLElement[] = [];
    const measure = () => {
      let offset = 0;
      for (const bar of bars) {
        bar.style.setProperty("--reader-toolbar-offset", `${offset}px`);
        bar.toggleAttribute("inert", state.current.fullscreen && !state.current.visible);
        offset += bar.getBoundingClientRect().height;
      }
      state.current.onHeight?.(offset);
    };
    const resize = new ResizeObserver(measure);
    let shell: Element | null = null;
    const discover = () => {
      const root = shadow.querySelector("[data-epdf]");
      if (root && root !== shell) {
        shell = root;
        observer.disconnect();
        observer.observe(root, { childList: true });
      }
      const found = [...shadow.querySelectorAll<HTMLElement>('[data-epdf] > [data-epdf-i$="-toolbar"]')];
      if (found.length === bars.length && found.every((bar, i) => bar === bars[i])) return;
      resize.disconnect();
      bars = found;
      for (const bar of bars) {
        bar.setAttribute("data-reader-toolbar", "");
        resize.observe(bar);
      }
      measure();
    };
    const observer = new MutationObserver(discover);
    observer.observe(shadow, { childList: true, subtree: true });
    update.current = measure;
    discover();
    return () => {
      observer.disconnect();
      resize.disconnect();
      style.remove();
      for (const bar of bars) {
        bar.removeAttribute("data-reader-toolbar");
        bar.removeAttribute("inert");
        bar.style.removeProperty("--reader-toolbar-offset");
      }
      update.current = undefined;
    };
  }, [container]);

  useEffect(() => {
    state.current = { fullscreen, visible, onHeight };
    container?.toggleAttribute("data-reader-fullscreen", fullscreen);
    update.current?.();
  }, [container, fullscreen, visible, onHeight]);
}
