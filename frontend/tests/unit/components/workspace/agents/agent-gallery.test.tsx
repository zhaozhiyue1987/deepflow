import userEvent from "@testing-library/user-event";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, rs } from "@rstest/core";

const mocks = rs.hoisted(() => ({
  createExternalA2AAgent: rs.fn(),
}));

const nativeAgent = {
  name: "native_researcher",
  description: "Native DeerFlow agent",
  model: "kimi-k2.6",
  tool_groups: null,
  skills: null,
};

const externalAgent = {
  name: "vendor_writer",
  source: "external",
  display_name: "Vendor Writer",
  description: "External writing agent",
  enabled: true,
  health_status: "healthy",
  card_url: "http://localhost/api/a2a/agents/vendor_writer/card",
  task_url: "http://localhost/api/a2a/agents/vendor_writer/tasks",
  upstream_card_fetched_at: "2026-06-30T05:00:00Z",
  token_prefix: "a2a_abcd123",
};

rs.mock("next/navigation", () => ({
  useRouter: () => ({
    push: rs.fn(),
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      agents: {
        title: "Agents",
        description: "Manage agents",
        newAgent: "New Agent",
        emptyTitle: "No agents",
        emptyDescription: "Create your first agent",
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
  useAgents: () => ({
    agents: [nativeAgent],
    isLoading: false,
  }),
  useExternalA2AAgents: () => ({
    agents: [externalAgent],
    isLoading: false,
  }),
  useDeleteAgent: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useCreateExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: mocks.createExternalA2AAgent,
  }),
  useEnableAgentA2A: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useDisableAgentA2A: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useRotateAgentA2A: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useEnableExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useDisableExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
  useRotateExternalA2AAgent: () => ({
    isPending: false,
    mutateAsync: rs.fn(),
  }),
}));

rs.mock("@/core/clipboard", () => ({
  writeTextToClipboard: rs.fn(),
}));

rs.mock("sonner", () => ({
  toast: {
    success: rs.fn(),
    error: rs.fn(),
  },
}));

import { AgentGallery } from "@/components/workspace/agents/agent-gallery";

beforeEach(() => {
  mocks.createExternalA2AAgent.mockReset();
  mocks.createExternalA2AAgent.mockResolvedValue({
    name: "vendor_reviewer",
    source: "external",
    display_name: "Vendor Reviewer",
    description: "Reviews work",
    enabled: false,
    health_status: "unknown",
    card_url: "http://localhost/api/a2a/agents/vendor_reviewer/card",
    task_url: "http://localhost/api/a2a/agents/vendor_reviewer/tasks",
    upstream_card_fetched_at: "2026-06-30T05:00:00Z",
    token_prefix: null,
  });
});

afterEach(() => {
  cleanup();
});

describe("AgentGallery A2A visualization", () => {
  test("renders native and external A2A agents in the same gallery", () => {
    render(<AgentGallery />);

    expect(screen.getByText("native_researcher")).toBeTruthy();
    expect(screen.getByText("vendor_writer")).toBeTruthy();
    expect(screen.getByText("External")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
  });

  test("registers an external A2A agent from the gallery dialog", async () => {
    const user = userEvent.setup();
    render(<AgentGallery />);

    await user.click(
      screen.getByRole("button", { name: "Register External A2A" }),
    );
    await user.type(screen.getByLabelText("Name"), "vendor_reviewer");
    await user.type(screen.getByLabelText("Display name"), "Vendor Reviewer");
    await user.type(screen.getByLabelText("Description"), "Reviews work");
    await user.type(
      screen.getByLabelText("Upstream Agent Card URL"),
      "https://vendor.example.com/.well-known/agent-card.json",
    );
    await user.selectOptions(screen.getByLabelText("Upstream auth type"), [
      "bearer",
    ]);
    await user.type(screen.getByLabelText("Upstream bearer token"), "secret");
    document.body.style.pointerEvents = "none";
    await user.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => {
      expect(mocks.createExternalA2AAgent).toHaveBeenCalledWith({
        name: "vendor_reviewer",
        display_name: "Vendor Reviewer",
        description: "Reviews work",
        upstream_card_url:
          "https://vendor.example.com/.well-known/agent-card.json",
        upstream_auth: {
          type: "bearer",
          token: "secret",
        },
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.body.style.pointerEvents).not.toBe("none");
    });
  });

  test("resets external registration dialog state after cancel", async () => {
    const user = userEvent.setup();
    render(<AgentGallery />);

    await user.click(
      screen.getByRole("button", { name: "Register External A2A" }),
    );
    await user.selectOptions(screen.getByLabelText("Upstream auth type"), [
      "bearer",
    ]);
    expect(screen.getByLabelText("Upstream bearer token")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    await user.click(
      screen.getByRole("button", { name: "Register External A2A" }),
    );

    expect(
      (screen.getByLabelText("Upstream auth type") as HTMLSelectElement).value,
    ).toBe("none");
    expect(screen.queryByLabelText("Upstream bearer token")).toBeNull();
  });
});
