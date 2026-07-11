"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { useAuth } from "../../../lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const { signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signup(email, password);
      router.push("/missions");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mx-auto max-w-sm space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Sign up</h1>
        <p className="mt-1 text-sm text-slate-500">Create an account to start orchestrating missions.</p>
      </div>

      <form className="space-y-4 rounded-md border border-line bg-white p-5 shadow-sm" onSubmit={onSubmit}>
        <label className="block">
          <span className="text-sm font-medium">Email</span>
          <input
            className="mt-1 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Password</span>
          <input
            className="mt-1 w-full rounded-md border border-line px-3 py-2 outline-none focus:border-accent"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>
        {error && (
          <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
        )}
        <button
          className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-50"
          type="submit"
          disabled={submitting}
        >
          {submitting ? "Creating account…" : "Sign up"}
        </button>
      </form>

      <p className="text-center text-sm text-slate-500">
        Already have an account?{" "}
        <Link className="text-accent hover:underline" href="/login">
          Log in
        </Link>
      </p>
    </section>
  );
}
