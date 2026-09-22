/**
 * ARES Minecraft Village Builder
 *
 * Blueprint system and autonomous construction engine for the
 * "Village of Antigravity" on the Jenkins Robotics Rack PC server.
 *
 * Blueprints:
 *   1. Town Hall (Oak & Cobblestone Lodge with Door, Windows, Bed, Chest, Crafting Table)
 *   2. Central Fountain & Monument (Cobblestone basin, water, glowing lanterns/torches)
 *   3. Community Farm (Tilled soil, water canal, wheat crops, perimeter fence)
 *   4. Residential Cottages & Lamp Posts (Connecting roads and cozy houses)
 *
 * Copyright (c) 2026 Jenkins Robotics. MIT License.
 */

import { Vec3 } from 'vec3';
import pkg from 'mineflayer-pathfinder';
const { goals } = pkg;

export class VillageBuilder {
  constructor(bot) {
    this.bot = bot;
    this.isBuilding = false;
    this.currentStructure = null;
  }

  async sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async announce(msg) {
    try {
      if (this.bot && this.bot.chat) {
        this.bot.chat(msg);
      }
    } catch (_) {}
    console.log(`[VillageBuilder] ${msg}`);
  }

  async ensureItem(itemName, count = 1) {
    const item = this.bot.inventory.items().find(i => i.name === itemName && i.count >= count);
    return item != null;
  }

  async equipBlock(blockName) {
    const item = this.bot.inventory.items().find(i => i.name === blockName);
    if (!item) return false;
    await this.bot.equip(item, 'hand');
    return true;
  }

  async placeAt(x, y, z, blockName) {
    const targetPos = new Vec3(Math.floor(x), Math.floor(y), Math.floor(z));
    
    // Check if block is already what we want
    const current = this.bot.blockAt(targetPos);
    if (current && current.name === blockName) return true;

    // Equip item
    const equipped = await this.equipBlock(blockName);
    if (!equipped) return false;

    // Move close if needed
    if (this.bot.entity.position.distanceTo(targetPos) > 4.2) {
      try {
        await this.bot.pathfinder.goto(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2.5));
      } catch (_) {}
    }

    // Look at target
    try {
      await this.bot.lookAt(targetPos.offset(0.5, 0.5, 0.5));
    } catch (_) {}

    // Find reference block
    const offsets = [[0, -1, 0], [0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]];
    for (const [dx, dy, dz] of offsets) {
      const ref = this.bot.blockAt(targetPos.offset(dx, dy, dz));
      if (ref && ref.name !== 'air' && ref.name !== 'cave_air' && ref.name !== 'water' && ref.name !== 'lava') {
        try {
          await this.bot.placeBlock(ref, new Vec3(-dx, -dy, -dz));
          await this.sleep(150);
          return true;
        } catch (_) {}
      }
    }
    return false;
  }

  /**
   * Build the "Antigravity Town Hall" structure
   * Dimensions: 7x6x5 oak planks, cobblestone base, door, glass, torches, and roof.
   */
  async buildTownHall(originX, originY, originZ) {
    this.isBuilding = true;
    this.currentStructure = 'Antigravity Town Hall';
    await this.announce('🏛️ Commencing construction of the Antigravity Town Hall!');

    const ox = Math.floor(originX);
    const oy = Math.floor(originY);
    const oz = Math.floor(originZ);

    // 1. Cobblestone Foundation (7x7)
    await this.announce('🔨 Laying cobblestone foundation...');
    for (let dx = 0; dx < 7; dx++) {
      for (let dz = 0; dz < 7; dz++) {
        await this.placeAt(ox + dx, oy, oz + dz, 'cobblestone');
      }
    }

    // 2. Oak Plank Walls (Height 3)
    await this.announce('🪵 Raising oak timber walls for the lodge...');
    for (let dy = 1; dy <= 3; dy++) {
      for (let dx = 0; dx < 7; dx++) {
        for (let dz = 0; dz < 7; dz++) {
          const isEdge = dx === 0 || dx === 6 || dz === 0 || dz === 6;
          if (!isEdge) continue;

          // Leave door opening at (3, 1) and (3, 2) on front wall (dz = 0)
          if (dz === 0 && dx === 3 && (dy === 1 || dy === 2)) continue;

          // Window slits at center of side walls
          if ((dx === 0 || dx === 6) && dz === 3 && dy === 2) {
            await this.placeAt(ox + dx, oy + dy, oz + dz, 'glass');
            continue;
          }

          // Corner pillars use oak log or cobblestone
          const isCorner = (dx === 0 || dx === 6) && (dz === 0 || dz === 6);
          const block = isCorner ? 'cobblestone' : 'oak_planks';
          await this.placeAt(ox + dx, oy + dy, oz + dz, block);
        }
      }
    }

    // 3. Wooden Roof & Torches
    await this.announce('✨ Installing the roof and safety torches...');
    for (let dx = 0; dx < 7; dx++) {
      for (let dz = 0; dz < 7; dz++) {
        await this.placeAt(ox + dx, oy + 4, oz + dz, 'oak_planks');
      }
    }

    // Place corner torches for lighting
    await this.placeAt(ox, oy + 5, oz, 'torch');
    await this.placeAt(ox + 6, oy + 5, oz, 'torch');
    await this.placeAt(ox, oy + 5, oz + 6, 'torch');
    await this.placeAt(ox + 6, oy + 5, oz + 6, 'torch');

    // 4. Interior Amenities: Crafting table, Chest, Bed
    await this.placeAt(ox + 1, oy + 1, oz + 5, 'crafting_table');
    await this.placeAt(ox + 2, oy + 1, oz + 5, 'chest');
    await this.placeAt(ox + 5, oy + 1, oz + 5, 'red_bed');

    await this.announce('🏰 Antigravity Town Hall complete! Welcome to the Village of Antigravity!');
    this.isBuilding = false;
    this.currentStructure = null;
    return { ok: true, structure: 'Antigravity Town Hall', location: { x: ox, y: oy, z: oz } };
  }

  /**
   * Build the "Central Monument / Lamp Post"
   */
  async buildMonument(originX, originY, originZ) {
    this.isBuilding = true;
    this.currentStructure = 'Antigravity Monument';
    await this.announce('⛲ Erecting the Monument of Antigravity...');

    const ox = Math.floor(originX);
    const oy = Math.floor(originY);
    const oz = Math.floor(originZ);

    // 3x3 stone base
    for (let dx = -1; dx <= 1; dx++) {
      for (let dz = -1; dz <= 1; dz++) {
        await this.placeAt(ox + dx, oy, oz + dz, 'cobblestone');
      }
    }

    // Central Pillar (height 4)
    await this.placeAt(ox, oy + 1, oz, 'cobblestone');
    await this.placeAt(ox, oy + 2, oz, 'oak_log');
    await this.placeAt(ox, oy + 3, oz, 'oak_log');
    await this.placeAt(ox, oy + 4, oz, 'torch');

    // 4 Corner lanterns/torches
    await this.placeAt(ox - 1, oy + 1, oz - 1, 'torch');
    await this.placeAt(ox + 1, oy + 1, oz - 1, 'torch');
    await this.placeAt(ox - 1, oy + 1, oz + 1, 'torch');
    await this.placeAt(ox + 1, oy + 1, oz + 1, 'torch');

    await this.announce('✨ Monument of Antigravity illuminated and completed!');
    this.isBuilding = false;
    this.currentStructure = null;
    return { ok: true, structure: 'Antigravity Monument' };
  }

  /**
   * Build the "Community Farmland"
   */
  async buildFarm(originX, originY, originZ) {
    this.isBuilding = true;
    this.currentStructure = 'Antigravity Community Farm';
    await this.announce('🌾 Cultivating the Antigravity Community Farm...');

    const ox = Math.floor(originX);
    const oy = Math.floor(originY);
    const oz = Math.floor(originZ);

    // 5x5 soil plot with center water & crops
    for (let dx = -2; dx <= 2; dx++) {
      for (let dz = -2; dz <= 2; dz++) {
        if (dx === 0 && dz === 0) {
          await this.placeAt(ox, oy, oz, 'water');
        } else {
          await this.placeAt(ox + dx, oy, oz + dz, 'dirt');
          await this.placeAt(ox + dx, oy + 1, oz + dz, 'wheat_seeds');
        }
      }
    }

    // 4 Corner torches to keep crops growing overnight
    await this.placeAt(ox - 2, oy + 1, oz - 2, 'torch');
    await this.placeAt(ox + 2, oy + 1, oz - 2, 'torch');
    await this.placeAt(ox - 2, oy + 1, oz + 2, 'torch');
    await this.placeAt(ox + 2, oy + 1, oz + 2, 'torch');

    await this.announce('🥕 Community Farm is planted and flourishing!');
    this.isBuilding = false;
    this.currentStructure = null;
    return { ok: true, structure: 'Antigravity Community Farm' };
  }

  /**
   * Build the "Roman Domus / Villa" architectural upgrade
   * Features: Symmetrical Colonnade pillars, Sandstone & Polished Stone mosaic floor,
   * Central Impluvium Atrium, Grand Portico Archway, and Roman Lantern lighting.
   */
  async buildRomanVilla(originX, originY, originZ) {
    this.isBuilding = true;
    this.currentStructure = 'Roman Domus Villa';
    await this.announce('🏛️ Commencing construction of the Roman Domus Villa!');

    const ox = Math.floor(originX);
    const oy = Math.floor(originY);
    const oz = Math.floor(originZ);

    // 1. Mosaic Floor (9x9) - Sandstone & Polished Diorite/Stone
    await this.announce('🏛️ Laying Roman mosaic stone & sandstone flooring...');
    for (let dx = -4; dx <= 4; dx++) {
      for (let dz = -4; dz <= 4; dz++) {
        const isBorder = Math.abs(dx) === 4 || Math.abs(dz) === 4;
        const block = isBorder ? 'smooth_stone' : ((dx + dz) % 2 === 0 ? 'sandstone' : 'cobblestone');
        await this.placeAt(ox + dx, oy, oz + dz, block);
      }
    }

    // 2. Colonnade Pillars (4 Corner Classical Columns - Height 4)
    await this.announce('🏛️ Raising Roman Colonnade pillars...');
    const pillarOffsets = [[-3, -3], [3, -3], [-3, 3], [3, 3], [-3, 0], [3, 0]];
    for (const [px, pz] of pillarOffsets) {
      for (let h = 1; h <= 3; h++) {
        await this.placeAt(ox + px, oy + h, oz + pz, 'smooth_stone');
      }
      await this.placeAt(ox + px, oy + 4, oz + pz, 'torch');
    }

    // 3. Central Impluvium (Atrium Fountain)
    await this.announce('⛲ Constructing central Atrium and Impluvium water basin...');
    await this.placeAt(ox, oy, oz, 'water');
    await this.placeAt(ox - 1, oy + 1, oz, 'torch');
    await this.placeAt(ox + 1, oy + 1, oz, 'torch');
    await this.placeAt(ox, oy + 1, oz - 1, 'torch');
    await this.placeAt(ox, oy + 1, oz + 1, 'torch');

    // 4. Perimeter Walls & Classical Archways
    for (let dy = 1; dy <= 3; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        for (let dz = -4; dz <= 4; dz++) {
          const isOuter = Math.abs(dx) === 4 || Math.abs(dz) === 4;
          if (!isOuter) continue;
          // Leave grand entrance arch at (dx=0, dz=-4)
          if (dz === -4 && Math.abs(dx) <= 1 && (dy === 1 || dy === 2)) continue;
          // Window openings
          if (Math.abs(dx) === 4 && Math.abs(dz) === 1 && dy === 2) {
            await this.placeAt(ox + dx, oy + dy, oz + dz, 'glass');
            continue;
          }
          await this.placeAt(ox + dx, oy + dy, oz + dz, 'sandstone');
        }
      }
    }

    // 5. Living Quarters Amenities
    await this.placeAt(ox - 3, oy + 1, oz + 3, 'red_bed');
    await this.placeAt(ox - 2, oy + 1, oz + 3, 'chest');
    await this.placeAt(ox + 3, oy + 1, oz + 3, 'crafting_table');

    await this.announce('🏛️ Roman Domus Villa completed in honor of Shu_Walker and Jenkins Robotics!');
    this.isBuilding = false;
    this.currentStructure = null;
    return { ok: true, structure: 'Roman Domus Villa', location: { x: ox, y: oy, z: oz } };
  }
}
