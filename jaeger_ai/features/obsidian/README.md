# Obsidian vault adapter

Set `JAEGER_OBSIDIAN_VAULT` to an existing local directory before Jaeger starts. The tool catalogue then includes `obsidian_list_notes`, `obsidian_read_note`, and `obsidian_search_notes`. No app launch, index, database, or file mutation occurs.

Only regular `.md` files are read. Hidden folders and files, including `.obsidian`, and symlinks are excluded. Reads use directory-relative descriptors with no-follow checks. Each note is capped at 1 MB; list and search results at 100; search scans at most 5,000 candidate files. Front matter is returned as raw text, without YAML parsing.
