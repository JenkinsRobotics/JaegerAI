# Avatar v2 vendored libraries (no CDN)

| Library | Version | License | Source | Local change |
|---|---|---|---|---|
| three | 0.186.1 | MIT (three/0.186.1/LICENSE) | npm `three@0.186.1`: build/three.module.js, build/three.core.js, examples/jsm/loaders/GLTFLoader.js, examples/jsm/utils/BufferGeometryUtils.js, examples/jsm/utils/SkeletonUtils.js | the bare `'three'` import in the three addons is rewritten to a relative path (no import map needed) |
| @pixiv/three-vrm | 3.5.5 | MIT (three-vrm/3.5.5/LICENSE) | npm `@pixiv/three-vrm@3.5.5`: lib/three-vrm.module.min.js | bare `"three"` import rewritten to `../../three/0.186.1/three.module.js` |

The VRM model is NOT in git. It is a runtime asset at `~/.jaeger/assets/avatar/`
(override: `JAEGER_AVATAR_VRM`), served at `/api/jaeger/avatar/model.vrm`.
Default model: `VRM1_Constraint_Twist_Sample.vrm` from pixiv/three-vrm
(packages/three-vrm/examples/models, branch dev). sha256
12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2.
Embedded VRMC_vrm.meta: authors "pixiv Inc.", "(c) 2022 pixiv Inc.",
licenseUrl https://vrm.dev/licenses/1.0/ (VRM Public License 1.0),
avatarPermission everyone, commercialUsage corporation, allowRedistribution
true, modification allowModificationRedistribution, creditNotation unnecessary,
allowAntisocialOrHateUsage false.
