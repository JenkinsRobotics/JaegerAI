const fs = require("fs");
const express = require("express");
const bodyParser = require("body-parser");
const mineflayer = require("mineflayer");

const skills = require("./lib/skillLoader");
const { initCounter, getNextTime } = require("./lib/utils");
const obs = require("./lib/observation/base");
const OnChat = require("./lib/observation/onChat");
const OnError = require("./lib/observation/onError");
const { Voxels, BlockRecords } = require("./lib/observation/voxels");
const Status = require("./lib/observation/status");
const Inventory = require("./lib/observation/inventory");
const OnSave = require("./lib/observation/onSave");
const Chests = require("./lib/observation/chests");
const { plugin: tool } = require("mineflayer-tool");
const { CoopModeManager } = require("./lib/coopModes");
const coopActions = require("./lib/coopActions");
const blueprints = require("./lib/blueprints");
const { BedrockLanBroadcaster, buildJoinGuide } = require("./lib/lanBroadcaster");

let bot = null;
let modeManager = null;
let lanBroadcaster = new BedrockLanBroadcaster();
let chatInbox = [];
let chatSeq = 0;

function recordInboundChat(username, message) {
    if (!bot || username === bot.username) return;
    const text = String(message || "").trim();
    if (!text) return;
    chatSeq += 1;
    chatInbox.push({
        id: chatSeq,
        username: String(username || "player"),
        message: text,
        timestamp: Date.now() / 1000,
    });
    if (chatInbox.length > 50) {
        chatInbox.shift();
    }
}

const app = express();

app.use(bodyParser.json({ limit: "50mb" }));
app.use(bodyParser.urlencoded({ limit: "50mb", extended: false }));

app.get("/health", (_req, res) => {
    res.json({
        ok: true,
        connected: Boolean(bot && bot.entity),
        username: bot?.username || null,
        modes: modeManager ? modeManager.getStatus() : null,
        nearby_players: bot && bot.entity ? coopActions.listNearbyPlayers(bot) : [],
    });
});

app.post("/start", (req, res) => {
    if (bot) onDisconnect("Restarting bot");
    bot = null;
    console.log(req.body);
    bot = mineflayer.createBot({
        host: req.body.host || "127.0.0.1", // minecraft server ip
        port: Number(req.body.port || 25565), // minecraft server port
        username: req.body.username || "Jaeger",
        disableChatSigning: true,
        checkTimeoutInterval: 60 * 60 * 1000,
    });
    bot.once("error", onConnectionFailed);

    // Event subscriptions
    bot.waitTicks = Number(req.body.waitTicks || 10);
    bot.globalTickCounter = 0;
    bot.stuckTickCounter = 0;
    bot.stuckPosList = [];
    bot.iron_pickaxe = false;

    bot.on("kicked", onDisconnect);

    // mounting will cause physicsTick to stop
    bot.on("mount", () => {
        bot.dismount();
    });

    bot.once("spawn", async () => {
        bot.removeListener("error", onConnectionFailed);
        let itemTicks = 1;
        if (req.body.reset === "hard") {
            bot.chat("/clear @s");
            bot.chat("/kill @s");
            const inventory = req.body.inventory ? req.body.inventory : {};
            const equipment = req.body.equipment
                ? req.body.equipment
                : [null, null, null, null, null, null];
            for (let key in inventory) {
                bot.chat(`/give @s minecraft:${key} ${inventory[key]}`);
                itemTicks += 1;
            }
            const equipmentNames = [
                "armor.head",
                "armor.chest",
                "armor.legs",
                "armor.feet",
                "weapon.mainhand",
                "weapon.offhand",
            ];
            for (let i = 0; i < 6; i++) {
                if (i === 4) continue;
                if (equipment[i]) {
                    bot.chat(
                        `/item replace entity @s ${equipmentNames[i]} with minecraft:${equipment[i]}`
                    );
                    itemTicks += 1;
                }
            }
        }

        if (req.body.position) {
            bot.chat(
                `/tp @s ${req.body.position.x} ${req.body.position.y} ${req.body.position.z}`
            );
        }

        // if iron_pickaxe is in bot's inventory
        if (
            bot.inventory.items().find((item) => item.name === "iron_pickaxe")
        ) {
            bot.iron_pickaxe = true;
        }

        const { pathfinder } = require("mineflayer-pathfinder");
        const tool = require("mineflayer-tool").plugin;
        const collectBlock = require("mineflayer-collectblock").plugin;
        const pvp = require("mineflayer-pvp").plugin;
        const hawkeyeMod = require("minecrafthawkeye");
        const minecraftHawkEye = typeof hawkeyeMod === "function" ? hawkeyeMod : (hawkeyeMod.default || hawkeyeMod.plugin);
        bot.loadPlugin(pathfinder);
        bot.loadPlugin(tool);
        bot.loadPlugin(collectBlock);
        bot.loadPlugin(pvp);
        if (typeof minecraftHawkEye === "function") {
            bot.loadPlugin(minecraftHawkEye);
        }

        // bot.collectBlock.movements.digCost = 0;
        // bot.collectBlock.movements.placeCost = 0;

        obs.inject(bot, [
            OnChat,
            OnError,
            Voxels,
            Status,
            Inventory,
            OnSave,
            Chests,
            BlockRecords,
        ]);
        skills.inject(bot);

        if (req.body.spread) {
            bot.chat(`/spreadplayers ~ ~ 0 300 under 80 false @s`);
            await bot.waitForTicks(bot.waitTicks);
        }

        await bot.waitForTicks(bot.waitTicks * itemTicks);

        // Start Mindcraft-inspired survival & co-op reflex modes + inbound chat capture
        if (modeManager) {
            modeManager.stop();
        }
        modeManager = new CoopModeManager(bot);
        modeManager.start();
        bot.on("chat", recordInboundChat);

        res.json(bot.observe());

        initCounter(bot);
        if (req.body.reset === "hard") {
            bot.chat("/gamerule keepInventory true");
            bot.chat("/gamerule doDaylightCycle false");
        }
    });

    function onConnectionFailed(e) {
        console.log(e);
        if (modeManager) {
            modeManager.stop();
            modeManager = null;
        }
        bot = null;
        res.status(400).json({ error: e });
    }
    function onDisconnect(message) {
        if (modeManager) {
            modeManager.stop();
            modeManager = null;
        }
        if (bot && bot.viewer) {
            bot.viewer.close();
        }
        if (bot) {
            bot.end();
        }
        console.log(message);
        bot = null;
    }
});

app.post("/step", async (req, res) => {
    // import useful package
    let response_sent = false;
    function otherError(err) {
        console.log("Uncaught Error");
        bot.emit("error", handleError(err));
        bot.waitForTicks(bot.waitTicks).then(() => {
            if (!response_sent) {
                response_sent = true;
                res.json(bot.observe());
            }
        });
    }

    process.on("uncaughtException", otherError);

    const mcData = require("minecraft-data")(bot.version);
    mcData.itemsByName["leather_cap"] = mcData.itemsByName["leather_helmet"];
    mcData.itemsByName["leather_tunic"] =
        mcData.itemsByName["leather_chestplate"];
    mcData.itemsByName["leather_pants"] =
        mcData.itemsByName["leather_leggings"];
    mcData.itemsByName["leather_boots"] = mcData.itemsByName["leather_boots"];
    mcData.itemsByName["lapis_lazuli_ore"] = mcData.itemsByName["lapis_ore"];
    mcData.blocksByName["lapis_lazuli_ore"] = mcData.blocksByName["lapis_ore"];
    const {
        Movements,
        goals: {
            Goal,
            GoalBlock,
            GoalNear,
            GoalXZ,
            GoalNearXZ,
            GoalY,
            GoalGetToBlock,
            GoalLookAtBlock,
            GoalBreakBlock,
            GoalCompositeAny,
            GoalCompositeAll,
            GoalInvert,
            GoalFollow,
            GoalPlaceBlock,
        },
        pathfinder,
        Move,
        ComputedPath,
        PartiallyComputedPath,
        XZCoordinates,
        XYZCoordinates,
        SafeBlock,
        GoalPlaceBlockOptions,
    } = require("mineflayer-pathfinder");
    const { Vec3 } = require("vec3");

    // Set up pathfinder
    const movements = new Movements(bot, mcData);
    bot.pathfinder.setMovements(movements);

    bot.globalTickCounter = 0;
    bot.stuckTickCounter = 0;
    bot.stuckPosList = [];

    function onTick() {
        bot.globalTickCounter++;
        if (bot.pathfinder.isMoving()) {
            bot.stuckTickCounter++;
            if (bot.stuckTickCounter >= 100) {
                onStuck(1.5);
                bot.stuckTickCounter = 0;
            }
        }
    }

    bot.on("physicTick", onTick);

    // initialize fail count
    let _craftItemFailCount = 0;
    let _killMobFailCount = 0;
    let _mineBlockFailCount = 0;
    let _placeItemFailCount = 0;
    let _smeltItemFailCount = 0;

    // Retrieve array form post bod
    const code = req.body.code;
    const programs = req.body.programs;
    bot.cumulativeObs = [];
    await bot.waitForTicks(bot.waitTicks);
    const r = await evaluateCode(code, programs);
    process.off("uncaughtException", otherError);
    if (r !== "success") {
        bot.emit("error", handleError(r));
    }
    await returnItems();
    // wait for last message
    await bot.waitForTicks(bot.waitTicks);
    if (!response_sent) {
        response_sent = true;
        res.json(bot.observe());
    }
    bot.removeListener("physicTick", onTick);

    async function evaluateCode(code, programs) {
        // Echo the code produced for players to see it. Don't echo when the bot code is already producing dialog or it will double echo
        try {
            await eval("(async () => {" + programs + "\n" + code + "})()");
            return "success";
        } catch (err) {
            return err;
        }
    }

    function onStuck(posThreshold) {
        const currentPos = bot.entity.position;
        bot.stuckPosList.push(currentPos);

        // Check if the list is full
        if (bot.stuckPosList.length === 5) {
            const oldestPos = bot.stuckPosList[0];
            const posDifference = currentPos.distanceTo(oldestPos);

            if (posDifference < posThreshold) {
                teleportBot(); // execute the function
            }

            // Remove the oldest time from the list
            bot.stuckPosList.shift();
        }
    }

    function teleportBot() {
        const blocks = bot.findBlocks({
            matching: (block) => {
                return block.type === 0;
            },
            maxDistance: 1,
            count: 27,
        });

        if (blocks) {
            // console.log(blocks.length);
            const randomIndex = Math.floor(Math.random() * blocks.length);
            const block = blocks[randomIndex];
            bot.chat(`/tp @s ${block.x} ${block.y} ${block.z}`);
        } else {
            bot.chat("/tp @s ~ ~1.25 ~");
        }
    }

    function returnItems() {
        bot.chat("/gamerule doTileDrops false");
        const crafting_table = bot.findBlock({
            matching: mcData.blocksByName.crafting_table.id,
            maxDistance: 128,
        });
        if (crafting_table) {
            bot.chat(
                `/setblock ${crafting_table.position.x} ${crafting_table.position.y} ${crafting_table.position.z} air destroy`
            );
            bot.chat("/give @s crafting_table");
        }
        const furnace = bot.findBlock({
            matching: mcData.blocksByName.furnace.id,
            maxDistance: 128,
        });
        if (furnace) {
            bot.chat(
                `/setblock ${furnace.position.x} ${furnace.position.y} ${furnace.position.z} air destroy`
            );
            bot.chat("/give @s furnace");
        }
        if (bot.inventoryUsed() >= 32) {
            // if chest is not in bot's inventory
            if (!bot.inventory.items().find((item) => item.name === "chest")) {
                bot.chat("/give @s chest");
            }
        }
        // if iron_pickaxe not in bot's inventory and bot.iron_pickaxe
        if (
            bot.iron_pickaxe &&
            !bot.inventory.items().find((item) => item.name === "iron_pickaxe")
        ) {
            bot.chat("/give @s iron_pickaxe");
        }
        bot.chat("/gamerule doTileDrops true");
    }

    function handleError(err) {
        let stack = err.stack;
        if (!stack) {
            return err;
        }
        console.log(stack);
        const final_line = stack.split("\n")[1];
        const regex = /<anonymous>:(\d+):\d+\)/;

        const programs_length = programs.split("\n").length;
        let match_line = null;
        for (const line of stack.split("\n")) {
            const match = regex.exec(line);
            if (match) {
                const line_num = parseInt(match[1]);
                if (line_num >= programs_length) {
                    match_line = line_num - programs_length;
                    break;
                }
            }
        }
        if (!match_line) {
            return err.message;
        }
        let f_line = final_line.match(
            /\((?<file>.*):(?<line>\d+):(?<pos>\d+)\)/
        );
        if (f_line && f_line.groups && fs.existsSync(f_line.groups.file)) {
            const { file, line, pos } = f_line.groups;
            const f = fs.readFileSync(file, "utf8").split("\n");
            // let filename = file.match(/(?<=node_modules\\)(.*)/)[1];
            let source = file + `:${line}\n${f[line - 1].trim()}\n `;

            const code_source =
                "at " +
                code.split("\n")[match_line - 1].trim() +
                " in your code";
            return source + err.message + "\n" + code_source;
        } else if (
            f_line &&
            f_line.groups &&
            f_line.groups.file.includes("<anonymous>")
        ) {
            const { file, line, pos } = f_line.groups;
            let source =
                "Your code" +
                `:${match_line}\n${code.split("\n")[match_line - 1].trim()}\n `;
            let code_source = "";
            if (line < programs_length) {
                source =
                    "In your program code: " +
                    programs.split("\n")[line - 1].trim() +
                    "\n";
                code_source = `at line ${match_line}:${code
                    .split("\n")
                    [match_line - 1].trim()} in your code`;
            }
            return source + err.message + "\n" + code_source;
        }
        return err.message;
    }
});

app.get("/modes", (_req, res) => {
    if (!bot || !bot.entity || !modeManager) {
        res.status(400).json({ ok: false, error: "Bot not spawned" });
        return;
    }
    res.json({ ok: true, ...modeManager.getStatus() });
});

app.post("/modes", (req, res) => {
    if (!bot || !bot.entity || !modeManager) {
        res.status(400).json({ ok: false, error: "Bot not spawned" });
        return;
    }
    try {
        const { mode, enabled, target, distance } = req.body || {};
        const status = modeManager.setMode(mode, enabled, { target, distance });
        res.json({ ok: true, ...status });
    } catch (err) {
        res.status(400).json({ ok: false, error: err.message || String(err) });
    }
});

app.get("/chat-inbox", (req, res) => {
    const sinceId = Number(req.query.since_id || 0);
    const messages = chatInbox.filter((m) => m.id > sinceId);
    res.json({
        ok: true,
        last_id: chatSeq,
        messages,
        nearby_players: bot && bot.entity ? coopActions.listNearbyPlayers(bot) : [],
    });
});

function classifySurfaceBlock(name) {
    const n = String(name || "air").toLowerCase();
    if (n.includes("water")) return "water";
    if (n.includes("lava") || n.includes("fire")) return "lava";
    if (n.includes("leaves") || n.includes("vine")) return "leaves";
    if (n.includes("log") || n.includes("wood") || n.includes("plank")) return "wood";
    if (n.includes("_bed")) return "bed";
    if (n.includes("chest") || n.includes("barrel")) return "chest";
    if (n.includes("crafting_table") || n.includes("furnace")) return "craft";
    if (n.includes("ore") || n.includes("diamond") || n.includes("iron_block")) return "ore";
    if (n.includes("sand") || n.includes("gravel")) return "sand";
    if (n.includes("snow") || n.includes("ice")) return "snow";
    if (n.includes("grass") || n.includes("moss")) return "grass";
    if (n.includes("dirt") || n.includes("mud") || n.includes("clay")) return "dirt";
    if (n.includes("stone") || n.includes("cobble") || n.includes("deepslate") || n.includes("andesite") || n.includes("granite")) return "stone";
    if (n === "air" || n === "cave_air" || n === "void_air") return "air";
    return "other";
}

app.get("/radar", (req, res) => {
    if (!bot || !bot.entity) {
        res.status(400).json({ ok: false, connected: false, error: "Bot not spawned" });
        return;
    }
    const radius = Math.max(4, Math.min(Number(req.query.radius || 8), 10));
    const bx = Math.floor(bot.entity.position.x);
    const by = Math.floor(bot.entity.position.y);
    const bz = Math.floor(bot.entity.position.z);
    const grid = [];

    for (let dz = -radius; dz <= radius; dz++) {
        const row = [];
        for (let dx = -radius; dx <= radius; dx++) {
            let foundKind = "air";
            let foundDy = 0;
            for (let dy = 5; dy >= -5; dy--) {
                const blk = bot.blockAt(bot.entity.position.floored().offset(dx, dy, dz));
                if (!blk) continue;
                const bname = blk.name || "air";
                if (bname !== "air" && bname !== "cave_air" && bname !== "void_air" && bname !== "short_grass" && bname !== "tall_grass") {
                    foundKind = classifySurfaceBlock(bname);
                    foundDy = dy;
                    break;
                }
            }
            row.push([foundKind, foundDy]);
        }
        grid.push(row);
    }

    const entities = [];
    for (const ent of Object.values(bot.entities || {})) {
        if (!ent || !ent.position || ent === bot.entity) continue;
        const dx = ent.position.x - bot.entity.position.x;
        const dz = ent.position.z - bot.entity.position.z;
        const dist = Math.hypot(dx, dz);
        if (dist > radius + 2) continue;
        entities.push({
            name: String(ent.username || ent.name || ent.type || "entity"),
            type: String(ent.type || "mob"),
            dx: Number(dx.toFixed(1)),
            dz: Number(dz.toFixed(1)),
            distance: Number(dist.toFixed(1)),
        });
    }
    entities.sort((a, b) => a.distance - b.distance);

    const inv = {};
    for (const item of bot.inventory ? bot.inventory.items() : []) {
        inv[item.name] = (inv[item.name] || 0) + item.count;
    }

    res.json({
        ok: true,
        connected: true,
        radius,
        bot: {
            username: bot.username,
            x: bx,
            y: by,
            z: bz,
            yaw: Number((bot.entity.yaw || 0).toFixed(2)),
            health: Number((bot.health || 0).toFixed(1)),
            food: Number((bot.food || 0).toFixed(1)),
        },
        grid,
        entities: entities.slice(0, 24),
        nearby_players: coopActions.listNearbyPlayers(bot),
        inventory: inv,
        modes: modeManager ? modeManager.getStatus().modes : {},
        chat_inbox: chatInbox.slice(-10),
    });
});

app.post("/coop", async (req, res) => {
    if (!bot || !bot.entity) {
        res.status(400).json({ ok: false, error: "Bot not spawned" });
        return;
    }
    const body = req.body || {};
    const action = String(body.action || "").trim();
    if (modeManager) modeManager.setExternalBusy(true);
    try {
        let result;
        if (action === "nearby_players") {
            const players = coopActions.listNearbyPlayers(bot, Number(body.max_distance || 64));
            result = { ok: true, nearby_players: players, summary: `Found ${players.length} player(s).` };
        } else if (action === "go_to_player") {
            result = await coopActions.goToPlayer(bot, body.player || body.username || "", body.distance || 3);
        } else if (action === "follow_player") {
            result = await coopActions.followPlayer(bot, body.player || body.username || "", body.distance || 3, modeManager);
        } else if (action === "give_to_player") {
            result = await coopActions.giveToPlayer(bot, body.player || body.username || "", body.item || "", body.count || 1);
        } else if (action === "eat") {
            result = await coopActions.eatFood(bot, body.item || "");
        } else if (action === "go_to_bed") {
            result = await coopActions.goToBed(bot);
        } else if (action === "collect_blocks") {
            result = await coopActions.collectBlocks(bot, body.item || body.block || "", body.count || 4);
        } else if (action === "build_blueprint") {
            const origin = body.x !== undefined ? { x: body.x, y: body.y, z: body.z } : null;
            result = await blueprints.buildBlueprint(bot, body.blueprint || "shelter", origin);
        } else if (action === "guard_area") {
            const anchor = body.x !== undefined
                ? { x: Number(body.x), y: Number(body.y ?? bot.entity.position.y), z: Number(body.z) }
                : { x: Math.round(bot.entity.position.x), y: Math.round(bot.entity.position.y), z: Math.round(bot.entity.position.z) };
            const radius = Number(body.radius || 10);
            if (modeManager) {
                modeManager.setMode("guard_area", true, { anchor, radius });
            }
            result = { ok: true, summary: `Now guarding area around (${anchor.x}, ${anchor.y}, ${anchor.z}) within ${radius} blocks.`, anchor, radius };
        } else if (action === "stop_actions") {
            if (modeManager) {
                try { modeManager.setMode("guard_area", false); } catch {}
            }
            result = coopActions.stopActions(bot, modeManager);
        } else {
            res.status(400).json({ ok: false, error: `Unsupported co-op action: ${action}` });
            return;
        }
        res.json({
            ...result,
            modes: modeManager ? modeManager.getStatus() : null,
            nearby_players: coopActions.listNearbyPlayers(bot),
            observation: bot.observe(),
        });
    } catch (err) {
        res.status(500).json({ ok: false, error: err.message || String(err) });
    } finally {
        if (modeManager) modeManager.setExternalBusy(false);
    }
});

app.get("/join-guide", (req, res) => {
    const javaPort = Number(req.query.java_port || 25565);
    const bedrockPort = Number(req.query.bedrock_port || 19132);
    res.json({
        ok: true,
        guide: buildJoinGuide({ javaPort, bedrockPort }),
        lan_broadcast: lanBroadcaster.status(),
        available_blueprints: blueprints.AVAILABLE_BLUEPRINTS,
    });
});

app.post("/lan-broadcast", (req, res) => {
    const body = req.body || {};
    const enabled = Boolean(body.enabled);
    if (enabled) {
        if (body.server_name) lanBroadcaster.serverName = String(body.server_name);
        if (body.world_name) lanBroadcaster.worldName = String(body.world_name);
        if (body.bedrock_port) lanBroadcaster.port = Number(body.bedrock_port);
        const st = lanBroadcaster.start(() => (bot && bot.players ? Object.keys(bot.players).length : 1));
        res.json({ ok: true, lan_broadcast: st });
    } else {
        const st = lanBroadcaster.stop();
        res.json({ ok: true, lan_broadcast: st });
    }
});

app.post("/stop", (req, res) => {
    if (modeManager) {
        modeManager.stop();
        modeManager = null;
    }
    if (bot) {
        try { bot.end(); } catch {}
        bot = null;
    }
    res.json({
        message: "Bot stopped",
    });
});

app.post("/pause", (req, res) => {
    if (!bot) {
        res.status(400).json({ error: "Bot not spawned" });
        return;
    }
    bot.chat("/pause");
    bot.waitForTicks(bot.waitTicks).then(() => {
        res.json({ message: "Success" });
    });
});

// Server listening to PORT 3000

const DEFAULT_PORT = 3000;
const PORT = process.argv[2] || DEFAULT_PORT;
app.listen(PORT, () => {
    console.log(`Server started on port ${PORT}`);
});
