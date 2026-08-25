# Proposal 0027: Ship a capability-synchronized agent skill

**Status:** Implemented (0.6.0)
**Relates to:** Agent adoption of newly shipped PMD features
**Touches:** distribution contents, agent guidance, release tests

## Motivation

PMD's agent interface evolves faster than an agent's remembered instructions.
Documentation in the repository is not sufficient when an installed package or
a source checkout is handed directly to an agent: the recommended discovery and
editing workflow must travel with the project and remain synchronized with its
public capabilities.

## Proposal

1. The source and binary distributions **MUST** include a discoverable
   `skills/polyglot-pmd/SKILL.md` agent skill.
2. The skill **MUST** begin its workflow with runtime version and capability
   discovery. Runtime output remains authoritative over its shipped snapshot.
3. The skill **MUST** record the release version, agent protocol, public agent
   commands, features, and semantic operations it was written against.
4. Tests **MUST** fail when those public capability lists or the package version
   change without a corresponding skill update.
5. A public feature change **MUST** update the skill in the same release change
   when it affects an agent workflow.

## Alternatives considered

- **Only link to the online documentation.** This is unavailable offline and can
  describe a different version than the installed package.
- **Hard-code workflows without capability discovery.** That turns the skill
  stale as soon as a user invokes it against another compatible release.
- **Generate the whole skill from CLI help.** Help text cannot encode safety
  boundaries, decision rules, or recommended semantic-edit workflows.
