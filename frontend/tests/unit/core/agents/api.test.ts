/**
 * Tests for the error-classification behaviour of `checkAgentName`.
 *
 * Issue #3041: when the backend returns a non-200 response (e.g. a 500 with
 * a database error, a 422 from misbehaving routing, or any other 4xx/5xx
 * not in the 502/503/504 set), the UI used to swallow the backend detail
 * into a generic "Could not verify name availability" fallback because the
 * page-level catch block only handled `reason === "backend_unreachable"`.
 *
 * The fix carries the raw backend detail as `AgentNameCheckError.detail`
 * (distinct from `message`, which always has a non-empty value because
 * `checkAgentName` substitutes a generated fallback when the backend sent
 * no detail). The UI uses `detail` to decide whether to surface a real
 * backend string or fall back to the localised "could not verify" copy.
 *
 * These tests pin both halves of the contract so a future refactor doesn't
 * silently drop the detail or leak the generated fallback into the UI.
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import {
  AgentsApiDisabledError,
  checkAgentName,
  createExternalA2AAgent,
  disableAgentA2A,
  disableExternalA2AAgent,
  enableAgentA2A,
  enableExternalA2AAgent,
  getA2AAgentCard,
  listExternalA2AAgents,
  rotateAgentA2A,
  rotateExternalA2AAgent,
} from "@/core/agents/api";
import { fetch as fetcher } from "@/core/api/fetcher";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("checkAgentName", () => {
  test("returns availability payload on 200", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { available: true, name: "dealagent" }),
    );
    const result = await checkAgentName("dealagent");
    expect(result).toEqual({ available: true, name: "dealagent" });
  });

  test("treats network-layer fetch rejection as backend_unreachable", async () => {
    mockedFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "backend_unreachable",
    });
  });

  test.each([502, 503, 504])(
    "treats HTTP %i as backend_unreachable",
    async (status) => {
      mockedFetch.mockResolvedValueOnce(
        jsonResponse(status, { detail: "Bad Gateway" }),
      );
      await expect(checkAgentName("dealagent")).rejects.toMatchObject({
        name: "AgentNameCheckError",
        reason: "backend_unreachable",
      });
    },
  );

  test("recognises agents_api disabled detail and throws AgentsApiDisabledError", async () => {
    const detail =
      "Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP.";
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail }));
    await expect(checkAgentName("dealagent")).rejects.toBeInstanceOf(
      AgentsApiDisabledError,
    );
  });

  test("carries backend 422 detail through AgentNameCheckError.detail (issue #3041)", async () => {
    // This is the exact response shape produced by `_validate_agent_name`
    // when the user submits a name with disallowed characters — e.g. a
    // trailing space, a dot, a Chinese character, or invisible whitespace
    // pasted in from another window.
    const detail =
      "Invalid agent name 'deal agent'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).";
    mockedFetch.mockResolvedValueOnce(jsonResponse(422, { detail }));

    await expect(checkAgentName("deal agent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      // The full detail is preserved on both `detail` (for the UI to
      // recognise "real backend detail vs generated fallback") and
      // `message` (for stack traces / logs).
      detail,
      message: detail,
    });
  });

  test("falls back to statusText in message but leaves detail null when backend returns no detail", async () => {
    // The fallback message must NOT mask the absence of a real backend
    // detail — the page-level catch relies on `detail === null` to choose
    // the localised generic fallback rather than rendering the bare
    // "Failed to check agent name: Internal Server Error" string.
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      detail: null,
      message: expect.stringContaining("Internal Server Error"),
    });
  });

  test("treats non-string detail as null (defence against future schema drift)", async () => {
    // If the backend ever returns `{detail: {code, message}}` (the shape
    // used by auth errors today) on this endpoint, we must not surface a
    // `[object Object]` string. `detail` should fall back to null so the
    // page uses its localised fallback.
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(500, { detail: { code: "x", message: "y" } }),
    );
    await expect(checkAgentName("dealagent")).rejects.toMatchObject({
      name: "AgentNameCheckError",
      reason: "request_failed",
      detail: null,
    });
  });

  test("does not misclassify a 422 with unrelated detail as agents_api disabled", async () => {
    // Defence-in-depth: the disabled detector matches on the substring
    // "agents_api.enabled", so a 422 whose detail accidentally contains
    // the same substring would be misclassified. The validation detail
    // produced by `_validate_agent_name` never contains it; this test
    // simply asserts that "Invalid agent name ..." stays in the
    // request_failed branch, which is where the page now surfaces it.
    const detail =
      "Invalid agent name 'deal.agent'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).";
    mockedFetch.mockResolvedValueOnce(jsonResponse(422, { detail }));
    await expect(checkAgentName("deal.agent")).rejects.not.toBeInstanceOf(
      AgentsApiDisabledError,
    );
  });
});

describe("external A2A agents api", () => {
  test("lists current user's registered external A2A agents from backend external_agents field", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        external_agents: [
          {
            name: "vendor_writer",
            source: "external",
            display_name: "Vendor Writer",
            description: "External writing agent",
            enabled: true,
            health_status: "healthy",
            card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
            task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
            upstream_card_fetched_at: "2026-06-30T05:00:00Z",
            token_prefix: "a2a_abcdef",
          },
        ],
      }),
    );

    await expect(listExternalA2AAgents()).resolves.toMatchObject([
      {
        name: "vendor_writer",
        source: "external",
        enabled: true,
        health_status: "healthy",
      },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith("/api/a2a/external-agents");
  });

  test("creates an external A2A agent registration with upstream auth body", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        name: "vendor_writer",
        source: "external",
        display_name: "Vendor Writer",
        description: "External writing agent",
        enabled: false,
        health_status: "unknown",
        card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
        task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
        upstream_card_fetched_at: "2026-06-30T05:00:00Z",
        token_prefix: null,
      }),
    );

    await createExternalA2AAgent({
      name: "vendor_writer",
      display_name: "Vendor Writer",
      description: "External writing agent",
      upstream_card_url: "https://vendor.example.com/.well-known/agent-card.json",
      upstream_auth: {
        type: "bearer",
        token: "upstream-secret",
      },
    });

    expect(mockedFetch).toHaveBeenCalledWith("/api/a2a/external-agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "vendor_writer",
        display_name: "Vendor Writer",
        description: "External writing agent",
        upstream_card_url:
          "https://vendor.example.com/.well-known/agent-card.json",
        upstream_auth: {
          type: "bearer",
          token: "upstream-secret",
        },
      }),
    });
  });

  test("enables gateway A2A publication and preserves one-time token response", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        name: "vendor_writer",
        source: "external",
        display_name: "Vendor Writer",
        description: "External writing agent",
        enabled: true,
        health_status: "unknown",
        card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
        task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
        upstream_card_fetched_at: "2026-06-30T05:00:00Z",
        token_prefix: "a2a_abcd123",
        token: "a2a_abcd123_secret",
      }),
    );

    await expect(enableExternalA2AAgent("vendor_writer")).resolves.toMatchObject({
      enabled: true,
      token_prefix: "a2a_abcd123",
      token: "a2a_abcd123_secret",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/a2a/external-agents/vendor_writer/a2a/enable",
      { method: "POST" },
    );
  });

  test("disables an external gateway A2A publication", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        name: "vendor_writer",
        source: "external",
        display_name: "Vendor Writer",
        description: "External writing agent",
        enabled: false,
        health_status: "unknown",
        card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
        task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
        upstream_card_fetched_at: "2026-06-30T05:00:00Z",
        token_prefix: null,
        token: null,
      }),
    );

    await expect(disableExternalA2AAgent("vendor_writer")).resolves.toMatchObject(
      {
        enabled: false,
        token_prefix: null,
      },
    );
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/a2a/external-agents/vendor_writer/a2a/disable",
      { method: "POST" },
    );
  });

  test("rotates an external gateway A2A publication token", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        name: "vendor_writer",
        source: "external",
        display_name: "Vendor Writer",
        description: "External writing agent",
        enabled: true,
        health_status: "unknown",
        card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
        task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
        upstream_card_fetched_at: "2026-06-30T05:00:00Z",
        token_prefix: "a2a_rotated",
        token: "a2a_rotated_secret",
      }),
    );

    await expect(rotateExternalA2AAgent("vendor_writer")).resolves.toMatchObject(
      {
        enabled: true,
        token_prefix: "a2a_rotated",
        token: "a2a_rotated_secret",
      },
    );
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/a2a/external-agents/vendor_writer/a2a/rotate",
      { method: "POST" },
    );
  });
});

describe("native agent A2A publication api", () => {
  test("enables a native agent A2A publication and returns one-time token", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        enabled: true,
        agent_name: "native-researcher",
        source: "native",
        registry_url: "http://localhost/api/a2a/registry",
        card_url: "http://localhost/api/a2a/agents/native-researcher/card",
        task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
        token_prefix: "a2a_native",
        token: "a2a_native_secret",
      }),
    );

    await expect(enableAgentA2A("native-researcher")).resolves.toMatchObject({
      enabled: true,
      agent_name: "native-researcher",
      source: "native",
      token: "a2a_native_secret",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/agents/native-researcher/a2a/enable",
      { method: "POST" },
    );
  });

  test("disables a native agent A2A publication", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        enabled: false,
        agent_name: "native-researcher",
        source: "native",
        registry_url: "http://localhost/api/a2a/registry",
        card_url: "http://localhost/api/a2a/agents/native-researcher/card",
        task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
        token_prefix: null,
        token: null,
      }),
    );

    await expect(disableAgentA2A("native-researcher")).resolves.toMatchObject({
      enabled: false,
      agent_name: "native-researcher",
      source: "native",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/agents/native-researcher/a2a/disable",
      { method: "POST" },
    );
  });

  test("rotates a native agent A2A publication token", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        enabled: true,
        agent_name: "native-researcher",
        source: "native",
        registry_url: "http://localhost/api/a2a/registry",
        card_url: "http://localhost/api/a2a/agents/native-researcher/card",
        task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
        token_prefix: "a2a_rotated",
        token: "a2a_rotated_secret",
      }),
    );

    await expect(rotateAgentA2A("native-researcher")).resolves.toMatchObject({
      enabled: true,
      token_prefix: "a2a_rotated",
      token: "a2a_rotated_secret",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/agents/native-researcher/a2a/rotate",
      { method: "POST" },
    );
  });
});

describe("A2A public protocol api", () => {
  test("loads a gateway-published Agent Card without duplicating /api", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        name: "vendor_writer",
        source: "external",
        description: "External writing agent",
        url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
        card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
        capabilities: {},
        defaultInputModes: ["text/plain"],
        defaultOutputModes: ["text/plain"],
      }),
    );

    await expect(getA2AAgentCard("vendor_writer")).resolves.toMatchObject({
      name: "vendor_writer",
      source: "external",
      url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/a2a/agents/vendor_writer/card",
    );
  });
});
