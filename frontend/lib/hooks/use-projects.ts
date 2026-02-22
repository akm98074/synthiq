import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import {
  projectsApi,
  setAuthToken,
  type CreateProjectPayload,
} from "@/lib/api-client";

function useSetAuthToken() {
  const { getToken } = useAuth();
  useEffect(() => {
    getToken().then((token) => setAuthToken(token));
  }, [getToken]);
}

export function useProjects() {
  useSetAuthToken();
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list(),
  });
}

export function useProject(id: string) {
  useSetAuthToken();
  return useQuery({
    queryKey: ["projects", id],
    queryFn: () => projectsApi.get(id),
    enabled: !!id,
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  useSetAuthToken();
  return useMutation({
    mutationFn: (payload: CreateProjectPayload) => projectsApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  useSetAuthToken();
  return useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
