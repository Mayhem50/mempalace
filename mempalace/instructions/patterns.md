## Pattern Search Skill

- When you are looking for a memory by topic, project, person, or keyword, use `mempalace_search`.
- When you recognize a problem shape or failure mode, use `mempalace_search_pattern`.
- When you want cleaner results with fewer config and agent-guide hits, prefer `mempalace_search_pattern_clean`.
- When you do not know which structural labels exist yet, call `mempalace_list_patterns` first, then narrow with `mempalace_search_pattern`.
- Read the returned `aaak_summary` first. Open the full drawer only if the summary looks relevant.
- Pattern labels are extracted automatically when new drawers are filed through MemPalace ingestion or MCP writes.

Suggested flow:

1. Topic lookup: `mempalace_search`
2. Pattern lookup: `mempalace_search_pattern`
3. Cleaner pattern lookup: `mempalace_search_pattern_clean`
4. Unknown label space: `mempalace_list_patterns` then `mempalace_search_pattern`
5. Full detail: use the returned `source_file` or `episode_id` to inspect the original drawer in the palace
