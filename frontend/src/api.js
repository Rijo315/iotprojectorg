
const DEFAULT_API_URL =
  import.meta.env.VITE_API_URL || "http://localhost:5000";

export function getApiUrl() {
  return (
    localStorage.getItem("workerMonitorApiUrl") || DEFAULT_API_URL
  ).replace(/\/+$/, "");
}

export function saveApiUrl(url) {
  const cleaned = url.trim().replace(/\/+$/, "");
  localStorage.setItem("workerMonitorApiUrl", cleaned);
  return cleaned;
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(`${getApiUrl()}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.error || `Server returned HTTP ${response.status}`
      );
    }

    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The backend request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  health: () => request("/api/health"),
  status: () => request("/api/status"),
  events: () => request("/api/events"),

  setSos: (active) =>
    request("/api/sos", {
      method: "POST",
      body: JSON.stringify({ active }),
    }),
};
