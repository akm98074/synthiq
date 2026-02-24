"use client";

import { useState, KeyboardEvent } from "react";
import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface InstructionBarProps {
  sectionId: string;
  isPending: boolean;
  onSubmit: (sectionId: string, instruction: string) => void;
}

export function InstructionBar({
  sectionId,
  isPending,
  onSubmit,
}: InstructionBarProps) {
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || isPending) return;
    onSubmit(sectionId, trimmed);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") submit();
  }

  return (
    <div className="flex gap-2 pt-3 border-t border-slate-100">
      <Input
        className="text-sm flex-1"
        placeholder='Edit instruction, e.g. "Make this more concise" or "Add a risk caveat"'
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isPending}
      />
      <Button
        size="sm"
        variant="outline"
        className="shrink-0 gap-1"
        disabled={!value.trim() || isPending}
        onClick={submit}
      >
        {isPending ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Send className="w-3.5 h-3.5" />
        )}
      </Button>
    </div>
  );
}
