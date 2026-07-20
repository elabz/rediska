## ADDED Requirements

### Requirement: Automated build and publish on main

The repository SHALL include a GitHub Actions workflow that, on every push to `main`, builds the `rediska-web`, `rediska-core`, and `rediska-worker` Docker images and publishes them to GHCR tagged with both the commit SHA and `latest`.

#### Scenario: Successful push to main

- **WHEN** a commit lands on `main` whose paths include non-doc-only changes
- **THEN** the workflow builds and publishes all three images to `ghcr.io/elabz/rediska-<service>` with tags `<sha>` and `latest`

#### Scenario: Docs-only commit

- **WHEN** a commit on `main` changes only files under `openspec/`, `docs/`, or any `*.md`
- **THEN** the workflow does not run the build/publish/deploy steps

### Requirement: Automated deploy to on-prem server

The workflow SHALL, after a successful publish, reach the on-prem server through Tailscale and apply the new images: pull, recreate containers, run database migrations, and run the smoke test.

#### Scenario: End-to-end success

- **WHEN** images publish successfully
- **THEN** the workflow joins the tailnet, SSHes to the configured host, runs `scripts/deploy/update.sh <sha>`, and the script completes with a passing smoke test

#### Scenario: Smoke test fails on the server

- **WHEN** `scripts/deploy/update.sh` exits non-zero because the smoke test failed
- **THEN** the workflow is marked as failed and surfaces the smoke-test output in the GitHub Actions logs; the deployment is NOT auto-rolled-back

### Requirement: Manual re-deploy and rollback

The workflow SHALL support `workflow_dispatch` with a `tag` input so an operator can deploy a specific previously-built image (e.g., for rollback to a prior SHA).

#### Scenario: Manual rollback

- **WHEN** the operator triggers `workflow_dispatch` with `tag=<previous-sha>`
- **THEN** the deploy step runs `scripts/deploy/update.sh <previous-sha>` and the server runs that exact image set

### Requirement: Reproducible builds tagged by commit

Each published image SHALL be uniquely tagged by the commit SHA in addition to any moving tags. SHA-tagged images MUST NOT be overwritten.

#### Scenario: Image identity for a SHA

- **WHEN** the workflow runs twice for the same commit SHA (e.g., a re-run)
- **THEN** the resulting image digests under the SHA tag are identical (build is hermetic), OR the second run is a no-op because the SHA tag already exists

### Requirement: Server-side deploy script preserves state

The server-side `scripts/deploy/update.sh` SHALL be idempotent and SHALL not delete user data (MySQL volumes, attachments directory, Elasticsearch indices) under any code path.

#### Scenario: Repeated deploy of the same SHA

- **WHEN** the script is invoked twice in a row with the same SHA
- **THEN** the second invocation is a no-op or applies only the smoke test, and all persistent data is unchanged
