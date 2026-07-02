import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  A2AAgentCard,
  Agent,
  AgentA2APublication,
  CreateAgentRequest,
  ExternalA2AAgent,
  ExternalA2AAgentCreateRequest,
  UpdateAgentRequest,
} from "./types";

const BACKEND_UNAVAILABLE_STATUSES = new Set([502, 503, 504]);

export class AgentNameCheckError extends Error {
  constructor(
    message: string,
    public readonly reason: "backend_unreachable" | "request_failed",
    /**
     * Raw backend `detail` string when the failure came from a backend
     * response carrying one. `null` when no detail was provided (e.g.
     * network-layer failure, empty response body, unparseable body) — in
     * which case `message` is a generated fallback like "Failed to check
     * agent name: Bad Gateway" and the UI should prefer its own localized
     * fallback instead of surfacing the generated string.
     */
    public readonly detail: string | null = null,
  ) {
    super(message);
    this.name = "AgentNameCheckError";
  }
}

export class AgentsApiDisabledError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentsApiDisabledError";
  }
}

function isAgentsApiDisabledDetail(detail: string | undefined): boolean {
  return typeof detail === "string" && detail.includes("agents_api.enabled");
}

export async function listAgents(): Promise<Agent[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`);
  if (!res.ok) throw new Error(`Failed to load agents: ${res.statusText}`);
  const data = (await res.json()) as { agents: Agent[] };
  return data.agents;
}

export async function getAgent(name: string): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`);
  if (!res.ok) throw new Error(`Agent '${name}' not found`);
  return res.json() as Promise<Agent>;
}

export async function createAgent(request: CreateAgentRequest): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledDetail(err.detail)) {
      throw new AgentsApiDisabledError(err.detail!);
    }
    throw new Error(err.detail ?? `Failed to create agent: ${res.statusText}`);
  }
  return res.json() as Promise<Agent>;
}

export async function updateAgent(
  name: string,
  request: UpdateAgentRequest,
): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to update agent: ${res.statusText}`);
  }
  return res.json() as Promise<Agent>;
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete agent: ${res.statusText}`);
}

export async function checkAgentName(
  name: string,
): Promise<{ available: boolean; name: string }> {
  let res: Response;
  try {
    res = await fetch(
      `${getBackendBaseURL()}/api/agents/check?name=${encodeURIComponent(name)}`,
    );
  } catch {
    throw new AgentNameCheckError(
      "Could not reach the DeerFlow backend.",
      "backend_unreachable",
    );
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledDetail(err.detail)) {
      throw new AgentsApiDisabledError(err.detail!);
    }
    if (BACKEND_UNAVAILABLE_STATUSES.has(res.status)) {
      throw new AgentNameCheckError(
        "Could not reach the DeerFlow backend.",
        "backend_unreachable",
      );
    }
    const backendDetail = typeof err.detail === "string" ? err.detail : null;
    throw new AgentNameCheckError(
      backendDetail ?? `Failed to check agent name: ${res.statusText}`,
      "request_failed",
      backendDetail,
    );
  }
  return res.json() as Promise<{ available: boolean; name: string }>;
}

export async function listExternalA2AAgents(): Promise<ExternalA2AAgent[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/a2a/external-agents`);
  if (!res.ok) {
    throw new Error(`Failed to load external A2A agents: ${res.statusText}`);
  }
  const data = (await res.json()) as { external_agents: ExternalA2AAgent[] };
  return data.external_agents;
}

export async function createExternalA2AAgent(
  request: ExternalA2AAgentCreateRequest,
): Promise<ExternalA2AAgent> {
  const res = await fetch(`${getBackendBaseURL()}/api/a2a/external-agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to create external A2A agent: ${res.statusText}`,
    );
  }
  return res.json() as Promise<ExternalA2AAgent>;
}

export async function enableExternalA2AAgent(
  name: string,
): Promise<ExternalA2AAgent> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/a2a/external-agents/${encodeURIComponent(name)}/a2a/enable`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to enable external A2A agent: ${res.statusText}`,
    );
  }
  return res.json() as Promise<ExternalA2AAgent>;
}

export async function disableExternalA2AAgent(
  name: string,
): Promise<ExternalA2AAgent> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/a2a/external-agents/${encodeURIComponent(name)}/a2a/disable`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to disable external A2A agent: ${res.statusText}`,
    );
  }
  return res.json() as Promise<ExternalA2AAgent>;
}

export async function rotateExternalA2AAgent(
  name: string,
): Promise<ExternalA2AAgent> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/a2a/external-agents/${encodeURIComponent(name)}/a2a/rotate`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ??
        `Failed to rotate external A2A agent token: ${res.statusText}`,
    );
  }
  return res.json() as Promise<ExternalA2AAgent>;
}

export async function enableAgentA2A(
  name: string,
): Promise<AgentA2APublication> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}/a2a/enable`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to enable agent A2A publication: ${res.statusText}`,
    );
  }
  return res.json() as Promise<AgentA2APublication>;
}

export async function disableAgentA2A(
  name: string,
): Promise<AgentA2APublication> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}/a2a/disable`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ??
        `Failed to disable agent A2A publication: ${res.statusText}`,
    );
  }
  return res.json() as Promise<AgentA2APublication>;
}

export async function rotateAgentA2A(
  name: string,
): Promise<AgentA2APublication> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}/a2a/rotate`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ??
        `Failed to rotate agent A2A publication token: ${res.statusText}`,
    );
  }
  return res.json() as Promise<AgentA2APublication>;
}

export async function getA2AAgentCard(name: string): Promise<A2AAgentCard> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/a2a/agents/${encodeURIComponent(name)}/card`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load A2A Agent Card: ${res.statusText}`);
  }
  return res.json() as Promise<A2AAgentCard>;
}
