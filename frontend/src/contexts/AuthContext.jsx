import { createContext, useContext, useState, useCallback } from 'react';
import { authAPI, usersAPI } from '../services/api';
import { wsService } from '../services/websocket';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const login = useCallback(async (phone, password) => {
    const { data } = await authAPI.login({ phone, password });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user_id', data.user_id);

    const { data: user } = await usersAPI.getMe();
    setCurrentUser(user);

    // Connect WebSocket
    wsService.connect(data.user_id, data.access_token);

    return user;
  }, []);

  const register = useCallback(async (phone, username, password) => {
    const { data } = await authAPI.register({ phone, username, password });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user_id', data.user_id);

    const { data: user } = await usersAPI.getMe();
    setCurrentUser(user);
    wsService.connect(data.user_id, data.access_token);

    return user;
  }, []);

  const logout = useCallback(async () => {
    try { await authAPI.logout(); } catch (_) {}
    wsService.disconnect();
    localStorage.clear();
    setCurrentUser(null);
  }, []);

  const initFromStorage = useCallback(async () => {
    const token = localStorage.getItem('access_token');
    const userId = localStorage.getItem('user_id');
    if (!token || !userId) return false;

    try {
      setIsLoading(true);
      const { data: user } = await usersAPI.getMe();
      setCurrentUser(user);
      wsService.connect(userId, token);
      return true;
    } catch (_) {
      localStorage.clear();
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ currentUser, login, register, logout, initFromStorage, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};