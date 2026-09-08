"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { BottomNav, Sidebar } from "@/components/nav";
import { CommandPalette } from "@/components/palette";
import { QuickLog } from "@/components/quick-log";
import { PageLoading } from "@/components/ui";
import { api } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { data: user, isLoading, isError } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
  });

  const { data: profile } = useQuery({
    queryKey: ["profile"],
    queryFn: api.profile,
    enabled: !!user,
    retry: false,
  });

  useEffect(() => {
    if (isError) router.replace("/login");
  }, [isError, router]);

  useEffect(() => {
    if (profile && !profile.onboarding_completed && pathname !== "/onboarding") {
      router.replace("/onboarding");
    }
  }, [profile, pathname, router]);

  if (isLoading || !user) {
    return (
      <div className="min-h-dvh">
        <PageLoading />
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh">
      <Sidebar />
      <div className="min-w-0 flex-1 pb-24 md:pb-8">
        {children}
        <div className="mx-auto max-w-5xl px-4 sm:px-6">
          <button
            onClick={async () => {
              await api.logout().catch(() => {});
              queryClient.clear();
              router.replace("/login");
            }}
            className="mb-8 mt-10 text-xs text-faint underline-offset-2 hover:text-muted hover:underline md:hidden"
          >
            Log out
          </button>
        </div>
      </div>
      <QuickLog />
      <CommandPalette />
      <BottomNav />
    </div>
  );
}
