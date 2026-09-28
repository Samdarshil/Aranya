import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { sessionStore, type Session } from '../api/client';

type AppState = { session: Session | null; farmId: number | null; setFarmId: (id: number | null) => void; signIn: (s: Session) => void; signOut: () => void };
const Context = createContext<AppState | null>(null);
const FARM_KEY = 'aranya_farm_id';

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => sessionStore.get());
  const [farmId, updateFarmId] = useState<number | null>(() => {
    const parsed = Number(localStorage.getItem(FARM_KEY));
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  });
  const setFarmId = (id: number | null) => {
    const validId = id && Number.isInteger(id) && id > 0 ? id : null;
    updateFarmId(validId);
    if (validId) localStorage.setItem(FARM_KEY, String(validId)); else localStorage.removeItem(FARM_KEY);
  };
  const signIn = (value: Session) => { sessionStore.set(value); setSession(value); if (value.farm_id) setFarmId(value.farm_id); };
  const signOut = () => { sessionStore.clear(); setSession(null); };
  useEffect(() => {
    const expired = () => setSession(null);
    window.addEventListener('aranya:session-expired', expired);
    return () => window.removeEventListener('aranya:session-expired', expired);
  }, []);
  const value = useMemo(() => ({ session, farmId, setFarmId, signIn, signOut }), [session, farmId]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useApp() {
  const value = useContext(Context);
  if (!value) throw new Error('useApp must be used inside AppProvider');
  return value;
}
