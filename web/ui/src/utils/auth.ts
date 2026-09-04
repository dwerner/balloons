/**
 * Authentication utilities for Balloons frontend.
 *
 * Handles JWT token storage, login flow, and API calls.
 */

// Storage key for JWT token
const TOKEN_KEY = 'balloons:auth-token';
const USER_KEY = 'balloons:user';

export interface User {
  id: string;
  username: string;
  role: 'admin' | 'user';
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
}

/**
 * Get the stored JWT token.
 */
export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Get the stored user info.
 */
export function getUser(): User | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(USER_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored) as User;
  } catch {
    return null;
  }
}

/**
 * Check if user is authenticated (has valid-looking token).
 */
export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;

  // Check if token is expired (JWT tokens have exp claim)
  try {
    const parts = token.split('.');
    if (parts.length !== 3 || !parts[1]) {
      clearAuth();
      return false;
    }
    const payload = JSON.parse(atob(parts[1]));
    const exp = payload.exp;
    if (exp && exp * 1000 < Date.now()) {
      // Token expired, clear it
      clearAuth();
      return false;
    }
  } catch {
    // Malformed token
    clearAuth();
    return false;
  }

  return true;
}

/**
 * Store authentication data.
 */
export function setAuth(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/**
 * Clear authentication data.
 */
export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/**
 * Get the current auth state.
 */
export function getAuthState(): AuthState {
  const token = getToken();
  const user = getUser();
  return {
    isAuthenticated: isAuthenticated(),
    token,
    user,
  };
}

/**
 * Get the base URL for API calls (HTTPS).
 */
export function getApiBaseUrl(port: number): string {
  if (typeof window === 'undefined') {
    return `https://localhost:${port}`;
  }

  // Check for explicit override
  if ((window as any).BALLOONS_API_URL) {
    return (window as any).BALLOONS_API_URL;
  }

  // Use page protocol (should be HTTPS in production)
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return `${protocol}//${window.location.hostname}:${port}`;
}

/**
 * Auth server HTTP ports per server slot (WS port + 1).
 * Mirrors AUTH_PORTS in App.tsx -- keep in sync.
 */
const AUTH_PORTS: Record<'A' | 'B', number> = { A: 8701, B: 8711 };

/**
 * Get the base URL of the HTTP auth server for the current server slot.
 *
 * This is the server that also serves GET /uploads/{filename}, so image
 * fetches must target it (not the WS server). Slot is persisted by App.tsx
 * under 'balloons:server-slot'; defaults to A.
 */
export function getAuthBaseUrl(): string {
  if (typeof window === 'undefined') {
    return `https://localhost:${AUTH_PORTS.A}`;
  }
  const slot: 'A' | 'B' =
    localStorage.getItem('balloons:server-slot') === 'B' ? 'B' : 'A';
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return `${protocol}//${window.location.hostname}:${AUTH_PORTS[slot]}`;
}

/**
 * Get the WebSocket URL with auth token.
 *
 * Note: WS server runs on a different port than HTTP auth server.
 * The wsPort parameter is the WS server port (e.g. 8765).
 */
export function getWsUrlWithAuth(wsPort: number): string {
  if (typeof window === 'undefined') {
    return `wss://localhost:${wsPort}`;
  }

  // Check for explicit override
  if ((window as any).BALLOONS_WS_URL) {
    return (window as any).BALLOONS_WS_URL;
  }

  // Use page protocol
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getToken();
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${protocol}//${window.location.hostname}:${wsPort}${tokenParam}`;
}

/**
 * Login with username and password.
 */
export async function login(
  baseUrl: string,
  username: string,
  password: string,
): Promise<LoginResponse> {
  const response = await fetch(`${baseUrl}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Login failed' }));
    throw new Error(error.error || 'Login failed');
  }

  const data: LoginResponse = await response.json();
  setAuth(data.token, data.user);
  return data;
}

/**
 * Logout - clears stored auth.
 */
export function logout(): void {
  clearAuth();
}

/**
 * Refresh the JWT token.
 */
export async function refreshToken(baseUrl: string): Promise<string | null> {
  const currentToken = getToken();
  if (!currentToken) return null;

  try {
    const response = await fetch(`${baseUrl}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${currentToken}`,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      // Token refresh failed, clear auth
      clearAuth();
      return null;
    }

    const data = await response.json();
    if (data.token) {
      localStorage.setItem(TOKEN_KEY, data.token);
      return data.token;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Make an authenticated API request.
 */
export async function authFetch(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  // If we get a 401, clear auth and let the UI handle re-login
  if (response.status === 401) {
    clearAuth();
  }

  return response;
}
