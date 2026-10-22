"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export function FollowButton({ handle, followers }: { handle: string; followers: number }) {
  const { user } = useSession();
  const [following, setFollowing] = useState(false);
  const [count, setCount] = useState(followers);
  if (!user || user.creator_handle === handle) return null;
  const toggle = async () => {
    await api(`/creators/${handle}/follow`, { method: following ? "DELETE" : "POST" });
    setCount((c) => c + (following ? -1 : 1));
    setFollowing(!following);
  };
  return <button className={following ? "btn-ghost" : "btn-gold"} onClick={toggle}>{following ? "Following" : "Follow"} · {count}</button>;
}
