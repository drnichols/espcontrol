# Media Player Mute Status and Control Design

**Date:** 2026-10-24
**Status:** Approved

## Goal

Show a media player's confirmed mute state on the existing Volume tab icon and
add a separate mute toggle inside the Volume tab of the Media card popup.

## Scope

This enhancement applies to the **All Controls** popup opened by All Controls
and Cover Art Media cards. It uses the card's primary `media_player` entity for
both status and control.

The change does not add a new Media card type, change saved card configuration,
or add web-editor settings. It does not infer mute from a zero volume level and
does not send mute actions to individual speaker-group members.

## Home Assistant Contract

Home Assistant defines `VOLUME_MUTE` as supported-feature bit `8`, publishes the
current value through the `is_volume_muted` attribute, and accepts changes through
`media_player.volume_mute` with a required boolean `is_volume_muted` value.

References:

- [Media player feature constants](https://github.com/home-assistant/core/blob/dev/homeassistant/components/media_player/const.py)
- [Media player service registration](https://github.com/home-assistant/core/blob/dev/homeassistant/components/media_player/__init__.py)
- [Media player entity properties](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/core/entity/media-player.md)

## User Experience

### Volume tab status

The existing Volume tab remains in the same position and retains its navigation
behavior. Its icon reflects only confirmed Home Assistant state:

- Show **Volume Off** when mute support is advertised, the mute attribute is
  known, and `is_volume_muted` is true.
- Show **Volume High** when mute is false, unknown, or unsupported.

The fallback deliberately avoids presenting an unknown or unsupported player as
muted.

### Separate mute control

The Volume tab footer becomes a balanced three-button row:

```text
volume down  |  mute  |  volume up
```

The middle button always uses the **Volume Off** glyph. It uses normal inactive
styling while unmuted and the Media card's accent colour while muted.

- Hide the button when `VOLUME_MUTE` is known to be unsupported.
- Show it disabled when mute is supported but `is_volume_muted` is not known.
- Enable it when the main player is available, the state is known, the feature
  is supported, and no mute action is pending.
- Keep the existing volume arc, percentage, maximum-volume behavior, and
  volume-down/volume-up capability rules unchanged.

## Architecture

Mute belongs to the existing shared media playback state rather than to the
popup itself. This preserves one Home Assistant subscription per primary entity
and lets every Media control context receive the same current value.

### Capability policy

Extend `media_volume_capability.h` with focused, pure helpers for:

- `SUPPORT_VOLUME_MUTE = 8`
- deciding whether mute is supported from known feature flags
- parsing Home Assistant boolean attribute values without treating unknown,
  unavailable, null, or empty values as false

The existing volume capability test will cover these rules.

### Shared playback state

Extend `MediaPlaybackState` with:

- `mute_subscribed`
- `mute_known`
- `muted`

Reset all three when a pooled playback state is rebound. Once
`supported_features` is known and advertises `VOLUME_MUTE`, subscribe once to
`is_volume_muted`, following the existing conditional Shuffle and Repeat
subscription pattern. Reannounce Home Assistant subscriptions when the mute
subscription is added.

Each valid mute update sets `mute_known`, stores the value, and applies the
shared state to all attached `MediaControlCtx` consumers. Invalid values clear
`mute_known` without changing the last confirmed boolean.

### Control context and popup

Extend `MediaControlCtx` with the confirmed mute state and pending-action data.
Extend `MediaControlModalUi` with the mute button and any timer needed to end a
pending action safely. Use a 1,500 ms pending timeout, matching the existing
short volume-confirmation window.

When shared state is applied to a control context:

1. Copy mute capability and confirmed state.
2. Clear a pending action immediately when Home Assistant confirms its target.
3. Refresh the Volume tab icon and Volume tab controls if this context owns the
   open popup.
4. Re-layout the open Volume tab only when mute capability changes visibility;
   ordinary state changes update styles in place.

The popup's cleanup path must cancel the pending timer and clear widget pointers
so repeated open/close cycles and card deletion cannot retain stale LVGL objects.

## Action and Confirmation Behavior

Tapping mute sends this action to the primary entity:

```yaml
action: media_player.volume_mute
target:
  entity_id: media_player.example
data:
  is_volume_muted: true
```

The boolean is the inverse of the last confirmed mute state. The helper that
builds Home Assistant actions must emit literal `true` or `false`.

The UI does not change the icon or active styling optimistically. It disables
the mute button while the action is pending:

- A matching Home Assistant update confirms the action and clears pending state.
- A valid non-matching update remains authoritative; the button stays pending
  briefly to allow integrations that report the old value before the new one.
- A one-shot timeout after 1,500 ms clears pending state and refreshes the button
  if no matching confirmation arrives.
- Unavailable or malformed updates never fabricate a mute state.

No retry is sent automatically. The user may retry after the pending timeout.

## Speaker Groups

The mute status, supported-feature check, and action target always use the Media
card's primary entity. EspControl does not aggregate group-member mute state or
send one action per member. The Home Assistant integration remains responsible
for any group-wide behavior triggered by muting the primary entity.

## Error and Compatibility Behavior

- Players without `VOLUME_MUTE` retain the current two-button minus/plus footer;
  the mute button itself is hidden.
- Before `supported_features` arrives, the tab shows **Volume High** and no mute
  action can be sent.
- If support is advertised but the attribute remains unknown, the mute button is
  visible but disabled.
- If the player becomes unavailable, all existing availability behavior remains
  authoritative and mute cannot be toggled.
- Existing configurations require no migration and older backups remain valid.

## Expected File Changes

- `components/espcontrol/media_volume_capability.h` — mute capability and state
  parsing policy.
- `components/espcontrol/button_grid_actions.h` — `media_player.volume_mute`
  action helper.
- `components/espcontrol/button_grid_media.h` — shared state, conditional
  subscription, context propagation, Volume tab icon, three-button layout,
  pending confirmation, and cleanup.
- `tests/firmware/media_volume_capability_test.cpp` — pure capability and parsing
  tests.
- `tests/firmware/media_mute_control_test.py` — production-function integration
  harness for subscription ownership, action routing, icon/button state, pending
  confirmation, timeout, and cleanup.
- `tests/firmware/CMakeLists.txt` — register the new integration test.
- `docs/card-types/media.md` — document live mute status and control.

No changes are expected in `src/webserver/cards/media.ts`, card contracts, saved
configuration parsing, or migrations.

## Verification

### Automated

1. Run the mute capability and integration tests first.
2. Run all firmware tests.
3. Run the repository fast check graph through the committed uv environment:

   ```sh
   uv sync --locked
   uv run npm test
   ```

4. Compile the ESP32-P4 86 development firmware with the repository-pinned
   ESPHome version.

### Physical device

Use the ESP32-P4 86 at `192.168.1.118`, currently observed on firmware v2.13.0.
Back up its configuration before OTA and request confirmation immediately before
writing firmware.

Verify with a mute-capable primary `media_player`:

1. Open All Controls and select Volume.
2. Mute and unmute from Home Assistant; confirm the tab icon and mute-button
   active styling follow without reopening the popup.
3. Use the new mute button; confirm Home Assistant changes the primary entity
   and the panel updates only after Home Assistant reports the result.
4. Try rapid repeat taps and confirm only one action is accepted while pending.
5. Confirm a failed or delayed action re-enables the button after timeout without
   displaying an invented state.
6. Confirm volume arc, percentage, maximum volume, and minus/plus controls still
   behave normally.
7. Test a grouped player and confirm EspControl targets only the primary entity.
8. Reopen the popup and reboot the panel; confirm the current mute state is
   restored from Home Assistant.

## Acceptance Criteria

- The Volume tab shows **Volume Off** only for a confirmed muted primary entity.
- A separate, capability-gated mute button appears between volume down and up.
- The button toggles the primary entity through `media_player.volume_mute` and
  waits for Home Assistant confirmation before changing visible state.
- Unsupported, unknown, unavailable, delayed, and grouped-player cases follow
  the fallback rules above.
- Existing Media card configuration and all non-mute volume behavior remain
  compatible.
- Automated checks pass, ESP32-P4 86 firmware compiles, and the physical test
  checklist is ready for user confirmation before merge.
