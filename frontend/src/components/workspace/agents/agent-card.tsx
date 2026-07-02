"use client";

import {
  BotIcon,
  CopyIcon,
  KeyRoundIcon,
  MessageSquareIcon,
  PowerIcon,
  RotateCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type ComponentProps, type ReactElement, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useDeleteAgent,
  useDisableAgentA2A,
  useDisableExternalA2AAgent,
  useEnableAgentA2A,
  useEnableExternalA2AAgent,
  useRotateAgentA2A,
  useRotateExternalA2AAgent,
} from "@/core/agents";
import type { Agent } from "@/core/agents";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: Agent;
}

/**
 * Reveals the full text in a tooltip ONLY when its trigger is actually clipped.
 * Clipping is measured on pointer enter against the trigger's own box, covering
 * both single-line `truncate` (width) and multi-line `line-clamp` (height), so
 * untruncated content never pops a redundant tooltip.
 */
function TruncatedTooltip({
  text,
  children,
}: {
  text: string;
  children: ReactElement;
}) {
  const [truncated, setTruncated] = useState(false);
  return (
    <Tooltip>
      <TooltipTrigger
        asChild
        onPointerEnter={(e) => {
          const el = e.currentTarget;
          setTruncated(
            el.scrollWidth > el.clientWidth ||
              el.scrollHeight > el.clientHeight,
          );
        }}
      >
        {children}
      </TooltipTrigger>
      {truncated && (
        <TooltipContent className="max-w-xs text-wrap break-words">
          {text}
        </TooltipContent>
      )}
    </Tooltip>
  );
}

/**
 * Long, user-controlled labels (agent model, skills, tool groups) that must
 * never break the card layout: width is capped to the parent and the text is
 * truncated with an ellipsis, with the full value revealed on hover.
 */
function TruncatedBadge({
  label,
  variant,
  className,
}: {
  label: string;
  variant: ComponentProps<typeof Badge>["variant"];
  className?: string;
}) {
  return (
    <TruncatedTooltip text={label}>
      <Badge
        variant={variant}
        className={cn("block max-w-full truncate", className)}
      >
        {label}
      </Badge>
    </TruncatedTooltip>
  );
}

export function AgentCard({ agent }: AgentCardProps) {
  const { t } = useI18n();
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const enableNativeA2A = useEnableAgentA2A();
  const disableNativeA2A = useDisableAgentA2A();
  const rotateNativeA2A = useRotateAgentA2A();
  const enableExternalA2A = useEnableExternalA2AAgent();
  const disableExternalA2A = useDisableExternalA2AAgent();
  const rotateExternalA2A = useRotateExternalA2AAgent();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const source = agent.source ?? "native";
  const [a2aState, setA2AState] = useState({
    enabled: Boolean(agent.enabled),
    cardUrl: agent.card_url ?? null,
    taskUrl: agent.task_url ?? null,
    tokenPrefix: agent.token_prefix ?? null,
    token: null as string | null,
  });
  const healthStatus = agent.health_status;
  const sourceLabel = source === "external" ? "External" : "Native";
  const healthLabel =
    healthStatus === "healthy"
      ? "Healthy"
      : healthStatus === "unhealthy"
        ? "Unhealthy"
        : healthStatus === "unknown"
          ? "Unknown"
          : null;

  function handleChat() {
    router.push(`/workspace/agents/${agent.name}/chats/new`);
  }

  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function copyValue(value: string, label: string) {
    const didCopy = await writeTextToClipboard(value);
    if (!didCopy) {
      toast.error(t.clipboard.failedToCopyToClipboard);
      return;
    }
    toast.success(`${label} copied`);
  }

  function applyA2AResponse(response: {
    enabled: boolean;
    card_url: string;
    task_url: string;
    token_prefix: string | null;
    token?: string | null;
  }) {
    setA2AState({
      enabled: response.enabled,
      cardUrl: response.card_url,
      taskUrl: response.task_url,
      tokenPrefix: response.token_prefix,
      token: response.token ?? null,
    });
  }

  async function handleEnableA2A() {
    try {
      const response =
        source === "external"
          ? await enableExternalA2A.mutateAsync(agent.name)
          : await enableNativeA2A.mutateAsync(agent.name);
      applyA2AResponse(response);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDisableA2A() {
    try {
      const response =
        source === "external"
          ? await disableExternalA2A.mutateAsync(agent.name)
          : await disableNativeA2A.mutateAsync(agent.name);
      applyA2AResponse(response);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRotateA2A() {
    try {
      const response =
        source === "external"
          ? await rotateExternalA2A.mutateAsync(agent.name)
          : await rotateNativeA2A.mutateAsync(agent.name);
      applyA2AResponse(response);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const isA2APending =
    enableNativeA2A.isPending ||
    disableNativeA2A.isPending ||
    rotateNativeA2A.isPending ||
    enableExternalA2A.isPending ||
    disableExternalA2A.isPending ||
    rotateExternalA2A.isPending;

  return (
    <>
      <Card className="group flex flex-col transition-shadow hover:shadow-md">
        <CardHeader className="pb-3">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <BotIcon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <TruncatedTooltip text={agent.name}>
                  <CardTitle className="truncate text-base">
                    {agent.name}
                  </CardTitle>
                </TruncatedTooltip>
                {agent.model && (
                  <TruncatedBadge
                    label={agent.model}
                    variant="secondary"
                    className="mt-0.5 text-xs"
                  />
                )}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Badge variant={source === "external" ? "default" : "secondary"}>
                {sourceLabel}
              </Badge>
              {healthLabel && (
                <Badge variant="outline" className="text-xs">
                  {healthLabel}
                </Badge>
              )}
            </div>
          </div>
          {agent.description && (
            <TruncatedTooltip text={agent.description}>
              <CardDescription className="mt-2 line-clamp-2 text-sm">
                {agent.description}
              </CardDescription>
            </TruncatedTooltip>
          )}
        </CardHeader>

        {(a2aState.cardUrl || a2aState.taskUrl || a2aState.token) && (
          <CardContent className="space-y-2 pt-0 pb-3 text-xs">
            {a2aState.cardUrl && (
              <div className="min-w-0">
                <div className="text-muted-foreground flex items-center justify-between gap-2">
                  <span>A2A Card URL</span>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    aria-label="Copy A2A card URL"
                    onClick={() =>
                      void copyValue(a2aState.cardUrl!, "A2A card URL")
                    }
                  >
                    <CopyIcon className="h-3 w-3" />
                  </Button>
                </div>
                <TruncatedTooltip text={a2aState.cardUrl}>
                  <div className="truncate font-mono">{a2aState.cardUrl}</div>
                </TruncatedTooltip>
              </div>
            )}
            {a2aState.taskUrl && (
              <div className="min-w-0">
                <div className="text-muted-foreground flex items-center justify-between gap-2">
                  <span>A2A Task URL</span>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    aria-label="Copy A2A task URL"
                    onClick={() =>
                      void copyValue(a2aState.taskUrl!, "A2A task URL")
                    }
                  >
                    <CopyIcon className="h-3 w-3" />
                  </Button>
                </div>
                <TruncatedTooltip text={a2aState.taskUrl}>
                  <div className="truncate font-mono">{a2aState.taskUrl}</div>
                </TruncatedTooltip>
              </div>
            )}
            {a2aState.tokenPrefix && !a2aState.token && (
              <div>
                <div className="text-muted-foreground">A2A Token Prefix</div>
                <div className="font-mono">{a2aState.tokenPrefix}</div>
              </div>
            )}
            {a2aState.token && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">One-time A2A token</span>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    aria-label="Copy A2A token"
                    onClick={() =>
                      void copyValue(a2aState.token!, "A2A token")
                    }
                  >
                    <CopyIcon className="h-3 w-3" />
                  </Button>
                </div>
                <div className="mt-1 break-all font-mono">{a2aState.token}</div>
              </div>
            )}
          </CardContent>
        )}

        {(agent.tool_groups?.length ?? agent.skills?.length ?? 0) > 0 && (
          <CardContent className="pt-0 pb-3">
            <div className="flex flex-wrap gap-1">
              {agent.tool_groups?.map((group) => (
                <TruncatedBadge
                  key={`tg:${group}`}
                  label={group}
                  variant="outline"
                  className="text-xs"
                />
              ))}
              {agent.skills?.map((skill) => (
                <TruncatedBadge
                  key={`sk:${skill}`}
                  label={skill}
                  variant="secondary"
                  className="text-xs"
                />
              ))}
            </div>
          </CardContent>
        )}

        <CardFooter className="mt-auto flex items-center justify-between gap-2 pt-3">
          <Button size="sm" className="flex-1" onClick={handleChat}>
            <MessageSquareIcon className="mr-1.5 h-3.5 w-3.5" />
            {t.agents.chat}
          </Button>
          <div className="flex gap-1">
            {a2aState.enabled ? (
              <>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0"
                  onClick={handleRotateA2A}
                  disabled={isA2APending}
                  title="Rotate A2A token"
                  aria-label="Rotate A2A token"
                >
                  <RotateCwIcon className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0"
                  onClick={handleDisableA2A}
                  disabled={isA2APending}
                  title="Disable A2A"
                  aria-label="Disable A2A"
                >
                  <PowerIcon className="h-3.5 w-3.5" />
                </Button>
              </>
            ) : (
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                onClick={handleEnableA2A}
                disabled={isA2APending}
                title="Enable A2A"
                aria-label="Enable A2A"
              >
                <KeyRoundIcon className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
              onClick={() => setDeleteOpen(true)}
              title={t.agents.delete}
            >
              <Trash2Icon className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardFooter>
      </Card>

      {/* Delete Confirm */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.agents.delete}</DialogTitle>
            <DialogDescription>{t.agents.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteAgent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAgent.isPending}
            >
              {deleteAgent.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
