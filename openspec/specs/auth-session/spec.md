# auth-session Specification

## Purpose
Rediska is a single-user, local-only system. This capability covers bootstrap of the one local admin user, cookie-session login/logout through the core API and the Next.js BFF, and the onboarding gate that blocks the rest of the API until at least one provider identity exists.

## Requirements

### Requirement: Single local admin user is created via first-run bootstrap

The system SHALL support exactly one local admin user, created through `POST /setup/bootstrap` with a username and password. The password SHALL be stored as an Argon2 hash, never in plaintext.

#### Scenario: First-run bootstrap creates the user

- **WHEN** `POST /setup/bootstrap` is called on a fresh install with a username and password
- **THEN** a `local_users` row is created with an Argon2 password hash
- **AND** subsequent logins with those credentials succeed

#### Scenario: Setup status reports completion state

- **WHEN** a client calls `GET /setup/status`
- **THEN** the response reports whether the admin user exists and whether at least one identity is configured, so the UI can route to the correct onboarding step

### Requirement: Login issues a server-side session with an httpOnly cookie

`POST /auth/login` SHALL verify the password against the Argon2 hash, create a server-side `sessions` row, and set a `session` cookie that is httpOnly and Secure. Session lifetime SHALL be governed by `SESSION_EXPIRE_HOURS` (default one week).

#### Scenario: Successful login

- **WHEN** the user submits valid credentials to `POST /auth/login`
- **THEN** a `sessions` row is created with an expiry derived from `SESSION_EXPIRE_HOURS`
- **AND** the response sets a `session` cookie marked httpOnly and Secure

#### Scenario: Logout invalidates the session

- **WHEN** the user calls `POST /auth/logout`
- **THEN** the server-side session is invalidated and the cookie no longer authenticates requests

#### Scenario: Current-user introspection

- **WHEN** a client with a valid session cookie calls `GET /auth/me`
- **THEN** the response identifies the logged-in local user
- **AND** an expired or missing session yields 401

### Requirement: BFF proxies enforce the session cookie

The Next.js BFF login route SHALL parse the core `Set-Cookie` response and re-set the `session` cookie as httpOnly, `secure`, `sameSite=lax` with a one-week max age. Every other BFF proxy route under `/api/core/*` SHALL return 401 when the request carries no `session` cookie, and otherwise SHALL forward the cookie to the core API.

#### Scenario: Proxy without a cookie

- **WHEN** any `/api/core/*` route (other than login) receives a request without a `session` cookie
- **THEN** the BFF responds 401 without contacting the core API

#### Scenario: Proxy with a cookie

- **WHEN** a request carries a `session` cookie
- **THEN** the BFF forwards it as `Cookie: session=...` to `CORE_API_URL` and relays the core response status and JSON body

### Requirement: Onboarding gate blocks the API until an identity exists

The core API SHALL apply `OnboardingGateMiddleware`, returning 403 for all routes until at least one identity exists, except bypass paths: `/setup`, `/auth`, `/providers/`, and health endpoints.

#### Scenario: No identity configured yet

- **WHEN** no identity exists and a client calls a non-bypass endpoint such as `GET /conversations`
- **THEN** the core API responds 403
- **AND** calls to `/setup/*`, `/auth/*`, `/providers/*`, and health endpoints still succeed so onboarding can complete

#### Scenario: Gate lifts after first identity

- **WHEN** the first identity is created (e.g. via the Reddit OAuth flow)
- **THEN** previously gated endpoints become accessible without restart

#### Scenario: Web onboarding redirect

- **WHEN** an authenticated page loads while `GET /setup/status` reports onboarding incomplete
- **THEN** the web app's `OnboardingGate` redirects the user to `/setup/identity`
