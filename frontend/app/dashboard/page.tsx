"use client";

import { useState } from "react";
import { UserButton } from "@clerk/nextjs";
import { Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProjectCard } from "@/components/dashboard/project-card";
import { CreateProjectDialog } from "@/components/dashboard/create-project-dialog";
import { useProjects } from "@/lib/hooks/use-projects";

export default function DashboardPage() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { data, isLoading, isError } = useProjects();

  const projects = data?.items ?? [];
  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Top nav */}
      <header className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
            <span className="text-white font-bold text-xs">S</span>
          </div>
          <span className="font-semibold text-slate-900">Synthiq</span>
        </div>
        <div className="flex items-center gap-4">
          <Button
            size="sm"
            className="bg-indigo-600 hover:bg-indigo-700 text-white gap-1"
            onClick={() => setOpen(true)}
          >
            <Plus className="w-4 h-4" />
            New project
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      {/* Main */}
      <main className="max-w-6xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Projects</h1>
            <p className="text-slate-500 text-sm mt-1">
              {projects.length} project{projects.length !== 1 ? "s" : ""} total
            </p>
          </div>
          <div className="relative w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <Input
              className="pl-9"
              placeholder="Search projects..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-40 rounded-lg bg-slate-200 animate-pulse"
              />
            ))}
          </div>
        )}

        {isError && (
          <div className="text-center py-20 text-slate-500">
            Failed to load projects. Please refresh.
          </div>
        )}

        {!isLoading && !isError && filtered.length === 0 && (
          <div className="text-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-indigo-50 flex items-center justify-center mx-auto mb-4">
              <span className="text-3xl">📄</span>
            </div>
            <h2 className="text-lg font-semibold text-slate-800 mb-2">
              {search ? "No projects match your search" : "No projects yet"}
            </h2>
            <p className="text-slate-500 text-sm mb-6">
              {search
                ? "Try a different search term"
                : "Create your first project to start synthesizing research"}
            </p>
            {!search && (
              <Button
                className="bg-indigo-600 hover:bg-indigo-700 text-white gap-1"
                onClick={() => setOpen(true)}
              >
                <Plus className="w-4 h-4" />
                New project
              </Button>
            )}
          </div>
        )}

        {!isLoading && !isError && filtered.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </main>

      <CreateProjectDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
