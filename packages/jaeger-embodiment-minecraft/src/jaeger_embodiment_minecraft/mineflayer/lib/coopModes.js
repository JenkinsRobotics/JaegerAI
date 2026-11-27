/**
 * JaegerAI Minecraft Co-Op Reflex Modes (CommonJS)
 *
 * Adapted from mindcraft-bots/mindcraft (`src/agent/modes.js`, MIT License).
 * Runs lightweight survival & companion reflexes on a 500ms timer without
 * blocking Mineflayer physics ticks:
 *   - self_preservation: swim in water, escape lava/fire, retreat at low health
 *   - auto_eat: automatically eat food from inventory when hunger drops
 *   - self_defense: fend off nearby hostile mobs (or back away from creepers)
 *   - unstuck: jump/nudge when pathfinder stalls in one spot
 *   - follow_player: continuous GoalFollow companion mode for co-op play
 */

const {
    Movements,
    goals: { GoalFollow, GoalNear, GoalInvert },
} = require("mineflayer-pathfinder");

const HOSTILE_MOBS = new Set([
    "zombie",
    "zombie_villager",
    "husk",
    "drowned",
    "skeleton",
    "stray",
    "wither_skeleton",
    "spider",
    "cave_spider",
    "creeper",
    "witch",
    "pillager",
    "vindicator",
    "phantom",
    "slime",
    "magma_cube",
    "blaze",
    "ghast",
    "silverfish",
    "endermite",
    "warden",
    "hoglin",
    "piglin_brute",
]);

const EDIBLE_KEYWORDS = [
    "cooked_",
    "bread",
    "apple",
    "golden_apple",
    "carrot",
    "golden_carrot",
    "baked_potato",
    "melon_slice",
    "sweet_berries",
    "glow_berries",
    "cookie",
    "pumpkin_pie",
    "mushroom_stew",
    "rabbit_stew",
    "beetroot_soup",
    "steak",
    "porkchop",
    "beef",
    "chicken",
    "mutton",
    "cod",
    "salmon",
    "rabbit",
    "dried_kelp",
    "honey_bottle",
];

function isEdibleItem(item) {
    if (!item || !item.name) return false;
    const name = item.name.toLowerCase();
    if (name.includes("rotten_flesh") || name.includes("spider_eye") || name.includes("pufferfish")) {
        return false;
    }
    return EDIBLE_KEYWORDS.some((kw) => name.includes(kw));
}

function findPlayerCaseInsensitive(bot, targetName) {
    if (!bot || !bot.players || !targetName) return null;
    const needle = String(targetName).trim().toLowerCase();
    for (const [uname, entry] of Object.entries(bot.players)) {
        if (uname.toLowerCase() === needle) {
            return { username: uname, player: entry };
        }
    }
    return null;
}

function findNearestHostile(bot, maxDistance) {
    if (!bot || !bot.entities || !bot.entity) return null;
    let closest = null;
    let bestDist = maxDistance;
    for (const ent of Object.values(bot.entities)) {
        if (!ent || !ent.position || ent === bot.entity) continue;
        const name = String(ent.name || "").toLowerCase();
        if (!HOSTILE_MOBS.has(name)) continue;
        const d = ent.position.distanceTo(bot.entity.position);
        if (d < bestDist) {
            bestDist = d;
            closest = ent;
        }
    }
    return closest;
}

async function equipBestWeapon(bot) {
    if (!bot || !bot.inventory) return;
    const items = bot.inventory.items();
    const priority = ["netherite_sword", "diamond_sword", "iron_sword", "stone_sword", "wooden_sword", "iron_axe", "stone_axe", "wooden_axe"];
    for (const p of priority) {
        const match = items.find((i) => i.name === p);
        if (match) {
            try {
                await bot.equip(match, "hand");
            } catch {}
            return;
        }
    }
}

class CoopModeManager {
    constructor(bot) {
        this.bot = bot;
        this.interval = null;
        this._runningTick = false;
        this._externalBusy = false;
        this._lastEatAt = 0;
        this._lastDamageAt = 0;
        this._prevHealth = 20;
        this._stuckPos = null;
        this._stuckSince = 0;
        this._behaviorLog = [];
        this.modes = {
            self_preservation: {
                enabled: true,
                description: "Swim in water, escape lava/fire, and retreat at critical health.",
            },
            auto_eat: {
                enabled: true,
                description: "Automatically eat food from inventory when hunger drops below 16.",
            },
            self_defense: {
                enabled: true,
                description: "Defend against nearby hostile mobs (and evade creepers).",
            },
            unstuck: {
                enabled: true,
                description: "Jump and nudge free when stuck while pathfinding.",
            },
            follow_player: {
                enabled: false,
                target: null,
                distance: 3,
                description: "Continuously follow a teammate player in co-op mode.",
            },
        };

        if (bot && typeof bot.on === "function") {
            bot.on("health", () => {
                if (typeof bot.health === "number" && bot.health < this._prevHealth) {
                    this._lastDamageAt = Date.now();
                }
                if (typeof bot.health === "number") {
                    this._prevHealth = bot.health;
                }
            });
        }
    }

    _log(msg) {
        this._behaviorLog.push({ ts: Date.now(), msg });
        if (this._behaviorLog.length > 30) {
            this._behaviorLog.shift();
        }
    }

    setExternalBusy(busy) {
        this._externalBusy = Boolean(busy);
    }

    setMode(name, enabled, opts = {}) {
        const key = String(name || "").trim();
        if (!Object.prototype.hasOwnProperty.call(this.modes, key)) {
            throw new Error(`Unknown mode: ${key}. Valid modes: ${Object.keys(this.modes).join(", ")}`);
        }
        this.modes[key].enabled = Boolean(enabled);
        if (key === "follow_player") {
            if (opts.target !== undefined) {
                this.modes[key].target = opts.target ? String(opts.target).trim() : null;
            }
            if (opts.distance !== undefined) {
                this.modes[key].distance = Math.max(1, Math.min(Number(opts.distance) || 3, 16));
            }
            if (!this.modes[key].enabled && this.bot && this.bot.pathfinder) {
                try {
                    this.bot.pathfinder.setGoal(null);
                } catch {}
            }
        }
        this._log(`mode:${key}=${this.modes[key].enabled}`);
        return this.getStatus();
    }

    getStatus() {
        const summary = {};
        for (const [k, v] of Object.entries(this.modes)) {
            summary[k] = { ...v };
        }
        return {
            active: Boolean(this.interval),
            modes: summary,
            recent_events: this._behaviorLog.slice(-10),
        };
    }

    start() {
        if (this.interval) return;
        this.interval = setInterval(() => {
            this._tick().catch(() => {});
        }, 500);
    }

    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
        }
        this.modes.follow_player.enabled = false;
    }

    _ensureMovements() {
        if (!this.bot || !this.bot.pathfinder || !this.bot.version) return;
        if (!this._movements) {
            const mcData = require("minecraft-data")(this.bot.version);
            this._movements = new Movements(this.bot, mcData);
            this._movements.canDig = true;
            this._movements.allow1by1towers = false;
        }
        this.bot.pathfinder.setMovements(this._movements);
    }

    async _tick() {
        const bot = this.bot;
        if (this._runningTick || this._externalBusy || !bot || !bot.entity) return;
        this._runningTick = true;
        try {
            // 1. Self-preservation (highest priority)
            if (this.modes.self_preservation.enabled) {
                const pos = bot.entity.position;
                const feet = bot.blockAt(pos);
                const head = bot.blockAt(pos.offset(0, 1, 0));
                const feetName = feet ? feet.name : "air";
                const headName = head ? head.name : "air";

                if (headName === "water" || feetName === "water") {
                    bot.setControlState("jump", true);
                } else {
                    bot.setControlState("jump", false);
                }

                if (feetName === "lava" || feetName === "fire" || headName === "lava" || headName === "fire") {
                    this._log("Escaping lava/fire!");
                    bot.setControlState("jump", true);
                    if (bot.pathfinder) {
                        this._ensureMovements();
                        bot.pathfinder.setGoal(new GoalNear(Math.round(pos.x + 5), Math.round(pos.y), Math.round(pos.z + 5), 1));
                    }
                    return;
                }

                if (Date.now() - this._lastDamageAt < 3000 && typeof bot.health === "number" && bot.health <= 5) {
                    const threat = findNearestHostile(bot, 12);
                    if (threat && bot.pathfinder) {
                        this._log(`Low health (${bot.health}); retreating from ${threat.name}`);
                        this._ensureMovements();
                        bot.pathfinder.setGoal(new GoalInvert(new GoalFollow(threat, 14)), true);
                        return;
                    }
                }
            }

            // 2. Auto-eat when hungry
            if (this.modes.auto_eat.enabled && typeof bot.food === "number" && bot.food < 16 && Date.now() - this._lastEatAt > 4000) {
                const food = bot.inventory.items().find(isEdibleItem);
                if (food) {
                    this._lastEatAt = Date.now();
                    try {
                        await bot.equip(food, "hand");
                        await bot.consume();
                        this._log(`Auto-ate ${food.name} (food=${bot.food})`);
                    } catch {}
                    return;
                }
            }

            // 3. Self-defense against immediate hostile threats
            if (this.modes.self_defense.enabled) {
                const hostile = findNearestHostile(bot, 6);
                if (hostile) {
                    if (hostile.name === "creeper" && bot.pathfinder) {
                        this._log("Backing away from creeper!");
                        this._ensureMovements();
                        bot.pathfinder.setGoal(new GoalInvert(new GoalFollow(hostile, 10)), true);
                        return;
                    }
                    if (bot.pvp) {
                        await equipBestWeapon(bot);
                        if (bot.pvp.target !== hostile) {
                            this._log(`Defending against ${hostile.name}`);
                            bot.pvp.attack(hostile);
                        }
                        return;
                    }
                } else if (bot.pvp && bot.pvp.target) {
                    try {
                        bot.pvp.stop();
                    } catch {}
                }
            }

            // 4. Follow player companion mode
            if (this.modes.follow_player.enabled && this.modes.follow_player.target && bot.pathfinder) {
                const match = findPlayerCaseInsensitive(bot, this.modes.follow_player.target);
                if (match && match.player && match.player.entity) {
                    const targetEnt = match.player.entity;
                    const dist = targetEnt.position.distanceTo(bot.entity.position);
                    const desired = this.modes.follow_player.distance || 3;
                    if (dist > desired + 1) {
                        this._ensureMovements();
                        bot.pathfinder.setGoal(new GoalFollow(targetEnt, desired), true);
                    }
                }
            }

            // 5. Unstuck recovery if moving without making progress
            if (this.modes.unstuck.enabled && bot.pathfinder && bot.pathfinder.isMoving()) {
                const cur = bot.entity.position;
                if (!this._stuckPos || cur.distanceTo(this._stuckPos) >= 1.5) {
                    this._stuckPos = cur.clone();
                    this._stuckSince = Date.now();
                } else if (Date.now() - this._stuckSince > 15000) {
                    this._log("Unstuck nudge triggered");
                    this._stuckSince = Date.now();
                    bot.setControlState("jump", true);
                    setTimeout(() => {
                        try {
                            bot.setControlState("jump", false);
                        } catch {}
                    }, 400);
                }
            } else {
                this._stuckPos = null;
                this._stuckSince = 0;
            }
        } finally {
            this._runningTick = false;
        }
    }
}

module.exports = {
    CoopModeManager,
    isEdibleItem,
    findPlayerCaseInsensitive,
};
