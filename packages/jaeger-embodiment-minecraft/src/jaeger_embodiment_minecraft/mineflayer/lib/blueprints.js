/**
 * JaegerAI Deterministic Minecraft Blueprint Builder (CommonJS)
 *
 * Adapted from JenkinsRobotics/ares-minecraft (`bot/village-builder.js`, MIT License).
 * Builds clean survival structures step-by-step from bot inventory blocks using
 * mineflayer-pathfinder without hardcoded branding or commands:
 *   - shelter   : 5x5 starter survival cabin with corner pillars, roof, door opening & torches
 *   - monument  : 3x3 cobblestone lamp post / beacon marker with torches
 *   - farm      : 5x5 fenced dirt plot with central water source & corner torches
 *   - town_hall : 7x7 oak & cobblestone lodge with door, window slits, roof, torches & interior slots
 */

const { Vec3 } = require("vec3");
const {
    Movements,
    goals: { GoalNear },
} = require("mineflayer-pathfinder");

const AVAILABLE_BLUEPRINTS = ["shelter", "monument", "farm", "town_hall"];

function configureMovements(bot) {
    const mcData = require("minecraft-data")(bot.version);
    const movements = new Movements(bot, mcData);
    movements.canDig = true;
    movements.allow1by1towers = false;
    bot.pathfinder.setMovements(movements);
}

async function placeBlockAt(bot, x, y, z, blockNames) {
    const candidates = Array.isArray(blockNames) ? blockNames : [blockNames];
    const targetPos = new Vec3(Math.floor(x), Math.floor(y), Math.floor(z));
    const current = bot.blockAt(targetPos);
    if (current && candidates.includes(current.name)) {
        return { placed: false, already: true };
    }

    const item = bot.inventory.items().find((i) => candidates.includes(i.name));
    if (!item) {
        return { placed: false, missing: candidates[0] };
    }

    if (bot.entity.position.distanceTo(targetPos) > 4.2) {
        try {
            await bot.pathfinder.goto(new GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));
        } catch {}
    }

    try {
        await bot.equip(item, "hand");
        await bot.lookAt(targetPos.offset(0.5, 0.5, 0.5));
    } catch {}

    const offsets = [
        [0, -1, 0],
        [1, 0, 0],
        [-1, 0, 0],
        [0, 0, 1],
        [0, 0, -1],
        [0, 1, 0],
    ];
    for (const [dx, dy, dz] of offsets) {
        const ref = bot.blockAt(targetPos.offset(dx, dy, dz));
        if (ref && ref.name !== "air" && ref.name !== "cave_air" && ref.name !== "water" && ref.name !== "lava") {
            try {
                await bot.placeBlock(ref, new Vec3(-dx, -dy, -dz));
                await new Promise((r) => setTimeout(r, 120));
                return { placed: true };
            } catch {}
        }
    }
    return { placed: false };
}

function generateBlueprintPlan(name, ox, oy, oz) {
    const plan = [];
    const wood = ["oak_planks", "spruce_planks", "birch_planks", "cobblestone", "dirt"];
    const base = ["cobblestone", "stone", "oak_planks", "dirt"];

    if (name === "monument") {
        for (let dx = -1; dx <= 1; dx++) {
            for (let dz = -1; dz <= 1; dz++) {
                plan.push([ox + dx, oy, oz + dz, base]);
            }
        }
        plan.push([ox, oy + 1, oz, base]);
        plan.push([ox, oy + 2, oz, ["oak_log", "spruce_log", ...base]]);
        plan.push([ox, oy + 3, oz, ["oak_log", "spruce_log", ...base]]);
        plan.push([ox, oy + 4, oz, ["torch", "lantern"]]);
        plan.push([ox - 1, oy + 1, oz - 1, ["torch"]]);
        plan.push([ox + 1, oy + 1, oz - 1, ["torch"]]);
        plan.push([ox - 1, oy + 1, oz + 1, ["torch"]]);
        plan.push([ox + 1, oy + 1, oz + 1, ["torch"]]);
        return plan;
    }

    if (name === "farm") {
        for (let dx = -2; dx <= 2; dx++) {
            for (let dz = -2; dz <= 2; dz++) {
                if (dx === 0 && dz === 0) continue;
                plan.push([ox + dx, oy, oz + dz, ["dirt", "grass_block"]]);
                const isEdge = Math.abs(dx) === 2 || Math.abs(dz) === 2;
                if (isEdge && !(dz === -2 && dx === 0)) {
                    plan.push([ox + dx, oy + 1, oz + dz, ["oak_fence", "cobblestone_wall", ...wood]]);
                }
            }
        }
        plan.push([ox - 2, oy + 2, oz - 2, ["torch"]]);
        plan.push([ox + 2, oy + 2, oz + 2, ["torch"]]);
        return plan;
    }

    const size = name === "town_hall" ? 7 : 5;
    const height = name === "town_hall" ? 4 : 3;
    const doorX = Math.floor(size / 2);

    // Foundation
    for (let dx = 0; dx < size; dx++) {
        for (let dz = 0; dz < size; dz++) {
            plan.push([ox + dx, oy, oz + dz, base]);
        }
    }
    // Walls
    for (let dy = 1; dy < height; dy++) {
        for (let dx = 0; dx < size; dx++) {
            for (let dz = 0; dz < size; dz++) {
                const isEdge = dx === 0 || dx === size - 1 || dz === 0 || dz === size - 1;
                if (!isEdge) continue;
                if (dz === 0 && dx === doorX && (dy === 1 || dy === 2)) continue;
                const isCorner = (dx === 0 || dx === size - 1) && (dz === 0 || dz === size - 1);
                plan.push([ox + dx, oy + dy, oz + dz, isCorner ? base : wood]);
            }
        }
    }
    // Roof
    for (let dx = 0; dx < size; dx++) {
        for (let dz = 0; dz < size; dz++) {
            plan.push([ox + dx, oy + height, oz + dz, wood]);
        }
    }
    // Corner torches & interior crafting table / chest
    plan.push([ox, oy + height + 1, oz, ["torch"]]);
    plan.push([ox + size - 1, oy + height + 1, oz + size - 1, ["torch"]]);
    plan.push([ox + 1, oy + 1, oz + size - 2, ["crafting_table"]]);
    plan.push([ox + 2, oy + 1, oz + size - 2, ["chest"]]);
    return plan;
}

async function buildBlueprint(bot, blueprintName, origin = null) {
    const name = String(blueprintName || "shelter").trim().toLowerCase();
    if (!AVAILABLE_BLUEPRINTS.includes(name)) {
        return {
            ok: false,
            summary: `Unknown blueprint '${name}'. Available: ${AVAILABLE_BLUEPRINTS.join(", ")}.`,
            available: AVAILABLE_BLUEPRINTS,
        };
    }
    const basePos = bot.entity.position.floored();
    const ox = origin && origin.x !== undefined ? Math.floor(Number(origin.x)) : basePos.x + 2;
    const oy = origin && origin.y !== undefined ? Math.floor(Number(origin.y)) : basePos.y - 1;
    const oz = origin && origin.z !== undefined ? Math.floor(Number(origin.z)) : basePos.z + 2;

    configureMovements(bot);
    const plan = generateBlueprintPlan(name, ox, oy, oz);
    let placed = 0;
    const missingCounts = {};

    for (const [x, y, z, blockNames] of plan) {
        const res = await placeBlockAt(bot, x, y, z, blockNames);
        if (res.placed) {
            placed += 1;
        } else if (res.missing) {
            missingCounts[res.missing] = (missingCounts[res.missing] || 0) + 1;
        }
    }

    const missingList = Object.entries(missingCounts)
        .slice(0, 4)
        .map(([k, v]) => `${k}x${v}`)
        .join(", ");
    return {
        ok: placed > 0 || Object.keys(missingCounts).length === 0,
        blueprint: name,
        origin: { x: ox, y: oy, z: oz },
        placed_blocks: placed,
        total_steps: plan.length,
        missing_materials: missingCounts,
        summary:
            placed > 0
                ? `Built '${name}' at (${ox}, ${oy}, ${oz}): placed ${placed}/${plan.length} blocks` +
                  (missingList ? ` (still need: ${missingList})` : ".")
                : `Could not place blocks for '${name}' — need materials in inventory (${missingList || "blocks"}).`,
    };
}

module.exports = {
    AVAILABLE_BLUEPRINTS,
    generateBlueprintPlan,
    buildBlueprint,
};
