import { useEffect, useState } from "react";
import api from "./api";

// Fail closed while loading or if the server cannot be reached.
export function useFeatures() {
    const [features, setFeatures] = useState({ registration: false, local_sync: false, ai_available: false, max_upload_mb: 15, max_pages: 150 });
    useEffect(() => {
        let active = true;
        api.get("/api/auth/features").then(({ data }) => {
            if (active) setFeatures(data);
        }).catch(() => {});
        return () => { active = false; };
    }, []);
    return features;
}
