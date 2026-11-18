"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError } from "@/lib/api/client";
import { getCurrentUser, signOut as signOutRequest, type CurrentUser } from "@/lib/api/session";

/**
 * Who is signed in, for the UI only: hiding a link is a convenience, never an
 * access control. Every request is still checked by the API.
 */

type SessionState =
  | { status: "loading" }
  | { status: "signed-in"; user: CurrentUser }
  | { status: "error"; message: string };

interface SessionContextValue {
  state: SessionState;
  signOut: () => Promise<void>;
  /** True if the signed-in user's role grants the permission (UI decisions only). */
  can: (permission: string) => boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  loadUser = getCurrentUser,
}: {
  children: ReactNode;
  loadUser?: () => Promise<CurrentUser>;
}) {
  const router = useRouter();
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    loadUser().then(
      (user) => active && setState({ status: "signed-in", user }),
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          router.replace("/login");
          return;
        }
        setState({
          status: "error",
          message: "Could not load your session. Try again later.",
        });
      },
    );
    return () => {
      active = false;
    };
  }, [loadUser, router]);

  const signOut = useCallback(async () => {
    try {
      await signOutRequest();
    } finally {
      router.replace("/login");
    }
  }, [router]);

  const value = useMemo<SessionContextValue>(
    () => ({
      state,
      signOut,
      can: (permission) =>
        state.status === "signed-in" && state.user.permissions.includes(permission),
    }),
    [state, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
