# Media Player Mute Status and Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the primary media player's confirmed mute state in the existing Volume tab icon and add a separate, capability-gated mute toggle between the volume-down and volume-up buttons.

**Architecture:** Extend the existing pure volume-capability policy, then carry mute through the pooled `MediaPlaybackState` used by every Media control context for a primary entity. The popup renders only confirmed Home Assistant state, sends `media_player.volume_mute` to the primary entity, and uses a 1,500 ms confirmation timeout without optimistic visual changes.

**Tech Stack:** C++17 header-only ESPHome/LVGL firmware, Home Assistant native API subscriptions/actions, Python 3.12 integration harnesses, CMake/CTest, pytest/ruff/npm orchestration through the repository `uv` environment.

## Global Constraints

- Use Home Assistant feature bit `VOLUME_MUTE = 8`, attribute `is_volume_muted`, and service `media_player.volume_mute` with boolean data key `is_volume_muted`.
- Status and actions always use the Media card's primary `media_player`; do not aggregate or address speaker-group members.
- Show **Volume Off** only when mute support and a true mute value are both confirmed; otherwise show **Volume High**.
- Keep the mute button separate from the Volume tab icon and place it in the balanced footer `volume down | mute | volume up`.
- Hide the mute button when support is unknown or known unsupported; show it disabled when support is confirmed but mute state is unknown.
- Keep the button inactive while unmuted and use the card accent colour while muted.
- Do not optimistically change mute status. Disable the button pending confirmation and clear pending after a matching update or after exactly 1,500 ms.
- A valid non-matching Home Assistant update remains visible and authoritative while the pending window continues; malformed values clear known state without changing the last confirmed boolean.
- Do not retry timed-out actions automatically.
- Preserve volume arc, percentage, maximum-volume, volume-step, popup-tab, card configuration, web-editor, and migration behavior.
- Manage Python only through `.python-version`, `pyproject.toml`, and `uv`; run commands with `env -u VIRTUAL_ENV` so an inherited environment cannot override the worktree `.venv`.
- Do not flash `192.168.1.118` until the user explicitly confirms the OTA write immediately before it occurs.

---

### Task 1: Mute capability policy and Home Assistant action

**Files:**

- Modify: `components/espcontrol/media_volume_capability.h`
- Modify: `components/espcontrol/button_grid_actions.h`
- Test: `tests/firmware/media_volume_capability_test.cpp`

**Interfaces:**

- Consumes: `send_media_player_action(const std::string &, const char *, const char *, const char *)` from `button_grid_actions.h`.
- Produces: `constexpr int espcontrol::media::SUPPORT_VOLUME_MUTE = 8`.
- Produces: `bool espcontrol::media::volume_mute_supported(bool supported_features_known, int supported_features)`.
- Produces: `bool espcontrol::media::parse_volume_mute_state(const std::string &value, bool &muted)`.
- Produces: `void send_media_mute_action(const std::string &entity_id, bool muted)`.

- [ ] **Step 1: Add failing capability and parser assertions**

Add `<string>` to the test and extend `main()` in `tests/firmware/media_volume_capability_test.cpp` with these imports and assertions:

```cpp
using espcontrol::media::SUPPORT_VOLUME_MUTE;
using espcontrol::media::parse_volume_mute_state;
using espcontrol::media::volume_mute_supported;

assert(!volume_mute_supported(false, SUPPORT_VOLUME_MUTE));
assert(!volume_mute_supported(true, 0));
assert(volume_mute_supported(true, SUPPORT_VOLUME_MUTE));
assert(volume_mute_supported(
  true, SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE));

bool muted = false;
assert(parse_volume_mute_state("true", muted) && muted);
assert(parse_volume_mute_state(" FALSE ", muted) && !muted);
muted = true;
for (const std::string &value : {
       "", "none", "null", "unknown", "unavailable", "on", "0"}) {
  assert(!parse_volume_mute_state(value, muted));
  assert(muted);  // Invalid input must not overwrite the last confirmed value.
}
```

- [ ] **Step 2: Run the focused test and confirm the red state**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run cmake -S tests/firmware -B build/tests/firmware
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run cmake --build build/tests/firmware --target media_volume_capability_test
```

Expected: compilation fails because `SUPPORT_VOLUME_MUTE`, `volume_mute_supported`, and `parse_volume_mute_state` do not exist.

- [ ] **Step 3: Implement the pure mute policy**

Add the required standard headers, constant, and helpers to `components/espcontrol/media_volume_capability.h`:

```cpp
#include <cctype>
#include <cstdint>
#include <string>

constexpr int SUPPORT_VOLUME_MUTE = 8;

inline bool volume_mute_supported(bool supported_features_known,
                                  int supported_features) {
  return supported_features_known &&
         (supported_features & SUPPORT_VOLUME_MUTE) != 0;
}

inline bool parse_volume_mute_state(const std::string &value, bool &muted) {
  size_t start = 0;
  while (start < value.size() &&
         std::isspace(static_cast<unsigned char>(value[start]))) {
    start++;
  }
  size_t end = value.size();
  while (end > start &&
         std::isspace(static_cast<unsigned char>(value[end - 1]))) {
    end--;
  }
  std::string normalized = value.substr(start, end - start);
  for (char &ch : normalized) {
    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
  }
  if (normalized == "true") {
    muted = true;
    return true;
  }
  if (normalized == "false") {
    muted = false;
    return true;
  }
  return false;
}
```

Keep these inside `namespace espcontrol::media`; do not interpret volume level zero as mute.

- [ ] **Step 4: Add the mute action helper**

Place this beside the Shuffle, Repeat, and Volume helpers in `components/espcontrol/button_grid_actions.h`:

```cpp
inline void send_media_mute_action(const std::string &entity_id,
                                   bool muted) {
  send_media_player_action(
    entity_id, "media_player.volume_mute", "is_volume_muted",
    muted ? "true" : "false");
}
```

- [ ] **Step 5: Run the focused capability test and confirm green**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run cmake --build build/tests/firmware --target media_volume_capability_test
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run ctest --test-dir build/tests/firmware -R '^media_volume_capability_test$' --output-on-failure
```

Expected: build succeeds and `1/1` test passes.

- [ ] **Step 6: Commit the policy boundary**

```bash
git add components/espcontrol/media_volume_capability.h components/espcontrol/button_grid_actions.h tests/firmware/media_volume_capability_test.cpp
git commit -m "feat: add media mute capability policy"
```

---

### Task 2: Shared mute state and conditional Home Assistant subscription

**Files:**

- Modify: `components/espcontrol/button_grid_media.h`
- Create: `tests/firmware/media_mute_control_test.py`
- Modify: `tests/firmware/CMakeLists.txt`

**Interfaces:**

- Consumes: `volume_mute_supported(...)` and `parse_volume_mute_state(...)` from Task 1.
- Produces in `MediaPlaybackState`: `bool mute_subscribed`, `bool mute_known`, and `bool muted`.
- Produces in `MediaControlCtx`: `bool mute_known`, `bool muted`, `bool mute_pending`, `bool mute_pending_target`, and `uint32_t mute_pending_until_ms`.
- Produces: `bool media_playback_subscribe_mute(MediaPlaybackState *)`, called by `media_playback_subscribe_modes(...)`, to own the single conditional `is_volume_muted` subscription per primary entity.
- Produces: `void media_playback_update_mute_state(MediaPlaybackState *, const std::string &)`, `void media_playback_apply_mute_to_control(MediaPlaybackState *, MediaControlCtx *)`, and `void media_playback_apply_mute_to_controls(MediaPlaybackState *)`.
- Extends: `media_playback_apply_state_to_control(MediaPlaybackState *, MediaControlCtx *)` to call the focused mute propagation helper.

- [ ] **Step 1: Create the failing production-function integration harness**

Create `tests/firmware/media_mute_control_test.py` using the repository's existing `definition()` extractor from `generate_media_lifecycle_integration.py`. Start it with:

```python
#!/usr/bin/env python3
"""Exercise production mute subscription, propagation, action, and UI policy."""
from pathlib import Path
import os
import subprocess
import tempfile

from generate_media_lifecycle_integration import definition

root = Path(__file__).resolve().parents[2]
media = (root / 'components/espcontrol/button_grid_media.h').read_text()
actions = (root / 'components/espcontrol/button_grid_actions.h').read_text()
source = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>
#include "media_volume_capability.h"

namespace esphome {
uint32_t now = 1000;
uint32_t millis() { return now; }
class StringRef {
 public:
  explicit StringRef(const char *value) : value_(value) {}
  const char *c_str() const { return value_; }
 private:
  const char *value_;
};
}

std::string string_ref_limited(esphome::StringRef value, size_t) {
  return value.c_str();
}
constexpr size_t HA_SHORT_STATE_MAX_LEN = 64;

struct MediaControlCtx {
  std::string entity_id;
  bool available = true;
  bool state_known = true;
  bool supported_features_known = false;
  int supported_features = 0;
  bool mute_known = false;
  bool muted = false;
  bool mute_pending = false;
  bool mute_pending_target = false;
  uint32_t mute_pending_until_ms = 0;
  uint32_t accent_color = 0x336699;
};

struct MediaPlaybackState {
  uint32_t generation = 1;
  std::string entity_id;
  bool supported_features_known = false;
  int supported_features = 0;
  bool mute_subscribed = false;
  bool mute_known = false;
  bool muted = false;
  std::vector<MediaControlCtx *> controls;
};

uint32_t ha_subscription_generation() { return 1; }
bool media_playback_generation_valid(MediaPlaybackState *state,
                                     uint32_t generation) {
  return state && state->generation == generation;
}

struct AttributeSubscription {
  std::string entity_id;
  std::string attribute;
  std::function<void(esphome::StringRef)> callback;
};
std::vector<AttributeSubscription> subscriptions;
int reannounce_count = 0;

void ha_subscribe_attribute(
    const std::string &entity_id,
    const std::string &attribute,
    std::function<void(esphome::StringRef)> callback) {
  subscriptions.push_back({entity_id, attribute, std::move(callback)});
}
void ha_reannounce_state_subscriptions() { reannounce_count++; }
'''
```

Append unchanged production definitions for the focused helpers:

```python
for name in (
    'media_playback_apply_mute_to_control',
    'media_playback_apply_mute_to_controls',
    'media_playback_update_mute_state',
    'media_playback_subscribe_mute',
):
    line, body = definition(media, name)
    source += f'\n#line {line} "button_grid_media.h"\n{body}\n'
```

Add exact C++ assertions covering subscription ownership and state propagation:

```cpp
source += r'''
int main() {
MediaPlaybackState state;
state.generation = ha_subscription_generation();
state.entity_id = "media_player.primary";
MediaControlCtx first;
MediaControlCtx second;
first.entity_id = second.entity_id = state.entity_id;
state.controls = {&first, &second};

state.supported_features_known = false;
assert(!media_playback_subscribe_mute(&state));
assert(subscriptions.empty());

state.supported_features_known = true;
state.supported_features = espcontrol::media::SUPPORT_VOLUME_MUTE;
if (media_playback_subscribe_mute(&state)) ha_reannounce_state_subscriptions();
if (media_playback_subscribe_mute(&state)) ha_reannounce_state_subscriptions();
assert(state.mute_subscribed);
assert(std::count_if(
  subscriptions.begin(), subscriptions.end(),
  [](const AttributeSubscription &item) {
    return item.entity_id == "media_player.primary" &&
           item.attribute == "is_volume_muted";
  }) == 1);
assert(reannounce_count == 1);

subscriptions.back().callback(esphome::StringRef("true"));
assert(state.mute_known && state.muted);
assert(first.mute_known && first.muted);
assert(second.mute_known && second.muted);

subscriptions.back().callback(esphome::StringRef("unknown"));
assert(!state.mute_known && state.muted);
assert(!first.mute_known && first.muted);
assert(!second.mute_known && second.muted);
return 0;
}
'''
```

Finally add source assertions proving the focused helper is wired into the existing lifecycle rather than remaining dead code:

```python
assert 'state->mute_subscribed = false;' in media
assert 'state->mute_known = false;' in media
assert 'state->muted = false;' in media
assert 'if (media_playback_subscribe_mute(state))' in media
assert 'media_playback_apply_mute_to_control(state, ctx);' in media
```

The Python wrapper must compile with the same strict flags as existing harnesses and run the binary:

```python
with tempfile.TemporaryDirectory(prefix='media-mute-control-') as directory:
    path = Path(directory)
    (path / 'test.cpp').write_text(source)
    subprocess.run([
        os.environ.get('CXX', 'c++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-I', str(root / 'components/espcontrol'), str(path / 'test.cpp'),
        '-o', str(path / 'test')
    ], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('Production media mute state and control passed')
```

- [ ] **Step 2: Register and run the integration test to verify it fails**

Append this beside the other Media Python tests in `tests/firmware/CMakeLists.txt`:

```cmake
add_test(NAME media_mute_control_test COMMAND
  ${CMAKE_COMMAND} -E env "CXX=${CMAKE_CXX_COMPILER}"
  ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/media_mute_control_test.py)
```

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python tests/firmware/media_mute_control_test.py
```

Expected: generated C++ compilation fails because the shared and control mute fields and mute subscription do not exist.

- [ ] **Step 3: Add and reset the shared and consumer state**

Add these fields to `MediaControlCtx` immediately after the existing volume/capability state:

```cpp
bool mute_known = false;
bool muted = false;
bool mute_pending = false;
bool mute_pending_target = false;
uint32_t mute_pending_until_ms = 0;
```

Add these fields to `MediaPlaybackState` next to `volume_subscribed` and `volume_known` respectively:

```cpp
bool mute_subscribed = false;
bool mute_known = false;
bool muted = false;
```

Reset them in `media_playback_reset_state(...)`:

```cpp
state->mute_subscribed = false;
state->mute_known = false;
state->muted = false;
```

- [ ] **Step 4: Subscribe once after capability discovery**

Add a focused subscription helper before `media_playback_subscribe_modes(...)`:

```cpp
inline void media_playback_apply_mute_to_control(
    MediaPlaybackState *state, MediaControlCtx *ctx) {
  if (!state || !ctx) return;
  const bool supported = espcontrol::media::volume_mute_supported(
    state->supported_features_known, state->supported_features);
  ctx->mute_known = supported && state->mute_known;
  ctx->muted = state->muted;
  if (ctx->mute_pending && ctx->mute_known &&
      ctx->muted == ctx->mute_pending_target) {
    ctx->mute_pending = false;
    ctx->mute_pending_until_ms = 0;
  }
}

inline void media_playback_apply_mute_to_controls(MediaPlaybackState *state) {
  if (!state) return;
  for (MediaControlCtx *ctx : state->controls) {
    media_playback_apply_mute_to_control(state, ctx);
  }
}

inline void media_playback_update_mute_state(MediaPlaybackState *state,
                                              const std::string &value) {
  if (!state) return;
  bool muted = state->muted;
  state->mute_known =
    espcontrol::media::parse_volume_mute_state(value, muted);
  if (state->mute_known) state->muted = muted;
  media_playback_apply_mute_to_controls(state);
}

inline bool media_playback_subscribe_mute(MediaPlaybackState *state) {
  if (!state || state->controls.empty() || state->entity_id.empty() ||
      state->mute_subscribed ||
      !espcontrol::media::volume_mute_supported(
        state->supported_features_known, state->supported_features)) {
    return false;
  }
  state->mute_subscribed = true;
  const std::string entity_id = state->entity_id;
  const uint32_t generation = state->generation;
  ha_subscribe_attribute(
    entity_id, std::string("is_volume_muted"),
    std::function<void(esphome::StringRef)>(
      [state, generation](esphome::StringRef value) {
        if (!media_playback_generation_valid(state, generation)) return;
        media_playback_update_mute_state(
          state, string_ref_limited(value, HA_SHORT_STATE_MAX_LEN));
      })
  );
  return true;
}
```

Because `media_playback_apply_state_to_control(...)` appears earlier in the header, add these declarations with the existing media playback forward declarations:

```cpp
inline void media_playback_apply_mute_to_control(
  MediaPlaybackState *state, MediaControlCtx *ctx);
inline void media_playback_apply_mute_to_controls(MediaPlaybackState *state);
inline void media_playback_update_mute_state(
  MediaPlaybackState *state, const std::string &value);
inline bool media_playback_subscribe_mute(MediaPlaybackState *state);
```

In `media_playback_subscribe_modes(...)`, add:

```cpp
if (media_playback_subscribe_mute(state)) subscription_added = true;
```

Retain the existing single `if (subscription_added) ha_reannounce_state_subscriptions();` after all optional subscriptions. The existing `supported_features` callback already invokes `media_playback_subscribe_modes(state)` for control consumers, so do not add a second capability subscription.

- [ ] **Step 5: Propagate confirmed mute state without optimistic mutation**

In `media_playback_apply_state_to_control(...)`, immediately after copying supported features, call:

```cpp
media_playback_apply_mute_to_control(state, ctx);
```

Do not clear pending for a valid non-matching value and do not overwrite `muted` when parsing failed.

- [ ] **Step 6: Run the shared-state integration test and focused CTest selection**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python tests/firmware/media_mute_control_test.py
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run cmake -S tests/firmware -B build/tests/firmware
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run ctest --test-dir build/tests/firmware -R '^media_(volume_capability|mute_control)_test$' --output-on-failure
```

Expected: the direct harness prints `Production media mute state and control passed`; CTest reports both selected tests passed.

- [ ] **Step 7: Commit shared mute ownership**

```bash
git add components/espcontrol/button_grid_media.h tests/firmware/media_mute_control_test.py tests/firmware/CMakeLists.txt
git commit -m "feat: subscribe to media mute state"
```

---

### Task 3: Volume tab status icon, mute button, and confirmation timeout

**Files:**

- Modify: `components/espcontrol/button_grid_media.h`
- Modify: `tests/firmware/media_mute_control_test.py`

**Interfaces:**

- Consumes: `send_media_mute_action(...)` from Task 1 and mute state fields from Task 2.
- Produces: `bool media_control_mute_supported(const MediaControlCtx *)`.
- Produces: `bool media_control_mute_pending_active(MediaControlCtx *)`.
- Produces: `void media_control_refresh_mute(MediaControlCtx *)`.
- Produces: `void media_control_send_mute_action(MediaControlCtx *)`.
- Produces in `MediaControlModalUi`: `lv_obj_t *volume_mute_btn` and `lv_timer_t *mute_pending_timer`.

- [ ] **Step 1: Extend the integration harness with failing UI/action assertions**

Add LVGL fixture state that records label text, hidden/disabled flags, button colour, timer creation/deletion, and sent Home Assistant action data. Extract unchanged production definitions for the new helpers once named:

```python
for name in (
    'media_control_mute_supported',
    'media_control_mute_pending_active',
    'media_control_refresh_mute',
    'media_control_mute_pending_timer_cb',
    'media_control_send_mute_action',
):
    line, body = definition(media, name)
    source += f'\n#line {line} "button_grid_media.h"\n{body}\n'
```

Extract `send_media_mute_action` from `button_grid_actions.h` and use a `send_media_player_action` stub that records all four arguments. Add these exact behavioral assertions to generated `main()`:

```cpp
MediaControlCtx ctx;
ctx.entity_id = "media_player.primary";
ctx.available = true;
ctx.supported_features_known = true;
ctx.supported_features = espcontrol::media::SUPPORT_VOLUME_MUTE;
ctx.mute_known = true;
ctx.muted = false;
MediaControlModalUi &ui = media_control_modal_ui();
ui.active = &ctx;
ui.volume_tab = make_test_button();
ui.volume_mute_btn = make_test_button();

media_control_refresh_mute(&ctx);
assert(button_label(ui.volume_tab) == find_icon("Volume High"));
assert(!button_hidden(ui.volume_mute_btn));
assert(button_enabled(ui.volume_mute_btn));
assert(!button_accented(ui.volume_mute_btn));

media_control_send_mute_action(&ctx);
assert(sent_entity == "media_player.primary");
assert(sent_service == "media_player.volume_mute");
assert(sent_key == "is_volume_muted" && sent_value == "true");
assert(ctx.mute_pending && ctx.mute_pending_target);
assert(ctx.mute_pending_until_ms == esphome::now + 1500);
assert(!button_enabled(ui.volume_mute_btn));
assert(button_label(ui.volume_tab) == find_icon("Volume High"));
assert(!button_accented(ui.volume_mute_btn));

const int sends_while_pending = action_send_count;
media_control_send_mute_action(&ctx);
assert(action_send_count == sends_while_pending);

ctx.muted = true;
ctx.mute_pending = false;
ctx.mute_pending_until_ms = 0;
media_control_refresh_mute(&ctx);
assert(button_label(ui.volume_tab) == find_icon("Volume Off"));
assert(button_accented(ui.volume_mute_btn));

ctx.mute_known = false;
media_control_refresh_mute(&ctx);
assert(button_label(ui.volume_tab) == find_icon("Volume High"));
assert(!button_enabled(ui.volume_mute_btn));

ctx.supported_features = 0;
media_control_refresh_mute(&ctx);
assert(button_hidden(ui.volume_mute_btn));
assert(button_label(ui.volume_tab) == find_icon("Volume High"));

ctx.supported_features = espcontrol::media::SUPPORT_VOLUME_MUTE;
ctx.mute_known = true;
ctx.muted = true;
ctx.mute_pending = true;
ctx.mute_pending_target = false;
ctx.mute_pending_until_ms = esphome::now + 1500;
media_control_refresh_mute(&ctx);
assert(button_label(ui.volume_tab) == find_icon("Volume Off"));
assert(button_accented(ui.volume_mute_btn));
assert(!button_enabled(ui.volume_mute_btn));

esphome::now += 1500;
media_control_mute_pending_timer_cb(ui.mute_pending_timer);
assert(!ctx.mute_pending && ctx.mute_pending_until_ms == 0);
assert(ui.mute_pending_timer == nullptr);
assert(button_enabled(ui.volume_mute_btn));
```

Also add source-level assertions in the Python test for the parts best protected structurally:

```python
assert 'ui.volume_mute_btn = control_modal_create_round_button(' in media
assert 'find_icon("Volume Off")' in media
assert 'ui.volume_minus_btn, ui.volume_mute_btn, ui.volume_plus_btn' in media
assert 'lv_timer_del(ui.mute_pending_timer)' in media
assert 'ui.volume_mute_btn = nullptr;' in media
```

- [ ] **Step 2: Run the harness and verify the UI/action red state**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python tests/firmware/media_mute_control_test.py
```

Expected: compilation or source assertion fails because the mute UI helpers and widgets do not exist.

- [ ] **Step 3: Add popup fields and pending-state helpers**

Add to `MediaControlModalUi` beside the existing Volume widgets:

```cpp
lv_obj_t *volume_mute_btn = nullptr;
lv_timer_t *mute_pending_timer = nullptr;
```

Add this constant and helpers near the existing volume pending helpers:

```cpp
constexpr uint32_t MEDIA_MUTE_PENDING_TIMEOUT_MS = 1500;

inline bool media_control_mute_supported(const MediaControlCtx *ctx) {
  return ctx && espcontrol::media::volume_mute_supported(
    ctx->supported_features_known, ctx->supported_features);
}

inline bool media_control_mute_pending_active(MediaControlCtx *ctx) {
  if (!ctx || !ctx->mute_pending) return false;
  if (ctx->mute_pending_until_ms != 0 &&
      (int32_t)(ctx->mute_pending_until_ms - esphome::millis()) > 0) {
    return true;
  }
  ctx->mute_pending = false;
  ctx->mute_pending_until_ms = 0;
  return false;
}
```

- [ ] **Step 4: Render confirmed mute state and fallback tab icon**

Implement `media_control_refresh_mute(...)` beside `media_control_refresh_volume(...)`:

```cpp
inline void media_control_refresh_mute(MediaControlCtx *ctx) {
  MediaControlModalUi &ui = media_control_modal_ui();
  if (!ctx || ui.active != ctx) return;
  const bool supported = media_control_mute_supported(ctx);
  const bool confirmed_muted = supported && ctx->mute_known && ctx->muted;
  if (ui.volume_tab) {
    lv_obj_t *label = control_modal_icon_label(ui.volume_tab);
    if (label) {
      lv_label_set_display_text(
        label, find_icon(confirmed_muted ? "Volume Off" : "Volume High"));
    }
  }
  if (!ui.volume_mute_btn) return;
  if (supported) lv_obj_clear_flag(ui.volume_mute_btn, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_add_flag(ui.volume_mute_btn, LV_OBJ_FLAG_HIDDEN);
  media_control_style_playback_mode_button(
    ui.volume_mute_btn, confirmed_muted,
    supported && ctx->available && ctx->state_known && ctx->mute_known &&
      !media_control_mute_pending_active(ctx),
    ctx->accent_color);
}
```

Add a forward declaration if required by header order. Call it from `media_control_refresh_modal(...)` and from the open-modal state-application path so the tab icon changes even while another tab is selected.

- [ ] **Step 5: Send one action and wait for Home Assistant confirmation**

Implement a one-shot callback and action helper:

```cpp
inline void media_control_mute_pending_timer_cb(lv_timer_t *timer) {
  MediaControlModalUi &ui = media_control_modal_ui();
  if (ui.mute_pending_timer == timer) ui.mute_pending_timer = nullptr;
  if (ui.active) {
    ui.active->mute_pending = false;
    ui.active->mute_pending_until_ms = 0;
    media_control_refresh_mute(ui.active);
  }
  if (timer) lv_timer_del(timer);
}

inline void media_control_send_mute_action(MediaControlCtx *ctx) {
  if (!ctx || !ctx->available || !ctx->state_known || !ctx->mute_known ||
      !media_control_mute_supported(ctx) ||
      media_control_mute_pending_active(ctx)) return;
  ctx->mute_pending = true;
  ctx->mute_pending_target = !ctx->muted;
  ctx->mute_pending_until_ms =
    esphome::millis() + MEDIA_MUTE_PENDING_TIMEOUT_MS;
  MediaControlModalUi &ui = media_control_modal_ui();
  if (ui.mute_pending_timer) lv_timer_del(ui.mute_pending_timer);
  ui.mute_pending_timer = lv_timer_create(
    media_control_mute_pending_timer_cb, MEDIA_MUTE_PENDING_TIMEOUT_MS, nullptr);
  send_media_mute_action(ctx->entity_id, ctx->mute_pending_target);
  media_control_refresh_mute(ctx);
}
```

At the start of `media_playback_apply_state_to_control(...)`, retain `const bool mute_was_pending = ctx->mute_pending;`. After `media_playback_apply_mute_to_control(state, ctx)` and after the function obtains `MediaControlModalUi &ui`, cancel the one-shot timer only when a matching update cleared pending:

```cpp
if (mute_was_pending && !ctx->mute_pending &&
    ui.active == ctx && ui.mute_pending_timer) {
  lv_timer_del(ui.mute_pending_timer);
  ui.mute_pending_timer = nullptr;
}
```

Leave a non-matching update pending until the callback.

- [ ] **Step 6: Create and wire the separate mute button**

In `media_control_create_volume_tab_content(...)`, create the middle round button only when `media_control_mute_supported(ctx)` is true:

```cpp
if (media_control_mute_supported(ctx)) {
  ui.volume_mute_btn = control_modal_create_round_button(
    ui.content_box, 56, find_icon("Volume Off"), ctx->icon_font,
    theme_display_color(current_theme().border),
    theme_display_color(current_theme().surface_primary),
    ctx->width_compensation_percent);
  if (ui.volume_mute_btn) {
    lv_obj_add_event_cb(ui.volume_mute_btn, [](lv_event_t *) {
      media_control_send_mute_action(media_control_modal_ui().active);
    }, LV_EVENT_CLICKED, nullptr);
  }
}
```

Keep the minus and plus callbacks unchanged. End the function with both:

```cpp
media_control_refresh_volume_controls(ctx);
media_control_refresh_mute(ctx);
```

- [ ] **Step 7: Lay out two or three buttons without changing the volume arc**

Replace the two-button layout call in the Volume section of `media_control_layout_modal(...)` with explicit balanced positioning. This repeats the existing compact-landscape size and icon rules while allowing either two or three buttons:

```cpp
lv_obj_t *volume_buttons[3] = {
  ui.volume_minus_btn, ui.volume_mute_btn, ui.volume_plus_btn
};
const int visible_volume_buttons = ui.volume_mute_btn ? 3 : 2;
lv_coord_t button_size = volume_buttons_layout.btn_size;
if (compact_landscape) {
  lv_coord_t compact_size = control_modal_scaled_px(
    56, volume_buttons_layout.short_side);
  if (compact_size < volume_buttons_layout.profile.base_touch_target) {
    compact_size = volume_buttons_layout.profile.base_touch_target;
  }
  if (button_size > compact_size) button_size = compact_size;
}
const lv_coord_t gap = volume_buttons_layout.controls_gap;
const lv_coord_t total_width =
  visible_volume_buttons * button_size +
  (visible_volume_buttons - 1) * gap;
lv_coord_t button_x = -total_width / 2 + button_size / 2;
for (lv_obj_t *button : volume_buttons) {
  if (!button) continue;
  lv_obj_set_size(button, button_size, button_size);
  lv_obj_set_style_radius(button, button_size / 2, LV_PART_MAIN);
  lv_obj_align(
    button, LV_ALIGN_CENTER, button_x,
    volume_buttons_layout.controls_center_y);
  lv_obj_t *label = lv_obj_get_child(button, 0);
  if (label) {
    lv_obj_set_style_transform_zoom(
      label, compact_landscape ? 200 : 256, LV_PART_MAIN);
    control_modal_center_tab_icon(label);
  }
  button_x += button_size + gap;
}
```

Do not change `control_modal_apply_step_buttons_layout(...)`; other modal types still use its two-button contract.

- [ ] **Step 8: Rebuild only when capability changes button visibility**

At the start of `media_playback_apply_state_to_control(...)`, retain the old support value:

```cpp
const bool previous_mute_supported = media_control_mute_supported(ctx);
```

After supported features are copied, calculate `mute_supported`. In the active-popup block:

```cpp
const bool mute_capability_changed =
  previous_mute_supported != mute_supported;
if (mute_capability_changed && ui.tab == MediaControlTab::VOLUME) {
  media_control_clear_tab_content();
}
layout_needed = layout_needed || mute_capability_changed;
media_control_refresh_mute(ctx);
```

Ordinary true/false/unknown updates must call `media_control_refresh_mute(ctx)` without clearing or rebuilding the tab.

- [ ] **Step 9: Cancel the timer and clear widget pointers during popup cleanup**

At the top of `media_control_clear_tab_content()`:

```cpp
if (ui.mute_pending_timer) {
  lv_timer_del(ui.mute_pending_timer);
  ui.mute_pending_timer = nullptr;
}
```

In its Volume pointer reset block:

```cpp
ui.volume_mute_btn = nullptr;
```

Do not clear `MediaControlCtx::mute_pending` merely because the user changes tabs; the time-based helper or a matching Home Assistant update remains authoritative.

- [ ] **Step 10: Run the mute harness and relevant Media regression tests**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python tests/firmware/media_mute_control_test.py
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run cmake -S tests/firmware -B build/tests/firmware
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run ctest --test-dir build/tests/firmware -R '^media_(volume_capability|mute_control|control_tabs_runtime|speaker_volume_event|power_override)_test$' --output-on-failure
```

Expected: the direct harness passes and all five selected CTest tests pass. Confirm the harness proves unsupported/unknown/true/false, pending duplicate suppression, matching confirmation, non-matching authoritative display, timeout, primary-entity routing, and cleanup.

- [ ] **Step 11: Commit the popup behavior**

```bash
git add components/espcontrol/button_grid_media.h tests/firmware/media_mute_control_test.py
git commit -m "feat: show and control media mute state"
```

---

### Task 4: User documentation and full local verification

**Files:**

- Modify: `docs/card-types/media.md`

**Interfaces:**

- Consumes: completed mute capability, shared state, and popup behavior from Tasks 1–3.
- Produces: user-facing explanation of automatic capability detection, status icon, separate control, and primary-entity group behavior.

- [ ] **Step 1: Add the user-facing mute behavior to Media documentation**

In `docs/card-types/media.md`, add this bullet after the existing Shuffle and Repeat bullets under **What to Expect**:

```markdown
- When the player supports mute, the Volume tab adds a mute button between volume down and volume up. The tab icon changes to Volume Off only after Home Assistant confirms the primary player is muted; grouped speakers continue to follow whatever mute behaviour their Home Assistant integration provides.
```

Do not describe a setting or migration because the feature is automatic and does not alter saved card configuration.

- [ ] **Step 2: Run formatting and static checks through uv**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv sync --locked
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run ruff check scripts tests
```

Expected: `uv sync --locked` succeeds and Ruff reports no errors.

- [ ] **Step 3: Run the complete repository fast-check graph**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run npm test
```

Expected: all task-graph checks pass, including all firmware CTests and web tests. Record the reported firmware and web test counts in the PR description rather than assuming the previous baseline counts.

- [ ] **Step 4: Compile the ESP32-P4 86 development firmware**

Run:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python scripts/local_esphome.py devices/esp32-p4-86/dev.yaml compile
```

Expected: ESPHome `2026.9.1` completes successfully and produces firmware for the ESP32-P4 86. This is a compile check only; do not invoke upload or OTA here.

- [ ] **Step 5: Review the diff against every acceptance rule**

Run:

```bash
git diff --check
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- components/espcontrol/media_volume_capability.h components/espcontrol/button_grid_actions.h components/espcontrol/button_grid_media.h tests/firmware docs/card-types/media.md
```

Confirm from the diff that:

```text
Volume Off requires supported + known + true.
Unknown/unsupported falls back to Volume High.
Unsupported hides the separate button; supported/unknown disables it.
The action targets ctx->entity_id and sends literal true/false.
No optimistic muted value is assigned on click.
Pending is 1500 ms, suppresses duplicate taps, clears on match or timeout.
No group-member mute loop exists.
No src/webserver card contract, configuration, or migration file changed.
Cleanup deletes the timer and clears the LVGL pointer.
```

Expected: `git diff --check` prints nothing and each acceptance rule is directly visible in implementation or tests.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/card-types/media.md
git commit -m "docs: explain media mute controls"
```

- [ ] **Step 7: Push the tested branch and open a ready-for-review PR**

```bash
git push
gh pr create --base main --head add-media-mute-control --title "Add media player mute status and control" --body-file /tmp/media-mute-pr.md
```

Before the command, create `/tmp/media-mute-pr.md` with `apply_patch` using this exact body:

```markdown
## Purpose

Show confirmed mute state on the Media popup's Volume tab and add a separate mute toggle for players that advertise Home Assistant mute support.

## Practical impact

- Volume Off appears only for a confirmed muted primary player.
- Supported players get a mute button between volume down and volume up.
- Actions wait for Home Assistant confirmation and time out safely after 1.5 seconds.
- Unsupported players keep the existing two-button volume footer.

## Automated checks

- `uv run npm test` — passed
- ESP32-P4 86 development compile with ESPHome 2026.9.1 — passed

## Physical testing still required

Do not merge yet. The ESP32-P4 86 at `192.168.1.118` still needs user-confirmed OTA installation and testing against a mute-capable primary media player.
```

Expected: the branch is pushed and the PR is open, ready for review, but remains unmerged.

---

### Task 5: User-confirmed physical device validation

**Files:** None.

**Interfaces:**

- Consumes: the compiled ESP32-P4 86 firmware and open PR from Task 4.
- Produces: user-confirmed hardware behavior required before merge.

- [ ] **Step 1: Stop and request explicit OTA confirmation**

Report the compile result, current device target `192.168.1.118`, and that OTA will replace its running firmware. Do not run an upload command until the user answers affirmatively at this checkpoint.

- [ ] **Step 2: After confirmation, upload through the pinned uv environment**

Run only after Step 1 is approved:

```bash
env -u VIRTUAL_ENV UV_CACHE_DIR=/tmp/espcontrol-uv-cache uv run python scripts/local_esphome.py devices/esp32-p4-86/dev.yaml upload --device 192.168.1.118
```

Expected: ESPHome reports a successful OTA upload and the panel reconnects.

- [ ] **Step 3: Ask the user to complete the focused hardware checklist**

Provide this checklist verbatim:

```text
1. Open All Controls and select Volume.
2. Mute/unmute in Home Assistant: tab icon and button styling update live.
3. Tap the panel mute button: HA changes the primary entity; UI waits for HA.
4. Tap rapidly: only one action is accepted during the 1.5 s pending window.
5. Delay/fail an action: button re-enables without inventing a state.
6. Check arc, percentage, maximum volume, minus, and plus are unchanged.
7. With a group, confirm only the primary entity receives the action.
8. Reopen the popup and reboot: current HA mute state is restored.
```

Expected: the user confirms all eight checks or reports a reproducible failure. Leave the PR open and do not close related issues until the user confirms success.
