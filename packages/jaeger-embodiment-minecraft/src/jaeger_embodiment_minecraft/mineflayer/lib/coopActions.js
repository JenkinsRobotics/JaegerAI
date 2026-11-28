/**
 * JaegerAI Deterministic Minecraft Co-Op Companion Actions (CommonJS)
 *
 * Adapted from mindcraft-bots/mindcraft (`src/agent/library/skills.js`, MIT License).
 * Provides reliable, zero-LLM-hallucination companion actions for co-op play:
 *   - listNearbyPlayers
 *   - goToPlayer
 *   - followPlayer
 *   - giveToPlayer
 *   - eatFood
 *   - goToBed
 *   - collectBlocks
 *   - stopActions
 */

const {
    Movements,
    goals: { GoalFollow, GoalNear },
} = require("mineflayer-pathfinder");
const { isEdibleItem, findPlayerCaseInsensitive } = require("./coopModes");

function configureMovements(bot) {
    const mcData = require("minecraft-data")(bot.version);
    const movements = new Movements(bot, mcData);
    movements.canDig = true;
    movements.allow1by1towers = false;
    bot.pathfinder.setMovements(movements);
    return { mcData, movements };
}

function listNearbyPlayers(bot, maxDistance = 64) {
    if (!bot || !bot.players || !bot.entity) return [];
    const results = [];
    for (const [username, info] of Object.entries(bot.players)) {
        if (username === bot.username) continue;
        if (info && info.entity && info.entity.position) {
            const d = info.entity.position.distanceTo(bot.entity.position);
            if (d <= maxDistance) {
                results.push({
                    username,
                    visible: true,
                    distance: Number(d.toFixed(1)),
                    position: {
                        x: Math.round(info.entity.position.x),
                        y: Math.round(info.entity.position.y),
                        z: Math.round(info.entity.position.z),
                    },
                });
            }
        } else {
            results.push({
                username,
                visible: false,
                distance: null,
                position: null,
            });
        }
    }
    results.sort((a, b) => (a.distance ?? 9999) - (b.distance ?? 9999));
    return results;
}

async function goToPlayer(bot, username, distance = 3) {
    const match = findPlayerCaseInsensitive(bot, username);
    if (!match || !match.player || !match.player.entity) {
        return {
            ok: false,
            summary: `Player '${username}' is not currently visible nearby.`,
            nearby_players: listNearbyPlayers(bot),
        };
    }
    const target = match.player.entity;
    const dist = Math.max(1, Math.min(Number(distance) || 3, 16));
    configureMovements(bot);
    try {
        await bot.pathfinder.goto(new GoalNear(target.position.x, target.position.y, target.position.z, dist));
        return {
            ok: true,
            summary: `Arrived near ${match.username} (${Math.round(target.position.x)}, ${Math.round(target.position.y)}, ${Math.round(target.position.z)}).`,
            player: match.username,
        };
    } catch (err) {
        return { ok: false, summary: `Could not reach ${match.username}: ${err.message || err}` };
    }
}

async function followPlayer(bot, username, distance = 3, modeManager = null) {
    const dist = Math.max(1, Math.min(Number(distance) || 3, 16));
    const match = findPlayerCaseInsensitive(bot, username);
    const resolvedName = match ? match.username : String(username || "").trim();
    if (!resolvedName) {
        return { ok: false, summary: "Player username is required to follow." };
    }
    if (modeManager) {
        modeManager.setMode("follow_player", true, { target: resolvedName, distance: dist });
    }
    if (match && match.player && match.player.entity && bot.pathfinder) {
        configureMovements(bot);
        bot.pathfinder.setGoal(new GoalFollow(match.player.entity, dist), true);
        return {
            ok: true,
            summary: `Now following ${resolvedName} at ${dist} blocks.`,
            player: resolvedName,
            visible: true,
        };
    }
    return {
        ok: true,
        summary: `Follow mode armed for ${resolvedName} (will lock on as soon as they come into render range).`,
        player: resolvedName,
        visible: false,
        nearby_players: listNearbyPlayers(bot),
    };
}

async function giveToPlayer(bot, username, itemName, count = 1) {
    const match = findPlayerCaseInsensitive(bot, username);
    if (!match || !match.player || !match.player.entity) {
        return {
            ok: false,
            summary: `Cannot give items: player '${username}' is not nearby.`,
            nearby_players: listNearbyPlayers(bot),
        };
    }
    const needle = String(itemName || "").trim().toLowerCase();
    const item = bot.inventory.items().find(
        (i) => i.name.toLowerCase() === needle || i.name.toLowerCase().includes(needle)
    );
    if (!item) {
        return { ok: false, summary: `No '${itemName}' found in inventory.` };
    }
    const nav = await goToPlayer(bot, match.username, 3);
    if (!nav.ok) return nav;
    const ent = match.player.entity;
    if (ent && ent.position) {
        await bot.lookAt(ent.position.offset(0, 1.4, 0));
    }
    const qty = Math.max(1, Math.min(Number(count) || 1, item.count));
    await bot.toss(item.type, null, qty);
    return {
        ok: true,
        summary: `Tossed ${qty}x ${item.name} to ${match.username}.`,
        item: item.name,
        count: qty,
        player: match.username,
    };
}

async function eatFood(bot, itemName = "") {
    const needle = String(itemName || "").trim().toLowerCase();
    const items = bot.inventory.items();
    const food = needle
        ? items.find((i) => i.name.toLowerCase() === needle || i.name.toLowerCase().includes(needle))
        : items.find(isEdibleItem);
    if (!food) {
        return { ok: false, summary: needle ? `No food matching '${needle}' in inventory.` : "No edible food in inventory." };
    }
    try {
        await bot.equip(food, "hand");
        await bot.consume();
        return { ok: true, summary: `Ate ${food.name} (food=${bot.food}, health=${bot.health}).`, item: food.name };
    } catch (err) {
        return { ok: false, summary: `Could not eat ${food.name}: ${err.message || err}` };
    }
}

async function goToBed(bot) {
    const bed = bot.findBlock({
        matching: (blk) => blk && blk.name && blk.name.endsWith("_bed"),
        maxDistance: 32,
    });
    if (!bed) {
        return { ok: false, summary: "No bed found within 32 blocks." };
    }
    configureMovements(bot);
    try {
        await bot.pathfinder.goto(new GoalNear(bed.position.x, bed.position.y, bed.position.z, 2));
        await bot.sleep(bed);
        return { ok: true, summary: `Went to sleep in ${bed.name}.` };
    } catch (err) {
        return { ok: false, summary: `Could not sleep in bed: ${err.message || err}` };
    }
}

async function collectBlocks(bot, blockName, count = 4) {
    const needle = String(blockName || "").trim().toLowerCase();
    if (!needle) {
        return { ok: false, summary: "Block name is required." };
    }
    const targetCount = Math.max(1, Math.min(Number(count) || 4, 16));
    const blocks = bot.findBlocks({
        matching: (blk) => blk && blk.name && (blk.name.toLowerCase() === needle || blk.name.toLowerCase().includes(needle)),
        maxDistance: 32,
        count: targetCount,
    });
    if (!blocks || blocks.length === 0) {
        return { ok: false, summary: `No '${blockName}' blocks found within 32 blocks.` };
    }
    configureMovements(bot);
    let collected = 0;
    for (const pos of blocks) {
        const blk = bot.blockAt(pos);
        if (!blk || blk.name === "air") continue;
        try {
            await bot.collectBlock.collect(blk, { ignoreNoPath: true });
            collected += 1;
        } catch {}
    }
    return {
        ok: collected > 0,
        summary: collected > 0 ? `Collected ${collected}x ${blockName}.` : `Failed to collect ${blockName}.`,
        collected,
    };
}

function stopActions(bot, modeManager = null) {
    if (modeManager) {
        try {
            modeManager.setMode("follow_player", false, { target: null });
        } catch {}
    }
    if (bot && bot.pathfinder) {
        try {
            bot.pathfinder.setGoal(null);
        } catch {}
    }
    if (bot && bot.pvp) {
        try {
            bot.pvp.stop();
        } catch {}
    }
    if (bot && typeof bot.clearControlStates === "function") {
        bot.clearControlStates();
    }
    return { ok: true, summary: "Stopped all movement, follow, and combat actions." };
}

module.exports = {
    listNearbyPlayers,
    goToPlayer,
    followPlayer,
    giveToPlayer,
    eatFood,
    goToBed,
    collectBlocks,
    stopActions,
};
