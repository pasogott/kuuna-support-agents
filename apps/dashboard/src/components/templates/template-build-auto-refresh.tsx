"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function TemplateBuildAutoRefresh(props: { active: boolean }): null {
  const router = useRouter();

  useEffect(() => {
    if (!props.active) {
      return;
    }

    const id = window.setInterval(() => {
      router.refresh();
    }, 4000);

    return () => window.clearInterval(id);
  }, [props.active, router]);

  return null;
}
