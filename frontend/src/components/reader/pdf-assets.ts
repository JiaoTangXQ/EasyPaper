import wasmUrl from "@embedpdf/pdfium/pdfium.wasm?url";

/** Absolute URL of the PDF engine. Shared so the reader can start fetching it early. */
export const PDFIUM_WASM_URL = new URL(wasmUrl, window.location.href).href;

let warmed = false;
/**
 * Start downloading the viewer code while the paper itself downloads, instead of
 * only after the PDF has arrived. The engine binary is not prefetched here: the
 * viewer fetches it from a worker, which would not reuse an in-flight request and
 * would download 2.3 MB twice. With immutable caching it downloads once per browser.
 */
export function warmPdfViewer() {
  if (warmed) return;
  warmed = true;
  void import("./PdfViewer").catch(() => {
    warmed = false;
  });
}
