import { describe, expect, it } from "vitest";
import app from "../src/index";

describe("health", () => {
  it("returns the service name", async () => {
    const response = await app.request("http://example.test/health");
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ service: "radio-epg" });
  });

  it("does not mount image APIs", async () => {
    const ingest = await app.request("http://example.test/v1/admin/images", { method: "POST" });
    const takedown = await app.request("http://example.test/v1/admin/takedown", { method: "POST" });
    const publicImage = await app.request("http://example.test/v1/images/missing/medium");

    expect(ingest.status).toBe(404);
    expect(takedown.status).toBe(404);
    expect(publicImage.status).toBe(404);
  });
});
