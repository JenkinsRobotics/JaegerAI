import { Direction, TileType, type OfficeFurniture, type OfficeSeat, type OfficeZoneLabel } from "./types";

export const OFFICE_COLS = 24;
export const OFFICE_ROWS = 15;

export interface OfficeFloorplan {
  cols: number;
  rows: number;
  tiles: TileType[][];
  furniture: OfficeFurniture[];
  seats: OfficeSeat[];
  zones: OfficeZoneLabel[];
  blockedTiles: Set<string>;
  loungeSpots: Array<{ col: number; row: number }>;
}

export function buildJaegerStudioFloorplan(): OfficeFloorplan {
  const tiles: TileType[][] = [];
  for (let r = 0; r < OFFICE_ROWS; r++) {
    const row: TileType[] = [];
    for (let c = 0; c < OFFICE_COLS; c++) {
      if (r === 0 || r === OFFICE_ROWS - 1 || c === 0 || c === OFFICE_COLS - 1) {
        row.push(TileType.WALL);
      } else if (r === 1) {
        // Upper architectural wall trim
        row.push(TileType.WALL);
      } else if (c >= 9 && c <= 14 && r >= 2 && r <= 6) {
        // Command center slate carpet
        row.push(TileType.FLOOR_CARPET_BLUE);
      } else if (c >= 16 && c <= 22 && r >= 9 && r <= 13) {
        // Coffee lounge warm carpet
        row.push(TileType.FLOOR_LOUNGE);
      } else if (c >= 16 && c <= 22 && r >= 2 && r <= 7) {
        // Media Studio bay
        row.push(TileType.FLOOR_SLATE);
      } else if (c >= 2 && c <= 7 && r >= 9 && r <= 13) {
        // Research & Ops wing
        row.push(TileType.FLOOR_CARPET_WARM);
      } else {
        row.push(TileType.FLOOR_WOOD);
      }
    }
    tiles.push(row);
  }

  // Interior glass divider stubs (leaving wide walkways for smooth BFS)
  tiles[2][8] = TileType.WALL;
  tiles[3][8] = TileType.WALL;
  tiles[2][15] = TileType.WALL;
  tiles[3][15] = TileType.WALL;

  const furniture: OfficeFurniture[] = [
    // Architectural wall windows & whiteboard along top wall (row 1)
    { id: "win-1", kind: "window", col: 2, row: 1, widthTiles: 3, heightTiles: 1 },
    { id: "wb-1", kind: "whiteboard", col: 10, row: 1, widthTiles: 4, heightTiles: 1, label: "ROADMAP" },
    { id: "win-2", kind: "window", col: 18, row: 1, widthTiles: 3, heightTiles: 1 },

    // Command Desk (Jaeger Primary Mind)
    { id: "desk-command", kind: "desk_dual", col: 11, row: 3, widthTiles: 2, heightTiles: 1, label: "JAEGER HQ" },
    { id: "chair-command", kind: "chair", col: 11, row: 4, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "plant-cmd-l", kind: "plant", col: 9, row: 2, widthTiles: 1, heightTiles: 1 },
    { id: "plant-cmd-r", kind: "plant", col: 14, row: 2, widthTiles: 1, heightTiles: 1 },

    // Engineering & Subagent Pod (West Wing)
    { id: "desk-eng-1", kind: "desk_dual", col: 2, row: 3, widthTiles: 2, heightTiles: 1, label: "CODE-1" },
    { id: "chair-eng-1", kind: "chair", col: 2, row: 4, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-eng-2", kind: "desk_dual", col: 5, row: 3, widthTiles: 2, heightTiles: 1, label: "CODE-2" },
    { id: "chair-eng-2", kind: "chair", col: 5, row: 4, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-eng-3", kind: "desk_single", col: 2, row: 6, widthTiles: 2, heightTiles: 1, label: "SUBAGENT-1" },
    { id: "chair-eng-3", kind: "chair", col: 2, row: 7, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-eng-4", kind: "desk_single", col: 5, row: 6, widthTiles: 2, heightTiles: 1, label: "SUBAGENT-2" },
    { id: "chair-eng-4", kind: "chair", col: 5, row: 7, widthTiles: 1, heightTiles: 1, walkable: true },

    // Media & YouTube Studio Bay (East Wing)
    { id: "desk-studio-1", kind: "desk_edit", col: 17, row: 3, widthTiles: 2, heightTiles: 1, label: "PRODUCER" },
    { id: "chair-studio-1", kind: "chair", col: 17, row: 4, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-studio-2", kind: "desk_edit", col: 20, row: 3, widthTiles: 2, heightTiles: 1, label: "EDITOR" },
    { id: "chair-studio-2", kind: "chair", col: 20, row: 4, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-studio-3", kind: "desk_single", col: 17, row: 6, widthTiles: 2, heightTiles: 1, label: "WRITER" },
    { id: "chair-studio-3", kind: "chair", col: 17, row: 7, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-studio-4", kind: "desk_single", col: 20, row: 6, widthTiles: 2, heightTiles: 1, label: "DIRECTOR" },
    { id: "chair-studio-4", kind: "chair", col: 20, row: 7, widthTiles: 1, heightTiles: 1, walkable: true },

    // Research, Ops & Rack Wing (South-West)
    { id: "rack-1", kind: "server_rack", col: 1, row: 10, widthTiles: 1, heightTiles: 2, label: "RACK" },
    { id: "books-1", kind: "bookshelf", col: 1, row: 12, widthTiles: 1, heightTiles: 2 },
    { id: "desk-res-1", kind: "desk_single", col: 3, row: 10, widthTiles: 2, heightTiles: 1, label: "RESEARCH" },
    { id: "chair-res-1", kind: "chair", col: 3, row: 11, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-res-2", kind: "desk_single", col: 6, row: 10, widthTiles: 2, heightTiles: 1, label: "OPS" },
    { id: "chair-res-2", kind: "chair", col: 6, row: 11, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-res-3", kind: "desk_single", col: 10, row: 10, widthTiles: 2, heightTiles: 1, label: "GROWTH" },
    { id: "chair-res-3", kind: "chair", col: 10, row: 11, widthTiles: 1, heightTiles: 1, walkable: true },
    { id: "desk-res-4", kind: "desk_single", col: 13, row: 10, widthTiles: 2, heightTiles: 1, label: "EMBODIMENT" },
    { id: "chair-res-4", kind: "chair", col: 13, row: 11, widthTiles: 1, heightTiles: 1, walkable: true },

    // Coffee Bar & Break Lounge (South-East)
    { id: "coffee-1", kind: "coffee_bar", col: 20, row: 9, widthTiles: 2, heightTiles: 1, label: "ESPRESSO" },
    { id: "sofa-1", kind: "sofa", col: 17, row: 12, widthTiles: 3, heightTiles: 1 },
    { id: "table-1", kind: "table_round", col: 18, row: 10, widthTiles: 1, heightTiles: 1 },
    { id: "plant-lounge", kind: "plant", col: 22, row: 13, widthTiles: 1, heightTiles: 1 },
    { id: "lamp-lounge", kind: "lamp", col: 16, row: 12, widthTiles: 1, heightTiles: 1 },
  ];

  const seats: OfficeSeat[] = [
    { id: "seat-command", zone: "command", seatCol: 11, seatRow: 4, facingDir: Direction.UP, deskCol: 11, deskRow: 3, label: "Command Desk" },
    { id: "seat-eng-1", zone: "engineering", seatCol: 2, seatRow: 4, facingDir: Direction.UP, deskCol: 2, deskRow: 3, label: "Eng Desk 1" },
    { id: "seat-eng-2", zone: "engineering", seatCol: 5, seatRow: 4, facingDir: Direction.UP, deskCol: 5, deskRow: 3, label: "Eng Desk 2" },
    { id: "seat-eng-3", zone: "engineering", seatCol: 2, seatRow: 7, facingDir: Direction.UP, deskCol: 2, deskRow: 6, label: "Subagent Bay 1" },
    { id: "seat-eng-4", zone: "engineering", seatCol: 5, seatRow: 7, facingDir: Direction.UP, deskCol: 5, deskRow: 6, label: "Subagent Bay 2" },
    { id: "seat-studio-1", zone: "studio", seatCol: 17, seatRow: 4, facingDir: Direction.UP, deskCol: 17, deskRow: 3, label: "Producer Desk" },
    { id: "seat-studio-2", zone: "studio", seatCol: 20, seatRow: 4, facingDir: Direction.UP, deskCol: 20, deskRow: 3, label: "Editing Suite" },
    { id: "seat-studio-3", zone: "studio", seatCol: 17, seatRow: 7, facingDir: Direction.UP, deskCol: 17, deskRow: 6, label: "Script Desk" },
    { id: "seat-studio-4", zone: "studio", seatCol: 20, seatRow: 7, facingDir: Direction.UP, deskCol: 20, deskRow: 6, label: "Director Desk" },
    { id: "seat-res-1", zone: "research", seatCol: 3, seatRow: 11, facingDir: Direction.UP, deskCol: 3, deskRow: 10, label: "Research Desk" },
    { id: "seat-res-2", zone: "research", seatCol: 6, seatRow: 11, facingDir: Direction.UP, deskCol: 6, deskRow: 10, label: "Ops Console" },
    { id: "seat-res-3", zone: "research", seatCol: 10, seatRow: 11, facingDir: Direction.UP, deskCol: 10, deskRow: 10, label: "Growth Desk" },
    { id: "seat-res-4", zone: "research", seatCol: 13, seatRow: 11, facingDir: Direction.UP, deskCol: 13, deskRow: 10, label: "Embodiment Bay" },
  ];

  const zones: OfficeZoneLabel[] = [
    { id: "engineering", title: "ENGINEERING & SUBAGENTS", col: 2, row: 2 },
    { id: "command", title: "COMMAND HQ", col: 10, row: 2 },
    { id: "studio", title: "MEDIA STUDIO", col: 17, row: 2 },
    { id: "research", title: "RESEARCH & OPS", col: 3, row: 9 },
    { id: "lounge", title: "COFFEE LOUNGE", col: 17, row: 9 },
  ];

  const blockedTiles = new Set<string>();
  for (const item of furniture) {
    if (item.walkable) continue;
    for (let dy = 0; dy < item.heightTiles; dy++) {
      for (let dx = 0; dx < item.widthTiles; dx++) {
        blockedTiles.add(`${item.col + dx},${item.row + dy}`);
      }
    }
  }

  const loungeSpots = [
    { col: 19, row: 10 },
    { col: 20, row: 10 },
    { col: 21, row: 10 },
    { col: 17, row: 11 },
    { col: 18, row: 11 },
    { col: 20, row: 11 },
    { col: 12, row: 7 },
    { col: 10, row: 7 },
  ];

  return {
    cols: OFFICE_COLS,
    rows: OFFICE_ROWS,
    tiles,
    furniture,
    seats,
    zones,
    blockedTiles,
    loungeSpots,
  };
}
