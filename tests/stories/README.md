# Story Files

This directory contains small markdown user stories for DFOS workflows in DerZug. They are not executable tests. They are lightweight workflow examples that describe how an analyst might combine existing widgets such as `Spool`, `Selection`, `Filter`, `Waterfall`, `Stft`, `Rolling`, and `Aggregate`.

The collection can include DAS, DSS, and DTS workflows. Some files describe workflows DerZug can already approximate today, while others are intentionally forward-looking and are meant to guide feature selection.

Use these files as:

- prompts for workflow design discussions
- examples when planning higher-level integration tests
- reference material for documenting realistic DFOS usage patterns

## Story Format

Each story lives in its own file and should include:

1. YAML front matter with at least:
   - `title`
   - `complexity`
   - `implemented`
   - `missing_features` when the story is intentionally ahead of current DerZug capabilities
2. A matching level-one heading.
3. A short user-story sentence in the form "As a ..., I want ..., so that ...".
4. A `## Workflow` section with concrete, sequential steps.
5. A `## Expected Outcome` section that states what success looks like.
6. A `## References` section when the story is grounded in external literature.

## Complexity Levels

- `basic`: A short linear workflow using one or two main transformations.
- `intermediate`: A workflow that includes multiple processing steps or one interpretive decision.
- `advanced`: A workflow that includes branching, repeated refinement, comparison across outputs, or a multi-stage handoff product.

## Writing Guidelines

- Keep the story grounded in widgets and data concepts that already exist in this repo.
- Prefer `patch` and `spool` terminology over generic words like "dataset" when possible.
- Describe workflows, not implementation details.
- Keep the steps concrete enough that someone could later translate the story into an integration test or demo workflow.
- If a story is intentionally forward-looking, mark the missing capabilities explicitly in `missing_features`.
- Keep each file focused on one analyst goal.
