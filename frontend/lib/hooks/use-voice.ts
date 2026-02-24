"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { voiceApi, VoiceProfile, projectsApi } from "@/lib/api-client";

export function useVoiceProfile() {
  return useQuery<VoiceProfile | null>({
    queryKey: ["voice-profile"],
    queryFn: () => voiceApi.get(),
    staleTime: 30_000,
  });
}

export function useUploadVoiceSample() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => voiceApi.uploadSample(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["voice-profile"] });
    },
  });
}

export function useDeleteVoiceProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => voiceApi.deleteProfile(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["voice-profile"] });
    },
  });
}

export function useProjectVoiceToggle(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      projectsApi.updateVoice(projectId, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
}
