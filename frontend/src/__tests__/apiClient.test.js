import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("antd", () => ({
  message: {
    error: vi.fn(),
  },
}));

import { message } from "antd";
import { apiClient } from "../api/client";

function jsonResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status || 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("fetch apiClient response contract", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it("unwraps LifeFlow success payloads for GET", async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ code: 0, message: "success", data: { answer: "ok" } }));

    await expect(apiClient.get("/api/rag/ask", { params: { top_k: 3 } })).resolves.toEqual({ answer: "ok" });
    expect(fetch.mock.calls[0][0]).toContain("top_k=3");
    expect(fetch.mock.calls[0][1].method).toBe("GET");
  });

  it("serializes JSON POST bodies", async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ code: 0, message: "success", data: { id: 1 } }));

    await expect(apiClient.post("/api/resources", { title: "Redis" })).resolves.toEqual({ id: 1 });
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toContain("application/json");
    expect(fetch.mock.calls[0][1].body).toBe('{"title":"Redis"}');
  });

  it("sends multipart upload without forcing Content-Type", async () => {
    const formData = new FormData();
    formData.append("file", new Blob(["hello"]), "note.txt");
    fetch.mockResolvedValueOnce(jsonResponse({ code: 0, message: "success", data: { id: 2 } }));

    await expect(apiClient.post("/api/imports/file", formData)).resolves.toEqual({ id: 2 });
    expect(fetch.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
    expect(fetch.mock.calls[0][1].body).toBe(formData);
  });

  it("rejects HTTP non-2xx responses", async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ message: "backend unavailable" }, { status: 503 }));

    await expect(apiClient.get("/health")).rejects.toMatchObject({http_status:503,error_code:'backend_unavailable'});
  });

  it("rejects LifeFlow business errors", async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ code: 1, message: "resource not found", data: null }));

    await expect(apiClient.get("/api/resources/999")).rejects.toMatchObject({http_status:200,error_code:'request_failed'});
  });

  it("rejects request timeouts", async () => {
    vi.useFakeTimers();
    fetch.mockImplementationOnce((_, init) => new Promise((_, reject) => {
      init.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
    }));

    const expectation = expect(apiClient.get("/slow", { timeout: 10 })).rejects.toMatchObject({error_code:'timeout'});
    await vi.advanceTimersByTimeAsync(11);

    await expectation;
  });

  it("rejects network errors", async () => {
    fetch.mockRejectedValueOnce(new Error("network down"));

    await expect(apiClient.get("/health")).rejects.toMatchObject({error_code:'network_error'});
  });
});
