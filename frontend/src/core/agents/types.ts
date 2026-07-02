export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  soul?: string | null;
  source?: "native" | "external";
  enabled?: boolean;
  health_status?: "unknown" | "healthy" | "unhealthy";
  card_url?: string;
  task_url?: string;
  token_prefix?: string | null;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
}

export interface ExternalA2AAgent {
  name: string;
  source: "external";
  display_name: string;
  description: string;
  enabled: boolean;
  health_status: "unknown" | "healthy" | "unhealthy";
  card_url: string;
  task_url: string;
  upstream_card_fetched_at: string | null;
  token_prefix: string | null;
  token?: string | null;
}

export interface AgentA2APublication {
  enabled: boolean;
  agent_name: string;
  source: "native";
  registry_url: string;
  card_url: string;
  task_url: string;
  token_prefix: string | null;
  token?: string | null;
}

export interface ExternalA2AAgentCreateRequest {
  name: string;
  display_name: string;
  description?: string;
  upstream_card_url: string;
  upstream_auth?: {
    type: "none" | "bearer";
    token?: string | null;
  };
}

export interface A2AAgentCard {
  name: string;
  source: "native" | "external";
  description: string;
  url: string;
  card_url: string;
  capabilities: Record<string, unknown>;
  defaultInputModes: string[];
  defaultOutputModes: string[];
}
