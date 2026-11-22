import type { NavigateFunction } from "react-router-dom";

export function currentEmail() {
  return localStorage.getItem("email") || "";
}

export function logout(navigate: NavigateFunction) {
  localStorage.removeItem("token");
  localStorage.removeItem("email");
  navigate("/login");
}

/** Broadcast that the paper list changed (import, delete, retry) so open views refresh. */
export const TASKS_CHANGED = "easypaper:tasks-changed";
export function announceTasksChanged() {
  window.dispatchEvent(new Event(TASKS_CHANGED));
}

/** Broadcast that review counts changed so the navigation badge refreshes. */
export const REVIEW_CHANGED = "easypaper:review-changed";
export function announceReviewChanged() {
  window.dispatchEvent(new Event(REVIEW_CHANGED));
}
