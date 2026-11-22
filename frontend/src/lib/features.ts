import { useEffect, useState } from "react";
import api from "./api";

export type Features = {
  registration: boolean;
  local_sync: boolean;
  ai_available: boolean;
  max_upload_mb: number;
  max_pages: number;
  gloss_preparation_site: "server" | "remote_worker" | "user_choice";
  gloss_worker_configured: boolean;
  /** False until the server answered. Callers must not show "AI unavailable" before this. */
  loaded: boolean;
};

// Fail closed while loading or if the server cannot be reached.
const FALLBACK: Features = {
  registration: false,
  local_sync: false,
  ai_available: false,
  max_upload_mb: 15,
  max_pages: 150,
  gloss_preparation_site: "server",
  gloss_worker_configured: false,
  loaded: false,
};

let cached: Features | null = null;
let inflight: Promise<Features> | null = null;

function loadFeatures(): Promise<Features> {
  if (cached) return Promise.resolve(cached);
  if (!inflight) {
    inflight = api
      .get("/api/auth/features")
      .then(({ data }) => {
        const loaded: Features = { ...FALLBACK, ...data, loaded: true };
        cached = loaded;
        return loaded;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Server capabilities. Fetched once per page load and shared by every caller. */
export function useFeatures(): Features {
  const [features, setFeatures] = useState<Features>(() => cached ?? FALLBACK);
  useEffect(() => {
    let active = true;
    loadFeatures()
      .then((data) => {
        if (active) setFeatures(data);
      })
      .catch(() => {
        if (active) setFeatures({ ...FALLBACK, loaded: true });
      });
    return () => {
      active = false;
    };
  }, []);
  return features;
}

/** Test hook: forget the cached capabilities. */
export function resetFeaturesCache() {
  cached = null;
  inflight = null;
}
