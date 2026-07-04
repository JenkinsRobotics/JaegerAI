---
name: home-assistant
description: "Read and control smart-home devices through a Home Assistant instance (REST API). Load this for 'turn on the lights', 'set the thermostat', 'is the door locked', 'what's the temperature in the bedroom' — anything Home Assistant manages. For Philips Hue WITHOUT Home Assistant, use openhue instead."
version: 1.0.0
platforms: [macos, linux, windows]
requires_tools: [ha_list_entities, ha_get_state, ha_list_services, ha_call_service]
metadata:
  jros:
    tags: [Smart-Home, Home-Assistant, IoT, Lights, Climate, Locks, Automation]
    category: smart-home
    related_skills: [openhue]
---

# HOME ASSISTANT

Read + control every device a Home Assistant instance manages, over its REST
API. Entities are named `domain.object_id` (`light.living_room`,
`climate.thermostat`, `lock.front_door`, `sensor.bedroom_temperature`).
Reads are free; `ha_call_service` changes the real world and is
permission-gated.

## TOOLS

- `ha_list_entities(domain="", area="")` — find devices. `domain` = 'light',
  'switch', 'climate', 'sensor', 'binary_sensor', 'cover', 'lock', 'fan',
  'media_player'. `area` matches room names in friendly names.
- `ha_get_state(entity_id="light.living_room")` — one entity, full attributes
  (brightness, setpoint, lock state, battery).
- `ha_list_services(domain="light")` — what actions a domain supports and the
  fields each accepts.
- `ha_call_service(domain="light", service="turn_on",
  entity_id="light.living_room", data_json='{"brightness": 128}')` — do it.
  `data_json` is an optional JSON-object string.

## SOP

1. FIND the entity: `ha_list_entities(domain="light", area="living room")`.
   Never guess an entity_id — always confirm it exists first.
2. READ before you write when the request depends on current state
   ("is the door locked", "how warm is it"): `ha_get_state(entity_id=...)`.
   For a pure read request, answer from the state and STOP here.
3. ACT: `ha_call_service(...)`. If unsure which service or fields, check
   `ha_list_services(domain=...)` first.
4. CONFIRM: the result's `affected_entities` shows the new state. If empty,
   `ha_get_state` the entity to verify, then report the outcome plainly.

## COMMON SERVICE CALLS

- Lights: `light.turn_on` / `light.turn_off` / `light.toggle`;
  data_json: `{"brightness": 0-255, "color_name": "blue"}`
- Thermostat: `climate.set_temperature` data_json `{"temperature": 21}`;
  `climate.set_hvac_mode` data_json `{"hvac_mode": "heat"}`
- Locks: `lock.lock` / `lock.unlock`
- Covers/blinds: `cover.open_cover` / `cover.close_cover`
- Media: `media_player.media_pause`, `media_player.volume_set`
  data_json `{"volume_level": 0.5}`
- Scenes/scripts: `scene.turn_on` / `script.turn_on` with entity_id, no data.

## ERROR HATCH

- `ok: false` + "not configured" → Home Assistant isn't set up. Tell the user:
  create a long-lived token (HA: Profile → Security → Long-lived access
  tokens), then save it — `set_credential(name="HASS_TOKEN", value=<token>)`
  and `set_credential(name="HASS_URL", value="http://homeassistant.local:8123")`.
  Do NOT invent a token or retry until they provide one.
- "did not answer" → the instance is down or HASS_URL is wrong; report it,
  suggest checking the URL, don't hammer retries.
- Entity not found / call errors twice → re-run `ha_list_entities()` with a
  BROADER filter (or none) and match on friendly_name; don't retry the same
  id a third time.
- Blocked domain error (shell_command etc.) → that's a deliberate safety
  wall; tell the user it's not allowed, do not look for a bypass.

## DONE WHEN

The user's question is answered from real entity state, or the requested
change is confirmed (affected_entities / re-read state shows it) and
reported back in one plain sentence.
