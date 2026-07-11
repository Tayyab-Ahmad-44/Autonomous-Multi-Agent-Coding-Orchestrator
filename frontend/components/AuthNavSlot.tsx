"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";

export function AuthNavSlot() {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();

  if (isLoading) return null;

  if (!user) {
    return (
      <>
        <Link className="text-slate-700 hover:text-ink" href="/login">
          Log in
        </Link>
        <Link className="text-slate-700 hover:text-ink" href="/signup">
          Sign up
        </Link>
      </>
    );
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <div className="flex items-center gap-3">
      <span className="text-slate-700">{user.email}</span>
      <button className="text-slate-700 hover:text-ink" onClick={handleLogout}>
        Log out
      </button>
    </div>
  );
}
