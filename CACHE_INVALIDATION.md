# Cache Invalidation System

## Overview

The system implements **automatic cache invalidation** to ensure users always get fresh results when their health data is updated, while still benefiting from caching for performance.

## How It Works

### 1. Data Version Tracking

Every session has a `data_version` number that tracks changes to user data:

```python
class AgentContext:
    data_version: int = 0  # Starts at 0, increments on data changes
```

### 2. Automatic File Monitoring

The orchestrator monitors user data files for changes:

**Monitored Files:**
- `servers/user_data/data/biomarkers.json`
- `servers/user_data/data/activity.json`
- `servers/user_data/data/food_journal.json`
- `servers/user_data/data/sleep.json`
- `servers/user_data/data/profile.json`

**Detection Method:**
- Tracks file modification times (`mtime`)
- Checks on every new request
- When file `mtime` changes → increments `data_version`

### 3. Cache Key Versioning

Response cache keys include the data version:

```python
cache_key = hash(f"{session_id}:{data_version}:{user_query}")
```

**Result:** When `data_version` changes, cache key changes → old cache is bypassed!

## Example Flow

### Scenario: User's Biomarkers Get Updated

**Step 1:** User asks question
```
User: "What are my biggest health issues?"
System: Executes full analysis (25s)
Cache: Stores response with key "session123:v0:biggest health issues"
```

**Step 2:** User asks same question again
```
User: "What are my biggest health issues?"
System: Returns cached response (0.01s - instant!)
Cache: Hit! Same session, same version, same query
```

**Step 3:** Biomarker data is updated
```
File: biomarkers.json modified (LDL changes from 167 to 157)
System: Detects file change on next request
Action: data_version incremented from 0 to 1
Log: "📝 Data file updated: biomarkers.json"
      "🔄 Data version incremented to 1 - cache will be invalidated"
```

**Step 4:** User asks same question with new data
```
User: "What are my biggest health issues?"
System: Cache MISS (looking for v1, but cached v0)
System: Executes fresh analysis with NEW biomarker data (25s)
Result: Returns updated analysis reflecting LDL improvement!
Cache: Stores new response with key "session123:v1:biggest health issues"
```

## What Gets Invalidated

### ✅ Automatically Invalidated
- **Response Cache**: Full responses to user queries
  - Invalidates when ANY user data file changes
  - Each user's cache is independent (session-aware)

### ✅ Stays Cached (Static Data)
- **Tool Result Cache**: Reference data that never changes
  - `get_biomarker_ranges` - Reference ranges
  - `get_workout_plan` - Workout templates
  - `get_supplement_info` - Supplement information

### ✅ Always Fresh (User Data)
- **Never Cached**: User-specific data always fetched fresh
  - `get_biomarkers` - User's actual values
  - `get_activity_log` - User's activity
  - `get_food_journal` - User's meals
  - `get_sleep_data` - User's sleep
  - `get_user_profile` - User's profile

## Testing Cache Invalidation

Use the provided test script:

```bash
# 1. Ask a question (gets cached)
# Visit http://localhost:5000 and ask: "What are my biggest health issues?"

# 2. Update the data
python test_cache_invalidation.py

# 3. Ask the same question again (cache invalidated, gets fresh data!)
# Visit http://localhost:5000 and ask: "What are my biggest health issues?"
```

## Console Output

When cache invalidation occurs, you'll see:

```
📝 Data file updated: biomarkers.json
🔄 Data version incremented to 1 - cache will be invalidated
```

When using cache with versioning:

```
💾 Response cached for 300s (data v0)
💾 RESPONSE CACHE HIT: Returning cached response (data v1)
```

## Benefits

1. **Data Freshness**: Users always get results reflecting their latest data
2. **Performance**: Still benefit from caching when data hasn't changed
3. **Automatic**: No manual cache clearing required
4. **Session-Aware**: Each user's cache is independent
5. **Transparent**: Clear logging shows when invalidation occurs

## Future Enhancements

Possible improvements:

1. **Per-File Versioning**: Track which specific file changed, only invalidate related queries
2. **Partial Invalidation**: Clear only caches that depend on the changed data
3. **Webhook Integration**: Trigger invalidation via API when external systems update data
4. **Admin Dashboard**: Manual cache control and monitoring

## Technical Details

- **Thread-Safe**: All cache operations use locks for concurrent requests
- **Memory Efficient**: Old cache entries automatically cleaned up (max 1000 entries)
- **Low Overhead**: File mtime checks are fast (~0.001s per file)
- **No False Positives**: Only real file modifications trigger invalidation

