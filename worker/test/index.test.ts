import { describe, expect, it } from "vitest";
import app from "../src/index";

describe("health", () => {
  it("returns the service name", async () => {
    const response = await app.request("http://example.test/health");
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ service: "radio-epg" });
  });
});
