/**
 * API Service Layer
 * =================
 * Centralized Axios instance with interceptors for:
 * - JWT token injection
 * - Automatic token refresh on 401
 * - Error normalization
 */
import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Primary Axios instance
const api = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Request interceptor: inject access token ──────────────────────────────────
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response interceptor: handle 401 with token refresh ───────────────────────
let isRefreshing = false;
let failedQueue = [];   // queued requests waiting for refresh

const processQueue = (error, token = null) => {
  failedQueue.forEach((prom) => {
    if (error) prom.reject(error);
    else prom.resolve(token);
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue this request until refresh completes
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) {
        // No refresh token — redirect to login
        window.location.href = '/login';
        return Promise.reject(error);
      }

      try {
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        });
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        api.defaults.headers.common.Authorization = `Bearer ${data.access_token}`;
        processQueue(null, data.access_token);
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        localStorage.clear();
        window.location.href = '/login';
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// ── Auth API ──────────────────────────────────────────────────────────────────
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  logout: () => api.post('/auth/logout'),
};

// ── Users API ─────────────────────────────────────────────────────────────────
export const usersAPI = {
  getMe: () => api.get('/users/me'),
  updateMe: (data) => api.patch('/users/me', data),
  search: (q) => api.get('/users/search', { params: { q } }),
  getProfile: (userId) => api.get(`/users/${userId}`),
};

// ── Chats API ─────────────────────────────────────────────────────────────────
export const chatsAPI = {
  listChats: () => api.get('/chats/'),
  getChat: (chatId) => api.get(`/chats/${chatId}`),
  createDirect: (participantId) => api.post('/chats/direct', { participant_id: participantId }),
  createGroup: (data) => api.post('/chats/group', data),
};

// ── Messages API ──────────────────────────────────────────────────────────────
export const messagesAPI = {
  getMessages: (chatId, before = null, limit = 50) =>
    api.get(`/messages/${chatId}`, { params: { before, limit } }),
  deleteMessage: (chatId, messageId) => api.delete(`/messages/${chatId}/${messageId}`),
};

// ── Media API ─────────────────────────────────────────────────────────────────
export const mediaAPI = {
  getPresignedUrl: (data) => api.post('/media/presign', data),
  uploadDirect: (formData) =>
    api.post('/media/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
};

export default api;