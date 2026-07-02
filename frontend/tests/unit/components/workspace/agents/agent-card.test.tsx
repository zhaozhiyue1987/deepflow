import userEvent from "@testing-library/user-event";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, rs } from "@rstest/core";

const mocks = rs.hoisted(() => ({
  deleteAgent: rs.fn(),
  enableAgentA2A: rs.fn(),
  disableAgentA2A: rs.fn(),
  rotateAgentA2A: rs.fn(),
  enableExternalA2A: rs.fn(),
  disableExternalA2A: rs.fn(),
  rotateExternalA2A: rs.fn(),
  writeTextToClipboard: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({
    push: rs.fn(),
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      agents: {
        chat: "Chat",
        delete: "Delete",
        deleteConfirm: "Delete this agent?",
        deleteSuccess: "Agent deleted",
      },
      common: {
        cancel: "Cancel",
        delete: "Delete",
        loading: "Loading",
      },
      clipboard: {
        copyToClipboard: "Copy to clipboard",
        failedToCopyToClipboard: "Failed to copy",
      },
    },
  }),
}));

rs.mock("@/core/agents", () => ({
  useDeleteAgent: () => ({
    isPending: false,
    mutateAsync: mocks.deleteAgent,
  }),
  useEnableAgentA2A: () => ({
    isPending: false,
    mutateAsync: mocks.enableAgentA2A,
  }),
  useDisableAgentA2A: () => ({
    isPending: false,
    mutateAsync: mocks.disableAgentA2A,
  }),
  useRotateAgentA2A: () => ({
    isPending: false,
    mutateAsync: mocks.rotateAgentA2A,
  }),
  useEnableExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: mocks.enableExternalA2A,
  }),
  useDisableExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: mocks.disableExternalA2A,
  }),
  useRotateExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: mocks.rotateExternalA2A,
  }),
}));

rs.mock("@/core/clipboard", () => ({
  writeTextToClipboard: mocks.writeTextToClipboard,
}));

rs.mock("sonner", () => ({
  toast: {
    success: rs.fn(),
    error: rs.fn(),
  },
}));

import { AgentCard } from "@/components/workspace/agents/agent-card";
import type { Agent } from "@/core/agents";

beforeEach(() => {
  mocks.deleteAgent.mockReset();
  mocks.enableAgentA2A.mockReset();
  mocks.disableAgentA2A.mockReset();
  mocks.rotateAgentA2A.mockReset();
  mocks.enableExternalA2A.mockReset();
  mocks.disableExternalA2A.mockReset();
  mocks.rotateExternalA2A.mockReset();
  mocks.writeTextToClipboard.mockReset();
  mocks.writeTextToClipboard.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
});

describe("AgentCard A2A visualization", () => {
  test("renders an external A2A agent with source, health, and gateway URLs", () => {
    render(
      <AgentCard
        agent={
          {
            name: "vendor_writer",
            description: "External writing agent",
            model: null,
            tool_groups: null,
            skills: null,
            source: "external",
            enabled: true,
            health_status: "healthy",
            card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
            task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
          } as Agent
        }
      />,
    );

    expect(screen.getByText("vendor_writer")).toBeTruthy();
    expect(screen.getByText("External")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(
      screen.getByText("http://localhost/api/a2a/agents/vendor_writer/card"),
    ).toBeTruthy();
    expect(
      screen.getByText("http://localhost/api/a2a/agents/vendor_writer/tasks"),
    ).toBeTruthy();
  });

  test("enables native A2A publication and shows one-time token with copy actions", async () => {
    const user = userEvent.setup();
    mocks.enableAgentA2A.mockResolvedValueOnce({
      enabled: true,
      agent_name: "native-researcher",
      source: "native",
      registry_url: "http://localhost/api/a2a/registry",
      card_url: "http://localhost/api/a2a/agents/native-researcher/card",
      task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
      token_prefix: "a2a_native",
      token: "a2a_native_secret",
    });

    render(
      <AgentCard
        agent={
          {
            name: "native-researcher",
            description: "Native research agent",
            model: "kimi-k2.6",
            tool_groups: null,
            skills: null,
            source: "native",
            enabled: false,
          } as Agent
        }
      />,
    );

    await user.click(screen.getByRole("button", { name: "Enable A2A" }));

    await waitFor(() => {
      expect(mocks.enableAgentA2A).toHaveBeenCalledWith("native-researcher");
    });
    expect(screen.getByText("a2a_native_secret")).toBeTruthy();
    expect(
      screen.getByText("http://localhost/api/a2a/agents/native-researcher/card"),
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Copy A2A token" }));
    expect(mocks.writeTextToClipboard).toHaveBeenCalledWith(
      "a2a_native_secret",
    );
  });

  test("rotates and disables an enabled native A2A publication", async () => {
    const user = userEvent.setup();
    mocks.rotateAgentA2A.mockResolvedValueOnce({
      enabled: true,
      agent_name: "native-researcher",
      source: "native",
      registry_url: "http://localhost/api/a2a/registry",
      card_url: "http://localhost/api/a2a/agents/native-researcher/card",
      task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
      token_prefix: "a2a_rotated",
      token: "a2a_rotated_secret",
    });
    mocks.disableAgentA2A.mockResolvedValueOnce({
      enabled: false,
      agent_name: "native-researcher",
      source: "native",
      registry_url: "http://localhost/api/a2a/registry",
      card_url: "http://localhost/api/a2a/agents/native-researcher/card",
      task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
      token_prefix: null,
      token: null,
    });

    render(
      <AgentCard
        agent={
          {
            name: "native-researcher",
            description: "Native research agent",
            model: "kimi-k2.6",
            tool_groups: null,
            skills: null,
            source: "native",
            enabled: true,
            card_url: "http://localhost/api/a2a/agents/native-researcher/card",
            task_url: "http://localhost/api/a2a/agents/native-researcher/tasks",
            token_prefix: "a2a_native",
          } as Agent
        }
      />,
    );

    await user.click(screen.getByRole("button", { name: "Rotate A2A token" }));
    await waitFor(() => {
      expect(mocks.rotateAgentA2A).toHaveBeenCalledWith("native-researcher");
    });
    expect(screen.getByText("a2a_rotated_secret")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Disable A2A" }));
    await waitFor(() => {
      expect(mocks.disableAgentA2A).toHaveBeenCalledWith("native-researcher");
    });
    expect(screen.getByRole("button", { name: "Enable A2A" })).toBeTruthy();
  });

  test("uses external A2A operations for external agents", async () => {
    const user = userEvent.setup();
    mocks.rotateExternalA2A.mockResolvedValueOnce({
      name: "vendor_writer",
      source: "external",
      display_name: "Vendor Writer",
      description: "External writing agent",
      enabled: true,
      health_status: "healthy",
      card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
      task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
      upstream_card_fetched_at: "2026-06-30T05:00:00Z",
      token_prefix: "a2a_rotated",
      token: "a2a_external_secret",
    });
    mocks.disableExternalA2A.mockResolvedValueOnce({
      name: "vendor_writer",
      source: "external",
      display_name: "Vendor Writer",
      description: "External writing agent",
      enabled: false,
      health_status: "healthy",
      card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
      task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
      upstream_card_fetched_at: "2026-06-30T05:00:00Z",
      token_prefix: null,
      token: null,
    });

    render(
      <AgentCard
        agent={
          {
            name: "vendor_writer",
            description: "External writing agent",
            model: null,
            tool_groups: null,
            skills: null,
            source: "external",
            enabled: true,
            health_status: "healthy",
            card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
            task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
            token_prefix: "a2a_external",
          } as Agent
        }
      />,
    );

    await user.click(screen.getByRole("button", { name: "Rotate A2A token" }));
    await waitFor(() => {
      expect(mocks.rotateExternalA2A).toHaveBeenCalledWith("vendor_writer");
    });
    expect(screen.getByText("a2a_external_secret")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Disable A2A" }));
    await waitFor(() => {
      expect(mocks.disableExternalA2A).toHaveBeenCalledWith("vendor_writer");
    });
  });
});
