## MODIFIED Requirements

### Requirement: TLS terminates at the external dev-proxy

The in-repo `rediska-nginx` service is retired and its configuration directory SHALL NOT exist in this repository. The `rediska.local` vhost and TLS termination SHALL be provided by the external dev-proxy stack (separate repo, e.g. `~/Web/dev-proxy`), which attaches to `rediska-net` and proxies to `rediska-web:3000`. No reverse-proxy service SHALL be defined in the compose stack.

#### Scenario: Browser reaches the app

- **WHEN** a browser on the LAN/VPN opens `https://rediska.local`
- **THEN** the dev-proxy terminates TLS and forwards to `rediska-web` over the internal Docker network

#### Scenario: Repository carries no proxy configuration

- **WHEN** the repository is checked out
- **THEN** it contains no `nginx/` directory and no compose service that terminates TLS or publishes a host port
