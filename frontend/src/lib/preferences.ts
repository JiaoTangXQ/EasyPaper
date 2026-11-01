import { useEffect, useState } from "react";
import api from "@/lib/api";

export type GlossPreparationPreference = "server" | "remote_worker";

export type UserPreferences = {
  reading: {
    gloss: {
      auto_speak: boolean;
      preparation: GlossPreparationPreference;
    };
  };
  updated_at?: string | null;
  [key: string]: unknown;
};

export const DEFAULT_USER_PREFERENCES: UserPreferences = {
  reading: {
    gloss: {
      auto_speak: false,
      preparation: "server",
    },
  },
};

export function normalizeUserPreferences(value: unknown): UserPreferences {
  const source = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const reading =
    source.reading && typeof source.reading === "object" ? (source.reading as Record<string, unknown>) : {};
  const gloss = reading.gloss && typeof reading.gloss === "object" ? (reading.gloss as Record<string, unknown>) : {};
  return {
    ...source,
    reading: {
      ...reading,
      gloss: {
        ...gloss,
        auto_speak: typeof gloss.auto_speak === "boolean" ? gloss.auto_speak : false,
        preparation:
          gloss.preparation === "remote_worker" || gloss.preparation === "server"
            ? gloss.preparation
            : "server",
      },
    },
    updated_at: typeof source.updated_at === "string" ? source.updated_at : null,
  };
}

export function useUserPreferences() {
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_USER_PREFERENCES);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void api
      .get("/api/settings/preferences")
      .then(({ data }) => {
        if (!cancelled) setPreferences(normalizeUserPreferences(data));
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { preferences, setPreferences, loading };
}
