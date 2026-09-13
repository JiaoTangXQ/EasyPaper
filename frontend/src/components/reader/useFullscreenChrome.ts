import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export function useFullscreenChrome(workspace: RefObject<HTMLElement>, fullscreen: boolean) {
  const headerRef = useRef<HTMLDivElement | null>(null);
  const [header, setHeader] = useState<HTMLDivElement | null>(null);
  const chromeRef = useCallback((node: HTMLDivElement | null) => {
    headerRef.current = node;
    setHeader(node);
  }, []);
  const [visible, setVisible] = useState(true);
  const [headerHeight, setHeaderHeight] = useState(0);
  const [toolbarHeight, setToolbarHeight] = useState(0);
  const timer = useRef<number>();
  const menuOpen = useRef(false);
  const showing = useRef(true);

  const cancelHide = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);
  const reveal = useCallback(() => {
    cancelHide();
    showing.current = true;
    setVisible(true);
  }, [cancelHide]);
  const scheduleHide = useCallback((delay = 650) => {
    if (!fullscreen || timer.current !== undefined || menuOpen.current) return;
    timer.current = window.setTimeout(() => {
      timer.current = undefined;
      let focused = document.activeElement;
      while (focused?.shadowRoot?.activeElement) focused = focused.shadowRoot.activeElement;
      const inToolbar = focused && (headerRef.current?.contains(focused) || focused.closest("[data-reader-toolbar]"));
      if (menuOpen.current || (inToolbar && focused?.matches(":focus-visible, input, textarea, select"))) return;
      showing.current = false;
      setVisible(false);
    }, delay);
  }, [fullscreen]);
  const holdForMenu = useCallback((open: boolean) => {
    menuOpen.current = open;
    if (open) reveal();
    else scheduleHide();
  }, [reveal, scheduleHide]);

  useEffect(() => {
    if (!header) return;
    const resize = new ResizeObserver(() => setHeaderHeight(header.getBoundingClientRect().height));
    resize.observe(header);
    return () => resize.disconnect();
  }, [header]);

  useEffect(() => {
    header?.toggleAttribute("inert", fullscreen && !visible);
  }, [header, fullscreen, visible]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      reveal();
      if (fullscreen) scheduleHide(1400);
    });
    return () => { cancelAnimationFrame(frame); cancelHide(); };
  }, [fullscreen, reveal, scheduleHide, cancelHide]);

  useEffect(() => {
    const root = workspace.current;
    if (!fullscreen || !root) return;
    const move = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const y = event.clientY - root.getBoundingClientRect().top;
      if (y <= (showing.current ? headerHeight + toolbarHeight : 14)) reveal();
      else scheduleHide();
    };
    const down = (event: PointerEvent) => {
      if (event.clientY - root.getBoundingClientRect().top > headerHeight + toolbarHeight) scheduleHide(250);
    };
    const focus = (event: FocusEvent) => {
      const target = event.composedPath()[0];
      if (target instanceof Element && (headerRef.current?.contains(target) || target.closest("[data-reader-toolbar]"))) reveal();
      else scheduleHide();
    };
    const leave = () => scheduleHide();
    root.addEventListener("pointermove", move);
    root.addEventListener("pointerdown", down);
    root.addEventListener("pointerleave", leave);
    root.addEventListener("focusin", focus);
    return () => {
      root.removeEventListener("pointermove", move);
      root.removeEventListener("pointerdown", down);
      root.removeEventListener("pointerleave", leave);
      root.removeEventListener("focusin", focus);
    };
  }, [fullscreen, headerHeight, toolbarHeight, reveal, scheduleHide, workspace]);

  return { chromeRef, visible, headerHeight, toolbarHeight, setToolbarHeight, reveal, holdForMenu };
}
