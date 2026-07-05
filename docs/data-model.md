# Data model

## Node types

- `company`
- `job`
- `skill`
- `location`
- `role_family`
- `source`

## Edge types

- `POSTS`
- `REQUIRES`
- `PREFERS`
- `LOCATED_IN`
- `BELONGS_TO`
- `ALIAS_OF`
- `SIMILAR_TO`

## Key principles

- A company page is one graph projection.
- A skill page is another graph projection.
- The underlying truth should exist only once.

## Important IDs

- `company_id`: `company:<slug>`
- `job_id`: `job:<company_slug>:<external_or_hash>`
- `skill_id`: `skill:<slug>`

## Normalization expectations

### Company normalization

The same company may appear as:

- `ByteDance`
- `Bytedance`
- `字节跳动`

These must converge to one canonical company ID.

### Skill normalization

The same skill may appear as:

- `SystemVerilog`
- `SV`

These should map to a canonical skill ID, with aliases preserved.

### Dedupe

Job dedupe prefers:

1. canonical external IDs
2. description hashes
3. title/company/location/skills fingerprints
