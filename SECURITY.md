# Security

This project talks to Dida365/TickTick private v2 endpoints and may use local account credentials or web-session cookies.

Rules for this repository:

- Do not commit passwords, session cookies, API tokens, `.env` files, or cookie/session caches.
- Keep live-account tests disabled by default; CI should run mock/contract tests only.
- Prefer local environment variables, macOS Keychain, or another local secret store for credentials.
- Never print session tokens, cookies, passwords, or full account payloads in logs.
- Treat generated cache files as local-only and covered by `.gitignore`.
