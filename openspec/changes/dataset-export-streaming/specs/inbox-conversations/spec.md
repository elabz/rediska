## ADDED Requirements

### Requirement: Dataset export streams with bounded memory
The dataset export SHALL read conversations in pages and fetch the messages of each page with one query, SHALL emit lines to the client as they are produced, and SHALL NOT hold the complete dataset in memory in the core API or in the web proxy. The output for given parameters SHALL be identical to the output of an unbatched export.

#### Scenario: Query count is per page
- **WHEN** 450 conversations are exported with a page size of 200
- **THEN** messages are fetched with three queries, not 450

#### Scenario: Proxy does not buffer
- **WHEN** the web proxy relays an export
- **THEN** it passes the upstream body through as a stream

### Requirement: Dataset export is audited when it finishes
The export SHALL write exactly one `dataset.export` audit entry when the stream ends, with result `ok`, `aborted` when the client disconnected, or `error`, and with the parameters and the counts reached. `GET /conversations/export-dataset/last` SHALL return the newest such entry's summary so the UI can show final counts and detect an incomplete file.

#### Scenario: Client cancels the download
- **WHEN** the client disconnects halfway through
- **THEN** one audit entry with result `aborted` and the partial counts is written and the database session is released

#### Scenario: Failure after streaming started
- **WHEN** an error occurs after the first lines were sent
- **THEN** the audit entry has result `error` and the export dialog reports failure rather than success

### Requirement: Dataset export can be previewed
`GET /conversations/export-dataset/preview` SHALL return, for the same filters as the export, the number of conversations and messages that would be read, without reading message bodies. The export dialog SHALL show this before the user starts the export.

#### Scenario: Preview with a list filter
- **WHEN** the user selects a conversation list in the export dialog
- **THEN** the dialog shows how many conversations and messages that list contains
