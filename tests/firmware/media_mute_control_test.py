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

for name in (
    'media_playback_apply_mute_to_control',
    'media_playback_apply_mute_to_controls',
    'media_playback_update_mute_state',
    'media_playback_subscribe_mute',
):
    line, body = definition(media, name)
    source += f'\n#line {line} "button_grid_media.h"\n{body}\n'

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

first.mute_pending = true;
first.mute_pending_target = false;
first.mute_pending_until_ms = 2000;
subscriptions.back().callback(esphome::StringRef("true"));
assert(first.mute_pending && first.mute_pending_until_ms == 2000);
subscriptions.back().callback(esphome::StringRef("unknown"));
assert(first.mute_pending && first.mute_pending_until_ms == 2000);
subscriptions.back().callback(esphome::StringRef("false"));
assert(first.mute_known && !first.muted);
assert(!first.mute_pending && first.mute_pending_until_ms == 0);
assert(second.mute_known && !second.muted);
return 0;
}
'''

assert 'state->mute_subscribed = false;' in media
assert 'state->mute_known = false;' in media
assert 'state->muted = false;' in media
assert 'if (media_playback_subscribe_mute(state))' in media
assert 'media_playback_apply_mute_to_control(state, ctx);' in media

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
