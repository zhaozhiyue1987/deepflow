"use client";

import { BotIcon, PlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  useAgents,
  useCreateExternalA2AAgent,
  useExternalA2AAgents,
} from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

import { AgentCard } from "./agent-card";

export function AgentGallery() {
  const { t } = useI18n();
  const { agents, isLoading } = useAgents();
  const { agents: externalA2AAgents, isLoading: isExternalA2ALoading } =
    useExternalA2AAgents();
  const createExternalA2AAgent = useCreateExternalA2AAgent();
  const router = useRouter();
  const [externalDialogOpen, setExternalDialogOpen] = useState(false);
  const [upstreamAuthType, setUpstreamAuthType] = useState<"none" | "bearer">(
    "none",
  );

  const releaseDialogPointerLock = useCallback(() => {
    if (typeof document === "undefined") {
      return;
    }

    window.setTimeout(() => {
      const hasOpenDialog = document.querySelector(
        '[data-slot="dialog-content"][data-state="open"]',
      );
      if (!hasOpenDialog && document.body.style.pointerEvents === "none") {
        document.body.style.pointerEvents = "";
      }
    }, 0);
  }, []);

  const handleExternalDialogOpenChange = useCallback(
    (open: boolean) => {
      setExternalDialogOpen(open);
      if (!open) {
        setUpstreamAuthType("none");
        releaseDialogPointerLock();
      }
    },
    [releaseDialogPointerLock],
  );
  const galleryAgents: Agent[] = [
    ...agents,
    ...externalA2AAgents.map((agent) => ({
      name: agent.name,
      description: agent.description,
      model: null,
      tool_groups: null,
      skills: null,
      source: agent.source,
      enabled: agent.enabled,
      health_status: agent.health_status,
      card_url: agent.card_url,
      task_url: agent.task_url,
      token_prefix: agent.token_prefix,
    })),
  ];
  const isGalleryLoading = isLoading || isExternalA2ALoading;

  const handleNewAgent = () => {
    router.push("/workspace/agents/new");
  };

  async function handleRegisterExternalA2A(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const authType = formData.get("upstream_auth_type") as "none" | "bearer";
    const token = String(formData.get("upstream_auth_token") ?? "");

    try {
      await createExternalA2AAgent.mutateAsync({
        name: String(formData.get("name") ?? ""),
        display_name: String(formData.get("display_name") ?? ""),
        description: String(formData.get("description") ?? ""),
        upstream_card_url: String(formData.get("upstream_card_url") ?? ""),
        upstream_auth: {
          type: authType,
          token: authType === "bearer" ? token : null,
        },
      });
      handleExternalDialogOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">{t.agents.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t.agents.description}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => handleExternalDialogOpenChange(true)}
          >
            Register External A2A
          </Button>
          <Button onClick={handleNewAgent}>
            <PlusIcon className="mr-1.5 h-4 w-4" />
            {t.agents.newAgent}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isGalleryLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            {t.common.loading}
          </div>
        ) : galleryAgents.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
              <BotIcon className="text-muted-foreground h-7 w-7" />
            </div>
            <div>
              <p className="font-medium">{t.agents.emptyTitle}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.agents.emptyDescription}
              </p>
            </div>
            <Button variant="outline" className="mt-2" onClick={handleNewAgent}>
              <PlusIcon className="mr-1.5 h-4 w-4" />
              {t.agents.newAgent}
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {galleryAgents.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        )}
      </div>

      <Dialog
        open={externalDialogOpen}
        onOpenChange={handleExternalDialogOpenChange}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Register External A2A</DialogTitle>
            <DialogDescription>
              Register an upstream A2A Agent Card and republish it through this
              DeerFlow gateway.
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleRegisterExternalA2A}>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="external-name">
                Name
              </label>
              <Input id="external-name" name="name" required />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-sm font-medium"
                htmlFor="external-display-name"
              >
                Display name
              </label>
              <Input id="external-display-name" name="display_name" required />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-sm font-medium"
                htmlFor="external-description"
              >
                Description
              </label>
              <Textarea id="external-description" name="description" />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-sm font-medium"
                htmlFor="external-upstream-card-url"
              >
                Upstream Agent Card URL
              </label>
              <Input
                id="external-upstream-card-url"
                name="upstream_card_url"
                required
                type="url"
              />
            </div>
            <div className="space-y-1.5">
              <label
                className="text-sm font-medium"
                htmlFor="external-upstream-auth-type"
              >
                Upstream auth type
              </label>
              <select
                id="external-upstream-auth-type"
                name="upstream_auth_type"
                className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
                value={upstreamAuthType}
                onChange={(event) =>
                  setUpstreamAuthType(event.target.value as "none" | "bearer")
                }
              >
                <option value="none">none</option>
                <option value="bearer">bearer</option>
              </select>
            </div>
            {upstreamAuthType === "bearer" && (
              <div className="space-y-1.5">
                <label
                  className="text-sm font-medium"
                  htmlFor="external-upstream-auth-token"
                >
                  Upstream bearer token
                </label>
                <Input
                  id="external-upstream-auth-token"
                  name="upstream_auth_token"
                  type="password"
                />
              </div>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleExternalDialogOpenChange(false)}
              >
                {t.common.cancel}
              </Button>
              <Button type="submit" disabled={createExternalA2AAgent.isPending}>
                Register
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
