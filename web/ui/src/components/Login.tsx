/**
 * Login component for Balloons authentication.
 *
 * Displays a centered login form with username/password fields.
 * Shows error messages on failed login attempts.
 */

import React, { useState, useCallback } from 'react';
import { login } from '../utils/auth';
import './Login.css';

interface LoginProps {
  /** Full URL for the HTTP auth server (e.g. http://localhost:8764 or https://...) */
  authUrl: string;
  onLoginSuccess: () => void;
}

export function Login({ authUrl, onLoginSuccess }: LoginProps): React.ReactElement {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      setIsLoading(true);

      try {
        await login(authUrl, username, password);
        onLoginSuccess();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Login failed');
      } finally {
        setIsLoading(false);
      }
    },
    [authUrl, username, password, onLoginSuccess],
  );

  const isInsecure =
    typeof window !== 'undefined' && window.location.protocol !== 'https:';

  // Check if error looks like a cert issue (null status = connection failed)
  const isCertError = error?.includes('Failed to fetch') || error?.includes('NetworkError');
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const authHealthUrl = `${authUrl}/health`;

  // Build URLs for both slots (auth: 8701/8711, ws: 8700/8710)
  const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'https' : 'http';
  const slotAAuthUrl = `${protocol}://${hostname}:8701/health`;
  const slotAWsUrl = `${protocol}://${hostname}:8700`;
  const slotBAuthUrl = `${protocol}://${hostname}:8711/health`;
  const slotBWsUrl = `${protocol}://${hostname}:8710`;

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-logo">🎈</div>
        <h1 className="login-title">Balloons</h1>
        <p className="login-subtitle">Sign in to your account</p>

        {isHttps && (
          <div className="login-cert-warning">
            <p>Using self-signed certs? Accept them first:</p>
            <div>
              <strong>Slot A:</strong>{' '}
              <a href={slotAAuthUrl} target="_blank" rel="noopener noreferrer">Auth</a>
              {' | '}
              <a href={slotAWsUrl} target="_blank" rel="noopener noreferrer">WS</a>
            </div>
            <div>
              <strong>Slot B:</strong>{' '}
              <a href={slotBAuthUrl} target="_blank" rel="noopener noreferrer">Auth</a>
              {' | '}
              <a href={slotBWsUrl} target="_blank" rel="noopener noreferrer">WS</a>
            </div>
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit}>
          {error && <div className="login-error">{error}</div>}

          <div className="login-input-group">
            <label className="login-label" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              type="text"
              className="login-input"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>

          <div className="login-input-group">
            <label className="login-label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="login-input"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <button type="submit" className="login-button" disabled={isLoading}>
            {isLoading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        {isInsecure && (
          <div className="login-tls-warning">
            ⚠️ Connection is not secure. For production, use HTTPS.
          </div>
        )}
      </div>
    </div>
  );
}
