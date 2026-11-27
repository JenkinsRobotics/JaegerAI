/**
 * 60fps HTML5 Canvas Virtual Office simulation & renderer.
 * Character state machine, BFS walking, Matrix spawn effect & z-sorted rendering
 * adapted from pixel-agents-hq/pixel-agents (MIT).
 */
import { buildJaegerStudioFloorplan, type OfficeFloorplan } from "./officeLayout";
import { drawFurnitureItem, drawOfficePet, drawPixelBubble, drawPixelCharacter } from "./sprites";
import { findPath, getWalkableTiles, type GridPoint } from "./tileMap";
import {
  Direction,
  TILE_SIZE,
  TileType,
  type OfficeAgentActivity,
  type OfficeAgentRecord,
  type OfficeSeat,
  type OfficeSnapshot,
} from "./types";

interface SimAgent {
  record: OfficeAgentRecord;
  seatId: string | null;
  x: number;
  y: number;
  tileCol: number;
  tileRow: number;
  dir: Direction;
  path: GridPoint[];
  walkFrame: number;
  animTimer: number;
  blinkTimer: number;
  blinking: boolean;
  wanderTimer: number;
  spawnMatrixProgress: number; // 0..1 green rain materialization effect
}

interface SimPet {
  x: number;
  y: number;
  tileCol: number;
  tileRow: number;
  dir: Direction;
  path: GridPoint[];
  frame: number;
  animTimer: number;
  idleTimer: number;
  sleeping: boolean;
  heartTimer: number;
}

const WALK_SPEED_PX_S = 44;
const PET_SPEED_PX_S = 28;

function tileCenter(col: number, row: number): { x: number; y: number } {
  return { x: (col + 0.5) * TILE_SIZE, y: (row + 0.5) * TILE_SIZE };
}

function directionBetween(dx: number, dy: number): Direction {
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx < 0 ? Direction.LEFT : Direction.RIGHT;
  }
  return dy < 0 ? Direction.UP : Direction.DOWN;
}

export class OfficeEngine {
  readonly floorplan: OfficeFloorplan;
  private readonly walkable: GridPoint[];
  private readonly agents = new Map<string, SimAgent>();
  private readonly seatOwners = new Map<string, string>();
  private pet: SimPet;
  private frameTick = 0;
  private estopActive = false;
  selectedAgentId: string | null = null;
  hoveredAgentId: string | null = null;

  constructor() {
    this.floorplan = buildJaegerStudioFloorplan();
    this.walkable = getWalkableTiles(this.floorplan.tiles, this.floorplan.blockedTiles);
    const petStart = tileCenter(18, 11);
    this.pet = {
      x: petStart.x,
      y: petStart.y,
      tileCol: 18,
      tileRow: 11,
      dir: Direction.RIGHT,
      path: [],
      frame: 0,
      animTimer: 0,
      idleTimer: 3.5,
      sleeping: false,
      heartTimer: 0,
    };
  }

  get worldWidth(): number {
    return this.floorplan.cols * TILE_SIZE;
  }

  get worldHeight(): number {
    return this.floorplan.rows * TILE_SIZE;
  }

  private pickSeat(rec: OfficeAgentRecord): OfficeSeat | null {
    // 1. Explicit seat requested and available
    if (rec.seatId) {
      const explicit = this.floorplan.seats.find((s) => s.id === rec.seatId);
      if (explicit && (!this.seatOwners.has(explicit.id) || this.seatOwners.get(explicit.id) === rec.id)) {
        return explicit;
      }
    }
    // 2. Primary agent takes command desk
    if (rec.kind === "primary") {
      const cmd = this.floorplan.seats.find((s) => s.zone === "command");
      if (cmd) return cmd;
    }
    // 3. Free seat in preferred zone
    const zoneFree = this.floorplan.seats.find(
      (s) => s.zone === rec.zone && (!this.seatOwners.has(s.id) || this.seatOwners.get(s.id) === rec.id),
    );
    if (zoneFree) return zoneFree;
    // 4. Any free seat
    return this.floorplan.seats.find((s) => !this.seatOwners.has(s.id)) ?? null;
  }

  syncSnapshot(snapshot: OfficeSnapshot): void {
    this.estopActive = Boolean(snapshot.estopActive);
    const incomingIds = new Set(snapshot.agents.map((a) => a.id));

    // Remove despawned subagents/agents and release their seats
    for (const [id, sim] of this.agents.entries()) {
      if (!incomingIds.has(id)) {
        if (sim.seatId && this.seatOwners.get(sim.seatId) === id) {
          this.seatOwners.delete(sim.seatId);
        }
        this.agents.delete(id);
        if (this.selectedAgentId === id) this.selectedAgentId = null;
      }
    }

    for (const rec of snapshot.agents) {
      const existing = this.agents.get(rec.id);
      if (existing) {
        const prevAct = existing.record.activity;
        existing.record = rec;
        // If agent just switched from idle/coffee to active work, send back to desk!
        const busy = rec.activity === "typing" || rec.activity === "reading" || rec.activity === "thinking" || rec.activity === "waiting_approval";
        if (busy && (prevAct === "idle" || prevAct === "coffee") && existing.seatId) {
          const seat = this.floorplan.seats.find((s) => s.id === existing.seatId);
          if (seat && (existing.tileCol !== seat.seatCol || existing.tileRow !== seat.seatRow)) {
            existing.path = findPath(
              existing.tileCol,
              existing.tileRow,
              seat.seatCol,
              seat.seatRow,
              this.floorplan.tiles,
              this.floorplan.blockedTiles,
            );
          }
        }
        continue;
      }

      const seat = this.pickSeat(rec);
      const startCol = seat ? seat.seatCol : 11;
      const startRow = seat ? seat.seatRow : 7;
      if (seat) this.seatOwners.set(seat.id, rec.id);
      const pos = tileCenter(startCol, startRow);
      this.agents.set(rec.id, {
        record: rec,
        seatId: seat?.id ?? null,
        x: pos.x,
        y: pos.y,
        tileCol: startCol,
        tileRow: startRow,
        dir: seat ? seat.facingDir : Direction.DOWN,
        path: [],
        walkFrame: 0,
        animTimer: 0,
        blinkTimer: 2 + Math.random() * 4,
        blinking: false,
        wanderTimer: 4 + Math.random() * 8,
        spawnMatrixProgress: rec.kind === "subagent" ? 0 : 1,
      });
    }
  }

  petCatIfHit(worldX: number, worldY: number): boolean {
    const dx = worldX - this.pet.x;
    const dy = worldY - (this.pet.y - 4);
    if (Math.hypot(dx, dy) <= 10) {
      this.pet.heartTimer = 2.4;
      this.pet.sleeping = false;
      return true;
    }
    return false;
  }

  hitTestAgent(worldX: number, worldY: number): OfficeAgentRecord | null {
    let best: { rec: OfficeAgentRecord; dist: number } | null = null;
    for (const sim of this.agents.values()) {
      const dx = worldX - sim.x;
      const dy = worldY - (sim.y - 10);
      if (Math.abs(dx) <= 9 && Math.abs(dy) <= 13) {
        const dist = Math.hypot(dx, dy);
        if (!best || dist < best.dist) {
          best = { rec: sim.record, dist };
        }
      }
    }
    return best?.rec ?? null;
  }

  step(dtRaw: number, reducedMotion: boolean): void {
    const dt = Math.min(Math.max(dtRaw, 0), 0.1);
    if (reducedMotion) return;
    this.frameTick += 1;

    for (const sim of this.agents.values()) {
      if (sim.spawnMatrixProgress < 1) {
        sim.spawnMatrixProgress = Math.min(1, sim.spawnMatrixProgress + dt * 2.2);
      }

      // Natural blinking
      sim.blinkTimer -= dt;
      if (sim.blinkTimer <= 0) {
        sim.blinking = !sim.blinking;
        sim.blinkTimer = sim.blinking ? 0.14 : 2.6 + Math.random() * 3.8;
      }

      if (this.estopActive) continue;

      const seat = sim.seatId ? this.floorplan.seats.find((s) => s.id === sim.seatId) : null;
      const act = sim.record.activity;
      const needsDesk = act === "typing" || act === "reading" || act === "thinking" || act === "waiting_approval";

      if (sim.path.length > 0) {
        const nextTile = sim.path[0];
        const target = tileCenter(nextTile.col, nextTile.row);
        const dx = target.x - sim.x;
        const dy = target.y - sim.y;
        const dist = Math.hypot(dx, dy);
        const move = WALK_SPEED_PX_S * dt;
        sim.dir = directionBetween(dx, dy);
        sim.animTimer += dt;
        if (sim.animTimer >= 0.16) {
          sim.animTimer = 0;
          sim.walkFrame = (sim.walkFrame + 1) % 4;
        }
        if (dist <= move) {
          sim.x = target.x;
          sim.y = target.y;
          sim.tileCol = nextTile.col;
          sim.tileRow = nextTile.row;
          sim.path.shift();
          if (sim.path.length === 0 && seat && sim.tileCol === seat.seatCol && sim.tileRow === seat.seatRow) {
            sim.dir = seat.facingDir;
          }
        } else {
          sim.x += (dx / dist) * move;
          sim.y += (dy / dist) * move;
        }
        continue;
      }

      // Seated animation at desk
      if (needsDesk && seat) {
        if (sim.tileCol !== seat.seatCol || sim.tileRow !== seat.seatRow) {
          sim.path = findPath(
            sim.tileCol,
            sim.tileRow,
            seat.seatCol,
            seat.seatRow,
            this.floorplan.tiles,
            this.floorplan.blockedTiles,
          );
        } else {
          sim.dir = seat.facingDir;
          sim.animTimer += dt;
          if (sim.animTimer >= 0.24) {
            sim.animTimer = 0;
            sim.walkFrame = (sim.walkFrame + 1) % 2;
          }
        }
        continue;
      }

      // Idle or coffee break: stroll gently between desk and lounge
      if (act === "idle" || act === "coffee") {
        sim.wanderTimer -= dt;
        if (sim.wanderTimer <= 0) {
          sim.wanderTimer = 7 + Math.random() * 10;
          const goCoffee = act === "coffee" || Math.random() < 0.45;
          const pool = goCoffee ? this.floorplan.loungeSpots : this.walkable;
          if (pool.length > 0) {
            const pick = pool[Math.floor(Math.random() * pool.length)];
            const p = findPath(
              sim.tileCol,
              sim.tileRow,
              pick.col,
              pick.row,
              this.floorplan.tiles,
              this.floorplan.blockedTiles,
            );
            if (p.length > 0 && p.length <= 26) {
              sim.path = p;
            }
          }
        }
      }
    }

    // Roaming office cat ("Pixel")
    if (this.pet.heartTimer > 0) this.pet.heartTimer = Math.max(0, this.pet.heartTimer - dt);
    if (!this.estopActive) {
      if (this.pet.path.length > 0) {
        const nextTile = this.pet.path[0];
        const target = tileCenter(nextTile.col, nextTile.row);
        const dx = target.x - this.pet.x;
        const dy = target.y - this.pet.y;
        const dist = Math.hypot(dx, dy);
        const move = PET_SPEED_PX_S * dt;
        this.pet.dir = directionBetween(dx, dy);
        this.pet.animTimer += dt;
        if (this.pet.animTimer >= 0.2) {
          this.pet.animTimer = 0;
          this.pet.frame = (this.pet.frame + 1) % 2;
        }
        if (dist <= move) {
          this.pet.x = target.x;
          this.pet.y = target.y;
          this.pet.tileCol = nextTile.col;
          this.pet.tileRow = nextTile.row;
          this.pet.path.shift();
        } else {
          this.pet.x += (dx / dist) * move;
          this.pet.y += (dy / dist) * move;
        }
      } else {
        this.pet.idleTimer -= dt;
        if (this.pet.idleTimer <= 0) {
          if (Math.random() < 0.35) {
            this.pet.sleeping = true;
            this.pet.idleTimer = 6 + Math.random() * 6;
          } else {
            this.pet.sleeping = false;
            this.pet.idleTimer = 4 + Math.random() * 5;
            const pick = this.floorplan.loungeSpots[Math.floor(Math.random() * this.floorplan.loungeSpots.length)];
            if (pick) {
              this.pet.path = findPath(
                this.pet.tileCol,
                this.pet.tileRow,
                pick.col,
                pick.row,
                this.floorplan.tiles,
                this.floorplan.blockedTiles,
              );
            }
          }
        }
      }
    }
  }

  render(ctx: CanvasRenderingContext2D, width: number, height: number, zoom: number, panX: number, panY: number): void {
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#0b1120";
    ctx.fillRect(0, 0, width, height);

    const worldW = this.worldWidth * zoom;
    const worldH = this.worldHeight * zoom;
    const originX = Math.floor((width - worldW) / 2 + panX);
    const originY = Math.floor((height - worldH) / 2 + panY);

    ctx.save();
    ctx.translate(originX, originY);
    ctx.scale(zoom, zoom);

    // 1. Floor & Wall tiles
    for (let r = 0; r < this.floorplan.rows; r++) {
      for (let c = 0; c < this.floorplan.cols; c++) {
        const t = this.floorplan.tiles[r][c];
        const x = c * TILE_SIZE;
        const y = r * TILE_SIZE;
        if (t === TileType.WALL) {
          ctx.fillStyle = r === 0 ? "#0f172a" : "#1e293b";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
          if (r === 1) {
            // Baseboard trim
            ctx.fillStyle = "#334155";
            ctx.fillRect(x, y + TILE_SIZE - 2, TILE_SIZE, 2);
          }
        } else if (t === TileType.FLOOR_WOOD) {
          ctx.fillStyle = (c + r) % 2 === 0 ? "#d6b588" : "#cfa977";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
          ctx.fillStyle = "rgba(120, 53, 15, 0.10)";
          ctx.fillRect(x, y + 7, TILE_SIZE, 1);
          ctx.fillRect(x, y + 15, TILE_SIZE, 1);
        } else if (t === TileType.FLOOR_CARPET_BLUE) {
          ctx.fillStyle = (c + r) % 2 === 0 ? "#1e3a5f" : "#1b3557";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
        } else if (t === TileType.FLOOR_SLATE) {
          ctx.fillStyle = (c + r) % 2 === 0 ? "#242f40" : "#293548";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
        } else if (t === TileType.FLOOR_CARPET_WARM) {
          ctx.fillStyle = (c + r) % 2 === 0 ? "#4a3b32" : "#42342c";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
        } else if (t === TileType.FLOOR_LOUNGE) {
          ctx.fillStyle = (c + r) % 2 === 0 ? "#312e81" : "#2e2b78";
          ctx.fillRect(x, y, TILE_SIZE, TILE_SIZE);
        }
      }
    }

    // 2. Subtle pixel zone labels on floor
    ctx.font = "bold 4.5px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "top";
    for (const z of this.floorplan.zones) {
      ctx.fillStyle = "rgba(248, 250, 252, 0.45)";
      ctx.fillText(z.title, z.col * TILE_SIZE + 2, z.row * TILE_SIZE + 2);
    }

    // Map active desk states so monitors glow when their occupant is working!
    const deskStateMap = new Map<string, OfficeAgentActivity>();
    for (const sim of this.agents.values()) {
      if (!sim.seatId) continue;
      const seat = this.floorplan.seats.find((s) => s.id === sim.seatId);
      if (seat && sim.tileCol === seat.seatCol && sim.tileRow === seat.seatRow && sim.path.length === 0) {
        deskStateMap.set(`${seat.deskCol},${seat.deskRow}`, sim.record.activity);
      }
    }

    // 3. Z-sorted renderables (furniture + characters + office pet)
    const drawables: Array<{ sortY: number; draw: () => void }> = [];

    for (const item of this.floorplan.furniture) {
      const sortY = (item.row + item.heightTiles) * TILE_SIZE - (item.walkable ? 12 : 2);
      const active = deskStateMap.get(`${item.col},${item.row}`) ?? null;
      drawables.push({
        sortY,
        draw: () =>
          drawFurnitureItem(
            ctx,
            item.kind,
            item.col,
            item.row,
            item.widthTiles,
            item.heightTiles,
            this.frameTick,
            active,
            this.estopActive,
          ),
      });
    }

    drawables.push({
      sortY: this.pet.y,
      draw: () => {
        drawOfficePet(ctx, this.pet.x, this.pet.y, this.pet.dir, this.pet.frame, this.pet.sleeping);
        if (this.pet.heartTimer > 0) {
          drawPixelBubble(ctx, this.pet.x, this.pet.y - 8, "heart", this.frameTick);
        }
      },
    });

    for (const sim of this.agents.values()) {
      drawables.push({
        sortY: sim.y + 1,
        draw: () => {
          const isWalking = sim.path.length > 0;
          const act = sim.record.activity;
          const pose = isWalking
            ? "walk"
            : act === "typing"
              ? "type"
              : act === "reading"
                ? "read"
                : "stand";

          if (sim.spawnMatrixProgress < 1) {
            ctx.save();
            ctx.globalAlpha = 0.25 + 0.75 * sim.spawnMatrixProgress;
            drawPixelCharacter(
              ctx,
              sim.x,
              sim.y,
              sim.record.paletteIndex,
              sim.dir,
              pose,
              sim.walkFrame,
              sim.blinking,
              sim.record.id === this.selectedAgentId || sim.record.id === this.hoveredAgentId,
              sim.record.kind === "primary",
            );
            // Green Matrix rain veil (pixel-agents pattern)
            ctx.fillStyle = "#22c55e";
            for (let gx = -6; gx <= 6; gx += 3) {
              const dropY = sim.y - 20 + ((this.frameTick * 2 + gx * 5) % 20);
              ctx.fillRect(Math.round(sim.x + gx), Math.round(dropY), 1.5, 4);
            }
            ctx.restore();
          } else {
            drawPixelCharacter(
              ctx,
              sim.x,
              sim.y,
              sim.record.paletteIndex,
              sim.dir,
              pose,
              sim.walkFrame,
              sim.blinking,
              sim.record.id === this.selectedAgentId || sim.record.id === this.hoveredAgentId,
              sim.record.kind === "primary",
            );
          }

          // Floating pixel status bubble
          if (act === "waiting_approval") {
            drawPixelBubble(ctx, sim.x, sim.y - 20, "permission", this.frameTick);
          } else if (act === "thinking") {
            drawPixelBubble(ctx, sim.x, sim.y - 20, "thinking", this.frameTick);
          } else if (act === "coffee") {
            drawPixelBubble(ctx, sim.x, sim.y - 20, "coffee", this.frameTick);
          }

          // Crisp name tag & live tool pill underneath
          ctx.font = "bold 4.5px ui-monospace, SFMono-Regular, Menlo, monospace";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          const label = sim.record.name.slice(0, 14);
          const tagW = Math.max(22, label.length * 3.1 + 6);
          ctx.fillStyle = "rgba(15, 23, 42, 0.82)";
          ctx.fillRect(Math.round(sim.x - tagW / 2), Math.round(sim.y + 1), Math.round(tagW), 7);
          ctx.fillStyle = sim.record.id === this.selectedAgentId ? "#38bdf8" : "#f8fafc";
          ctx.fillText(label, Math.round(sim.x), Math.round(sim.y + 2));

          if (sim.record.currentTool && (act === "typing" || act === "reading")) {
            const toolText = sim.record.currentTool.slice(0, 14);
            const tw = Math.max(20, toolText.length * 2.8 + 6);
            ctx.fillStyle = "rgba(14, 165, 233, 0.9)";
            ctx.fillRect(Math.round(sim.x - tw / 2), Math.round(sim.y - 28), Math.round(tw), 6.5);
            ctx.fillStyle = "#082f49";
            ctx.fillText(toolText, Math.round(sim.x), Math.round(sim.y - 27));
          }
          ctx.textAlign = "left";
        },
      });
    }

    drawables.sort((a, b) => a.sortY - b.sortY);
    for (const item of drawables) item.draw();

    // E-Stop safety wash
    if (this.estopActive) {
      ctx.fillStyle = "rgba(127, 29, 29, 0.22)";
      ctx.fillRect(0, 0, this.worldWidth, this.worldHeight);
    }

    ctx.restore();
  }

  screenToWorld(
    clientX: number,
    clientY: number,
    rect: DOMRect,
    zoom: number,
    panX: number,
    panY: number,
  ): { x: number; y: number } {
    const worldW = this.worldWidth * zoom;
    const worldH = this.worldHeight * zoom;
    const originX = Math.floor((rect.width - worldW) / 2 + panX);
    const originY = Math.floor((rect.height - worldH) / 2 + panY);
    return {
      x: (clientX - rect.left - originX) / zoom,
      y: (clientY - rect.top - originY) / zoom,
    };
  }
}
