# API Exploration: Finding note_id

## Search API (no cookie)

**Fields returned** (7 total):
- `author`, `description`, `identifier`, `name`, `tags`, `updated_at`, `version`

**Conclusion**: No `note_id`, `usage_count`, `post_id`, or any engagement-related fields.

## List API (needs cookie)

Code ready: `python -m src.explore_note_id --cookie "<cookie>" --explore`

The list_published_skills endpoint may return additional fields not present in the public search API. To test:
1. Provide a valid xiaohongshu.com login cookie
2. Run `python -m src.explore_note_id --cookie "<cookie>" --explore`
3. If note_id is found, run `--extract` to build the full mapping

## Bundle API (public)

Manifest files at `downloads/*.manifest.json` contain:
- `identifier`, `version`, `zip_url`, `sha256`, `bundle_size_bytes`, `size_bytes`
- `raw` dict with trace_id, sku info, but **no note_id**

## Manifests Raw Data

The `raw` field in manifest files contains the full `get_skill_bundle` response:
```
sha256, identifier, version, zip_url, bundle_size_bytes, size_bytes
```

No engagement data.

## Recommended Path Forward

1. **If list API has note_id**: Extract mapping, hand to MediaCrawler
2. **If list API also lacks note_id**: Use MediaCrawler to search xiaohongshu.com by skill name, match results back by name similarity
