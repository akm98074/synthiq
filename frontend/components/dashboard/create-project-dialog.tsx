"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateProject } from "@/lib/hooks/use-projects";
import { UpgradeModal } from "@/components/billing/upgrade-modal";
import type { DeliverableType } from "@/lib/api-client";

const DELIVERABLE_TYPES: { value: DeliverableType; label: string; description: string }[] = [
  {
    value: "executive_memo",
    label: "Executive Memo",
    description: "Concise leadership briefing with key findings",
  },
  {
    value: "competitive_landscape",
    label: "Competitive Landscape",
    description: "Market analysis across competitors and segments",
  },
  {
    value: "investment_thesis",
    label: "Investment Thesis",
    description: "PE/VC-style investment rationale and risk analysis",
  },
  {
    value: "project_brief",
    label: "Project Brief",
    description: "Scoped project definition with objectives and approach",
  },
  {
    value: "literature_summary",
    label: "Literature Summary",
    description: "Academic or research synthesis with citations",
  },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateProjectDialog({ open, onOpenChange }: Props) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [deliverableType, setDeliverableType] = useState<DeliverableType | "">("");
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [limitCode, setLimitCode] = useState<"project_limit_reached" | undefined>();
  const { mutateAsync: createProject, isPending } = useCreateProject();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !deliverableType) return;
    try {
      const project = await createProject({
        name: name.trim(),
        deliverable_type: deliverableType,
      });
      onOpenChange(false);
      setName("");
      setDeliverableType("");
      router.push(`/projects/${project.id}/ingest`);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: { code?: string } } } })?.response?.status;
      const code = (err as { response?: { status?: number; data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code;
      if (status === 402 && code === "project_limit_reached") {
        setLimitCode("project_limit_reached");
        setUpgradeOpen(true);
      }
    }
  }

  return (
    <>
    <UpgradeModal
      open={upgradeOpen}
      onClose={() => setUpgradeOpen(false)}
      limitCode={limitCode}
    />
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New Project</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="name">Project name</Label>
            <Input
              id="name"
              placeholder="e.g. Q2 Competitive Analysis"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="deliverable-type">Deliverable type</Label>
            <Select
              value={deliverableType}
              onValueChange={(v) => setDeliverableType(v as DeliverableType)}
            >
              <SelectTrigger id="deliverable-type">
                <SelectValue placeholder="Select a deliverable type" />
              </SelectTrigger>
              <SelectContent>
                {DELIVERABLE_TYPES.map((dt) => (
                  <SelectItem key={dt.value} value={dt.value}>
                    <div>
                      <div className="font-medium">{dt.label}</div>
                      <div className="text-xs text-slate-500">{dt.description}</div>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!name.trim() || !deliverableType || isPending}
              className="bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              {isPending ? "Creating..." : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    </>
  );
}
