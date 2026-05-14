import { AxiosError } from "axios";

export const getApiErrorMessage = (error: unknown, fallback: string) => {
    if (error instanceof AxiosError) {
        const data = error.response?.data as { detail?: string } | undefined;
        return data?.detail || fallback;
    }
    return fallback;
};
