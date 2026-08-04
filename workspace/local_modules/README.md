# local_modules/ — project-unique modules

Modules that exist only for this workspace: full module shape (module.yaml,
node, config, tests) but unpublished. THE PROMOTION PATH: when a second
project wants one, it graduates to its own repo (git mv, history intact)
and arrives back here as a pin. Shared code is PINNED (requirements), never
vendored; unique code is a LOCAL MODULE, never loose scripts.
