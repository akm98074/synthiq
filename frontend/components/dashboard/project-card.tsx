"use client";

import Link from "next/link";
import { FileText, Trash2, Clock } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDeleteProject } from "@/lib/hooks/use-projects";
import type { Project } from "@/lib/api-client";

const STATUS_LABELS: Record<Project["status"], { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
  created: { label: "Created", variant: "secondary" },
  ingesting: { label: "Ingesting", variant: "default" },
  indexing: { label: "Indexing", variant: "default" },
  cross_referencing: { label: "Cross-referencing", variant: "default" },
  generating: { label: "Generating", variant: "default" },
  ready: { label: "Ready", variant: "default" },
  error: { label: "Error", variant: "destructive" },
};

const DELIVERABLE_LABELS: Record<Project["deliverable_type"], string> = {
  executive_memo: "Executive Memo",
  competitive_landscape: "Competitive Landscape",
  investment_thesis: "Investment Thesis",
  project_brief: "Project Brief",
  literature_summary: "Literature Summary",
};

function projectTabHref(project: Project): string {
  if (project.status === "ready") return `/projects/${project.id}/draft`;
  if (project.status === "created") return `/projects/${project.id}/ingest`;
  return `/projects/${project.id}/map`;
}

export function ProjectCard({ project }: { project: Project }) {
  const { mutate: deleteProject, isPending } = useDeleteProject();
  const status = STATUS_LABELS[project.status] ?? { label: project.status, variant: "secondary" as const };

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-indigo-600 shrink-0 mt-0.5" />
            <CardTitle className="text-base leading-tight">
              <Link
                href={projectTabHref(project)}
                className="hover:text-indigo-600 transition-colors"
              >
                {project.name}
              </Link>
            </CardTitle>
          </div>
          <Badge variant={status.variant} className="shrink-0 text-xs">
            {status.label}
          </Badge>
        </div>
        <CardDescription className="ml-6">
          {DELIVERABLE_LABELS[project.deliverable_type]}
        </CardDescription>
      </CardHeader>

      <CardContent className="pb-2">
        <p className="text-sm text-slate-500 ml-6">
          {project.source_count} source{project.source_count !== 1 ? "s" : ""}
        </p>
      </CardContent>

      <CardFooter className="flex items-center justify-between pt-2 border-t">
        <div className="flex items-center gap-1 text-xs text-slate-400">
          <Clock className="w-3 h-3" />
          {new Date(project.created_at).toLocaleDateString()}
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-slate-400 hover:text-red-500"
            disabled={isPending}
            onClick={() => deleteProject(project.id)}
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span className="sr-only">Delete project</span>
          </Button>
          <Button
            asChild
            size="sm"
            variant="outline"
            className="h-7 text-xs"
          >
            <Link href={projectTabHref(project)}>Open</Link>
          </Button>
        </div>
      </CardFooter>
    </Card>
  );
}
