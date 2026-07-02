import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAgent,
  createExternalA2AAgent,
  deleteAgent,
  disableAgentA2A,
  disableExternalA2AAgent,
  enableAgentA2A,
  enableExternalA2AAgent,
  getAgent,
  listAgents,
  listExternalA2AAgents,
  rotateAgentA2A,
  rotateExternalA2AAgent,
  updateAgent,
} from "./api";
import type {
  CreateAgentRequest,
  ExternalA2AAgentCreateRequest,
  UpdateAgentRequest,
} from "./types";

export function useAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
  });
  return { agents: data ?? [], isLoading, error };
}

export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents", name],
    queryFn: () => getAgent(name!),
    enabled: !!name,
  });
  return { agent: data ?? null, isLoading, error };
}

export function useExternalA2AAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["a2a", "external-agents"],
    queryFn: () => listExternalA2AAgents(),
  });
  return { agents: data ?? [], isLoading, error };
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useCreateExternalA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ExternalA2AAgentCreateRequest) =>
      createExternalA2AAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["a2a", "external-agents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useEnableExternalA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => enableExternalA2AAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["a2a", "external-agents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useDisableExternalA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => disableExternalA2AAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["a2a", "external-agents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useRotateExternalA2AAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => rotateExternalA2AAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["a2a", "external-agents"],
      });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useEnableAgentA2A() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => enableAgentA2A(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["a2a"] });
    },
  });
}

export function useDisableAgentA2A() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => disableAgentA2A(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["a2a"] });
    },
  });
}

export function useRotateAgentA2A() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => rotateAgentA2A(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["a2a"] });
    },
  });
}
