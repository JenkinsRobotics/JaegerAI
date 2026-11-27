export const TILE_SIZE = 16;

export const TileType = {
  VOID: 0,
  WALL: 1,
  FLOOR_WOOD: 2,
  FLOOR_SLATE: 3,
  FLOOR_CARPET_BLUE: 4,
  FLOOR_CARPET_WARM: 5,
  FLOOR_LOUNGE: 6,
} as const;
export type TileType = (typeof TileType)[keyof typeof TileType];

export const Direction = {
  DOWN: 0,
  LEFT: 1,
  RIGHT: 2,
  UP: 3,
} as const;
export type Direction = (typeof Direction)[keyof typeof Direction];

export type OfficeAgentActivity =
  | "typing"
  | "reading"
  | "thinking"
  | "waiting_approval"
  | "idle"
  | "coffee"
  | "offline"
  | "estop";

export type OfficeZoneId = "command" | "engineering" | "studio" | "research" | "lounge";

export interface OfficeAgentRecord {
  id: string;
  name: string;
  role: string;
  kind: "primary" | "subagent" | "team" | "embodiment";
  zone: OfficeZoneId;
  activity: OfficeAgentActivity;
  statusLabel: string;
  currentTool?: string;
  currentTask?: string;
  model?: string;
  contextPct?: number;
  accentColor: string;
  paletteIndex: number;
  seatId?: string;
  updatedAt?: number;
}

export interface OfficeActivityEvent {
  id: string;
  timestamp: number;
  agentName: string;
  kind: "tool" | "autonomy" | "subagent" | "approval" | "embodiment" | "system";
  summary: string;
}

export interface OfficeSnapshot {
  agents: OfficeAgentRecord[];
  activityFeed: OfficeActivityEvent[];
  budgets?: {
    daily_cap_usd?: number;
    daily_spent_usd?: number;
    daily_remaining_usd?: number;
  };
  pendingApprovals: number;
  activeSubagents: number;
  estopActive: boolean;
  autonomyEnabled: boolean;
  minecraftConnected: boolean;
  minecraftSummary?: string;
  droidAwake: boolean;
  updatedAt: number;
}

export interface OfficeSeat {
  id: string;
  zone: OfficeZoneId;
  seatCol: number;
  seatRow: number;
  facingDir: Direction;
  deskCol: number;
  deskRow: number;
  label: string;
}

export type FurnitureKind =
  | "desk_dual"
  | "desk_single"
  | "desk_edit"
  | "chair"
  | "server_rack"
  | "plant"
  | "coffee_bar"
  | "sofa"
  | "whiteboard"
  | "bookshelf"
  | "window"
  | "table_round"
  | "lamp";

export interface OfficeFurniture {
  id: string;
  kind: FurnitureKind;
  col: number;
  row: number;
  widthTiles: number;
  heightTiles: number;
  walkable?: boolean;
  label?: string;
}

export interface OfficeZoneLabel {
  id: OfficeZoneId;
  title: string;
  col: number;
  row: number;
}
